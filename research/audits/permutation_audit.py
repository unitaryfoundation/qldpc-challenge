#!/usr/bin/env python3
"""Decide, where it can be decided, the permutation equivalences the gate only flags (issue #3427).

The gate has two dedup outcomes, an identical fingerprint and a shared
Weisfeiler-Leman (WL) signature, and everything between them is a human. This
audit runs over every pair of board entries that share a WL signature with
different fingerprints, and over the literature matches recorded in
`research/provenance/derived.json`, and reports one of four verdicts per pair:

* `equivalent`: a qubit permutation carries the first entry's X and Z row
  spaces onto the second's (optionally after an X/Z swap). The permutation is
  the evidence, found by nauty's canonical form of the typed Tanner graph
  (`research/provenance/iso_common.py`) or of the basis-independent
  hypergraph of all row-space vectors up to the check weight, and
  re-verified here by row-space mapping (`permutation_equivalence.check_pair`)
  with the ledger's negative control (one extra transposition must fail).
* `inequivalent`: a basis-independent invariant differs in both orientations
  (the ranks, the dimension and weight enumerator of the intersection of the X
  and Z row spaces, the dimensions and weight enumerators of the two hulls, or
  the per-weight counts of row-space vectors up to the check weight), or the
  hypergraphs of all row-space vectors up to the check weight are not
  isomorphic. The light vectors come from a Brouwer-Zimmermann enumeration
  over disjoint information sets, complete to that weight at any rank (issue
  #4057, after Leon's method); when they are exactly the check rows, this is
  the Tanner comparison made decisive. Sound; no permutation exists.
* `gb_family_no`: both entries are genuine cyclic two-block (generalized
  bicycle) codes and `verify/two_block_equivalence.py` finds no unit map,
  shift, or block swap carrying one onto the other. This is the family
  decider's verdict, the one the board already acts on; it is not a proof
  against permutations outside that group of maps.
* `undecided`: the invariants agree, the Tanner graphs are not isomorphic, and
  the light-vector enumeration is over its budget (`run --enum-budget`).
  Nothing here says the pair is one code or two.

Equivalent pairs with different claimed distances are flagged under
`distance_conflict`: the lighter entry's witness transports onto the heavier
entry, so the heavier claim is over-stated by the difference (issue #1651's
shape).

The literature half rebuilds each 2BGA match from its archive row on the
committed GAP tables under `research/kit/groups/`, fetches each QECDB match
from `https://qecdb.org/api/codes/<id>` (and keeps the fetched rows in the
output so the trail does not depend on the database staying up), and skips
the Wang-Pryadko rows, whose index id carries no polynomials.

Nothing here is a gate input. The output is a JSON record under
`research/audits/`; `recheck` re-verifies every recorded permutation from
the blob hashes it cites, as `permutation_equivalence.py` does for its ledger.

    uv run --extra research python research/audits/permutation_audit.py run \
        --out research/audits/permutation_audit-<date>.json
    uv run --extra research python research/audits/permutation_audit.py recheck \
        research/audits/permutation_audit-<date>.json
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for rel in ("verify", os.path.join("research", "provenance"), os.path.join("research", "kit"), HERE):
    p = os.path.join(ROOT, rel)
    if p not in sys.path:
        sys.path.insert(0, p)

import iso_common as I  # noqa: E402
import numpy as np  # noqa: E402
import permutation_equivalence as PE  # noqa: E402
import qldpc_verify as V  # noqa: E402
import two_block_equivalence as TB  # noqa: E402

AUDIT_VERSION = 2
# The 41 submissions issue #1204 found isomorphic to a published code, the
# literature half of #3427's audit. `run --all-literature` widens this to every
# `literature` row of derived.json.
ISSUE_1204_MATCHES = (
    "214-2-25 394-2-30 422-2-31 454-2-33 "
    "60-4-8 64-18-8 70-8-10 72-8-10 72-10-9 84-2-9 96-4-10 48-4-8 56-6-7 72-8-7 80-9-9 196-12-17 "
    "15-7-3 34-2-7 40-2-8 40-6-4 40-10-4 40-12-4 42-6-6 42-10-4 42-12-4 45-9-3 45-16-4 50-2-9 50-10-4 "
    "50-18-4 51-16-5 54-2-9 54-6-7 54-8-6 54-20-4 57-18-4 58-16-3 73-37-6 85-37-5 96-18-4 96-34-4").split()
# 2**rank row-space vectors are enumerated exactly below this; above it the
# low-weight enumerator and the hypergraph encoding are skipped.
ENUM_LIMIT = 2 ** 20
# A partial information set is used when its kernel has at most this many rows
# (every kernel combination is enumerated with it).
KERNEL_BITS = 8
# Row sums the light-vector enumeration may plan per row space before the pair
# is left undecided (`run --enum-budget`); 10**9 is about a minute of numpy.
DEFAULT_BUDGET = 10 ** 9
# Column orders tried for the information sets (the natural order and seeded
# shuffles); the cheapest complete plan is enumerated.
ORDER_TRIES = 6
QECDB_API = "https://qecdb.org/api/codes/{}"


# -- codes -------------------------------------------------------------------

def code_from_doc(slug, doc):
    return I.Code(slug, int(doc["n"]), doc["checks"]["X"], doc["checks"]["Z"],
                  {"k": doc.get("k"), "d": (doc.get("distance") or {}).get("d")})


def code_from_matrices(name, HX, HZ):
    sup = lambda H: [[int(q) for q in np.nonzero(r)[0]] for r in np.asarray(H)]  # noqa: E731
    return I.Code(name, int(np.asarray(HX).shape[1]), sup(HX), sup(HZ))


def dense(code):
    return I.dense(code.X, code.n).astype(np.int8), I.dense(code.Z, code.n).astype(np.int8)


def blob_sha(path):
    return subprocess.check_output(["git", "hash-object", path], cwd=ROOT, text=True).strip()


# -- GF(2) on bit-packed ints -----------------------------------------------------

def echelon_basis(vecs):
    """Return an independent spanning set of ``vecs`` (one vector per pivot bit)."""
    piv = {}
    for v0 in vecs:
        v = v0
        while v:
            h = v.bit_length() - 1
            if h in piv:
                v ^= piv[h]
            else:
                piv[h] = v
                break
    return [piv[h] for h in sorted(piv, reverse=True)]


def dependencies(vecs):
    """Return a basis of the masks m over ``vecs`` whose XOR is zero (the left kernel)."""
    piv, out = {}, []
    for i, v0 in enumerate(vecs):
        v, tag = v0, 1 << i
        while v:
            h = v.bit_length() - 1
            if h in piv:
                pv, pt = piv[h]
                v ^= pv
                tag ^= pt
            else:
                piv[h] = (v, tag)
                break
        if not v:
            out.append(tag)
    return out


def combine(vecs, mask):
    out, i = 0, 0
    while mask:
        if mask & 1:
            out ^= vecs[i]
        mask >>= 1
        i += 1
    return out


def hull_basis(basis):
    """Basis of C ∩ C^⊥ for the code C with the independent rows ``basis``."""
    gram = [sum(((b & c).bit_count() & 1) << j for j, c in enumerate(basis)) for b in basis]
    return [combine(basis, m) for m in dependencies(gram)]


def intersection_basis(bx, bz):
    """Basis of span(bx) ∩ span(bz) for independent ``bx`` and ``bz``."""
    low = (1 << len(bx)) - 1
    return [combine(bx, m & low) for m in dependencies(list(bx) + list(bz))]


def weight_enumerator(basis, limit=ENUM_LIMIT):
    """[[weight, count], ...] over the nonzero vectors of the span, or None past ``limit``."""
    if 2 ** len(basis) > limit:
        return None
    counts, cur = {}, 0
    for g in range(1, 2 ** len(basis)):
        cur ^= basis[(g & -g).bit_length() - 1]
        c = cur.bit_count()
        counts[c] = counts.get(c, 0) + 1
    return [[w, counts[w]] for w in sorted(counts)]


# -- invariants ----------------------------------------------------------------

def invariants(code):
    """Return the basis-independent invariants of ``code``, oriented (X, Z).

    The ranks, the dimension of the intersection of the X and Z row spaces,
    the dimensions of the two hulls (each row space meeting its own dual), the
    weight enumerators of those three subspaces when they have at most 2**20
    vectors, and the exact low-weight enumerators when the rank allows.
    """
    X, Z = code.normalized()
    bx, bz = echelon_basis(X), echelon_basis(Z)
    rx, rz = len(bx), len(bz)
    inter = intersection_basis(bx, bz)
    hx, hz = hull_basis(bx), hull_basis(bz)
    wmax = code.max_weight()
    lowx = I.low_weight_enumerator(X, wmax, limit=ENUM_LIMIT)
    lowz = I.low_weight_enumerator(Z, wmax, limit=ENUM_LIMIT)
    return {"n": code.n, "rank_X": rx, "rank_Z": rz, "intersection": len(inter),
            "hull_X": len(hx), "hull_Z": len(hz),
            "intersection_weights": weight_enumerator(inter),
            "hull_X_weights": weight_enumerator(hx), "hull_Z_weights": weight_enumerator(hz),
            "wmax": wmax, "low_X": lowx, "low_Z": lowz}


def _oriented(inv, swap):
    a, b = ("Z", "X") if swap else ("X", "Z")
    return (inv["rank_" + a], inv["rank_" + b], inv["low_" + a], inv["low_" + b],
            inv["hull_" + a], inv["hull_" + b], inv["hull_" + a + "_weights"], inv["hull_" + b + "_weights"])


def invariants_separate(ia, ib):
    """Name the invariant that differs in both orientations, or None."""
    if ia["n"] != ib["n"]:
        return "n"
    if ia["intersection"] != ib["intersection"]:
        return "intersection dimension"
    wa, wb = ia.get("intersection_weights"), ib.get("intersection_weights")
    if wa is not None and wb is not None and wa != wb:
        return "weight enumerator of the intersection of the X and Z row spaces"
    reasons = []
    a = _oriented(ia, False)
    for swap in (False, True):
        b = _oriented(ib, swap)
        if (a[0], a[1]) != (b[0], b[1]):
            reasons.append("ranks")
            continue
        if (a[4], a[5]) != (b[4], b[5]):
            reasons.append("hull dimensions")
            continue
        wmax = min(ia["wmax"], ib["wmax"])
        la, lb = a[2], b[2]
        lza, lzb = a[3], b[3]
        if la is not None and lb is not None and la[:wmax + 1] != lb[:wmax + 1]:
            reasons.append("low-weight enumerator of the X row space")
            continue
        if lza is not None and lzb is not None and lza[:wmax + 1] != lzb[:wmax + 1]:
            reasons.append("low-weight enumerator of the Z row space")
            continue
        if a[6] is not None and b[6] is not None and a[6] != b[6]:
            reasons.append("weight enumerator of the hull of the X row space")
            continue
        if a[7] is not None and b[7] is not None and a[7] != b[7]:
            reasons.append("weight enumerator of the hull of the Z row space")
            continue
        return None                                   # this orientation is not refuted
    return reasons[0] if reasons[0] == reasons[1] else " / ".join(reasons)


# -- the light vectors of a row space (Brouwer-Zimmermann) ---------------------

def _permute_bits(v, perm):
    out, i = 0, 0
    while v:
        if v & 1:
            out |= 1 << perm[i]
        v >>= 1
        i += 1
    return out


def information_sets(basis, n, kernel_bits=KERNEL_BITS, order=None):
    """Disjoint information sets of span(basis), greedily, as (systematic rows, kernel rows).

    Gauss-Jordan elimination restricted to the columns no earlier set used
    picks pivot columns, the first available column in ``order`` (a column
    permutation; None is the natural order); the systematic rows carry an
    identity block on them and the kernel rows vanish on them. A set whose
    columns do not carry the full rank is kept only when its kernel has at
    most ``kernel_bits`` rows, since every kernel combination is enumerated
    with it; it is the last set.
    """
    if order is not None:
        inverse = [0] * n
        for i, p in enumerate(order):
            inverse[p] = i
        sets = information_sets([_permute_bits(v, order) for v in basis], n, kernel_bits)
        return [([_permute_bits(v, inverse) for v in s], [_permute_bits(v, inverse) for v in kk]) for s, kk in sets]
    k = len(basis)
    used, sets = 0, []
    while True:
        avail = ((1 << n) - 1) & ~used
        rows = list(basis)
        pivots = {}                                   # pivot column -> row index
        taken = 0
        while True:
            cand = None
            for i, r in enumerate(rows):
                if i in pivots.values():
                    continue
                c = r & avail & ~taken
                if c:
                    cand = (i, (c & -c).bit_length() - 1)
                    break
            if cand is None:
                break
            i, p = cand
            pivots[p] = i
            taken |= 1 << p
            pr = rows[i]
            for j in range(k):
                if j != i and (rows[j] >> p) & 1:
                    rows[j] ^= pr
        r = len(pivots)
        if r == 0:
            break
        sys_idx = set(pivots.values())
        systematic = [rows[i] for i in sorted(sys_idx)]
        kernel = [rows[i] for i in range(k) if i not in sys_idx]
        if kernel and len(kernel) > kernel_bits:
            break
        sets.append((systematic, kernel))
        used |= taken
        if kernel:
            break
    return sets


def _thresholds(sets, wmax):
    """Per-set subset sizes t_i with sum(t_i + 1) > wmax, chosen cheapest first; and the cost in row sums."""
    from math import comb

    def marginal(i, t):
        r, kap = len(sets[i][0]), len(sets[i][1])
        return comb(r, t) << kap
    ts = [0] * len(sets)
    cost = sum(marginal(i, 0) for i in range(len(sets)))
    while sum(t + 1 for t in ts) <= wmax:
        open_sets = [i for i in range(len(sets)) if ts[i] < len(sets[i][0])]
        if not open_sets:
            break                                     # every set enumerates its whole row space
        i = min(open_sets, key=lambda i: marginal(i, ts[i] + 1))
        ts[i] += 1
        cost += marginal(i, ts[i])
    return ts, cost


def _pack(vecs, n):
    W = (n + 63) // 64
    arr = np.zeros((len(vecs), W), dtype=np.uint64)
    mask = (1 << 64) - 1
    for i, v in enumerate(vecs):
        for w in range(W):
            arr[i, w] = (v >> (64 * w)) & mask
    return arr


def _unpack(rows):
    return [int.from_bytes(r.astype("<u8").tobytes(), "little") for r in rows]


def _enumerate_set(systematic, kernel, t, n, wmax, found):
    """Add to ``found`` every sum of at most ``t`` systematic rows and a kernel combination with weight <= wmax."""
    from itertools import combinations
    R = _pack(systematic, n)
    span = [0]
    for v in kernel:
        span += [s ^ v for s in span]
    K = _pack(span, n)
    r = R.shape[0]

    def keep(cand):
        for e in K:
            block = cand ^ e
            wt = np.bitwise_count(block).sum(axis=1, dtype=np.int64)
            hit = np.flatnonzero(wt <= wmax)
            if hit.size:
                found.update(v for v in _unpack(block[hit]) if v)
    keep(np.zeros((1, R.shape[1]), dtype=np.uint64))            # s = 0
    if t >= 1 and r:
        keep(R)                                                    # s = 1
    if t >= 2 and r >= 2:
        pairs = [(i, j) for i in range(r) for j in range(i + 1, r)]
        P = np.array([R[i] ^ R[j] for i, j in pairs], dtype=np.uint64)
        start = [0] * (r + 1)                                      # first pair with i >= q
        pos = 0
        for q in range(r + 1):
            while pos < len(pairs) and pairs[pos][0] < q:
                pos += 1
            start[q] = pos
        for s in range(2, t + 1):
            for prefix in combinations(range(r), s - 2):
                last = prefix[-1] if prefix else -1
                lo = start[last + 1]
                if lo >= len(pairs):
                    continue
                if prefix:
                    base = np.bitwise_xor.reduce(R[list(prefix)], axis=0)
                else:
                    base = np.zeros(R.shape[1], dtype=np.uint64)
                keep(base[None, :] ^ P[lo:])


def light_vectors(vecs, n, wmax, budget=DEFAULT_BUDGET, tries=ORDER_TRIES):
    """Every row-space vector of weight <= wmax, complete, or None when the plan exceeds ``budget``.

    Brouwer-Zimmermann: with disjoint information sets I_1..I_m and subset
    sizes t_i, enumerating every sum of at most t_i systematic rows of set i
    (times every kernel combination, for a partial last set) finds each
    vector whose restriction to some I_i has at most t_i ones; a vector missed
    by all sets has weight at least sum(t_i + 1), so the list is complete up
    to wmax once that sum exceeds wmax. The sets depend on the column order,
    so ``tries`` orders are planned and the cheapest is enumerated. Returns
    (vectors, plan) where the plan records the sets, the subset sizes, the
    number of row sums, and the order's seed.
    """
    import random
    basis = echelon_basis(vecs)
    if not basis:
        return [], {"sets": [], "row_sums": 0}
    best = None
    for seed in range(tries):                          # the natural column order, then seeded shuffles
        order = None
        if seed:
            order = list(range(n))
            random.Random(seed).shuffle(order)
        sets = information_sets(basis, n, order=order)
        ts, cost = _thresholds(sets, wmax)
        if best is None or cost < best[2]:
            best = (sets, ts, cost, seed)
    sets, ts, cost, seed = best
    plan = {"sets": [{"rank": len(s), "kernel": len(kk), "t": t} for (s, kk), t in zip(sets, ts)],
            "row_sums": cost, "column_order_seed": seed}
    if cost > budget:
        return None, plan
    found = set()
    for (systematic, kernel), t in zip(sets, ts):
        _enumerate_set(systematic, kernel, t, n, wmax, found)
    return sorted(found), plan


def weight_counts(vecs, wmax):
    counts = [0] * (wmax + 1)
    for v in vecs:
        counts[v.bit_count()] += 1
    return counts


def light_vector_stage(a, b, budget=DEFAULT_BUDGET):
    """Decide the pair on the complete lists of light row-space vectors, or report why not.

    Both codes' X and Z row spaces are enumerated up to the larger of the two
    check weights. The per-weight counts are basis-independent invariants; when
    they agree in some orientation, nauty compares the hypergraphs whose
    hyperedges are those vectors, which decides equivalence in both directions
    because the lists are complete and contain every check row, so they span.
    """
    t0 = time.monotonic()
    wmax = max(a.max_weight(), b.max_weight())
    out = {"wmax": wmax, "method": "Brouwer-Zimmermann enumeration, complete to weight wmax"}
    lists = {}
    for code, key in ((a, "first"), (b, "second")):
        X, Z = code.normalized()
        lx, px = light_vectors(X, code.n, wmax, budget)
        lz, pz = light_vectors(Z, code.n, wmax, budget)
        out[key] = {"plan": {"X": px, "Z": pz}}
        if lx is None or lz is None:
            out["outcome"] = f"over budget: {key} needs {max(px['row_sums'] or 0, pz['row_sums'] or 0):,} row sums"
            out["seconds"] = round(time.monotonic() - t0, 2)
            return None, out
        assert I.rank_ints(lx) == len(echelon_basis(X)) and I.rank_ints(lz) == len(echelon_basis(Z))
        out[key]["counts"] = {"X": weight_counts(lx, wmax), "Z": weight_counts(lz, wmax)}
        out[key]["checks_only"] = {"X": lx == X, "Z": lz == Z}
        lists[key] = (lx, lz)
    ca, cb = out["first"]["counts"], out["second"]["counts"]
    agree = [swap for swap in (False, True)
             if (ca["X"], ca["Z"]) == ((cb["Z"], cb["X"]) if swap else (cb["X"], cb["Z"]))]
    if not agree:
        w = next(w for w in range(wmax + 1)
                 if ca["X"][w] != cb["X"][w] or ca["Z"][w] != cb["Z"][w])
        out["outcome"] = "counts differ"
        out["seconds"] = round(time.monotonic() - t0, 2)
        return ("inequivalent", f"count of row-space vectors of weight {w} differs in both orientations "
                                f"(enumeration complete to weight {wmax})"), out
    ha = I.Code(a.id + "@light", a.n, I.ints_to_rows(lists["first"][0]), I.ints_to_rows(lists["first"][1]))
    hb = I.Code(b.id + "@light", b.n, I.ints_to_rows(lists["second"][0]), I.ints_to_rows(lists["second"][1]))
    for swap in agree:
        perm = I.nauty_permutation(ha, hb, swap=swap)
        if perm is not None:
            out["outcome"] = "hypergraphs isomorphic"
            out["seconds"] = round(time.monotonic() - t0, 2)
            return ("equivalent", [perm[i] for i in range(a.n)], swap), out
    tanner = all(out[k]["checks_only"][s] for k in ("first", "second") for s in ("X", "Z"))
    out["outcome"] = "hypergraphs not isomorphic"
    out["seconds"] = round(time.monotonic() - t0, 2)
    tail = "; they are exactly the check rows, so this is the Tanner comparison made decisive)" if tanner else ")"
    return ("inequivalent",
            f"the hypergraphs of all row-space vectors of weight at most {wmax} are not isomorphic in any "
            "orientation (the lists are complete and span the row spaces, so no permutation exists" + tail), out


# -- the decision --------------------------------------------------------------

def find_permutation(a, b):
    """(perm, swap) from nauty on the typed Tanner graphs, else (None, None)."""
    for swap in (False, True):
        perm = I.nauty_permutation(a, b, swap=swap)
        if perm is not None:
            return [perm[i] for i in range(a.n)], swap
    return None, None


def _equivalent(out, a, b, doc_a, doc_b, perm, swap, how):
    ok, detail = PE.check_pair(doc_a, doc_b, perm, swap=swap)
    if not ok:
        out.update(verdict="undecided", reason=f"{how} isomorphism did not verify on the row spaces", detail=detail)
        return
    ctrl = PE.negative_control(doc_a, doc_b, perm) if not swap else None
    out.update(verdict="equivalent", permutation=perm, swap=swap, found_by=how, row_spaces=detail,
               negative_control={True: "a perturbed permutation fails",
                                 False: "skipped: the perturbation is an automorphism",
                                 None: "not run for a swapped pair"}[ctrl])
    da, db = a.meta.get("d"), b.meta.get("d")
    if da is not None and db is not None and da != db:
        out["distance_conflict"] = {"first_d": da, "second_d": db,
                                    "note": f"one code under two claims; the weight-{min(da, db)} witness "
                                            f"transports, so the claim of {max(da, db)} is over-stated"}


def decide(a, b, doc_a, doc_b, budget=DEFAULT_BUDGET):
    """One pair's verdict with its evidence."""
    t0 = time.monotonic()
    out = {"first": a.id, "second": b.id, "n": a.n}
    ia, ib = invariants(a), invariants(b)
    out["invariants"] = {"first": ia, "second": ib}
    sep = invariants_separate(ia, ib)
    if sep:
        out.update(verdict="inequivalent", reason=f"{sep} differs in both orientations")
        out["seconds"] = round(time.monotonic() - t0, 2)
        return out
    perm, swap = find_permutation(a, b)
    if perm is not None:
        _equivalent(out, a, b, doc_a, doc_b, perm, swap, "tanner")
        out["seconds"] = round(time.monotonic() - t0, 2)
        return out
    verdict, light = light_vector_stage(a, b, budget)
    out["light_vectors"] = light
    if verdict is not None:
        if verdict[0] == "equivalent":
            _equivalent(out, a, b, doc_a, doc_b, verdict[1], verdict[2], "hypergraph")
        else:
            out.update(verdict="inequivalent", reason=verdict[1])
        out["seconds"] = round(time.monotonic() - t0, 2)
        return out
    gb = None
    if TB.is_generalised_bicycle(doc_a) and TB.is_generalised_bicycle(doc_b):
        gb = TB.equivalent(doc_a, doc_b)
        if gb is None:
            out.update(verdict="gb_family_no",
                       reason="both are cyclic two-block codes and no unit map, shift, or block swap "
                              "carries one onto the other (verify/two_block_equivalence.py)")
        else:
            out.update(verdict="undecided",
                       reason=f"the two-block decider reports unit {gb[0]} (swap {gb[1]}) but no Tanner "
                              "isomorphism was found; left for a human")
        out["seconds"] = round(time.monotonic() - t0, 2)
        return out
    out.update(verdict="undecided",
               reason=f"invariants agree, Tanner graphs are not isomorphic, and the light-vector enumeration is "
                      f"{light['outcome']}")
    out["seconds"] = round(time.monotonic() - t0, 2)
    return out


