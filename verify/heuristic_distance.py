"""Heuristic distance verification (random-information-set search).

Server-side, reproducible UPPER-BOUND search for a low-weight logical operator. It
sits between the witness upper bound (`d<=`, cheap CI) and exact certification
(`d=`, verify/certify.py), filling the gap for dense / high-rate codes that exact
IP cannot reach. Two outcomes:

  refuted      a logical lighter than the claimed distance was found -> the claim
               is over-stated; the true distance is <= the found weight.
  corroborated a large fixed-budget search found nothing lighter -> confidence
               beyond a single witness (NOT a proof; exact remains the only d=).

This is purely an upper-bound search: every method here only exhibits a logical of
some weight, i.e. tightens d <= w. It never proves a lower bound. The run is
reproducible (fixed seed + trial budget) and computed server-side, never trusted
from the submission.

Engine: random information set (QDistRnd-style). Canonical path is pure Python on
verify/gf2.py (no build). If the gf2_fast C++ extension is importable it is used
for a faster, larger overall weight search; witnesses are always extracted by the
Python path (the C++ returns weights only).

General stabilizer codes (code_type "stabilizer"): there are no
sides. The same RREF engine runs once on K = ker(B | A), the normalizer of
S = (A | B) written as Pauli vectors (x | z), scoring every candidate by its
Pauli weight |supp x union supp z| (a Y counts once) and testing nontriviality
by anticommutation with a logical basis of N(S) modulo S. The accelerator has no
Pauli-weight kernel, so the fast pass runs on the symplectic doubling
H'_X = (A | B), H'_Z = (B | A) (arXiv:2609.30069, eq. 12), a CSS code on 2n
qubits whose X-logicals are exactly the Pauli logicals of the original (a
Z-logical maps to one by swapping halves). Its Hamming weight over 2n bits is an
upper bound on the Pauli weight, so every proposal is re-scored by Pauli weight
in Python before it counts; d'_X = d'_Z by the half-swap symmetry, so one side is
enough. The verdict for a stabilizer code is reported under the single side "P".

Orbit-fold pass (2026-10-08 audit): before RIS, the code's symmetries are read
from the matrices (block-circulant shifts, 2-D shifts, multipliers; plus the
Tanner-graph automorphism group when pynauty is importable) and the lightest
logical constant on the orbits of each cyclic subgroup is searched in the
folded code, then lifted and re-validated on the full matrices. This is the
shape RIS cannot sample -- every 14th qubit of each block -- and it is how
54 board entries came to be over-stated. See orbit_fold_min_logical.

Usage: python verify/heuristic_distance.py codes/foo.json [--trials N] [--seed S]
       [--fold-trials F]; exit code 2 on a refuted claim (so it can gate if desired).
"""
import argparse
import itertools
import json
import sys
import time

import numpy as np

import gf2

try:
    import gf2_fast as _fast            # optional C++ accelerator (weights only)
except ImportError:
    _fast = None


def _matrix(support_list, n):
    H = np.zeros((len(support_list), n), dtype=np.int8)
    for r, sup in enumerate(support_list):
        for q in sup:
            H[r, q] ^= 1
    return H


def _is_stabilizer(doc):
    return doc.get("code_type") == "stabilizer"


def stabilizer_matrices(doc):
    """Return (A, B), int8, of a stabilizer submission, S = (A | B)."""
    n = doc["n"]
    gens = doc["checks"]["S"]
    return (_matrix([g["X"] for g in gens], n),
            _matrix([g["Z"] for g in gens], n))


def doubled_matrices(A, B):
    """Return the symplectic doubling of S = (A | B).

    H'_X = (A | B), H'_Z = (B | A), a CSS code on 2n qubits. Isotropy of S is
    exactly its CSS commutation.
    """
    return (np.concatenate([A, B], axis=1).astype(np.int8),
            np.concatenate([B, A], axis=1).astype(np.int8))


def pauli_weight_rows(rows, n):
    """Pauli weight of each (x | z) row of a 2n-column array."""
    return (rows[:, :n] | rows[:, n:]).sum(1)


def _pauli_from_doubled(v, side, n):
    """Map a logical of the doubled CSS code back to a Pauli (x | z).

    An X-logical lies in ker(B | A) = N(S) and is already a Pauli vector; a
    Z-logical lies in ker(A | B) and outside row(B | A), so swapping its
    halves puts it in N(S) outside row(S) with the same Pauli weight.
    """
    v = np.asarray(v, dtype=np.int8)
    return v if side == "X" else np.concatenate([v[n:], v[:n]])


def _rref_perm(K, perm):
    """RREF of K under a random column permutation, mapped back to original
    columns. Reduced rows are low-weight combinations of K's rows (candidate
    low-weight logicals); the weight is permutation-invariant."""
    R, _ = gf2.rref(K[:, perm])
    out = np.zeros_like(R)
    out[:, perm] = R
    return out


def ris_min_logical(HX, HZ, trials, seed, pair_depth=8, max_seconds=None,
                    capture=None):
    """RIS upper-bound search for the lightest nontrivial X-type logical: a vector
    in ker(H_Z) that anticommutes with some Z-logical. Returns (weight, witness),
    or (None, None) if the code has no logicals of this type. Stops after `trials`
    permutations or `max_seconds` wall-clock, whichever comes first (the time cap
    keeps the CI gate bounded regardless of n).

    ``capture`` (a ``recapture.SideSink``, issue #2897) receives every
    nontrivial row ``consider`` sees at weight <= ``capture.threshold``. It
    reads what the search computed anyway and never touches ``best``, so the
    result for a given seed is the same with or without it."""
    n = HX.shape[1]
    K = gf2.kernel_basis(HZ)
    LZ = gf2.logical_basis(HX, HZ)
    if K.shape[0] == 0 or LZ.shape[0] == 0:
        return None, None
    rng = np.random.default_rng(seed)
    best, wit = n + 1, None
    deadline = (time.monotonic() + max_seconds) if max_seconds else None

    def consider(rows):
        nonlocal best, wit
        w = rows.sum(1)
        nontrivial = ((rows @ LZ.T) % 2).any(1)
        if capture is not None:
            hits = np.where(nontrivial & (w > 0) & (w <= capture.threshold))[0]
            if hits.size:
                capture.add(rows[hits], w[hits])
        for i in np.where(nontrivial & (w > 0) & (w < best))[0]:
            best, wit = int(w[i]), rows[i].copy()

    for t in range(trials):
        red = _rref_perm(K, rng.permutation(n))
        consider(red)
        if pair_depth > 1 and red.shape[0] >= 2:        # short combinations
            w = red.sum(1)
            light = np.argsort(w)[:min(pair_depth, red.shape[0])]
            sub = red[light]
            for a in range(len(light) - 1):
                consider(sub[a] ^ sub[a + 1:])
        if deadline and (t & 63) == 0 and time.monotonic() > deadline:
            break
    return best, wit


