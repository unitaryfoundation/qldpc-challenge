r"""Phantom-code construction kit -- arXiv:2609.16542 (Mao, Sun, Zhang).

Three pieces, consolidated:

* ``build_phantom_outer`` -- the sparse outer phantom CSS pair (Theorem 4.2):
  simplex/Hamming weight-three basis + variable-copying degree reduction;
  parameters d_X = R*2^(k-1), d_Z = 1, max row weight <= 3, max column
  degree <= 3, n = N*R with N = 2^k - 1.
* ``concatenate_with_inner`` -- block concatenation with a one-logical-qubit
  CSS inner code (Proposition 4.4): d~X = delta_X * dX, d~Z = delta_Z * dZ,
  w~ <= max{w_in, delta_X * w_out, delta_Z * w_out}.
* ``search_inner_codes`` -- bounded randomized search for a [[m,1,D]] CSS
  inner code smaller than the board's Steane codes.

The structural verdict recorded in fieldnotes/2026-09-18-phantom-codes-campaign.md:
every concatenated code has intrinsic Z-check weight w >= 3*delta_Z >= 9
for any inner code of distance >= 3, so the family cannot enter the
w <= 8 hackathon box; the modules remain the public implementation of the
family for further study.
"""
import numpy as np

def rref(M):
    """Reduced row echelon form over GF(2); returns a matrix whose nonzero
    rows span the same space as the rows of ``M``."""
    M = np.asarray(M, dtype=np.int8) % 2
    rows, cols = M.shape
    A = M.copy()
    pivot_row = 0
    for c in range(cols):
        piv = next((r for r in range(pivot_row, rows) if A[r, c]), None)
        if piv is None:
            continue
        A[[pivot_row, piv]] = A[[piv, pivot_row]]
        for r in range(rows):
            if r != pivot_row and A[r, c]:
                A[r] ^= A[pivot_row]
        pivot_row += 1
        if pivot_row == rows:
            break
    return A


def simplex_and_hamming_basis(k):
    """Return ``(P, S, B)`` where ``P`` lists the ``N = 2^k - 1`` nonzero
    vectors of ``F_2^k`` (as ints, bitmask-indexed), ``S`` is the ``N x N``
    generator rowspace basis of the simplex ``S_k`` expressed as a check
    matrix on the ``N`` coordinates (one row per basis word ``s_a``, so the
    number of rows is ``N`` and they span a ``k``-dimensional space), and
    ``B`` is a weight-three basis of the Hamming code ``H_k`` given as a list
    of length-``R`` incidence vectors on the ``N`` coordinates.
    """
    N = 2**k - 1
    # Coordinates indexed by the nonzero vectors x in F_2^k, x as an int in
    # [1, N].  The simplex basis word s_a has s_a[x] = popcount(a & x) % 2.
    S = np.zeros((N, N), dtype=np.int8)
    for a in range(1, N + 1):
        s = np.array([bin(a & x).count("1") % 2 for x in range(1, N + 1)],
                     dtype=np.int8)
        S[a - 1] = s
    S = rref(S)
    S = S[S.any(axis=1)]          # k independent rows -> simplex generator

    # Weight-three basis of H_k = S_k^perp (Prop 4.1).
    # For each non-unit x pick i(x) with bit set, then
    #   b_x = delta_x + delta_{x + e_i} + delta_{e_i}.
    # These R = N - k vectors are independent and span H_k.
    R = N - k
    B = np.zeros((R, N), dtype=np.int8)
    unit = [1 << e for e in range(k)]
    rows = []
    for x in range(1, N + 1):
        if x in unit:
            continue              # skip the unit vectors
        e = 1 << ((x & -x).bit_length() - 1)   # one set bit of x
        xp = x ^ e               # x + e_i
        b = np.zeros(N, dtype=np.int8)
        for co in (x, xp, e):
            if 1 <= co <= N:
                b[co - 1] ^= 1
        assert b.sum() == 3
        rows.append(b)
    assert len(rows) == R
    for i, row in enumerate(rows):
        B[i] = row
    return list(range(1, N + 1)), S, B


