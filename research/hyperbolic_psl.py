"""Rebuild the self-dual PSL(2,q) hyperbolic surface codes of arXiv:2610.10948.

The paper (Mahmoud and Rayan) states its construction algebraically and offers
its parity-check matrices on request only, so the matrices here are recomputed
from the construction as published rather than copied.

Construction (paper Sec. II). For a regular {p,p} tiling, take the orientation-
preserving triangle group

    Delta_p = <x, y | x^p = y^p = (xy)^2 = 1>

and a finite quotient Q = Delta_p / Gamma_PBC with Q = PSL(2,q) for prime q.
Self-duality is imposed through a projective involution J in PGL(2,q) (split or
non-split, i.e. two or zero fixed points on the projective line) constraining
the generators to y = J x J^{-1}, so conjugation by J swaps x and y and embeds a
strict face-vertex symmetry in the code. A valid pair satisfies ord(x) =
ord(y) = p and ord(xy) = 2 and generates all of Q.

Cells of the resulting closed orientable cellulation:

    edges    = left cosets of the order-2 subgroup <xy>   (data qubits)
    faces    = left cosets of <x>                        (Z checks)
    vertices = left cosets of <y>                        (X checks)

so n = |Q|/2, pF = pV = 2E, and k/n = (p-4)/p + 2/n by Euler. Checks commute
because each face boundary meets each vertex an even number of times.

The periodic identifications are the free choice: they leave n, k and the check
weight fixed while changing the shortest nontrivial homology class, hence the
code distance. Picking the class that maximises distance is the whole search.

Usage
-----
    uv run --extra research python research/hyperbolic_psl.py --list 11 5
    uv run --extra research python research/hyperbolic_psl.py --build 11 5 --class 0
    uv run --extra research python research/hyperbolic_psl.py --scan 11 5 --budget 40

``--list`` enumerates the generator classes and prints the distinct codes;
``--build`` writes one code's HX/HZ as .npy; ``--scan`` measures the distance of
successive classes with the kit's search and stops at the first class reaching
the target distance. Distances found here are upper bounds carrying a witness.
"""

import argparse
import sys
from collections import defaultdict, deque

import numpy as np

sys.path[:0] = ["research/kit", "verify"]


# ---------------------------------------------------------------- F_p^2


def mat_key(a, q):
    """Canonical PGL key for a 2x2 matrix: scaled to a unit entry, mod sign."""
    entries = [x % q for row in a for x in row]
    nz = [x for x in entries if x]
    if not nz:
        return None
    inv = pow(nz[0], q - 2, q)
    norm = tuple((e * inv) % q for e in entries)
    return min(norm, tuple((-e) % q for e in norm))


def mat_mul(a, b, q):
    return tuple(
        tuple(sum(a[i][k] * b[k][j] for k in range(2)) % q for j in range(2))
        for i in range(2)
    )


def mat_inv(a, q):
    (a_, b), (c, d) = a
    di = pow((a_ * d - b * c) % q, q - 2, q)
    return ((d * di) % q, (-b * di) % q), ((-c * di) % q, (a_ * di) % q)


def identity_key(q):
    return mat_key(((1, 0), (0, 1)), q)


def enumerate_psl(q):
    """Every det-1 2x2 matrix over F_q, keyed canonically (mod +-I)."""
    out = {}
    for a in range(q):
        for b in range(q):
            for c in range(q):
                for d in range(q):
                    if (a * d - b * c) % q == 1:
                        k = mat_key(((a, b), (c, d)), q)
                        out.setdefault(k, ((a, b), (c, d)))
    return out


def order_in_psl(m, q, identity):
    cur = ((1, 0), (0, 1))
    for e in range(1, 2 * q * q + 10):
        cur = mat_mul(cur, m, q)
        if mat_key(cur, q) == identity:
            return e
    raise RuntimeError("no order found")


def subgroup_generated(gens, psl, q):
    seen = {identity_key(q)}
    stack = [identity_key(q)]
    keys = [mat_key(g, q) for g in gens]
    while stack:
        cur = stack.pop()
        for gk in keys:
            for nxt in (mat_key(mat_mul(psl[cur], psl[gk], q), q),
                        mat_key(mat_mul(psl[gk], psl[cur], q), q)):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
    return seen


# ---------------------------------------------------------------- cells


def _cosets(H, psl, q, index):
    reps = []
    seen = set()
    for gk in psl:
        if gk in seen or gk not in index:
            continue
        seen.add(gk)
        reps.append(gk)
        for h in H:
            seen.add(mat_key(mat_mul(psl[gk], psl[h], q), q))
    return reps