# -- the board's WL clusters ------------------------------------------------

def wl_clusters():
    """Entries sharing a WL signature with different fingerprints, from the verifier's own reports."""
    by_sig = {}
    for e in V.board_reports(os.path.join(ROOT, "codes")):
        doc, rep = e["doc"], e["report"]
        if doc is None or rep is None:
            continue
        sig = (rep.get("signature") or {}).get("hash")
        by_sig.setdefault(sig, []).append((os.path.basename(e["path"])[:-5], rep.get("fingerprint"), doc))
    clusters = []
    for members in by_sig.values():
        if len({fp for _, fp, _ in members}) > 1:
            clusters.append(sorted(members, key=lambda m: m[0]))
    return sorted(clusters, key=lambda c: (c[0][2]["n"], c[0][0]))


def audit_board(budget=DEFAULT_BUDGET):
    pairs = []
    for members in wl_clusters():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                sa, _, da = members[i]
                sb, _, db = members[j]
                rec = decide(code_from_doc(sa, da), code_from_doc(sb, db), da, db, budget=budget)
                rec["first_blob"] = blob_sha(os.path.join(ROOT, "codes", sa + ".json"))
                rec["second_blob"] = blob_sha(os.path.join(ROOT, "codes", sb + ".json"))
                rec["k"] = da.get("k")
                pairs.append(rec)
                print(f"{rec['verdict']:13s} {sa} / {sb}  {rec.get('reason', rec.get('found_by', ''))}", flush=True)
    return pairs


