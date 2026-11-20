"""General lifted-product (LP) codes with matrix protographs, plus the SCE-paper
protograph catalog (arXiv:2606.24808, Supplemental S7).

The kit's ``products.lifted_product`` / ``group_algebra.build_2bga`` cover the
1x1-protograph case (a, b single group-algebra elements). This module implements
the *general* lifted product used by Panteleev-Kalachev and by the SCE paper:

    A in F2[G]^(mA x nA),  B in F2[G]^(mB x nB)
    A~ = block matrix of left-regular reps of the A entries
    B~ = block matrix of right-regular reps (by g^-1, the paper's convention)
    HX = [A~ (x) I_nB | I_mA (x) B~^T]
    HZ = [I_nA (x) B~ | A~^T (x) I_mB]
    n  = (nA*nB + mA*mB) * |G|

CSS commutation is automatic (left/right multiplications commute).

The paper's Table 1 codes are scalable families: n = f * |G(param)| with the
protograph fixed, so the same protograph instantiated at a smaller group
parameter gives a sub-cap (n <= 700) candidate. Exponents wrap modulo the
group parameter (standard lift-scaling).

Group conventions (element index -> group element):
    z3zt   G = Z_3 x Z_t,        (a, b) -> x^a y^b,  index a*t + b
    z22zt  G = Z_2 x Z_2 x Z_t,  (a, b, c) -> a^b c^... index (a*2 + b)*t + c
    dic    G = Dic_m (order 4m), (a, b) -> r^a s^b,  index (a mod 2m)*2 + b
    dih    G = D_m  (order 2m),  (a, b) -> r^a s^b,  index (a mod m)*2 + b
    ztz2   G = Z_t x Z_2,        (a, b) -> x^a y^b,  index (a mod t)*2 + b

Run ``uv run python research/kit/lp_protograph.py`` for the self-test, which
reproduces the paper's stated (n, k) at the paper's own group parameters.
"""

import numpy as np
from group_algebra import L_rep, R_rep, cyclic_product, metacyclic


# ----------------------------------------------------------------------
# Groups
# ----------------------------------------------------------------------
def dicyclic(m):
    """Dic_m = <r, s | r^(2m) = e, s^2 = r^m, s r s^-1 = r^-1>, order 4m.

    Returns (mul, n); element r^a s^b sits at index (a mod 2m)*2 + b.
    (``metacyclic`` builds the s^2 = e semidirect product, i.e. dihedral-like
    groups -- not the dicyclic, which needs its own table.)
    """
    N = 4 * m
    two_m = 2 * m

    def idx(a, b):
        return (a % two_m) * 2 + (b % 2)

    mul = np.zeros((N, N), dtype=np.int64)
    for a in range(two_m):
        for b in range(2):
            for c in range(two_m):
                for d in range(2):
                    e = a + (c if b == 0 else -c) + (m if b + d >= 2 else 0)
                    mul[idx(a, b), idx(c, d)] = idx(e, b + d)
    return mul


def build_group(family, t):
    """Cayley table for a paper family at group parameter ``t``."""
    if family == "z3zt":
        mul, _ = cyclic_product(3, t)
    elif family == "z22zt":
        mul, _ = cyclic_product(2, 2, t)
    elif family == "dic":
        mul = dicyclic(t)
    elif family == "dih":
        mul, _ = metacyclic(t, 2, t - 1)  # D_t: r order t, s^2 = e
    elif family == "ztz2":
        mul, _ = cyclic_product(t, 2)
    else:
        raise ValueError(f"unknown family {family}")
    return mul


def entry_index(family, t, entry):
    """Map a paper-notation exponent tuple to a Cayley-table index."""
    if family == "z3zt":
        a, b = entry
        return (a % 3) * t + (b % t)
    if family == "z22zt":
        a, b, c = entry
        return ((a % 2) * 2 + (b % 2)) * t + (c % t)
    if family == "dic":
        a, b = entry
        return (a % (2 * t)) * 2 + (b % 2)
    if family == "dih":
        a, b = entry
        return (a % t) * 2 + (b % 2)
    if family == "ztz2":
        a, b = entry
        return (a % t) * 2 + (b % 2)
    raise ValueError(f"unknown family {family}")


