"""Bivariate-bicycle (BB) codes on the torus Z_l x Z_m -- the canonical entry
family (the IBM "gross code" family, Bravyi et al., arXiv:2308.07915).

This is the *periodic* construction, and the simplest place to start: CSS
commutation is automatic because all circulants over the abelian group
Z_l x Z_m commute, so any choice of monomials gives a valid CSS code.

Conventions
-----------
  x = S_l (x) I_m     (cyclic shift of order l)
  y = I_l (x) S_m     (cyclic shift of order m)
A monomial x^a y^b is the permutation matrix S_l^a (x) S_m^b on the l*m
group-algebra qubits (index = i*m + j for cell (i mod l, j mod m)).

  A = sum_{(a,b) in A_terms} x^a y^b
  B = sum_{(c,d) in B_terms} x^c y^d
  H_X = [A | B],  H_Z = [B^T | A^T],   n = 2*l*m

Targets the ``bivariate bicycle (periodic)`` track; checks have weight
|A_terms| + |B_terms| (filtered by the w slider on the board, not a track).
"""
import numpy as np


def _shift(r):
    """r x r cyclic shift matrix S with S[i, (i+1) % r] = 1 (int8)."""
    S = np.zeros((r, r), dtype=np.int8)
    idx = np.arange(r)
    S[idx, (idx + 1) % r] = 1
    return S


def _monomial(l, m, a, b):
    """x^a y^b = S_l^a (x) S_m^b as an (l*m) x (l*m) int8 permutation matrix."""
    Sl = np.linalg.matrix_power(_shift(l), a % l).astype(np.int8)
    Sm = np.linalg.matrix_power(_shift(m), b % m).astype(np.int8)
    return np.kron(Sl, Sm).astype(np.int8)


def poly_matrix(l, m, terms):
    """Sum of monomials (mod 2) for ``terms`` = list of (a, b) exponent pairs."""
    M = np.zeros((l * m, l * m), dtype=np.int8)
    for (a, b) in terms:
        M = (M + _monomial(l, m, a, b)) % 2
    return M.astype(np.int8)


def build_bb(l, m, A_terms, B_terms):
    """Build the periodic BB code on Z_l x Z_m.

    Parameters
    ----------
    l, m : int
        Torus dimensions (orders of x and y).
    A_terms, B_terms : list of (a, b)
        Monomial exponent pairs for the two circulant blocks.

    Returns
    -------
    HX, HZ : int8 arrays of shape (l*m, 2*l*m). CSS commutation is guaranteed.
    """
    A = poly_matrix(l, m, A_terms)
    B = poly_matrix(l, m, B_terms)
    HX = np.concatenate([A, B], axis=1).astype(np.int8)
    HZ = np.concatenate([B.T, A.T], axis=1).astype(np.int8)
    return HX, HZ


# Known records (Bravyi et al.) for validation / as starting points.
# term lists use (x-exponent, y-exponent).
KNOWN = {
    "[[72,12,6]]":   dict(l=6,  m=6,  A=[(3, 0), (0, 1), (0, 2)], B=[(0, 3), (1, 0), (2, 0)]),
    "[[90,8,10]]":   dict(l=15, m=3,  A=[(9, 0), (0, 1), (0, 2)], B=[(0, 0), (2, 0), (7, 0)]),
    "[[108,8,10]]":  dict(l=9,  m=6,  A=[(3, 0), (0, 1), (0, 2)], B=[(0, 3), (1, 0), (2, 0)]),
    "[[144,12,12]]": dict(l=12, m=6,  A=[(3, 0), (0, 1), (0, 2)], B=[(0, 3), (1, 0), (2, 0)]),
    "[[288,12,18]]": dict(l=12, m=12, A=[(3, 0), (0, 2), (0, 7)], B=[(0, 3), (1, 0), (2, 0)]),
}


if __name__ == "__main__":
    from css import verify_css, compute_k
    from surrogate import distance_rand

    print(f"{'code':>16}  {'n':>4} {'k':>3}  css  {'d<=':>5}")
    for name, p in KNOWN.items():
        HX, HZ = build_bb(p["l"], p["m"], p["A"], p["B"])
        n = HX.shape[1]
        css = verify_css(HX, HZ)
        k = compute_k(HX, HZ)
        trials = 400 if n <= 150 else 150  # d_rand is an upper bound; cap for big n
        d = distance_rand(HX, HZ, trials=trials, seed=0)
        print(f"{name:>16}  {n:>4} {k:>3}  {str(css):>4}  {d:>5}")