# -- the literature matches ------------------------------------------------------

_TWO_BGA = re.compile(r"2bga:SmallGroup\((\d+),(\d+)\):a\[([\d, ]*)\]:b\[([\d, ]*)\]")


def rebuild_2bga(match_id):
    """(HX, HZ) of an archive row from its committed GAP table; identity implicit unless listed."""
    from group_algebra import build_2bga_small_group
    m = _TWO_BGA.match(match_id)
    order, gid = int(m.group(1)), int(m.group(2))

    def zero_based(text):
        idx = [int(x) - 1 for x in text.split(",") if x.strip()]
        return idx if 0 in idx else [0] + idx
    return build_2bga_small_group(order, gid, zero_based(m.group(3)), zero_based(m.group(4)))


def fetch_qecdb(record_id, fetch=None):
    """Fetch the record's H rows (Pauli strings) and parameters from the public API."""
    if fetch is None:
        def fetch(url):
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
    rec = fetch(QECDB_API.format(record_id))
    return {"id": record_id, "name": rec.get("name"), "n": rec.get("n"), "k": rec.get("k"),
            "css": rec.get("css"), "rows": rec["H"].split()}


def qecdb_matrices(rows):
    """CSS matrices from Pauli-string rows; a row mixing X and Z is refused."""
    n = len(rows[0])
    HX, HZ = [], []
    for r in rows:
        kinds = set(r) - {"I"}
        if kinds == {"X"}:
            HX.append([1 if c == "X" else 0 for c in r])
        elif kinds == {"Z"}:
            HZ.append([1 if c == "Z" else 0 for c in r])
        else:
            raise ValueError(f"row mixes {sorted(kinds)}; not a CSS generating set")
    return np.array(HX, dtype=np.int8).reshape(-1, n), np.array(HZ, dtype=np.int8).reshape(-1, n)