def choose_injections(B, R, seeds=None):
    """For each coordinate x, map each basis row ``j`` containing ``x`` to a
    copy index ``c(x, j)`` so that ``x -> (j -> c(x,j))`` is injective and
    lands in ``[0, R)``.  Returns a dict ``{(x, j) -> copy_index}``."""
    # copy[x] = sorted list of rows j whose support contains x; the t-th
    # element maps to copy index t -- an injection into [R].
    members = {}
    B = np.asarray(B, dtype=np.int8)
    nrows = B.shape[0]
    for j in range(nrows):
        coords = [int(x) for x in np.nonzero(B[j])[0]]
        for x in coords:
            members.setdefault(x, []).append(j)
    table = {}
    for x, jlist in members.items():
        for t, j in enumerate(sorted(jlist)):
            assert t < R, f"coordinate {x} hits too many Hamming words"
            table[(x, j)] = t
    return table


def build_phantom_outer(k, copy_table=None):
    """Build the sparse outer phantom CSS pair for logical dimension ``k``.

    Returns ``(HX, HZ, info)`` where ``HX`` has shape ``(0, M)`` (empty),
    ``HZ`` has shape ``(rank(V_Z), M)``, and ``info`` is a dict of structural
    facts: ``n``, ``N``, ``R``, ``k``, ``rankZ``, ``dX``, ``dZ``.
    """
    N = 2**k - 1
    R = N - k
    M = N * R
    P, S, B = simplex_and_hamming_basis(k)
    if copy_table is None:
        copy_table = choose_injections(B, R)

    # equality checks: for each x, pairs (x,r)-(x,r+1), r in [0, R-2)
    eq = []
    for x in range(N):
        base = x * R
        for r in range(R - 1):
            row = np.zeros(M, dtype=np.int8)
            row[base + r] = 1
            row[base + r + 1] = 1
            eq.append(row)
    # split Hamming checks
    hm = []
    for j in range(B.shape[0]):
        coords = [int(x) for x in np.nonzero(B[j])[0]]
        row = np.zeros(M, dtype=np.int8)
        for x in coords:
            c = copy_table[(x, j)]
            row[x * R + c] = 1
        hm.append(row)
    HZ = np.array(eq + hm, dtype=np.int8) % 2
    # Keep the natural sparse presentation: drop only exact-duplicate rows.
    # (rref would densify rows and inflate the reported check weight.)
    seen = set()
    keep = []
    for row in HZ:
        key = row.tobytes()
        if key not in seen:
            seen.add(key)
            keep.append(row)
    HZ = np.array(keep, dtype=np.int8) if keep else np.zeros((0, M), dtype=np.int8)
    HX = np.zeros((0, M), dtype=np.int8)

    info = dict(
        n=int(M), N=int(N), R=int(R), k=int(k),
        rankZ=int(HZ.shape[0]), dX=R * 2 ** (k - 1), dZ=1,
    )
    return HX, HZ, info


def outer_max_weight(HZ):
    """Maximum row weight of the Z-check matrix (the outer ``w_out``)."""
    return int(HZ.sum(axis=1).max())


if __name__ == "__main__":
    for k in (2, 3):
        HX, HZ, info = build_phantom_outer(k)
        print(f"k={k}: n={info['n']} N={info['N']} R={info['R']} "
              f"rankZ={info['rankZ']} k_out={info['n'] - 0 - info['rankZ']} "
              f"dX={info['dX']} dZ={info['dZ']} maxZhWt={outer_max_weight(HZ)}")

def _kernel(M):
    """Basis of the kernel of ``M`` over GF(2)."""
    M = np.asarray(M, dtype=np.int8) % 2
    m, n = M.shape
    A = M.copy()
    pivots = []
    r = 0
    for c in range(n):
        piv = next((i for i in range(r, m) if A[i, c]), None)
        if piv is None:
            continue
        A[[r, piv]] = A[[piv, r]]
        for i in range(m):
            if i != r and A[i, c]:
                A[i] ^= A[r]
        pivots.append(c)
        r += 1
        if r == m:
            break
    free = [c for c in range(n) if c not in pivots]
    K = []
    for f in free:
        v = np.zeros(n, dtype=np.int8)
        for ri, pc in enumerate(pivots):
            v[pc] = A[ri, f]
        v[f] = 1
        K.append(v)
    return np.array(K, dtype=np.int8)