# ----------------------------------------------------------------------
# General lifted product
# ----------------------------------------------------------------------
def _lift_block(mul, P, side, inv):
    """Expand a protograph of element-index lists into a block matrix of
    regular reps. ``side='L'`` uses L(g); ``side='R'`` uses R(g^-1) (the
    paper's rho(g) e_h = e_{h g^-1}).
    """
    rows, cols = len(P), len(P[0])
    N = mul.shape[0]
    M = np.zeros((rows * N, cols * N), dtype=np.int8)
    for i in range(rows):
        for j in range(cols):
            blk = np.zeros((N, N), dtype=np.int8)
            for g in P[i][j]:
                rep = L_rep(mul, g) if side == "L" else R_rep(mul, inv[g])
                blk = (blk + rep) % 2
            M[i * N : (i + 1) * N, j * N : (j + 1) * N] = blk
    return M


def lifted_product_protograph(mul, A, B):
    """General lifted product from protographs over F2[G].

    A, B : lists of lists of lists of int -- A[i][j] is the support (element
        indices) of group-algebra entry (i, j); singletons for the paper's
        codes. Shapes: A is mA x nA, B is mB x nB.

    Returns (HX, HZ) int8, n = (nA*nB + mA*mB)*|G|. CSS guaranteed.

    The paper's HX = [A~ (x) I_nB | I_mA (x) B~^T] uses Kronecker products at
    the PROTOGRAPH level (A~ an mA x nA block matrix of q x q blocks), not the
    flat np.kron of the expanded matrices -- flat kron interleaves the group
    index with the protograph-copy index and breaks the sector cancellation.
    Block placement here, with qubit index (sector 1) (j*nB + d)*N + h and
    (sector 2) (nA*nB + u*mB + e)*N + h:
        HX[(i,b), (j,d)] = A~[i][j] * delta_{b,d}
        HX[(i,b), (u,e)] = delta_{i,u} * B~[e,b]
        HZ[(a,f), (j,d)] = delta_{a,j} * B~[f,d]^T
        HZ[(a,f), (u,e)] = A~[u,a]^T * delta_{f,e}
    (HZ carries EXPANDED block transposes, exactly as the kit's 2BGA uses
    HZ = [R(b)^T | L(a)^T]; the 1x1-protograph case reduces to build_2bga.)
    CSS: (HX HZ^T)[(i,b),(a,f)] = lam(a) rho(b) + rho(b) lam(a) = 0, because
    A-blocks are sums of L(g), B-blocks sums of R(h), and L(g) R(h) = R(h) L(g).
    """
    N = mul.shape[0]
    # inverse table: inv[g] = h with g*h = identity (identity at index 0)
    inv = np.zeros(N, dtype=np.int64)
    for g in range(N):
        inv[g] = int(np.where(mul[g, :] == 0)[0][0])

    mA, nA = len(A), len(A[0])
    mB, nB = len(B), len(B[0])
    Aexp = _lift_block(mul, A, "L", inv)  # (mA*N, nA*N)
    Bexp = _lift_block(mul, B, "R", inv)  # (mB*N, nB*N)
    AexpT = np.ascontiguousarray(Aexp.T)  # (nA*N, mA*N), blocks transposed
    BexpT = np.ascontiguousarray(Bexp.T)  # (nB*N, mB*N)

    n1 = nA * nB * N  # sector-1 qubits
    n = n1 + mA * mB * N

    HX = np.zeros((mA * nB * N, n), dtype=np.int8)
    for i in range(mA):
        for b in range(nB):
            r = (i * nB + b) * N
            for j in range(nA):  # d == b
                c = (j * nB + b) * N
                HX[r : r + N, c : c + N] = Aexp[i * N : (i + 1) * N, j * N : (j + 1) * N]
            for e in range(mB):  # u == i
                c = n1 + (i * mB + e) * N
                HX[r : r + N, c : c + N] = Bexp[e * N : (e + 1) * N, b * N : (b + 1) * N]

    HZ = np.zeros((nA * mB * N, n), dtype=np.int8)
    for a in range(nA):
        for f in range(mB):
            r = (a * mB + f) * N
            for d in range(nB):  # j == a
                c = (a * nB + d) * N
                HZ[r : r + N, c : c + N] = BexpT[d * N : (d + 1) * N, f * N : (f + 1) * N]
            for u in range(mA):  # e == f
                c = n1 + (u * mB + f) * N
                HZ[r : r + N, c : c + N] = AexpT[a * N : (a + 1) * N, u * N : (u + 1) * N]
    return HX, HZ


