"""Minimum-stabilizer-support invariant of a CSS code (arXiv:2609.36213, Sec. 4).

What it computes, in order:

1. Every vector of weight <= ``wmax`` in ker H_Z and in ker H_X, EXACTLY, by
   meet-in-the-middle over supports of size <= ceil(wmax/2): two supports with
   the same syndrome differ by a kernel vector, and every kernel vector of
   weight <= wmax splits into two such halves. ``wmax`` defaults to the
   lightest check row, so the search always reaches the rows themselves and
   the minimum stabilizer weight comes out exact, not estimated.
2. The split of those vectors into stabilizers (in the opposite-type rowspace)
   and logicals. A logical of weight <= wmax found here is an exact ``d <=``
   statement and none found is an exact ``d > wmax``; this is a by-product,
   not a certifier. The board's distance arbiter is still
   ``verify/validate_candidate.py``.
3. The set of supports of the minimum-weight stabilizers (X- and Z-type
   together, as supports), the qubit/support incidence graph Gamma, the
   order of Aut(Gamma) and its orbits on qubits.

Why: a qubit permutation, with or without single-qubit Cliffords, that maps
one stabilizer code onto another maps minimum stabilizer supports onto
minimum stabilizer supports, so Aut(Gamma) is an invariant of the code under
that equivalence. An ordinary abelian 2BGA / bivariate-bicycle code of length
n carries a free translation action of order n/2 on each block that preserves
its stabilizer group, hence embeds in Aut(Gamma). So when n/2 does not divide
|Aut(Gamma)|, or Aut(Gamma) has more than two qubit orbits, or some orbit is
not a multiple of n/2 long, the code is not permutation-equivalent to ANY
abelian 2BGA code; the paper's Theorem 4.3 is the n = 144 case (|Aut| = 12
against 72). The converse is not claimed: a code that passes merely has not
been ruled out. This is a second notion of "same code wearing a different
hat" next to ``provenance.clifford_relabel_of`` (issue #2802), which is about
block Cliffords rather than permutations.

Backends for Aut(Gamma): ``pynauty`` when importable (instant; run with
``uv run --with pynauty ...``), else networkx VF2++, which is fine at n ~ 150
with a small automorphism group but can take an hour on a small, highly
symmetric code, so the fallback stops at ``aut_cap`` automorphisms and says
so in the report.

CLI: ``uv run python research/kit/supports.py codes/<slug>.json [--wmax W]``
prints the report as JSON.
"""

import json
import os
import sys
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "..", "verify"))
import gf2  # noqa: E402


# ----------------------------------------------------------------------
#  Exact low-weight kernel enumeration (meet in the middle)
# ----------------------------------------------------------------------
def _pack_cols(H):
    """Pack each column of H into ceil(m/64) uint64 words (bit i = row i)."""
    H = (np.asarray(H) % 2).astype(np.uint8)
    m, n = H.shape
    nw = (m + 63) // 64
    out = np.zeros((n, nw), dtype=np.uint64)
    for w in range(nw):
        rows = H[w * 64 : (w + 1) * 64]
        bits = rows.astype(np.uint64) << np.arange(rows.shape[0], dtype=np.uint64)[:, None]
        out[:, w] = bits.sum(axis=0, dtype=np.uint64)
    return out


def _combos(n, s):
    """All s-subsets of range(n) as an int16 array of shape (C(n, s), s), lexicographic."""
    if s == 0:
        return np.zeros((1, 0), dtype=np.int16)
    if s == 1:
        return np.arange(n, dtype=np.int16)[:, None]
    prev = _combos(n, s - 1)
    parts = []
    for i in range(n):
        sub = prev[prev[:, 0] > i]
        if sub.size == 0:
            continue
        parts.append(np.concatenate([np.full((sub.shape[0], 1), i, dtype=np.int16), sub], axis=1))
    return np.concatenate(parts)