def _dedup(M):
    """Drop exact-duplicate rows (preserving the natural sparse presentation)."""
    M = np.asarray(M, dtype=np.int8) % 2
    seen = set()
    keep = []
    for row in M:
        key = row.tobytes()
        if key not in seen:
            seen.add(key)
            keep.append(row)
    return np.array(keep, dtype=np.int8) if keep else np.zeros((0, M.shape[1]), dtype=np.int8)


def _in_rowspace(v, M):
    """Is ``v`` in the rowspace of ``M`` over GF(2)?"""
    v = np.asarray(v, dtype=np.int8) % 2
    M = np.asarray(M, dtype=np.int8) % 2
    if v.size == 0:
        return True
    C = np.vstack([M, v])
    return int(rref(C).any(axis=1).sum()) == int(M.shape[0])


def steane():
    """The [[7,1,3]] Steane CSS code: ``(UX, UZ, x, z, info)`` where
    ``UX = UZ`` is the [7,3,4] simplex code and ``x = z`` is a weight-three
    logical representative.  ``info`` holds ``m``, ``deltaX``, ``deltaZ``."""
    N = 7
    S = np.zeros((N, N), dtype=np.int8)
    for a in range(1, N + 1):
        s = np.array([bin(a & x).count("1") % 2 for x in range(1, N + 1)],
                     dtype=np.int8)
        S[a - 1] = s
    S = rref(S)
    S = S[S.any(axis=1)]            # [7,3,4] simplex generator (3 x 7)
    UX = S
    UZ = S
    # logical reps: weight-three words in U^perp \\ U.  For the simplex,
    # U^perp is the [7,4,3] Hamming code; pick a weight-three Hamming word
    # not in the simplex rowspace.
    H = _kernel(S)
    x = z = None
    for i in range(H.shape[0]):
        w = H[i]
        if w.sum() == 3 and not _in_rowspace(w, S):
            x = z = w
            break
    if x is None:
        raise ValueError("no weight-3 logical rep found")
    info = dict(m=int(N), deltaX=int(x.sum()), deltaZ=int(z.sum()))
    return UX, UZ, x, z, info


def concat_phantom(outer, inner):
    """Concatenate an outer pair with a one-logical-qubit inner code.

    ``outer`` = ``(HX, HZ, info_out)`` from ``build_phantom_outer``; ``inner``
    = ``(UX, UZ, x, z, info_in)`` from the catalog.  Returns
    ``(HXc, HZc, info)`` with the concatenated CSS pair and a dict of
    structural facts (``n``, ``k``, ``dX``, ``dZ``, ``maxW``).
    """
    HX, HZ, info_out = outer
    UX, UZ, x, z, info_in = inner
    m = info_in["m"]
    deltaX = info_in["deltaX"]
    deltaZ = info_in["deltaZ"]
    n0 = info_out["n"]
    n = m * n0

    def lift(blocks, rep):
        """Lift a length-``n0`` outer word to a length-``n`` word by putting
        ``rep`` in each block where the outer word is 1."""
        out = np.zeros(n, dtype=np.int8)
        for a_i in range(n0):
            if blocks[a_i]:
                out[a_i * m:(a_i + 1) * m] = rep
        return out

    # Internal checks: U_X and U_Z in every block (n0 copies each).
    X_internal = []
    Z_internal = []
    for b in range(n0):
        for row in UX:
            r = np.zeros(n, dtype=np.int8)
            r[b * m:(b + 1) * m] = row
            X_internal.append(r)
        for row in UZ:
            r = np.zeros(n, dtype=np.int8)
            r[b * m:(b + 1) * m] = row
            Z_internal.append(r)

    # Lifted outer checks: L_X(HX) and L_Z(HZ).
    X_lift = [lift(row, x) for row in HX]
    Z_lift = [lift(row, z) for row in HZ]

    HXc = np.array(X_internal + X_lift, dtype=np.int8) % 2
    HZc = np.array(Z_internal + Z_lift, dtype=np.int8) % 2
    # Keep the natural sparse presentation (the paper's bound w~ <= max{win, deltaX*wout, deltaZ*wout} refers to it).
    # Drop only exact-duplicate rows (never rref: elimination densifies rows and
    # would inflate the reported check weight beyond the natural presentation).
    HXc = _dedup(HXc)
    HZc = _dedup(HZc)

    dX = deltaX * info_out["dX"]
    dZ = deltaZ * info_out["dZ"]
    k = info_out["k"]
    info = dict(
        n=int(n), k=int(k), dX=int(dX), dZ=int(dZ),
        d=int(min(dX, dZ)), maxW=int(max(HXc.sum(axis=1).max(), HZc.sum(axis=1).max())),
        m=int(m), deltaX=int(deltaX), deltaZ=int(deltaZ),
        n0=int(n0),
    )
    return HXc, HZc, info


