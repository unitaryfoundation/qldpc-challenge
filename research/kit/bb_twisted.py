"""Twisted-torus bicycle (GBC) codes.

A twisted-torus bicycle code is a CSS code built from two bivariate
polynomials f(x,y), g(x,y) over the abelian quotient group Z^2 / L,
where L = <a1, a2> is a rank-2 sublattice of Z^2 (the "twist basis").

The construction (arXiv:2503.03827, Liang et al., PRX Quantum 6, 020357,
2025) is a generalized bicycle code (GBC):

    H_X = [ F | G ],   H_Z = [ Gbar | Fbar ]

where F, G are the circulant-like monomial matrices for f, g on the
quotient group, and Gbar/Fbar use negated exponents (the group inverse,
which for an abelian group is just -p, -q).

The quotient Z^2 / L has N = |det[a1, a2]| elements. Each qubit is
labelled by a coset representative (i, j) in the fundamental domain.
A monomial (p, q) acts by translation (i, j) -> (i+p, j+q) reduced mod L.

When L is the rectangular lattice <(l,0),(0,m)> this reduces to the
ordinary periodic torus (``bb.build_bb``). The twist basis a1, a2 lets
the quotient be a non-rectangular (sheared) torus, which is what yields
the board leader [[360,12,24]] (a1=[0,30], a2=[6,6], f=1+x+x^-1 y^3,
g=1+y+x^3 y^-1).

Quotient enumeration uses the Hermite normal form of [a1 a2] for an exact
canonical coset representative (no floating-point error).
"""
import numpy as np
import sympy as sp
from sympy.matrices.normalforms import hermite_normal_form


def _quotient(a1, a2):
    """Return (N, pts, reduce_vec) for the quotient Z^2 / <a1, a2>.

    pts : list of (i, j) canonical coset representatives, length N.
    reduce_vec(vec) : map any (i, j) to its canonical representative index.
    Returns None if the lattice basis is degenerate (singular).
    """
    a1 = np.array(a1, dtype=int)
    a2 = np.array(a2, dtype=int)
    M = sp.Matrix([[a1[0], a2[0]], [a1[1], a2[1]]])
    det = M.det()
    if det == 0:
        return None  # degenerate basis
    H = hermite_normal_form(M)                       # exact, upper-triangular
    U = (H * M.inv()).applyfunc(lambda x: int(x))    # unimodular, exact
    H = np.array(H.tolist(), dtype=int)
    U = np.array(U.tolist(), dtype=int)
    try:
        Ui = np.round(np.linalg.inv(U)).astype(int)  # exact integer inverse
    except np.linalg.LinAlgError:
        return None  # degenerate HNF transform
    h11, h12, h22 = H[0, 0], H[0, 1], H[1, 1]
    N = h11 * h22

    def coset_key(p):
        p0, p1 = int(p[0]), int(p[1])
        c1 = U[0, 0] * p0 + U[0, 1] * p1
        c2 = U[1, 0] * p0 + U[1, 1] * p1
        y = c2 % h22
        x = (c1 - h12 * (c2 // h22)) % h11
        return (x, y)

    def key_to_std(key):
        x, y = key
        return (int(Ui[0, 0] * x + Ui[0, 1] * y),
                int(Ui[1, 0] * x + Ui[1, 1] * y))

    index = {}
    pts = []
    for x in range(h11):
        for y in range(h22):
            key = (x, y)
            index[key] = len(pts)
            pts.append(key_to_std(key))
    assert len(pts) == N, f"{len(pts)} != {N}"

    def reduce_vec(vec):
        return index[coset_key(vec)]

    return N, pts, reduce_vec


def build_twisted_gbc(a1, a2, f_terms, g_terms):
    """Build a twisted-torus bicycle code.

    Parameters
    ----------
    a1, a2 : (int, int)
        Twist-basis lattice vectors spanning L = <a1, a2>. n = 2*|det[a1,a2]|.
    f_terms, g_terms : list of (int, int)
        Monomial offsets (p, q) for the polynomials f, g. Each term is a
        translation on the quotient group. The constant term is (0, 0).

    Returns
    -------
    HX, HZ : (n, n) int8 arrays, the CSS parity checks.
    """
    result = _quotient(a1, a2)
    if result is None:
        raise ValueError(f"degenerate lattice basis: a1={a1}, a2={a2}")
    N, pts, reduce_vec = result

    def mono(terms):
        Mat = np.zeros((N, N), dtype=np.int8)
        for (p, q) in terms:
            for src, (i, j) in enumerate(pts):
                t = reduce_vec((i + p, j + q))
                Mat[src, t] = (Mat[src, t] + 1) % 2
        return Mat

    F = mono(f_terms)
    G = mono(g_terms)
    Gbar = mono([(-p, -q) for (p, q) in g_terms])
    Fbar = mono([(-p, -q) for (p, q) in f_terms])
    HX = np.hstack([F, G]).astype(np.int8)
    HZ = np.hstack([Gbar, Fbar]).astype(np.int8)
    return HX, HZ


if __name__ == "__main__":
    from css import verify_css, compute_k
    from surrogate import distance_rand
    # Reproduce the board leader [[360,12,24]] (arXiv:2503.03827).
    a1 = [0, 30]
    a2 = [6, 6]
    f_terms = [(0, 0), (1, 0), (-1, 3)]   # f = 1 + x + x^-1 y^3
    g_terms = [(0, 0), (0, 1), (3, -1)]   # g = 1 + y + x^3 y^-1
    HX, HZ = build_twisted_gbc(a1, a2, f_terms, g_terms)
    n = HX.shape[1]
    k = compute_k(HX, HZ)
    d = distance_rand(HX, HZ, trials=400)
    print(f"360-12-24 repro: n={n} k={k} css={verify_css(HX, HZ)} d<={d} "
          f"(expect 360,12,24)")