def ris_min_pauli_logical(A, B, trials, seed, pair_depth=8, max_seconds=None,
                          capture=None):
    """Search for the lightest nontrivial logical Pauli operator, by Pauli weight.

    RIS upper-bound search on the stabilizer code S = (A | B). Returns
    (weight, witness) with the witness a 2n-vector (x | z), or (None, None)
    when the code has no logicals. Same engine and budget shape as
    ris_min_logical: K = ker(B | A) is the normalizer written as Pauli
    vectors, L a logical basis of N(S) modulo S, and a candidate is nontrivial
    iff it anticommutes with some row of L, i.e. (x | z) . (L_z | L_x) = 1.
    ``capture`` is as in ris_min_logical, by Pauli weight.
    """
    n = A.shape[1]
    S, SL = doubled_matrices(A, B)              # S = (A | B), S Lambda = (B | A)
    K = gf2.kernel_basis(SL)
    L = gf2.logical_basis(SL, S)                # ker(S Lambda) reduced mod row(S)
    if K.shape[0] == 0 or L.shape[0] == 0:
        return None, None
    LS = np.concatenate([L[:, n:], L[:, :n]], axis=1)   # L Lambda, so rows @ LS.T is the symplectic product
    rng = np.random.default_rng(seed)
    best, wit = n + 1, None
    deadline = (time.monotonic() + max_seconds) if max_seconds else None

    def consider(rows):
        nonlocal best, wit
        w = pauli_weight_rows(rows, n)
        nontrivial = ((rows @ LS.T) % 2).any(1)
        if capture is not None:
            hits = np.where(nontrivial & (w > 0) & (w <= capture.threshold))[0]
            if hits.size:
                capture.add(rows[hits], w[hits])
        for i in np.where(nontrivial & (w > 0) & (w < best))[0]:
            best, wit = int(w[i]), rows[i].copy()

    for t in range(trials):
        red = _rref_perm(K, rng.permutation(2 * n))
        consider(red)
        if pair_depth > 1 and red.shape[0] >= 2:        # short combinations
            w = pauli_weight_rows(red, n)
            light = np.argsort(w)[:min(pair_depth, red.shape[0])]
            sub = red[light]
            for a in range(len(light) - 1):
                consider(sub[a] ^ sub[a + 1:])
        if deadline and (t & 63) == 0 and time.monotonic() > deadline:
            break
    return best, wit


def _valid_logical(v, H_ker, H_row):
    """Report whether v is a nontrivial logical operator.

    True when v lies in ker(H_ker) and outside rowspace(H_row). Used to check
    anything the C++ accelerator hands back before it is recorded, so an
    accelerator bug cannot put an unbacked witness into a verdict.
    """
    if v.sum() == 0 or ((H_ker @ v) % 2).any():
        return False
    return gf2.rank(np.vstack([H_row, v[None, :]])) > gf2.rank(H_row)


def valid_pauli_logical(v, A, B):
    """Report whether the Pauli vector v = (x | z) is a nontrivial logical of S.

    In ker(B | A) and outside row(A | B). The Pauli-weight form of
    _valid_logical, applied to every accelerator proposal for a stabilizer
    code before it is trusted.
    """
    S, SL = doubled_matrices(A, B)
    return _valid_logical(np.asarray(v, dtype=np.int8), SL, S)


def pauli_witness(v, n):
    """Return the {"X": [...], "Z": [...]} form of a 2n Pauli vector (x | z)."""
    v = np.asarray(v)
    return {"X": sorted(int(j) for j in np.nonzero(v[:n])[0]),
            "Z": sorted(int(j) for j in np.nonzero(v[n:])[0])}


# ---------------------------------------------------------------------------
# Orbit-fold search: logicals that are constant on the orbits of a symmetry.
#
# RIS proposes supports of roughly uniform density, so it almost never lands
# on a logical whose support is a union of cosets of a shift subgroup -- and
# that is exactly the shape of the lightest logicals in the board's cyclic
# generalized-bicycle entries (every 14th qubit of each block on the
# [[700,26,100]] filing, found at weight 50 after the general battery had
# passed it; 54 entries were over-stated this way, audit of 2026-10-08).
#
# The fix is a change of search space, not of budget. For a qubit
# permutation g that preserves the stabilizer group and a cyclic subgroup
# <g^k>, a vector constant on the orbits of <g^k> is v = P x with P the
# n x c orbit-indicator matrix. It lies in ker(H) iff (H P) x = 0, and it is
# a nontrivial logical iff it anticommutes with some logical of the other
# type, i.e. (L P) x != 0. So the lightest orbit-constant logical is the
# lightest codeword of a code on c orbit-columns, weighted by orbit size --
# a much smaller problem that RIS (or exhaustion, when the folded kernel is
# tiny) solves in milliseconds. Every candidate is lifted and re-checked on
# the FULL matrices before it counts, so an incorrect symmetry can only waste
# time, never admit a false witness.
#
# Symmetries are read from the matrices, never from the family tag: block-wise
# cyclic shifts (n = blocks x L), 2-D shifts (L = l x m) and unit multipliers
# of a shift that was found. pynauty, when importable (research extra), adds
# the full automorphism group of the Tanner graph; the gate runs without it.
# ---------------------------------------------------------------------------

try:
    from pynauty import Graph as _NautyGraph, autgrp as _nauty_autgrp
except ImportError:                     # optional; structural detection remains
    _NautyGraph = None

# RIS trials per folded code in estimate()/refute_check(). Folded codes have
# tens to a few hundred columns, so an accelerated trial costs microseconds;
# at this budget the pass is about a second on the board's largest entries
# (the python fallback is held to the same wall-clock slice instead). 150
# trials found every one of the 2026-10-08 over-claims; more keeps tightening.
FOLD_TRIALS_DEFAULT = 1000
# RIS trials per random Pauli frame in the stabilizer pass: its own cap, since
# a frame trial runs on the full 2n-column doubling, not a folded code, and
# many cheap frames beat a few deep ones (the frame is what exposes the
# logical; 1,200 per frame found every non-CSS over-claim in the audit).
FRAME_TRIALS_MAX = 1200


def _fold_seconds(max_seconds):
    """Wall-clock cap for the fold pass inside estimate(): its own small slice,
    so the RIS budget that follows is exactly what it was before this pass."""
    if max_seconds is None:
        return None
    return min(30.0, max(3.0, 0.5 * max_seconds))


def _divisors(m):
    return [d for d in range(1, m + 1) if m % d == 0]