if __name__ == "__main__":
    inner = steane()
    print("Steane inner:", inner[4])
    for k in (2, 3):
        outer = build_phantom_outer(k)
        HXc, HZc, info = concat_phantom(outer, inner)
        print(f"k={k}: [[{info['n']},{info['k']},{info['d']}]] "
              f"dX={info['dX']} dZ={info['dZ']} maxW={info['maxW']} "
              f"n0={info['n0']} m={info['m']} deltaX/Z={info['deltaX']}/{info['deltaZ']}")

def min_weight_outside(perp_basis, space_basis):
    r"""Min weight of a vector in rowspace(perp_basis) \ rowspace(space_basis)."""
    perp = np.asarray(perp_basis, dtype=np.int8) % 2
    space = np.asarray(space_basis, dtype=np.int8) % 2
    n = perp.shape[1]
    best = n + 1
    r = perp.shape[0]
    for mask in range(1, 1 << r):
        v = (mask & 1) * perp[0]
        for i in range(1, r):
            if (mask >> i) & 1:
                v = (v + perp[i]) % 2
        if v.sum() >= best:
            continue
        # is v in rowspace(space)?
        C = np.vstack([space, v])
        if int(rref(C).any(axis=1).sum()) == space.shape[0]:
            continue
        best = int(v.sum())
        if best == 1:
            break
    return best


def search_inner(m, D, dimX, dimZ, trials=20000, seed=0):
    """Randomized search for a [[m,1,D]] CSS code with the given sector dims."""
    rng = np.random.default_rng(seed)
    for t in range(trials):
        # random U_Z: dimZ rows
        UZ = rng.integers(0, 2, size=(dimZ, m)).astype(np.int8)
        UZ = rref(UZ)
        UZ = UZ[UZ.any(axis=1)]
        if UZ.shape[0] != dimZ:
            continue
        UZperp = _kernel(UZ)          # dim m - dimZ
        # random U_X subseteq UZperp, dim dimX
        if dimX > UZperp.shape[0]:
            continue
        comb = rng.integers(0, 2, size=(dimX, UZperp.shape[0])).astype(np.int8)
        UX = (comb @ UZperp) % 2
        UX = rref(UX)
        UX = UX[UX.any(axis=1)]
        if UX.shape[0] != dimX:
            continue
        # d_X = min weight in UZperp \\ UX
        dX = min_weight_outside(UZperp, UX)
        if dX < D:
            continue
        # d_Z = min weight in UX^perp \\ UZ
        UXperp = _kernel(UX)
        dZ = min_weight_outside(UXperp, UZ)
        if dZ < D:
            continue
        return UX, UZ, int(dX), int(dZ)
    return None


if __name__ == "__main__":
    # Try [[13,1,5]]: dimX+dimZ = 12.  Try (6,6),(5,7),(7,5).
    for dimX, dimZ in ((6, 6), (5, 7), (7, 5)):
        res = search_inner(13, 5, dimX, dimZ, trials=30000, seed=1)
        if res:
            UX, UZ, dX, dZ = res
            print(f"FOUND [[13,1,5]] with dimX={dimX} dimZ={dimZ}: dX={dX} dZ={dZ}")
            break
        else:
            print(f"no [[13,1,5]] with dimX={dimX} dimZ={dimZ} in 30000 trials")
    else:
        print("no [[13,1,5]] found")