def low_weight_kernel(H, wmax, *, chunk=2_000_000):
    """Return every nonzero v with H v = 0 over GF(2) and |v| <= wmax, exactly.

    Vectors come back as a set of frozensets of column indices, plus a small
    dict of work counters. Cost is dominated by the C(n, ceil(wmax/2))
    half-supports enumerated: n = 144, wmax = 8 is 17.7 M supports and about
    15 s; n = 300, wmax = 8 is 330 M and out of reach of a laptop.
    """
    H = np.asarray(H) % 2
    m, n = H.shape
    h = (wmax + 1) // 2
    cb = _pack_cols(H)
    nw = cb.shape[1]
    sup_parts, syn_parts, size_parts = [], [], []
    for s in range(h + 1):
        C = _combos(n, s)
        K = C.shape[0]
        syn = np.zeros((K, nw), dtype=np.uint64)
        if s > 0:
            for a in range(0, K, chunk):
                syn[a : a + chunk] = np.bitwise_xor.reduce(cb[C[a : a + chunk].astype(np.int64)], axis=1)
        pad = np.full((K, h), -1, dtype=np.int16)
        pad[:, :s] = C
        sup_parts.append(pad)
        syn_parts.append(syn)
        size_parts.append(np.full(K, s, dtype=np.int8))
    sup = np.concatenate(sup_parts)
    syn = np.concatenate(syn_parts)
    size = np.concatenate(size_parts)
    order = np.lexsort([syn[:, w] for w in range(nw)])
    syn, sup, size = syn[order], sup[order], size[order]
    change = np.any(syn[1:] != syn[:-1], axis=1)
    starts = np.concatenate([[0], np.nonzero(change)[0] + 1, [len(syn)]])
    found = set()
    pairs = 0
    for a, b in zip(starts[:-1], starts[1:]):
        if b - a < 2:
            continue
        sets = [frozenset(int(x) for x in sup[i][: size[i]]) for i in range(a, b)]
        for i, Si in enumerate(sets):
            for Sj in sets[i + 1 :]:
                pairs += 1
                v = Si ^ Sj
                if 0 < len(v) <= wmax:
                    found.add(v)
    for v in found:  # belt and braces: re-check against H
        x = np.zeros(n, dtype=np.int8)
        x[list(v)] = 1
        assert not ((H @ x) % 2).any()
    return found, {"half_supports": int(len(syn)), "collision_pairs": pairs}


def split_stabilizers(vectors, H_same, n):
    """Split vectors of ker(H_opposite) into (stabilizers, logicals) by membership in rowspace(H_same)."""
    R, piv = gf2.rref(H_same)
    stab, logi = set(), set()
    for v in vectors:
        x = np.zeros(n, dtype=np.int8)
        x[list(v)] = 1
        for i, c in enumerate(piv):
            if x[c]:
                x ^= R[i]
        (stab if not x.any() else logi).add(v)
    return stab, logi


# ----------------------------------------------------------------------
#  Incidence graph and its automorphisms
# ----------------------------------------------------------------------
def automorphisms(n, supports, *, aut_cap=200_000):
    """Order of Aut(Gamma) and the qubit orbit sizes for the qubit/support incidence graph.

    Returns ``(order, orbit_sizes, backend, capped)``. Vertex colours keep
    qubits and supports apart. With pynauty the order is exact; with the
    networkx fallback enumeration stops at ``aut_cap`` and ``capped`` says so.
    """
    supports = sorted(supports, key=sorted)
    try:
        import pynauty
    except ImportError:
        pynauty = None
    if pynauty is not None:
        adj = {q: [] for q in range(n)}
        for i, S in enumerate(supports):
            adj[n + i] = sorted(S)
        g = pynauty.Graph(
            n + len(supports),
            directed=False,
            adjacency_dict=adj,
            vertex_coloring=[set(range(n)), set(range(n, n + len(supports)))],
        )
        _gens, size1, size2, orbit_ids, _norb = pynauty.autgrp(g)
        order = int(round(size1 * 10**size2))
        counts = {}
        for q in range(n):
            counts[orbit_ids[q]] = counts.get(orbit_ids[q], 0) + 1
        return order, sorted(counts.values()), "pynauty", False

    import networkx as nx
    from networkx.algorithms.isomorphism import vf2pp_all_isomorphisms

    G = nx.Graph()
    for q in range(n):
        G.add_node(("q", q), kind="q")
    for i, S in enumerate(supports):
        G.add_node(("s", i), kind="s")
        G.add_edges_from((("s", i), ("q", q)) for q in S)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    count = 0
    for iso in vf2pp_all_isomorphisms(G, G, node_label="kind"):
        count += 1
        for q in range(n):
            ra, rb = find(q), find(iso[("q", q)][1])
            if ra != rb:
                parent[ra] = rb
        if count >= aut_cap:
            break
    sizes = {}
    for q in range(n):
        sizes[find(q)] = sizes.get(find(q), 0) + 1
    return count, sorted(sizes.values()), "networkx", count >= aut_cap