# ----------------------------------------------------------------------
# The SCE paper's Table 1 protographs (arXiv:2606.24808, Supplemental S7)
# ----------------------------------------------------------------------
# Entries are exponent tuples in the family's generator notation; e = (0, 0).
PAPER_CODES = {
    # abelian Z_3 x Z_t, n = 102 t  (paper: t=14, [[1428,186,<=18]])
    "R1Elite01": {
        "family": "z3zt",
        "A": [
            [(2, 8), (1, 10), (2, 6), (0, 0), (2, 10)],
            [(1, 4), (2, 8), (1, 7), (2, 7), (1, 9)],
            [(0, 13), (2, 4), (1, 13), (0, 4), (0, 5)],
        ],
        "B": [
            [(0, 10), (0, 6), (1, 0), (0, 5), (2, 6)],
            [(0, 6), (1, 1), (0, 9), (0, 5), (1, 12)],
            [(0, 3), (0, 3), (0, 1), (2, 2), (0, 7)],
        ],
    },
    # abelian Z_2 x Z_2 x Z_t, n = 136 t  (paper: t=11, [[1496,198,<=16]])
    "R1Elite02": {
        "family": "z22zt",
        "A": [
            [(0, 0, 5), (1, 0, 7), (0, 0, 2), (0, 0, 6), (1, 1, 2)],
            [(1, 1, 2), (0, 1, 3), (0, 1, 4), (0, 1, 10), (1, 0, 6)],
            [(0, 0, 1), (1, 0, 10), (0, 0, 3), (0, 1, 1), (0, 0, 9)],
        ],
        "B": [
            [(1, 1, 4), (1, 1, 3), (0, 0, 0), (0, 1, 0), (0, 1, 0)],
            [(1, 0, 3), (1, 1, 2), (0, 1, 8), (1, 1, 4), (0, 0, 7)],
            [(0, 1, 4), (1, 0, 1), (1, 0, 2), (1, 0, 7), (0, 1, 5)],
        ],
    },
    # non-abelian Dic_m, 5x3 protographs, n = 136 m (paper: m=11, [[1496,194,<=20]])
    "R2Elite01": {
        "family": "dic",
        "A": [
            [(8, 0), (1, 0), (15, 0)],
            [(7, 1), (2, 0), (18, 1)],
            [(4, 0), (1, 0), (0, 0)],
            [(3, 1), (3, 0), (2, 1)],
            [(1, 0), (3, 0), (5, 0)],
        ],
        "B": [
            [(11, 0), (0, 1), (9, 0)],
            [(12, 0), (0, 0), (11, 0)],
            [(10, 0), (3, 1), (16, 0)],
            [(10, 0), (3, 0), (18, 0)],
            [(9, 0), (6, 1), (1, 1)],
        ],
    },
    # non-abelian D_m (rotation order m), 5x3, n = 68 m (paper: m=22, [[1496,198,<=16]])
    "R2Elite02": {
        "family": "dih",
        "A": [
            [(12, 0), (3, 1), (17, 0)],
            [(8, 0), (0, 1), (15, 0)],
            [(4, 1), (20, 1), (13, 1)],
            [(0, 0), (17, 1), (11, 0)],
            [(19, 0), (14, 0), (9, 0)],
        ],
        "B": [
            [(21, 0), (1, 0), (10, 0)],
            [(12, 0), (0, 0), (3, 0)],
            [(3, 0), (14, 0), (3, 0)],
            [(1, 1), (6, 1), (19, 0)],
            [(14, 0), (5, 0), (11, 0)],
        ],
    },
    # non-abelian Dic_m, 3x5, n = 136 m (paper: m=11, [[1496,192,<=16]])
    "R3Elite01": {
        "family": "dic",
        "A": [
            [(14, 1), (1, 1), (10, 1), (19, 0), (6, 0)],
            [(5, 1), (21, 1), (15, 0), (9, 0), (3, 1)],
            [(18, 1), (19, 0), (20, 1), (21, 1), (0, 0)],
        ],
        "B": [
            [(19, 1), (18, 1), (9, 0), (19, 0), (8, 1)],
            [(2, 1), (21, 0), (3, 1), (11, 0), (1, 1)],
            [(12, 1), (17, 0), (18, 0), (15, 1), (12, 1)],
        ],
    },
    # non-abelian Dic_m, 3x5, n = 136 m (paper: m=11, [[1496,198,<=14]])
    "R3Elite02": {
        "family": "dic",
        "A": [
            [(16, 0), (17, 1), (18, 0), (0, 1), (2, 0)],
            [(17, 1), (1, 1), (2, 1), (4, 1), (6, 1)],
            [(18, 0), (2, 1), (5, 0), (8, 1), (11, 0)],
        ],
        "B": [
            [(15, 0), (9, 1), (1, 0), (10, 1), (3, 0)],
            [(11, 0), (5, 0), (15, 0), (9, 0), (3, 0)],
            [(7, 0), (2, 1), (13, 0), (8, 1), (3, 0)],
        ],
    },
    # abelian Z_t x Z_2, 3x4, n = 50 t (paper: t=30, [[1500,81,<=18]])
    "R3EliteP01": {
        "family": "ztz2",
        "A": [
            [(22, 0), (17, 0), (19, 0), (21, 0)],
            [(23, 1), (11, 1), (22, 1), (10, 1)],
            [(1, 0), (28, 0), (2, 0), (29, 0)],
        ],
        "B": [
            [(28, 1), (11, 1), (7, 1), (17, 1)],
            [(26, 0), (18, 1), (29, 0), (21, 1)],
            [(5, 1), (28, 1), (21, 1), (25, 1)],
        ],
    },
    # abelian Z_t x Z_2, 3x4, n = 50 t (paper: t=30, [[1500,76,<=20]])
    "R3EliteP02": {
        "family": "ztz2",
        "A": [
            [(6, 1), (6, 0), (6, 1), (6, 0)],
            [(0, 0), (1, 0), (2, 0), (26, 0)],
            [(24, 1), (26, 0), (21, 1), (23, 0)],
        ],
        "B": [
            [(29, 1), (13, 0), (8, 1), (3, 0)],
            [(10, 0), (6, 0), (2, 0), (28, 0)],
            [(2, 1), (29, 0), (26, 1), (12, 0)],
        ],
    },
}