def assemble(x, y, xy, psl, q, Q, p):
    """Build (n, X, Z) for one generator pair, or None if the cellulation is
    not a valid closed orientable {p,p} complex."""
    Qlist = sorted(Q)
    index = {gk: i for i, gk in enumerate(Qlist)}

    def cyc(g, order):
        H, cur = set(), ((1, 0), (0, 1))
        for _ in range(order):
            cur = mat_mul(cur, g, q)
            k = mat_key(cur, q)
            H.add(k)
            if k == identity_key(q):
                break
        return H

    H_xy, H_x, H_y = cyc(xy, 2), cyc(x, p), cyc(y, p)
    edge_reps = _cosets(H_xy, psl, q, index)
    face_reps = _cosets(H_x, psl, q, index)
    vert_reps = _cosets(H_y, psl, q, index)
    if not edge_reps:
        return None

    def coset_map(reps, H):
        m = {}
        for r in reps:
            for h in H:
                m[mat_key(mat_mul(psl[r], psl[h], q), q)] = r
        return m

    cos_e = coset_map(edge_reps, H_xy)
    cos_f = coset_map(face_reps, H_x)
    cos_v = coset_map(vert_reps, H_y)
    if any(g not in cos_e or g not in cos_f or g not in cos_v for g in Qlist):
        return None

    eidx = {r: i for i, r in enumerate(edge_reps)}
    fidx = {r: i for i, r in enumerate(face_reps)}
    vidx = {r: i for i, r in enumerate(vert_reps)}
    n = len(edge_reps)
    Z = [[] for _ in face_reps]
    X = [[] for _ in vert_reps]
    for g in Qlist:
        e = eidx[cos_e[g]]
        Z[fidx[cos_f[g]]].append(e)
        X[vidx[cos_v[g]]].append(e)
    Z = [sorted(set(s)) for s in Z]
    X = [sorted(set(s)) for s in X]
    if any(len(s) != p for s in Z) or any(len(s) != p for s in X):
        return None
    deg = defaultdict(int)
    for s in X + Z:
        for a in s:
            deg[a] += 1
    if len(deg) != n or any(v != 4 for v in deg.values()):
        return None
    return n, X, Z


def generator_pairs(q, p, psl):
    """Yield every (x, y) meeting the paper's conditions."""
    identity = identity_key(q)
    xs = [m for m in psl.values()
          if _safe_order(m, q, identity) == p]
    js, seen = [], set()
    for a in range(q):
        for b in range(q):
            for c in range(q):
                for d in range(q):
                    if (a + d) % q == 0 and (a * d - b * c) % q != 0:
                        k = mat_key(((a, b), (c, d)), q)
                        if k not in seen:
                            seen.add(k)
                            js.append(((a, b), (c, d)))
    for x in xs:
        for J in js:
            (ja, jb), (jc, jd) = J
            di = pow((ja * jd - jb * jc) % q, q - 2, q)
            Jn = tuple(tuple((e * di) % q for e in row) for row in J)
            y = mat_mul(mat_mul(Jn, x, q), mat_inv(Jn, q), q)
            if mat_key(y, q) == identity or _safe_order(y, q, identity) != p:
                continue
            xy = mat_mul(x, y, q)
            if _safe_order(xy, q, identity) != 2:
                continue
            Q = subgroup_generated([x, y], psl, q)
            if len(Q) == len(psl):
                yield x, y, xy, Q


def _safe_order(m, q, identity):
    try:
        return order_in_psl(m, q, identity)
    except RuntimeError:
        return None


def to_matrix(sets, n):
    M = np.zeros((len(sets), n), dtype=np.uint8)
    for i, s in enumerate(sets):
        for a in s:
            M[i, a] = 1
    return M


def distinct_codes(q, p, limit=None):
    """Deduplicated codes from the class enumeration, in enumeration order."""
    psl = enumerate_psl(q)
    seen, out = set(), []
    for x, y, xy, Q in generator_pairs(q, p, psl):
        code = assemble(x, y, xy, psl, q, Q, p)
        if code is None:
            continue
        n, X, Z = code
        sig = (tuple(sorted(map(tuple, X))), tuple(sorted(map(tuple, Z))))
        if sig in seen:
            continue
        seen.add(sig)
        out.append((to_matrix(X, n), to_matrix(Z, n)))
        if limit and len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("q", type=int, help="prime field size")
    ap.add_argument("p", type=int, help="tiling parameter p of the {p,p} tiling")
    ap.add_argument("--list", action="store_true",
                    help="enumerate and report the distinct codes")
    ap.add_argument("--build", type=int, metavar="CLASS",
                    help="write HX/HZ .npy for one class index")
    ap.add_argument("--scan", action="store_true",
                    help="measure classes until one reaches --target")
    ap.add_argument("--target", type=int, default=0,
                    help="stop once a class reaches this distance")
    ap.add_argument("--budget", type=int, default=40,
                    help="how many classes --scan may measure")
    ap.add_argument("--trials", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--outdir", default=".")
    args = ap.parse_args()

    from css import compute_k
    from surrogate import lightest_logical, validate_logical

    if args.list:
        for i, (HX, HZ) in enumerate(distinct_codes(args.q, args.p)):
            print(f"class {i}: n={HX.shape[1]} k={compute_k(HX, HZ)}")
        return

    if args.build is not None:
        HX, HZ = distinct_codes(args.q, args.p, limit=args.build + 1)[args.build]
        n = HX.shape[1]
        np.save(f"{args.outdir}/Hx.npy", HX)
        np.save(f"{args.outdir}/Hz.npy", HZ)
        print(f"n={n} k={compute_k(HX, HZ)} -> {args.outdir}/Hx.npy, Hz.npy")
        return

    if args.scan:
        for i, (HX, HZ) in enumerate(distinct_codes(args.q, args.p)):
            if i >= args.budget:
                print(f"budget {args.budget} exhausted")
                return
            wz, sx = lightest_logical(HZ, HX, trials=args.trials, seed=args.seed)
            wx, sX = lightest_logical(HX, HZ, trials=args.trials, seed=args.seed)
            okz = validate_logical(HX, HZ, "Z", wz, sx)
            okx = validate_logical(HX, HZ, "X", wx, sX)
            d = min(wz, wx)
            print(f"class {i}: n={HX.shape[1]} k={compute_k(HX, HZ)} "
                  f"dZ={wz} dX={wx} validated={okz[0] and okx[0]}", flush=True)
            if args.target and d >= args.target:
                print(f"reached target d>={args.target} at class {i}")
                return


if __name__ == "__main__":
    main()