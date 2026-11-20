"""Quadricycle codes: rank-4 periodic generalized bicycles.

The natural rank-4 extension of the bivariate-bicycle family: two block
polynomials A, B over the group algebra F_2[G] of the abelian torus
G = Z_l1 x Z_l2 x Z_l3 x Z_l4, with H_X = [A | B], H_Z = [B^T | A^T].
CSS commutation is automatic (all circulants over an abelian group commute),
exactly as in ``bb.py``; n = 2 * l1 * l2 * l3 * l4 and the check weight is
|A_terms| + |B_terms| (assuming distinct terms per side, which the sampler
enforces so supports cannot cancel mod 2).

What makes this a *different search family* from BB codes: the four shifts
are independent, so the code does not reduce to any rank-2 torus. The
trivariate codes of arXiv:2406.19151 use a *dependent* third variable
(z = x*y) and do so reduce; a genuine quadricycle does not.

Sanity anchor: with dims (l, m, 1, 1) and terms padded with zeros, this
module reproduces ``bb.build_bb`` exactly.
"""

import numpy as np


def _shift(r):
    """R x r cyclic shift matrix S with S[i, (i+1) % r] = 1 (int8)."""
    S = np.zeros((r, r), dtype=np.int8)
    idx = np.arange(r)
    S[idx, (idx + 1) % r] = 1
    return S


def _monomial4(dims, term):
    """x1^a x2^b x3^c x4^d as a (prod(dims)) x (prod(dims)) permutation."""
    M = np.array([[1]], dtype=np.int8)
    for r, e in zip(dims, term):
        M = np.kron(M, np.linalg.matrix_power(_shift(r), e % r).astype(np.int8))
    return M


def poly_matrix4(dims, terms):
    """Sum of monomials (mod 2) for ``terms`` = list of 4-tuple exponents."""
    M = np.zeros((int(np.prod(dims)),) * 2, dtype=np.int8)
    for t in terms:
        M = (M + _monomial4(dims, t)) % 2
    return M.astype(np.int8)


def quad_shape(dims, A_terms, B_terms):
    """Exact (n, max_check_weight) from the parameters alone."""
    n = 2 * int(np.prod(dims))
    w = len(set(A_terms)) + len(set(B_terms))
    return n, w


def build_quad(dims, A_terms, B_terms):
    """Build the rank-4 periodic generalized bicycle on Z_l1 x Z_l2 x Z_l3 x Z_l4.

    Returns (HX, HZ) as int8 arrays of shape (prod(dims), 2*prod(dims)).
    """
    A = poly_matrix4(dims, A_terms)
    B = poly_matrix4(dims, B_terms)
    HX = np.hstack([A, B]).astype(np.int8)
    HZ = np.hstack([B.T, A.T]).astype(np.int8)
    return HX, HZ


def sample_quadricycle(
    num, *, dim_range=(2, 11), max_site=350, weight=2, seed=0, n_range=None, max_weight=None, audit=None
):
    """Yield ``num`` random quadricycle candidates ``(spec, HX, HZ)``.

    Each picks a random torus with prod(dims) <= ``max_site`` (so
    n = 2*prod <= 700, the verifier cap) and two sets of ``weight`` distinct
    monomials. ``spec`` is JSON-serializable:
    ``{"family": "quadricycle", "dims": [...], "A": [...], "B": [...]}``.

    ``n_range`` / ``max_weight`` reject before building, using the exact
    (n, w) from ``quad_shape``. Pass ``audit`` as a dict to receive counts.
    """
    rng = np.random.default_rng(seed)
    tally = audit if audit is not None else {}
    for key in ("sampled", "rejected_n", "rejected_w", "built"):
        tally.setdefault(key, 0)

    lo, hi = dim_range
    for _ in range(num):
        # rejection-sample dims with prod <= max_site
        for _try in range(200):
            dims = [int(rng.integers(lo, hi + 1)) for _ in range(4)]
            if int(np.prod(dims)) <= max_site:
                break
        else:
            continue
        grid = [
            (a, b, c, d) for a in range(dims[0]) for b in range(dims[1]) for c in range(dims[2]) for d in range(dims[3])
        ]
        A = [grid[i] for i in rng.choice(len(grid), size=weight, replace=False)]
        B = [grid[i] for i in rng.choice(len(grid), size=weight, replace=False)]
        tally["sampled"] += 1
        n, w = quad_shape(dims, A, B)
        if n_range is not None and not (n_range[0] <= n <= n_range[1]):
            tally["rejected_n"] += 1
            continue
        if max_weight is not None and w > max_weight:
            tally["rejected_w"] += 1
            continue
        tally["built"] += 1
        HX, HZ = build_quad(dims, A, B)
        yield ({"family": "quadricycle", "dims": dims, "A": [list(t) for t in A], "B": [list(t) for t in B]}, HX, HZ)


if __name__ == "__main__":
    import sys

    sys.path.insert(0, "research/kit")
    from bb import build_bb
    from css import compute_k, verify_css

    # sanity: degenerate rank-4 (dims l,m,1,1) must equal bb.build_bb exactly
    A2, B2 = [(6, 6), (5, 0)], [(2, 2), (0, 5)]
    HX2, HZ2 = build_bb(7, 8, A2, B2)
    A4 = [(a, b, 0, 0) for (a, b) in A2]
    B4 = [(a, b, 0, 0) for (a, b) in B2]
    HX4, HZ4 = build_quad((7, 8, 1, 1), A4, B4)
    assert np.array_equal(HX2, HX4) and np.array_equal(HZ2, HZ4), "rank-2 mismatch"
    print("sanity: quad(7,8,1,1) == bb(7,8) exact match")

    # the [[112,2,10]] trivariate row, rebuilt as a quadricycle-shaped code
    assert verify_css(HX4, HZ4)
    k = compute_k(HX4, HZ4)
    print(f"[[112,{k},?]] rebuilt; CSS ok")

    # a genuinely rank-4 code: Z_3 x Z_3 x Z_5 x Z_7, n = 2*315 = 630
    dims = (3, 3, 5, 7)
    A = [(0, 0, 0, 0), (1, 2, 3, 4)]
    B = [(2, 1, 1, 6), (0, 2, 4, 2)]
    HX, HZ = build_quad(dims, A, B)
    assert verify_css(HX, HZ)
    k = compute_k(HX, HZ)
    print(f"[[630,{k},?]] rank-4 demo on Z_3xZ_3xZ_5xZ_7; CSS ok")

    # sampler smoke test
    audit = {}
    got = list(sample_quadricycle(20, seed=1, n_range=(60, 700), audit=audit))
    print(f"sampler: {audit}, first spec dims={got[0][0]['dims']}")