def abelian_2bga_obstruction(HX, HZ, *, wmax=None, aut_cap=200_000):
    """Run the whole invariant on (HX, HZ) and return the report dict.

    ``abelian_2bga_realization_possible`` is False exactly when the invariant
    rules an abelian 2BGA / BB realization out; True means not ruled out.
    """
    HX = np.asarray(HX) % 2
    HZ = np.asarray(HZ) % 2
    n = HX.shape[1]
    if wmax is None:
        wmax = int(min(HX.sum(1).min(), HZ.sum(1).min()))
    t0 = time.time()
    kerZ, infoZ = low_weight_kernel(HZ, wmax)  # X-type operators
    kerX, infoX = low_weight_kernel(HX, wmax)  # Z-type operators
    xs, xl = split_stabilizers(kerZ, HX, n)
    zs, zl = split_stabilizers(kerX, HZ, n)
    wmin = min(len(v) for v in xs | zs)
    xmin = {v for v in xs if len(v) == wmin}
    zmin = {v for v in zs if len(v) == wmin}
    minsup = xmin | zmin
    rows = [frozenset(np.nonzero(r)[0].tolist()) for r in HX] + [frozenset(np.nonzero(r)[0].tolist()) for r in HZ]
    t1 = time.time()
    order, orbits, backend, capped = automorphisms(n, minsup, aut_cap=aut_cap)
    half = n // 2
    divides = order % half == 0
    orbits_ok = len(orbits) <= 2 and all(s % half == 0 for s in orbits)
    return {
        "n": n,
        "wmax": wmax,
        "min_stabilizer_weight": wmin,
        "x_stabilizers_le_wmax": len(xs),
        "z_stabilizers_le_wmax": len(zs),
        "lightest_x_logical_le_wmax": min((len(v) for v in xl), default=None),
        "lightest_z_logical_le_wmax": min((len(v) for v in zl), default=None),
        "min_supports": len(minsup),
        "x_min_supports": len(xmin),
        "z_min_supports": len(zmin),
        "xz_shared_min_supports": len(xmin & zmin),
        "rows_are_exactly_the_min_supports": set(rows) == minsup,
        "aut_order": order,
        "aut_backend": backend,
        "aut_capped": capped,
        "qubit_orbit_sizes": orbits,
        "half_n_divides_aut": divides,
        "orbits_compatible_with_2bga": orbits_ok,
        "abelian_2bga_realization_possible": divides and orbits_ok,
        "work": {
            "ker_HZ": infoZ,
            "ker_HX": infoX,
            "seconds_enumeration": round(t1 - t0, 1),
            "seconds_automorphisms": round(time.time() - t1, 1),
        },
    }


def _from_doc(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    n = d["n"]
    HX = np.zeros((len(d["checks"]["X"]), n), dtype=np.int8)
    HZ = np.zeros((len(d["checks"]["Z"]), n), dtype=np.int8)
    for i, r in enumerate(d["checks"]["X"]):
        HX[i, r] = 1
    for i, r in enumerate(d["checks"]["Z"]):
        HZ[i, r] = 1
    return HX, HZ


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("doc", help="submission JSON (codes/<slug>.json or a staged candidate)")
    ap.add_argument("--wmax", type=int, default=None, help="weight bound (default: lightest check)")
    ap.add_argument("--aut-cap", type=int, default=200_000)
    args = ap.parse_args()
    HX, HZ = _from_doc(args.doc)
    print(json.dumps(abelian_2bga_obstruction(HX, HZ, wmax=args.wmax, aut_cap=args.aut_cap), indent=1))