# Column factor f = nA*nB + mA*mB per protograph shape (constant per code).
_F = {
    "R1Elite01": 34,
    "R1Elite02": 34,
    "R2Elite01": 34,
    "R2Elite02": 34,
    "R3Elite01": 34,
    "R3Elite02": 34,
    "R3EliteP01": 25,
    "R3EliteP02": 25,
}


def instantiate(name, t):
    """Build a paper family at group parameter ``t``. Returns (HX, HZ, spec)."""
    code = PAPER_CODES[name]
    family = code["family"]
    mul = build_group(family, t)
    conv = lambda P: [[[entry_index(family, t, e)] for e in row] for row in P]
    A = conv(code["A"])
    B = conv(code["B"])
    HX, HZ = lifted_product_protograph(mul, A, B)
    f = _F[name]
    spec = {
        "family": "lifted-product",
        "source": "arXiv:2606.24808 Table 1 / S7",
        "code": name,
        "group": family,
        "group_param": t,
        "group_order": int(mul.shape[0]),
        "n_factor": f,
    }
    return HX, HZ, spec


def max_check_weight(HX, HZ):
    return max(int(HX[i].sum()) for i in range(HX.shape[0])) if HX.size else 0, max(
        int(HZ[i].sum()) for i in range(HZ.shape[0])
    ) if HZ.size else 0


# ----------------------------------------------------------------------
# Self-test: reproduce the paper's stated (n, k) at the paper's parameters
# ----------------------------------------------------------------------
if __name__ == "__main__":
    from css import compute_k, verify_css

    paper = {
        # name: (param, n, k) as stated in Table 1
        "R1Elite01": (14, 1428, 186),
        "R1Elite02": (11, 1496, 198),
        "R2Elite01": (11, 1496, 194),
        "R2Elite02": (22, 1496, 198),
        "R3Elite01": (11, 1496, 192),
        "R3Elite02": (11, 1496, 198),
        "R3EliteP01": (30, 1500, 81),
        "R3EliteP02": (30, 1500, 76),
    }
    print("=== lp_protograph self-test: paper parameters at paper sizes ===")
    print("(note: the paper says 'all stabilizer weight 8', but its S7 protographs")
    print(" for R3EliteP01/P02 are 3x4, giving row weight nA+mB = 7; we expect 7.)")
    ok_all = True
    for name, (t, n_paper, k_paper) in paper.items():
        HX, HZ, spec = instantiate(name, t)
        n = HX.shape[1]
        css = verify_css(HX, HZ)
        k = compute_k(HX, HZ)
        wx, wz = max_check_weight(HX, HZ)
        code = PAPER_CODES[name]
        w_expect = len(code["A"][0]) + len(code["B"])
        ok = (n == n_paper) and css and (k == k_paper) and wx == wz == w_expect
        ok_all &= ok
        print(
            f"  {name:11s} G-param={t:2d}: n={n:5d} (want {n_paper})  "
            f"k={k:3d} (want {k_paper})  css={css}  w=({wx},{wz}) want {w_expect}  "
            f"{'OK' if ok else 'MISMATCH'}"
        )
    print("ALL OK" if ok_all else "SOME MISMATCHES -- fix before sweeping")