def _labelled_rows(Lab):
    """Rows of a labelled matrix (0 = absent, else a small label) as hashable keys."""
    out = set()
    for r in Lab:
        nz = np.flatnonzero(r)
        out.add(tuple(zip(nz.tolist(), r[nz].tolist())))
    return out


class _RowInvariance:
    """Test whether a qubit permutation preserves a set of labelled check matrices.

    Two tests, cheap first. ``rows``: the permuted row set equals the row set
    (exact for a matrix listed as all shifts of a template). ``span``: every
    permuted row lies in the row space -- the right notion when redundant
    rows were dropped, as several board GB entries did, at the cost of a
    reduction per test. For a labelled (non-CSS) matrix the span test reduces
    the (x | z) symplectic rows, with the labels mapped alongside."""

    def __init__(self, mats, n):
        self.mats = mats
        self.n = n
        self.keys = [_labelled_rows(M) for M in mats]
        self._rref = None

    def rows(self, perm):
        for Lab, keys in zip(self.mats, self.keys):
            for r in Lab:
                nz = np.flatnonzero(r)
                cols = perm[nz]
                order = np.argsort(cols)
                if tuple(zip(cols[order].tolist(), r[nz][order].tolist())) not in keys:
                    return False
        return True

    @staticmethod
    def _binary(Lab):
        """(x | z) binary form of a labelled matrix (label 1 = x, 2 = z, 3 = both);
        a plain 0/1 matrix maps to itself."""
        if (Lab <= 1).all():
            return Lab.astype(np.int8)
        return np.concatenate([(Lab & 1), (Lab >> 1)], axis=1).astype(np.int8)

    def span(self, perm):
        if self._rref is None:
            self._rref = [gf2.rref(self._binary(M)) for M in self.mats]
        for Lab, (R, piv) in zip(self.mats, self._rref):
            if len(piv) == 0:
                continue
            V = self._binary(Lab[:, np.argsort(perm)])     # permuted rows
            V = V.copy()
            for i, c in enumerate(piv):
                mask = V[:, c].astype(bool)
                if mask.any():
                    V[mask] ^= R[i]
            if V.any():
                return False
        return True

    def __call__(self, perm):
        return self.rows(perm) or self.span(perm)


def _affine_multipliers(inv, M, cyc, blk, m, nb, build, max_multipliers):
    """Automorphisms of the form cyc -> u*cyc + s_b (a unit multiplier with a
    per-block offset) on top of a detected cyclic shift. The candidates come
    from one row: since the rows are all shifts of each other, the multiplied
    block-b part of row 0 must be a shift of row 0's block-b part, which pins
    s_b down to a few values; each candidate is then verified in full."""
    out = []
    r0 = np.flatnonzero(M[0])
    parts = [np.sort(cyc[r0[blk[r0] == b]]) for b in range(nb)]
    if any(len(pt) == 0 for pt in parts):
        return out
    sets = [set(pt.tolist()) for pt in parts]
    for u in range(2, m):
        if len(out) >= max_multipliers or np.gcd(u, m) != 1:
            if len(out) >= max_multipliers:
                break
            continue
        choices = []
        for b in range(nb):
            T = (u * parts[b]) % m
            t0 = int(T[0])
            cands = {int((x - t0) % m) for x in parts[b]}
            ok = [sv for sv in cands if {int((t + sv) % m) for t in T} == sets[b]]
            if not ok:
                break
            choices.append(ok)
        if len(choices) < nb:
            continue
        for offs in itertools.product(*choices):
            off = np.array(offs)[blk]
            perm = build((u * cyc + off) % m)
            if inv(perm):
                out.append(perm)
                break
    return out


