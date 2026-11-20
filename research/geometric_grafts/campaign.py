"""Exact-d contraction campaign on the affine checkerboard base.

Beats the randomized surrogate at d = 3: "no logical of weight <= 2" is decidable
by enumeration over columns of the opposite check matrix, not by sampling.

    v = e_q          commutes  <=>  H_opp[:, q] == 0
    v = e_q + e_r    commutes  <=>  H_opp[:, q] == H_opp[:, r]

so both sides are exactly a column-equality question, and non-triviality is a
rowspace membership test. A surviving candidate therefore has d >= 3 with no
statistical caveat, which is what lets the search accept a removal with
confidence at a fraction of the cost of a trial budget.

Moves are r=1 grafts (a qubit in exactly one stabilizer of its own type, removed
with that stabilizer) -- commutation is preserved by construction and k is
re-checked after each one. Acceptance: k unchanged, exact d >= 3, one connected
stabilizer block.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "verify/gf2.py").exists())
sys.path[:0] = [
    str(ROOT / "research/kit"),
    str(ROOT / "verify"),
    str(ROOT / "research/local2d"),
    str(HERE / "874-157-3"),
]

from gf2 import rref  # noqa: E402
from qldpc_verify import _stabilizer_block_count  # noqa: E402
from reproduce import construct, supports  # noqa: E402

try:
    import gf2_fast as _fast
except ImportError:  # portable fallback
    _fast = None


def _rref(H):
    """RREF over GF(2), native when the extension is built."""
    return _fast.gf2_rref(H) if _fast is not None else rref(H)


def _basis(H):
    """((R, piv, pidx), rank) of H. (None, 0) when H is empty.

    pidx maps pivot column -> row index, which is what makes membership
    testing O(support) instead of O(rank).
    """
    if H.size == 0:
        return None, 0
    R, piv = _rref(H)
    R = np.asarray(R, dtype=np.uint8)
    piv = list(piv)
    pidx = {int(c): i for i, c in enumerate(piv)}
    return (R, piv, pidx), len(piv)


def _residual(v, basis):
    """V minus its rowspace projection, in O(|supp v|).

    In RREF no row carries a second pivot column, so eliminating pivot p[i]
    never re-sets a pivot already cleared: the reduction is exactly

        v  ->  v XOR  XOR( R[i] for i with v[piv[i]] = 1 )

    with the `v[piv[i]]` read off the ORIGINAL vector. For the weight-<=2
    probes here that is at most two row XORs, against a rank-400 loop.
    """
    R, piv, pidx = basis
    w = v.copy()
    for c in np.flatnonzero(v):
        i = pidx.get(int(c))
        if i is not None:
            w ^= R[i]
    return w


def _weight_le_2_logicals(H_same, H_opp, basis):
    """All non-trivial weight-<=2 operators of this type, exactly.

    Commutation is column equality of H_opp: e_q commutes iff its column
    vanishes, e_q + e_r iff the two columns agree. Both facts are GF(2) and
    need no sampling. Returns True when every such operator is a stabiliser.
    """
    n = H_opp.shape[1]
    seen = {}
    for q in range(n):
        key = H_opp[:, q].tobytes()
        probes = []
        if not any(key):
            probes.append(q)  # e_q: a zero opposite column
        if key in seen:
            probes.append((seen[key], q))  # e_a + e_q: matching columns
        else:
            seen[key] = q
        for p in probes:
            v = np.zeros(n, dtype=np.uint8)
            if isinstance(p, tuple):
                v[p[0]] = v[p[1]] = 1
            else:
                v[p] = 1
            if _residual(v, basis).any():
                return False
    return True


def exact_ge_3(HX, HZ):
    """True iff neither side carries a logical of weight <= 2. Exact."""
    if HX.size == 0 or HZ.size == 0:
        return False
    bx, rx = _basis(HX)
    bz, rz = _basis(HZ)
    if bx is None or bz is None:
        return False
    return _weight_le_2_logicals(HX, HZ, bx) and _weight_le_2_logicals(HZ, HX, bz)


def _block_count(Rx, Rz, n):
    """Number of disjoint qubit blocks, from rows already in RREF."""
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for R in (Rx, Rz):
        for r in np.asarray(R):
            hit = np.nonzero(r)[0]
            if not hit.size:
                continue
            a = find(int(hit[0]))
            for q in hit[1:]:
                b = find(int(q))
                if a != b:
                    parent[b] = a
    return len({find(q) for q in range(n)})


def _admissible(HX, HZ, k0):
    """One pass: rank (hence k), exact d >= 3, single stabilizer block.

    Two RREFs total instead of the three separate ones a composed check would
    run -- the ranks, the membership bases and the block decomposition are all
    the same reduction, so paying for it twice doubles the campaign's cost for
    no extra information.
    """
    if HX.size == 0 or HZ.size == 0:
        return False
    bx, rx = _basis(HX)
    bz, rz = _basis(HZ)
    if bx is None or bz is None:
        return False
    if HX.shape[1] - rx - rz != k0:
        return False
    if not (_weight_le_2_logicals(HX, HZ, bx) and _weight_le_2_logicals(HZ, HX, bz)):
        return False
    return _block_count(bx[0], bz[0], HX.shape[1]) == 1


def one_connected(HX, HZ):
    blocks, sizes = _stabilizer_block_count(HX, HZ, HX.shape[1])
    return blocks == 1, blocks, sizes


def _blocks(HX, HZ, n):
    """Qubit indices of each stabilizer-group block, largest first."""
    rows = []
    for H in (HX, HZ):
        R, _ = _rref(H)
        rows.extend([int(q) for q in np.nonzero(np.asarray(r))[0]] for r in np.asarray(R))
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for r in rows:
        if not r:
            continue
        a = find(r[0])
        for q in r[1:]:
            b = find(q)
            if a != b:
                parent[b] = a
    groups = {}
    for q in range(n):
        groups.setdefault(find(q), []).append(q)
    return sorted(groups.values(), key=len, reverse=True)


def project_k0(HX, HZ, coords, originals):
    """Drop every k=0 block, keeping the encoding core.

    The rectangle completion leaves a few two-qubit spurs with k = 0 behind;
    the 945 and 925 recipes both project them away before contracting. Rank is
    additive over disjoint blocks, so dropping k=0 blocks changes neither n's
    rank accounting nor k, and the core comes out as a single connected block.
    """
    n = HX.shape[1]
    blocks = _blocks(HX, HZ, n)
    keep = []
    total_k = n - len(_rref(HX)[1]) - len(_rref(HZ)[1])
    for b in blocks:
        # len, not count_nonzero: a pivot sitting in column 0 is index 0 and
        # would silently not count.
        rb = len(_rref(HX[:, b])[1])
        rz = len(_rref(HZ[:, b])[1])
        if len(b) - rb - rz != 0:
            keep.append(b)
    if len(keep) != 1:
        raise ValueError(f"{len(keep)} nonzero-k blocks (expected 1)")
    idx = keep[0]
    a, b = HX[:, idx], HZ[:, idx]
    a, b = a[a.any(1)], b[b.any(1)]
    ok, blocks_n, sizes = one_connected(a, b)
    if not ok:
        raise ValueError(f"core not connected: {blocks_n} blocks {sizes}")
    return (a, b, np.asarray(coords)[idx], [originals[i] for i in idx], (total_k, len(idx)))


def _pivot_move(HX, HZ, q, side, r):
    """Delete qubit q using own-side row r as the pivot. Any degree >= 1.

    XOR the pivot into every OTHER own-side row covering q, so the pivot is
    then the only one covering it; drop the pivot row and the qubit column.
    No opposite-side row changes its overlap, because no own-side row carries
    q any more. This is the `contract` primitive the 945 and 925 recipes are
    built from, and it admits degree-2 pivots the r=1 graft cannot reach.
    """
    own_is_x = side == "X"
    A = HX if own_is_x else HZ
    B = HZ if own_is_x else HX
    cover = np.nonzero(A[:, q])[0]
    if cover.size == 0:
        return None
    if r not in cover:
        return None
    pivot = A[r].copy()
    A2 = A.copy()
    for rr in cover:
        if rr != r:
            A2[rr] ^= pivot
    A2 = np.delete(A2, r, axis=0)
    B2 = np.delete(B, q, axis=1)
    A2 = np.delete(A2, q, axis=1)
    return (A2, B2) if own_is_x else (B2, A2)


def graft_campaign(
    HX, HZ, coords, originals, *, k0, seed, d_floor=3, verbose=False, rng=None, progress=None, degree_max=3
):
    """Shrink the code while keeping k, exact d >= 3 and one connected block.

    Tries every qubit, on each side where it is covered, against each pivot
    row up to `degree_max`. Boundary-first, as in the recorded contractions:
    the rim is where a removal stops disturbing the bulk.
    """
    rng = rng if rng is not None else np.random.default_rng(seed)
    orig = list(originals)
    removed = 0
    blacklist = set()
    xmin, xmax = coords[:, 0].min(), coords[:, 0].max()
    ymin, ymax = coords[:, 1].min(), coords[:, 1].max()
    while True:
        wx = HX.sum(axis=0) if HX.size else np.zeros(HX.shape[1])
        wz = HZ.sum(axis=0) if HZ.size else np.zeros(HZ.shape[1])
        cands = []
        for t, w in (("X", wx), ("Z", wz)):
            for q in np.where((w >= 1) & (w <= degree_max))[0]:
                if orig[int(q)] not in blacklist:
                    cands.append((t, int(q), int(w[q])))
        if not cands:
            break
        # boundary-first: the note's contractions paid off on the rim
        rng.shuffle(cands)
        cands.sort(key=lambda tc: -_edge_distance(coords, int(tc[1]), xmin, xmax, ymin, ymax))
        accepted = False
        for t, q, deg in cands:
            A = HX if t == "X" else HZ
            for r in np.nonzero(A[:, q])[0]:
                out = _pivot_move(HX, HZ, q, t, int(r))
                if out is None:
                    continue
                HX2, HZ2 = out
                if not _admissible(HX2, HZ2, k0):
                    continue
                HX, HZ = HX2, HZ2
                coords = np.delete(coords, q, axis=0)
                xmin, xmax = coords[:, 0].min(), coords[:, 0].max()
                ymin, ymax = coords[:, 1].min(), coords[:, 1].max()
                orig.pop(q)
                removed += 1
                accepted = True
                if verbose:
                    print(f"  -{t} deg={deg} -> n={HX.shape[1]}", flush=True)
                if progress is not None:
                    progress(removed, HX.shape[1])
                break
            if accepted:
                break
        if not accepted:
            break
    return HX, HZ, coords, orig, removed


def _edge_distance(coords, q, xmin, xmax, ymin, ymax):
    """How far from the bounding-box rim a qubit sits (0 = on the rim)."""
    x, y = coords[q][0], coords[q][1]
    return min(x - xmin, xmax - x, y - ymin, ymax - y)


def base_state(W, H, px, pz, order):
    m, rec = construct(W, H, px, pz, order)
    if m is None:
        return None
    HX, HZ = m
    coords = np.array([[x, y] for x in range(W) for y in range(H)], dtype=float)
    orig = list(range(W * H))
    HX, HZ, coords, orig, (k_total, n_core) = project_k0(HX, HZ, coords, orig)
    if k_total != rec["k"]:
        raise ValueError(f"k drifted on projection: {k_total} != {rec['k']}")
    if not exact_ge_3(HX, HZ):
        raise ValueError("core already has a <=2 logical")
    return HX, HZ, coords, orig, k_total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=HERE / "out")
    args = ap.parse_args()
    args.out.mkdir(exist_ok=True)

    # bases worth contracting: highest g at n <= 1000 from the rectangle census
    bases = [
        (34, 29, 3, 1, 3, 173),
        (31, 31, 3, 1, 3, 169),
        (36, 26, 3, 1, 3, 164),
        (36, 27, 2, 2, 2, 170),
        (34, 29, 3, 1, 0, 172),
        (32, 31, 1, 4, 3, 173),
    ]
    best = None

    def dump(best):
        if best is None:
            return
        (_, k), HX, HZ, coords, orig, meta = best
        out = {
            "meta": meta,
            "n": int(HX.shape[1]),
            "k": int(-k),
            "coords": coords.tolist(),
            "originals": orig,
            "checks": supports(HX),
            "checks_Z": supports(HZ),
        }
        p = args.out / f"contracted-{out['n']}-{out['k']}-3.json"
        p.write_text(json.dumps(out))
        print("wrote", p, flush=True)

    for W, H, px, pz, order, expect_k in bases:
        try:
            st = base_state(W, H, px, pz, order)
        except ValueError as exc:
            print(f"base {W}x{H} p=({px},{pz}) o={order}: {exc}; skip")
            continue
        if st is None:
            print(f"base {W}x{H} p=({px},{pz}) o={order}: incomplete, skip")
            continue
        HX, HZ, coords, orig, k0 = st
        if k0 != expect_k:
            print(f"base {W}x{H} p=({px},{pz}) o={order}: k={k0} != {expect_k}; skip")
            continue
        n0 = HX.shape[1]
        t0 = time.time()
        for seed in (0, 1, 2, 3, 4, 5):
            r = np.random.default_rng(seed)
            a, b, c, o, rm = graft_campaign(
                HX.copy(), HZ.copy(), coords.copy(), list(orig), k0=k0, seed=seed, rng=r, d_floor=3
            )
            n1 = a.shape[1]
            ok, blocks, sizes = one_connected(a, b)
            g = 9 * k0 / n1
            print(
                f"{W}x{H} p=({px},{pz}) o={order} seed={seed}: "
                f"n {n0}->{n1} (-{rm}) k={k0} g={g:.4f} blocks={blocks} "
                f"{time.time() - t0:.1f}s",
                flush=True,
            )
            if ok and (best is None or (n1, -k0) < best[0]):
                best = ((n1, -k0), a, b, c, o, (W, H, px, pz, order, seed, n0, n1, k0))
                dump(best)
    if best is None:
        print("nothing survived")
        return
    (_, k), HX, HZ, coords, orig, meta = best
    out = {
        "meta": meta,
        "n": int(HX.shape[1]),
        "k": int(-k),
        "coords": coords.tolist(),
        "originals": orig,
        "checks": supports(HX),
    }
    out["checks_Z"] = supports(HZ)
    p = args.out / f"contracted-{out['n']}-{out['k']}-3.json"
    p.write_text(json.dumps(out))
    print("wrote", p)


if __name__ == "__main__":
    main()
