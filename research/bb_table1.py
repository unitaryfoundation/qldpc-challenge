"""Bivariate bicycle (BB) codes from arXiv:2407.03973, Table 1.

"Logical Operators and Fold-Transversal Gates of Bivariate Bicycle Codes"
(Eberhardt, Smith, Varma). Table 1 lists ten codes C(c, d) on an l x m lattice
with their claimed [[n, k, d]]. Every row is reproduced here exactly, which is
what pins the convention below: a BB code on Z_l x Z_m has

    H_X = [ M(c) | M(d)^T ],   H_Z = [ M(d) | M(c)^T ]

with M(p) the sum, over the support of p, of the shift matrices for (i, j),
acting on the right on F_2[G]. l is the order of x and m is the order of y --
transposing the two changes the code, and getting it backwards silently yields
a valid-looking CSS code with the wrong k.

This module uses exactly the convention of research/kit/bb.py's build_bb, which
is what produced the submitted document, so build_from_table("128-14-12")
regenerates codes/128-14-12.json bit-for-bit. (The other common BB form,
[ M(c) | M(d)^T ] with [ M(d) | M(c)^T ], gives the same n, k, weight and
distance but a differently-labelled set of qubits, so the two are not
interchangeable when the submission is a specific matrix.) Build BB codes with
research/kit/bb.py; this module exists to pin that convention against the
paper's printed table and is not a second builder.

The convention is pinned against the board's own baseline entry
codes/144-12-12.json (Bravyi et al., arXiv:2308.07915; A = x^3 + y^2 + y,
B = x^2 + x + y^3, orders (12, 6)): this form reproduces n = 144, rank 66 per
sector and k = 12 for that row, and it reproduces all ten of Table 1.

Nothing here computes a distance or asserts a track: verify/validate_candidate.py
decides both. Run this file directly to print the reproduction table.
"""
from __future__ import annotations

import numpy as np

# Table 1 of arXiv:2407.03973 as (label, l, m, c_support, d_support).
# x^i y^j is the exponent pair (i, j), reduced mod l (x order) and mod m (y order).
TABLE_1 = {
    "90-8-10":   (3, 15, [(0, 0), (0, 1), (0, 5)], [(0, 3), (1, 0), (2, 0)]),
    "144-12-12": (12, 6, [(3, 0), (0, 1), (0, 2)], [(0, 3), (1, 0), (2, 0)]),
    "108-16-6":  (6, 9,  [(0, 0), (0, 1), (0, 2)], [(0, 3), (2, 0), (4, 0)]),
    "128-14-12": (8, 8,  [(2, 0), (0, 1), (0, 3), (0, 4)], [(0, 2), (1, 0), (3, 0), (4, 0)]),
    "162-4-16":  (9, 9,  [(0, 0), (1, 0), (0, 1)], [(3, 0), (0, 1), (0, 2)]),
    "162-12-8":  (9, 9,  [(0, 0), (1, 0), (0, 6)], [(0, 3), (2, 0), (3, 0)]),
    "162-24-6":  (9, 9,  [(0, 0), (0, 1), (0, 2)], [(0, 3), (3, 0), (6, 0)]),
    "270-8-18":  (9, 15, [(3, 0), (0, 1), (0, 2)], [(0, 3), (1, 0), (2, 0)]),
    "98-6-12":   (7, 7,  [(1, 0), (0, 3), (0, 4)], [(0, 1), (3, 0), (4, 0)]),
    "162-8-12":  (9, 9,  [(3, 0), (0, 1), (0, 2)], [(0, 3), (1, 0), (2, 0)]),
}

# The row this campaign submitted.
SUBMITTED = "128-14-12"


def _shift_matrix(l: int, m: int, i: int, j: int) -> np.ndarray:
    """M_{(i,j)}: the permutation matrix for the monomial x^i y^j.

    Same indexing as research/kit/bb.py: cell (a, b) of Z_l x Z_m sits at
    index a * m + b, and the monomial acts as the Kronecker product of the two
    cyclic shifts.
    """
    S = np.zeros((l * m, l * m), dtype=np.int64)
    for a in range(l):
        for b in range(m):
            S[a * m + b, ((a + i) % l) * m + (b + j) % m] = 1
    return S


def poly_matrix(terms, l: int, m: int) -> np.ndarray:
    """M(p) = sum over the support of p of M_{(i,j)}, over GF(2)."""
    M = np.zeros((l * m, l * m), dtype=np.int64)
    for (i, j) in terms:
        M ^= _shift_matrix(l, m, i, j)
    return M


def build(l: int, m: int, c_terms, d_terms):
    """Return (HX, HZ) for the BB code C(c, d). CSS commutation is guaranteed.

    Matches research/kit/bb.py's build_bb: HX = [M(c) | M(d)],
    HZ = [M(d)^T | M(c)^T].
    """
    Mc = poly_matrix(c_terms, l, m)
    Md = poly_matrix(d_terms, l, m)
    HX = np.hstack([Mc, Md])
    HZ = np.hstack([Md.T, Mc.T])
    return HX, HZ


def build_from_table(key: str):
    l, m, ct, dt = TABLE_1[key]
    return build(l, m, ct, dt)


def _gf2_rank(M: np.ndarray) -> int:
    M = (np.asarray(M) % 2).astype(np.int64).copy()
    r = 0
    for c in range(M.shape[1]):
        piv = next((i for i in range(r, M.shape[0]) if M[i, c]), None)
        if piv is None:
            continue
        M[[r, piv]] = M[[piv, r]]
        for i in range(M.shape[0]):
            if i != r and M[i, c]:
                M[i] ^= M[r]
        r += 1
    return r


if __name__ == "__main__":
    for label, (l, m, ct, dt) in TABLE_1.items():
        HX, HZ = build(l, m, ct, dt)
        n = HX.shape[1]
        k = n - _gf2_rank(HX) - _gf2_rank(HZ)
        w = max(int(r.sum()) for r in HX)
        commute = not bool(((HX @ HZ.T) % 2).any())
        claimed = "-".join(label.split("-"))
        print(f"{label:12s} n={n:4d} k={k:3d} w={w:2d} "
              f"commutes={commute}  (paper: [[{claimed}]])")