def structural_automorphisms(mats, n, max_multipliers=8):
    """Qubit permutations preserving each labelled matrix in ``mats``, found
    from the matrices alone: cyclic shifts within blocks (n = blocks x L,
    qubit = block*L + pos) and across them (qubit = pos*blocks + block, the
    interleaved layout), 2-D (l x m) shifts, and affine unit multipliers
    pos -> u*pos + s_block on a shift that was found (_affine_multipliers).
    Returns a list of int64 permutations (maybe empty). A permutation is
    accepted when it maps every matrix's row set, or failing that its row
    space, onto itself (_RowInvariance)."""
    inv = _RowInvariance(mats, n)
    idx = np.arange(n)
    gens = []
    for L in _divisors(n):
        if L < 2:
            continue
        blocks = n // L
        for layout in ("inner", "outer"):
            if layout == "inner":
                cyc, blk, m, nb = idx % L, idx // L, L, blocks
                build = lambda c, L=L: blk * L + c                 # noqa: E731
            else:
                if blocks < 2 or L == n // 2:          # outer at L is inner at n/L
                    continue
                cyc, blk, m, nb = idx // L, idx % L, blocks, L
                build = lambda c, L=L: c * L + blk                 # noqa: E731
            shift = build((cyc + 1) % m)
            if inv(shift):
                gens.append(shift)
                gens += _affine_multipliers(inv, mats[0], cyc, blk, m, nb, build,
                                            max_multipliers)
                break
        else:
            for rows_ in _divisors(L):              # 2-D shifts, inner layout only
                cols_ = L // rows_
                if rows_ < 2 or cols_ < 2:
                    continue
                base, pos = (idx // L) * L, idx % L
                a, b = pos // cols_, pos % cols_
                s1 = base + ((a + 1) % rows_) * cols_ + b
                s2 = base + a * cols_ + (b + 1) % cols_
                if inv(s1) and inv(s2):
                    gens.extend([s1, s2])
    return gens


def _rebuild_symmetric_checks(mats, n):
    """Rebuild a symmetric (shift-closed) check set before automorphism search.

    A row-reduced check matrix can hide a symmetry that its row space still has:
    the structural detectors accept such a matrix through their span test, but
    nauty builds its graph from the *rows*, so a row-reduced set exposes no
    automorphism.  When a structural shift is found, close the row set under it
    (all shifts of every row) and hand that symmetric set to nauty.  Matrices
    with no detectable shift are returned unchanged.  Returns a list of arrays.
    """
    out = []
    for Lab in mats:
        M = np.asarray(Lab)
        try:
            gens = structural_automorphisms([M], n)
        except Exception:
            gens = []
        if not gens:
            out.append(M.copy())
            continue
        rows = [r.copy() for r in M]
        seen = {tuple(r.tolist()) for r in rows}
        frontier = list(rows)
        # Bound the closure: a row space has dimension <= n, so more than a
        # small multiple of the original rows (or of n) is blowup, not signal.
        cap = max(M.shape[0] * 4, 2 * n)
        while frontier and len(rows) < cap:
            r = frontier.pop()
            for g in gens:
                invp = np.argsort(g)
                r2 = r[invp].copy()
                t = tuple(r2.tolist())
                if t not in seen:
                    seen.add(t)
                    rows.append(r2)
                    frontier.append(r2)
                    if len(rows) >= cap:
                        break
        if M.shape[0] < len(rows) <= cap:
            out.append(np.asarray(rows, dtype=M.dtype))
        else:
            out.append(M.copy())
    return out


def nauty_automorphisms(mats, n):
    """Generators of the Tanner-graph automorphism group restricted to qubits,
    via pynauty; [] when pynauty is not importable. Each matrix is a vertex
    colour; a labelled incidence (non-CSS) becomes an auxiliary vertex
    coloured by its label so Pauli types are preserved."""
    if _NautyGraph is None:
        return []
    mats = _rebuild_symmetric_checks(mats, n)
    adj = {}
    colours = [set(range(n))]
    nxt = n
    aux_colours = {}
    for M in mats:
        cls = set()
        for r in M:
            v = nxt
            nxt += 1
            cls.add(v)
            nz = np.flatnonzero(r)
            if (r[nz] == 1).all():
                adj[v] = [int(j) for j in nz]
            else:
                adj[v] = []
                for j in nz:
                    a = nxt
                    nxt += 1
                    adj[a] = [int(j), v]
                    aux_colours.setdefault(int(r[j]), set()).add(a)
        colours.append(cls)
    colours += [c for _, c in sorted(aux_colours.items())]
    g = _NautyGraph(nxt, directed=False, adjacency_dict=adj,
                    vertex_coloring=colours)
    gens, *_ = _nauty_autgrp(g)
    return [np.array(p[:n], dtype=np.int64) for p in gens]


def _perm_order(p):
    seen = np.zeros(len(p), dtype=bool)
    order = 1
    for s in range(len(p)):
        if seen[s]:
            continue
        cyc, j = 0, s
        while not seen[j]:
            seen[j] = True
            j = p[j]
            cyc += 1
        order = int(np.lcm(order, cyc))
    return order


def _perm_pow(p, k):
    r, b = np.arange(len(p)), p.copy()
    while k:
        if k & 1:
            r = b[r]
        b = b[b]
        k >>= 1
    return r


def _orbit_labels(p):
    lab = -np.ones(len(p), dtype=np.int64)
    c = 0
    for s in range(len(p)):
        if lab[s] >= 0:
            continue
        j = s
        while lab[j] < 0:
            lab[j] = c
            j = p[j]
        c += 1
    return lab, c


def orbit_partitions(gens, n, rng, max_words=24, max_partitions=80, min_orbits=4):
    """Orbit partitions of cyclic subgroups <h^k>, for h among the generators
    and a few random words in them, k a proper divisor of ord(h). Each entry is
    (labels, orbit_count, orbit_size_bound); coarsest first, deduplicated."""
    if not gens:
        return []
    elems = list(gens)
    ident = np.arange(n)
    for _ in range(max_words):
        w = ident
        for _ in range(int(rng.integers(2, 5))):
            g = gens[int(rng.integers(len(gens)))]
            if rng.random() < 0.5:
                g = np.argsort(g)                   # inverse
            w = g[w]
        elems.append(w)
    seen, out = set(), []
    for h in elems:
        o = _perm_order(h)
        if o == 1:
            continue
        for k in _divisors(o):
            if k == o:
                continue
            lab, c = _orbit_labels(_perm_pow(h, k))
            if c < min_orbits or c >= n:
                continue
            key = lab.tobytes()
            if key in seen:
                continue
            seen.add(key)
            out.append((lab, c, o // k))
    out.sort(key=lambda t: t[1])
    return out[:max_partitions]


_FOLD_EXHAUSTIVE_DIM = 14
# Threads for the accelerated fold loop; fixed so a verdict replays from its
# seed alone (the per-thread streams depend on the split), as in gate_changed.
FOLD_THREADS = 4


def _fold_search(F, Lf, sizes, trials, rng, best, pauli_c=None, deadline=None):
    """Lightest x with F x = 0, Lf x != 0, weight = sum of orbit sizes over
    supp(x) (for a Pauli fold, over supp(x_f) | supp(z_f)). Returns (w, x).

    The loop runs in the C++ accelerator (gf2_fast.fold_rand_witness) when it
    is built -- CI builds it, and the fold then costs well under a second on
    the board's largest entries -- and in python otherwise. Either way the
    result is a PROPOSAL: the caller lifts it and re-validates on the full
    matrices before it counts. The accelerator draws its own seed from
    ``rng`` so a run is reproducible from the printed seed."""
    if Lf.shape[0] == 0:
        return None, None
    if _fast is not None and hasattr(_fast, "fold_rand_witness"):
        w, sup = _fast.fold_rand_witness(
            F.astype(np.int8), Lf.astype(np.int8), [int(v) for v in sizes],
            int(pauli_c or 0), int(trials), int(rng.integers(2**62)), 8,
            _FOLD_EXHAUSTIVE_DIM, FOLD_THREADS)
        if w is None or w >= best:
            return None, None
        x = np.zeros(F.shape[1], dtype=np.int8)
        x[list(sup)] = 1
        return int(w), x
    K = gf2.kernel_basis(F)
    if K.shape[0] == 0:
        return None, None
    wit = None

    def weight(rows):
        if pauli_c is None:
            return rows.astype(np.int64) @ sizes
        return (rows[:, :pauli_c] | rows[:, pauli_c:]).astype(np.int64) @ sizes

    def consider(rows):
        nonlocal best, wit
        w = weight(rows)
        nontrivial = ((rows.astype(np.int64) @ Lf.T) % 2).any(1)
        for i in np.where(nontrivial & (w > 0) & (w < best))[0]:
            best, wit = int(w[i]), rows[i].copy()

    dim = K.shape[0]
    if dim <= _FOLD_EXHAUSTIVE_DIM:
        for msk in range(1, 1 << dim):
            bits = np.array([(msk >> b) & 1 for b in range(dim)], dtype=np.int64)
            consider(((bits @ K.astype(np.int64)) % 2).astype(np.int8)[None, :])
    else:
        for t in range(trials):
            red = _rref_perm(K, rng.permutation(K.shape[1]))
            consider(red)
            w = weight(red)
            light = np.argsort(w)[:8]
            sub = red[light]
            for a in range(len(light) - 1):
                consider(sub[a] ^ sub[a + 1:])
            if deadline and (t & 63) == 63 and time.monotonic() > deadline:
                break
    return (best, wit) if wit is not None else (None, None)


def orbit_fold_min_logical(HX, HZ, trials, seed, max_seconds=None, gens=None):
    """Orbit-fold search for the lightest X- and Z-type logicals of a CSS code.
    Returns {"X": (w, witness) | None, "Z": ..., "partitions": k} where every
    witness has been re-validated on the full matrices (_valid_logical).
    ``partitions`` is 0 when no symmetry was found (nothing searched)."""
    n = HX.shape[1]
    rng = np.random.default_rng(seed)
    if gens is None:
        gens = structural_automorphisms([HX, HZ], n) + nauty_automorphisms([HX, HZ], n)
    parts = orbit_partitions(gens, n, rng)
    out = {"X": None, "Z": None, "partitions": 0}
    if not parts:
        return out
    LZ = gf2.logical_basis(HX, HZ)              # anticommutation rows for X-type
    LX = gf2.logical_basis(HZ, HX)
    best = {"X": n + 1, "Z": n + 1}
    deadline = (time.monotonic() + max_seconds) if max_seconds else None
    for lab, c, _ in parts:
        if deadline and time.monotonic() > deadline:
            break
        out["partitions"] += 1
        P = np.zeros((n, c), dtype=np.int64)
        P[np.arange(n), lab] = 1
        sizes = P.sum(0)
        for side, H_ker, H_row, L in (("X", HZ, HX, LZ), ("Z", HX, HZ, LX)):
            F = ((H_ker.astype(np.int64) @ P) % 2).astype(np.int8)
            Lf = ((L.astype(np.int64) @ P) % 2).astype(np.int8)
            w, x = _fold_search(F, Lf, sizes, trials, rng, best[side], deadline=deadline)
            if x is None:
                continue
            v = ((P @ x.astype(np.int64)) % 2).astype(np.int8)
            if int(v.sum()) == w and _valid_logical(v, H_ker, H_row):
                best[side] = w
                out[side] = (w, v)
    return out


_FRAMES = [np.array(m, dtype=np.int64) for m in
           ([[1, 0], [0, 1]], [[0, 1], [1, 0]], [[1, 1], [0, 1]],
            [[1, 0], [1, 1]], [[1, 1], [1, 0]], [[0, 1], [1, 1]])]
_FRAMES_INV = [np.array([[m[1, 1], m[0, 1]], [m[1, 0], m[0, 0]]]) % 2 for m in _FRAMES]


def _apply_frame(M, fr, n, inverse=False):
    """Per-qubit symplectic frame on rows (x | z): a Y-heavy logical becomes
    X- or Z-heavy in some frame, where RIS sees it as sparse."""
    T = np.stack([(_FRAMES_INV if inverse else _FRAMES)[f] for f in fr])
    X, Z = M[:, :n].astype(np.int64), M[:, n:].astype(np.int64)
    Xn = (X * T[:, 0, 0] + Z * T[:, 0, 1]) % 2
    Zn = (X * T[:, 1, 0] + Z * T[:, 1, 1]) % 2
    return np.concatenate([Xn, Zn], axis=1).astype(np.int8)


def orbit_fold_min_pauli_logical(A, B, trials, seed, max_seconds=None, frames=12):
    """Stabilizer-code counterpart: orbit folds on Pauli vectors (x | z) plus
    RIS in ``frames`` random single-qubit Pauli frames. Returns
    {"P": (w, witness) | None, "partitions": k, "frames": f}; the witness is a
    2n Pauli vector validated by valid_pauli_logical."""
    n = A.shape[1]
    rng = np.random.default_rng(seed)
    S, SL = doubled_matrices(A, B)
    L = gf2.logical_basis(SL, S)
    LS = np.concatenate([L[:, n:], L[:, :n]], axis=1)
    out = {"P": None, "partitions": 0, "frames": 0}
    if L.shape[0] == 0:
        return out
    best = n + 1
    deadline = (time.monotonic() + max_seconds) if max_seconds else None
    Lab = (A.astype(np.int64) + 2 * B.astype(np.int64)).astype(np.int8)
    gens = structural_automorphisms([Lab], n) + nauty_automorphisms([Lab], n)
    for lab, c, _ in orbit_partitions(gens, n, rng):
        if deadline and time.monotonic() > deadline:
            break
        out["partitions"] += 1
        P = np.zeros((n, c), dtype=np.int64)
        P[np.arange(n), lab] = 1
        sizes = P.sum(0)
        P2 = np.zeros((2 * n, 2 * c), dtype=np.int64)
        P2[:n, :c] = P
        P2[n:, c:] = P
        F = ((SL.astype(np.int64) @ P2) % 2).astype(np.int8)     # (B P | A P)
        Lf = ((LS.astype(np.int64) @ P2) % 2).astype(np.int8)
        w, x = _fold_search(F, Lf, sizes, trials, rng, best, pauli_c=c, deadline=deadline)
        if x is None:
            continue
        v = ((P2 @ x.astype(np.int64)) % 2).astype(np.int8)
        if int(pauli_weight_rows(v[None, :], n)[0]) == w and valid_pauli_logical(v, A, B):
            best, out["P"] = w, (w, v)
    for _ in range(frames):
        if deadline and time.monotonic() > deadline:
            break
        out["frames"] += 1
        fr = rng.integers(0, 6, n)
        Sf = _apply_frame(np.concatenate([A, B], axis=1).astype(np.int8), fr, n)
        HX2, SLf = doubled_matrices(Sf[:, :n], Sf[:, n:])
        if _fast is not None:
            # Accelerated: Hamming-weight RIS on the framed doubling (an upper
            # bound on the Pauli weight); the find is unframed, re-scored by
            # Pauli weight and validated before it counts.
            d_fast, side, sup = _fast.distance_rand_witness(
                HX2, SLf, min(4 * int(trials), FRAME_TRIALS_MAX),
                int(rng.integers(2**62)), 8, FOLD_THREADS)
            if side in ("X", "Z"):
                v = np.zeros(2 * n, dtype=np.int8)
                v[list(sup)] = 1
                v = _pauli_from_doubled(v, side, n)
                back = _apply_frame(v[None, :], fr, n, inverse=True)[0]
                wi = int(pauli_weight_rows(back[None, :], n)[0])
                if wi < best and valid_pauli_logical(back, A, B):
                    best, out["P"] = wi, (wi, back.copy())
            continue
        K = gf2.kernel_basis(SLf)
        if K.shape[0] == 0:
            break
        for t in range(max(1, min(trials, FRAME_TRIALS_MAX) // 3)):
            if deadline and (t & 15) == 15 and time.monotonic() > deadline:
                break
            red = _rref_perm(K, rng.permutation(2 * n))
            cands = [red]
            w = pauli_weight_rows(red, n)
            sub = red[np.argsort(w)[:8]]
            for a in range(len(sub) - 1):
                cands.append(sub[a] ^ sub[a + 1:])
            for cand in cands:
                arr = np.asarray(cand, dtype=np.int8)
                w = pauli_weight_rows(arr, n)
                keep = (w > 0) & (w < best)
                if not keep.any():
                    continue
                back = _apply_frame(arr[keep], fr, n, inverse=True)
                for i in np.where(((back.astype(np.int64) @ LS.T) % 2).any(1))[0]:
                    wi = int(pauli_weight_rows(back[i][None, :], n)[0])
                    if wi < best and valid_pauli_logical(back[i], A, B):
                        best, out["P"] = wi, (wi, back[i].copy())
    return out



def _sat_available():
    try:
        import pycryptosat  # noqa: F401
        from pysat.card import CardEnc  # noqa: F401
        return True
    except Exception:
        return False


def _sat_fold_side(F, Lf, sizes, claimed, time_limit):
    """SAT fold on one side.  F is the folded check matrix (m x c), Lf the
    folded logical generators (k x c); ``sizes[j]`` is the orbit size of column
    j.  Returns (weight, x) with weight < claimed, or None."""
    if not _sat_available():
        return None
    if Lf is None or Lf.shape[0] == 0:
        return None
    from pycryptosat import Solver
    from pysat.card import CardEnc, EncType
    _, c = F.shape
    W = int(claimed) - 1
    if W < 1:
        return None
    # Weighted cardinality via expanded (duplicate) literals.
    expanded = []
    for j in range(c):
        expanded.extend([j + 1] * int(sizes[j]))
    s = Solver(threads=1)
    for row in F:
        idx = [int(j) + 1 for j in range(c) if row[j]]
        if idx:
            s.add_xor_clause(idx, False)
    top = c
    selectors = []
    for t in range(Lf.shape[0]):
        top += 1
        selectors.append(top)
        tidx = [int(j) + 1 for j in range(c) if Lf[t, j]]
        s.add_xor_clause(tidx + [top], False)
    if not selectors:
        return None
    s.add_clause(selectors)
    card = CardEnc.atmost(lits=expanded, bound=W, top_id=top,
                          encoding=EncType.seqcounter)
    top = max(top, card.nv)
    for cl in card.clauses:
        s.add_clause(cl)
    sat, sol = s.solve(time_limit=time_limit)
    if not sat:
        return None
    x = np.array([1 if sol[j + 1] else 0 for j in range(c)], dtype=np.int8)
    w = int(sum(int(sizes[j]) for j in range(c) if x[j]))
    if w <= 0 or w >= claimed:
        return None
    return w, x


def _sat_fold_partition(P, sizes, HX, HZ, claimed, time_budget):
    """Try both sides on one orbit partition.  Returns (side, weight, full_vector)
    or None."""
    # X side: v in ker HZ, outside rowspace HX.
    Fx = (HZ @ P) % 2
    Lx = gf2.logical_basis(HX, HZ)
    Lfx = (Lx @ P) % 2
    # Z side.
    Fz = (HX @ P) % 2
    Lz = gf2.logical_basis(HZ, HX)
    Lfz = (Lz @ P) % 2
    per_side = max(1.0, time_budget / 2.0)
    for side, F, Lf in (("X", Fx, Lfx), ("Z", Fz, Lfz)):
        res = _sat_fold_side(F, Lf, sizes, claimed, per_side)
        if res is None:
            continue
        w, x = res
        v = (P @ x).astype(np.int8)
        H_ker, H_row = (HZ, HX) if side == "X" else (HX, HZ)
        if _valid_logical(v, H_ker, H_row):
            return side, int(v.sum()), v
    return None


def orbit_fold_sat_refute(doc, seed=0, max_seconds=60.0, gens=None):
    """SAT-fold refutation stage (optional; needs pycryptosat + python-sat).
    Returns (refuted, d_found, witness, partitions) like orbit_fold_refute."""
    if not _sat_available():
        return False, None, None, 0
    n = doc["n"]
    claimed = int(doc["distance"]["d"])
    if _is_stabilizer(doc):
        return False, None, None, 0
    HX = _matrix(doc["checks"]["X"], n)
    HZ = _matrix(doc["checks"]["Z"], n)
    if gens is None:
        gens = structural_automorphisms([HX, HZ], n) + nauty_automorphisms([HX, HZ], n)
    if not gens:
        return False, None, None, 0
    rng = np.random.default_rng(seed)
    parts = orbit_partitions(gens, n, rng)
    if not parts:
        return False, None, None, 0
    # Per-partition time share so a slow solver does not consume the whole budget
    # on the first partition.
    per_part = max(1.0, max_seconds / max(1, len(parts)))
    t0 = time.monotonic()
    searched = 0
    for part in parts:
        if time.monotonic() - t0 >= max_seconds:
            break
        labels, c, _ = part
        sizes = np.array([int(np.sum(labels == j)) for j in range(c)], dtype=int)
        P = np.zeros((n, c), dtype=np.int8)
        for q in range(n):
            P[q, int(labels[q])] = 1
        remaining = min(per_part, max_seconds - (time.monotonic() - t0))
        if remaining <= 0:
            break
        res = _sat_fold_partition(P, sizes, HX, HZ, claimed, remaining)
        searched += 1
        if res is not None:
            side, w, v = res
            H_ker, H_row = (HZ, HX) if side == "X" else (HX, HZ)
            if _valid_logical(v, H_ker, H_row) and w < claimed:
                return True, int(v.sum()), sorted(int(q) for q in np.nonzero(v)[0]), searched
    return False, None, None, searched


def orbit_fold_refute(doc, seed=0, trials=300, max_seconds=60.0):
    """Gate mechanism in the refute_check tuple shape: (refuted, d_found,
    witness, searched). ``searched`` is the number of orbit partitions (plus
    frames, for a stabilizer code) actually searched; 0 means the code showed
    no usable symmetry and nothing ran, so the caller leaves the mechanism out
    of its method list rather than recording a meaningless null result."""
    n = doc["n"]
    claimed = int(doc["distance"]["d"])
    if _is_stabilizer(doc):
        A, B = stabilizer_matrices(doc)
        res = orbit_fold_min_pauli_logical(A, B, trials, seed, max_seconds=max_seconds)
        searched = res["partitions"] + res["frames"]
        if res["P"] is None:
            return False, None, None, searched
        w, v = res["P"]
        return (w < claimed), w, (pauli_witness(v, n) if w < claimed else None), searched
    HX = _matrix(doc["checks"]["X"], n)
    HZ = _matrix(doc["checks"]["Z"], n)
    gens = structural_automorphisms([HX, HZ], n) + nauty_automorphisms([HX, HZ], n)
    res = orbit_fold_min_logical(HX, HZ, trials, seed, max_seconds=max_seconds,
                                 gens=gens)
    found = [res[s] for s in ("X", "Z") if res[s] is not None]
    if found:
        w, v = min(found, key=lambda t: t[0])
        if w < claimed:
            wit = sorted(int(j) for j in np.nonzero(v)[0])
            return True, w, wit, res["partitions"]
    # SAT fold fallback for large folded kernels (optional; needs python-sat).
    if _sat_available() and gens:
        sref, sw, swit, sp = orbit_fold_sat_refute(doc, seed=seed + 97,
                                                  max_seconds=max(5.0, 0.5 * max_seconds),
                                                  gens=gens)
        if sref:
            return True, sw, swit, res["partitions"] + sp
    if found:
        w, v = min(found, key=lambda t: t[0])
        wit = sorted(int(j) for j in np.nonzero(v)[0]) if w < claimed else None
        return (w < claimed), w, wit, res["partitions"]
    return False, None, None, res["partitions"]


def _merge_fold(sides, res, n):
    """Fold results into estimate()'s ``sides`` (min per side, witness recorded)."""
    for side in ("X", "Z", "P"):
        hit = res.get(side)
        if hit is None:
            continue
        w, v = hit
        cur = sides.get(side, {}).get("lightest_found")
        if cur is None or w < cur:
            sides.setdefault(side, {"value": None})
            sides[side].update(
                lightest_found=w,
                witness=(pauli_witness(v, n) if side == "P"
                         else sorted(int(j) for j in np.nonzero(v)[0])))


def _estimate_stabilizer(doc, trials, seed, fast_trials, max_seconds,
                         fold_trials=0, capture=None):
    """Run estimate() for a stabilizer code: one Pauli-weight side, P. The
    orbit-fold + random-frame pass (orbit_fold_min_pauli_logical) runs first
    when ``fold_trials`` > 0, under its own cap, as in the CSS path."""
    n = doc["n"]
    A, B = stabilizer_matrices(doc)
    claimed = int(doc["distance"]["d"])
    sides = {}
    fold = None
    if fold_trials:
        fold = orbit_fold_min_pauli_logical(A, B, fold_trials, seed + 5,
                                            max_seconds=_fold_seconds(max_seconds))
        _merge_fold(sides, fold, n)
        if capture is not None and fold.get("P") is not None:
            capture.add_vector("P", fold["P"][1], fold["P"][0])
    wP, witP = ris_min_pauli_logical(A, B, trials, seed, max_seconds=max_seconds,
                                     capture=capture.side("P") if capture is not None else None)
    cur = sides.get("P", {}).get("lightest_found")
    if wP is not None and (cur is None or wP < cur):
        sides["P"] = {"lightest_found": wP, "witness": pauli_witness(witP, n)}
    if "P" in sides:
        sides["P"]["value"] = doc["distance"].get("P", {}).get("value")
    d_heur = sides["P"]["lightest_found"] if "P" in sides else None

    method = "ris-pauli"
    if fold is not None and (fold["partitions"] or fold["frames"]):
        method += f"+orbit-fold({fold['partitions']}+{fold['frames']}f)"
    if _fast is not None and 0 < fast_trials <= trials:
        print(f"warning: gf2_fast is available but skipped "
              f"(fast_trials={fast_trials} <= trials={trials}); raise "
              f"--fast-trials or lower --trials to use the accelerator "
              f"(fast_trials=0 disables it deliberately)", file=sys.stderr)
    if _fast is not None and fast_trials > trials:
        # The accelerator searches the doubled CSS code by Hamming weight over
        # 2n bits, an upper bound on the Pauli weight (a Y is two bits, one
        # qubit). Its proposal is mapped back to a Pauli, validated by the
        # pinned python stack, and re-scored by Pauli weight; only then may
        # it tighten the verdict.
        HX2, HZ2 = doubled_matrices(A, B)
        d_fast, side, sup = _fast.distance_rand_witness(HX2, HZ2, fast_trials,
                                                        seed, 8, 8)
        if d_fast is not None and side in ("X", "Z"):
            v = np.zeros(2 * n, dtype=np.int8)
            v[list(sup)] = 1
            v = _pauli_from_doubled(v, side, n)
            if valid_pauli_logical(v, A, B):
                wp = int(pauli_weight_rows(v[None, :], n)[0])
                if d_heur is None or wp < d_heur:
                    d_heur = wp
                    sides.setdefault("P", {})
                    sides["P"].update(lightest_found=wp,
                                      witness=pauli_witness(v, n))
        method += "+gf2_fast(doubled)"
        trials = max(trials, fast_trials)

    if d_heur is None:
        verdict = "inconclusive"
    elif d_heur < claimed:
        verdict = "refuted"
    elif d_heur == claimed:
        verdict = "corroborated"
    else:
        verdict = "inconclusive"
    res = {"name": doc.get("name", ""), "claimed_d": claimed,
           "d_heuristic": d_heur, "verdict": verdict,
           "sides": sides, "trials": trials, "seed": seed, "method": method,
           "fold_partitions": (fold["partitions"] + fold["frames"]) if fold else 0}
    if capture is not None:
        capture.result = res
    return res


def estimate(doc, trials=20000, seed=0, fast_trials=400000, max_seconds=None,
             fold_trials=FOLD_TRIALS_DEFAULT, capture=None):
    """Heuristic distance verdict for a submission `doc`.

    ``trials`` is the pure-Python RIS budget per side; ``fast_trials`` is the
    gf2_fast accelerator's overall budget, used only when it exceeds ``trials``
    (the fast path reports weights, not witnesses, so it must out-search the
    Python pass to add anything). Pass ``fast_trials=0`` to disable the
    accelerator explicitly (refute_check does: the CI gate is pure Python with
    a fixed seed, so it stays deterministic). Any other skipped-accelerator
    combination warns on stderr -- see issue #290.

    ``fold_trials`` is the orbit-fold budget (RIS trials per folded code; see
    orbit_fold_min_logical). It runs first, under its own small wall-clock
    cap (_fold_seconds), so the RIS budget below is unchanged by it; pass
    ``fold_trials=0`` to skip it (the gate does, after running the fold at a
    larger budget as its own stage).

    A stabilizer code (code_type "stabilizer") takes _estimate_stabilizer:
    one Pauli-weight side P, the whole budget on it.

    ``capture`` (a ``recapture.Capture``, issue #2897) collects every logical
    the RIS passes see at weight <= its threshold, plus the fold pass's
    validated find per side, and receives this function's report as
    ``capture.result``. It changes nothing about the verdict."""
    if _is_stabilizer(doc):
        return _estimate_stabilizer(doc, trials, seed, fast_trials, max_seconds,
                                    fold_trials=fold_trials, capture=capture)
    n = doc["n"]
    HX = _matrix(doc["checks"]["X"], n)
    HZ = _matrix(doc["checks"]["Z"], n)
    claimed = int(doc["distance"]["d"])

    sides = {}
    fold = None
    if fold_trials:
        fold = orbit_fold_min_logical(HX, HZ, fold_trials, seed + 5,
                                      max_seconds=_fold_seconds(max_seconds))
        _merge_fold(sides, fold, n)
        if capture is not None:
            for side in ("X", "Z"):
                if fold.get(side) is not None:
                    capture.add_vector(side, fold[side][1], fold[side][0])
    half = (max_seconds / 2) if max_seconds else None       # split budget per side
    sink_x = capture.side("X") if capture is not None else None
    sink_z = capture.side("Z") if capture is not None else None
    wX, witX = ris_min_logical(HX, HZ, trials, seed, max_seconds=half, capture=sink_x)      # X (ker HZ)
    wZ, witZ = ris_min_logical(HZ, HX, trials, seed + 1, max_seconds=half, capture=sink_z)  # Z (ker HX)
    for side, w, wit in (("X", wX, witX), ("Z", wZ, witZ)):
        cur = sides.get(side, {}).get("lightest_found")
        if w is not None and (cur is None or w < cur):
            sides[side] = {"lightest_found": w,
                           "witness": sorted(int(j) for j in np.nonzero(wit)[0])}
    for side, block in sides.items():
        block["value"] = doc["distance"].get(side, {}).get("value")
    d_heur = min([b["lightest_found"] for b in sides.values()], default=None)

    method = "ris"
    if fold is not None and fold["partitions"]:
        method += f"+orbit-fold({fold['partitions']})"
    if _fast is not None and 0 < fast_trials <= trials:
        print(f"warning: gf2_fast is available but skipped "
              f"(fast_trials={fast_trials} <= trials={trials}); raise "
              f"--fast-trials or lower --trials to use the accelerator "
              f"(fast_trials=0 disables it deliberately)", file=sys.stderr)
    # Optional C++ accelerator: a larger overall search (min over both sides).
    if _fast is not None and fast_trials > trials:
        # Take the witness straight from the accelerator rather than asking the
        # Python pass to re-find it. The re-find never worked at large n: the
        # accelerator is orders of magnitude faster per trial, so a budget that
        # lets it reach weight w leaves the Python pass far short of w, and the
        # tighter weight was recorded with no witness to back it.
        d_fast, side, sup = _fast.distance_rand_witness(HX, HZ, fast_trials,
                                                        seed, 8, 8)
        d_fast = int(d_fast) if d_fast is not None else None
        if d_fast is not None and (d_heur is None or d_fast < d_heur):
            d_heur = d_fast
            if side in ("X", "Z"):
                wit = np.zeros(n, dtype=np.int8)
                wit[list(sup)] = 1
                # Validate before recording: the accelerator is not the trusted
                # stack, so a witness only counts once gf2 agrees it is in the
                # right kernel and outside the opposite rowspace.
                H_ker, H_row = (HZ, HX) if side == "X" else (HX, HZ)
                if _valid_logical(wit, H_ker, H_row):
                    sides.setdefault(side, {})
                    sides[side].update(
                        lightest_found=int(wit.sum()),
                        witness=sorted(int(j) for j in np.nonzero(wit)[0]))
        method += "+gf2_fast"
        trials = max(trials, fast_trials)

    if d_heur is None:
        verdict = "inconclusive"
    elif d_heur < claimed:
        verdict = "refuted"          # found a lighter logical -> claim over-stated
    elif d_heur == claimed:
        verdict = "corroborated"     # found exactly the claimed weight, none lighter
    else:
        verdict = "inconclusive"     # budget too small to even reach the claimed weight

    res = {"name": doc.get("name", ""), "claimed_d": claimed,
           "d_heuristic": d_heur, "verdict": verdict,
           "sides": sides, "trials": trials, "seed": seed, "method": method,
           "fold_partitions": fold["partitions"] if fold else 0}
    if capture is not None:
        capture.result = res
    return res


def refute_check(doc, seed=0, max_seconds=10.0, trials=None,
                 fold_trials=FOLD_TRIALS_DEFAULT, capture=None):
    """CI gate. Run a bounded, time-capped RIS search and report whether it found a
    logical LIGHTER than the claimed distance. Returns (refuted, d_found, witness,
    trials). Sound (the witness is a checkable lighter logical) but not complete (a
    null result is not a proof); pure Python with a fixed seed, so deterministic and
    non-flaky. Budget is n-scaled trials under a wall-clock cap; pass ``trials`` to
    override the default target (the CI gate scales both with code size).
    ``capture`` is handed to estimate() unchanged (the weekly sweep's recapture
    record, issue #2897); the gate never passes one."""
    n = doc["n"]
    if trials is None:
        trials = min(8000, 2500 + 40 * n)
    res = estimate(doc, trials=trials, seed=seed, fast_trials=0,
                   max_seconds=max_seconds, fold_trials=fold_trials,
                   capture=capture)
    claimed = int(doc["distance"]["d"])
    dh = res["d_heuristic"]
    refuted = dh is not None and dh < claimed
    witness = None
    if refuted:
        for s in res["sides"].values():
            if s.get("lightest_found") == dh:
                witness = s["witness"]
                break
    return refuted, dh, witness, res["trials"]


def main(path, trials, seed, fast_trials=None, fold_trials=FOLD_TRIALS_DEFAULT):
    doc = json.load(open(path))
    # A bigger --trials budget must never silently turn the accelerator off
    # (issue #290): unless --fast-trials is given explicitly, scale the fast
    # budget with the requested depth. --fast-trials 0 forces pure Python.
    if fast_trials is None:
        fast_trials = max(400000, 4 * trials)
    res = estimate(doc, trials=trials, seed=seed, fast_trials=fast_trials,
                   fold_trials=fold_trials)
    print(json.dumps(res, indent=2))
    return 2 if res["verdict"] == "refuted" else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--trials", type=int, default=20000,
                    help="pure-Python RIS trials per side (default 20000)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--fast-trials", type=int, default=None,
                    help="gf2_fast overall trial budget (default: "
                         "max(400000, 4*trials)); 0 disables the accelerator")
    ap.add_argument("--fold-trials", type=int, default=FOLD_TRIALS_DEFAULT,
                    help="orbit-fold RIS trials per folded code (default "
                         f"{FOLD_TRIALS_DEFAULT}); 0 disables the fold pass")
    args = ap.parse_args()
    sys.exit(main(args.path, args.trials, args.seed, args.fast_trials,
                  args.fold_trials))