def audit_literature(fetch=None, slugs=ISSUE_1204_MATCHES, budget=DEFAULT_BUDGET):
    """Re-derive the index's literature matches for ``slugs`` (None: every literature row)."""
    with open(os.path.join(ROOT, "research", "provenance", "derived.json"), encoding="utf-8") as f:
        entries = json.load(f)["entries"]
    out = []
    for slug, ent in sorted(entries.items()):
        if ent.get("bucket") != "literature":
            continue
        if slugs is not None and slug not in slugs:
            continue
        path = os.path.join(ROOT, "codes", slug + ".json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        board = code_from_doc(slug, doc)
        for m in ent.get("matches", []):
            rec = {"slug": slug, "blob": blob_sha(path), "source": m.get("source"), "id": m.get("id"),
                   "ref": m.get("ref")}
            try:
                if m.get("source", "").startswith("lin_pryadko_2bga"):
                    HX, HZ = rebuild_2bga(m["id"])
                    lit = code_from_matrices(m["id"], HX, HZ)
                elif m.get("source") == "qecdb":
                    fetched = fetch_qecdb(m["id"].split(":", 1)[1], fetch)
                    rec["record"] = fetched
                    HX, HZ = qecdb_matrices(fetched["rows"])
                    lit = code_from_matrices(m["id"], HX, HZ)
                else:
                    rec.update(verdict="not_re_derived", reason="the index id carries no construction to rebuild from")
                    out.append(rec)
                    print(f"{rec['verdict']:13s} {slug} <- {m['id']}", flush=True)
                    continue
            except (FileNotFoundError, ValueError, KeyError, OSError) as e:
                rec.update(verdict="not_re_derived", reason=f"{type(e).__name__}: {e}")
                out.append(rec)
                print(f"{rec['verdict']:13s} {slug} <- {m['id']}  {rec['reason']}", flush=True)
                continue
            lit_doc = {"n": lit.n, "checks": {"X": lit.X, "Z": lit.Z}}
            perm, swap = find_permutation(lit, board)
            how = "tanner"
            if perm is None:
                sep = invariants_separate(invariants(lit), invariants(board))
                if sep:
                    rec.update(verdict="inequivalent", reason=f"{sep} differs in both orientations")
                else:
                    verdict, light = light_vector_stage(lit, board, budget)
                    rec["light_vectors"] = light
                    if verdict is None:
                        rec.update(verdict="undecided", reason="no Tanner isomorphism, the invariants agree, and "
                                   f"the light-vector enumeration is {light['outcome']}")
                    elif verdict[0] == "inequivalent":
                        rec.update(verdict="inequivalent", reason=verdict[1])
                    else:
                        perm, swap, how = verdict[1], verdict[2], "hypergraph"
            if perm is not None:
                ok, detail = PE.check_pair(lit_doc, doc, perm, swap=swap)
                rec.update(verdict="equivalent" if ok else "undecided", permutation=perm, swap=swap,
                           found_by=how, row_spaces=detail,
                           literature_n=lit.n, literature_k=lit.k())
            out.append(rec)
            print(f"{rec['verdict']:13s} {slug} <- {m['id']}", flush=True)
    return out


# -- the record and its re-check --------------------------------------------------

def run(out_path, fetch=None, all_literature=False, budget=DEFAULT_BUDGET):
    t0 = time.monotonic()
    board = audit_board(budget)
    lit = audit_literature(fetch, slugs=None if all_literature else ISSUE_1204_MATCHES, budget=budget)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    record = {
        "audit_version": AUDIT_VERSION,
        "issue": 3427,
        "date": datetime.date.today().isoformat(),
        "head": head,
        "literature_scope": ("every literature row of derived.json" if all_literature
                             else "the 41 matches of issue #1204"),
        "semantics": "permutation[i] = j means qubit i of the first code is qubit j of the second; equivalence "
                     "means the permuted X and Z row spaces of the first equal those of the second, after an "
                     "X/Z swap when swap is true",
        "enum_budget": budget,
        "counts": {
            "board_pairs": len(board),
            "board": {v: sum(1 for p in board if p["verdict"] == v)
                      for v in ("equivalent", "inequivalent", "gb_family_no", "undecided")},
            "literature_matches": len(lit),
            "literature": {v: sum(1 for p in lit if p["verdict"] == v)
                           for v in ("equivalent", "inequivalent", "undecided", "not_re_derived")},
        },
        "board_pairs": board,
        "literature": lit,
        "seconds": round(time.monotonic() - t0, 1),
    }
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(record, f, indent=1, sort_keys=True)
        f.write("\n")
    print(json.dumps(record["counts"], indent=1))
    return record


def recheck(path):
    """Re-verify every recorded equivalence from the blob hashes it cites."""
    with open(path, encoding="utf-8") as f:
        rec = json.load(f)
    failures = 0
    for p in rec["board_pairs"]:
        if p["verdict"] != "equivalent":
            continue
        a, b = PE.load_blob(p["first_blob"]), PE.load_blob(p["second_blob"])
        ok, detail = PE.check_pair(a, b, p["permutation"], swap=p.get("swap", False))
        failures += 0 if ok else 1
        print(f"{'EQUIVALENT' if ok else 'NOT EQUIVALENT'}  {p['first']} -> {p['second']}  "
              f"X {detail.get('X')}  Z {detail.get('Z')}")
    for p in rec["literature"]:
        if p["verdict"] != "equivalent":
            continue
        board = PE.load_blob(p["blob"])
        if p["source"] == "qecdb":
            HX, HZ = qecdb_matrices(p["record"]["rows"])
        else:
            HX, HZ = rebuild_2bga(p["id"])
        lit = code_from_matrices(p["id"], HX, HZ)
        ok, detail = PE.check_pair({"n": lit.n, "checks": {"X": lit.X, "Z": lit.Z}}, board,
                                   p["permutation"], swap=p.get("swap", False))
        failures += 0 if ok else 1
        print(f"{'EQUIVALENT' if ok else 'NOT EQUIVALENT'}  {p['id']} -> {p['slug']}  "
              f"X {detail.get('X')}  Z {detail.get('Z')}")
    print(f"{failures} failure(s)")
    return failures


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="audit the board's WL clusters and the literature matches")
    r.add_argument("--out", default=os.path.join(HERE, f"permutation_audit-{datetime.date.today().isoformat()}.json"))
    r.add_argument("--all-literature", action="store_true",
                   help="re-derive every literature row of derived.json, not only the 41 of issue #1204")
    r.add_argument("--enum-budget", type=float, default=DEFAULT_BUDGET,
                   help="row sums the light-vector enumeration may plan per row space (default %(default)s)")
    c = sub.add_parser("recheck", help="re-verify the permutations a record carries")
    c.add_argument("record")
    args = ap.parse_args(argv)
    if args.cmd == "run":
        run(args.out, all_literature=args.all_literature, budget=int(args.enum_budget))
        return 0
    return 1 if recheck(args.record) else 0


if __name__ == "__main__":
    sys.exit(main())
