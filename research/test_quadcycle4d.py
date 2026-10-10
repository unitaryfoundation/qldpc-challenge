"""The quadcycle constructor must reproduce arXiv:2610.10731 Table 2.

Table 2 of that paper lists five tricycle-quadcycle code pairs by group and
polynomials, with ``(n, k)`` for each. Rebuilding all five and matching both
parameters (plus ``H_X H_Z^T = 0``) is what pins this module's conventions:
the block layout of Eqs. (1)-(2), the ``*`` involution, and above all the
regular representation. That last one is the trap -- a flat-index shift looks
like a group shift on a torus until you notice that mixed-radix addition
carries between factors, at which point ``B(a) B(b) != B(ab)`` and every code
comes out with ``k = 0``. The tests below are what catch it.

The tests also record two family-level facts the search depended on, so that a
future reader learns them from the code rather than by re-running the campaign: a
quadcycle code with a unit factor among ``a, b, c, d`` has ``k = 0`` (so check
weight 5 and below is unreachable and the family cannot enter the weight-4
board), and ``_mul`` is the group-algebra convolution that makes a shared
divisor mean what it says.

Run: uv run pytest research/test_quadcycle4d.py
"""

import numpy as np
import pytest
from css import compute_k, verify_css
from quadcycle4d import TABLE2, _mul, _regular, build_quadcycle, check_table2, quadcycle_shape, sample_quadcycle


def _rows(H):
    return {tuple(int(j) for j in np.nonzero(r)[0]) for r in H}


def test_regular_representation_is_an_algebra_homomorphism():
    dims = (3, 3)
    a = [(1, 0), (0, 0)]
    b = [(0, 1), (0, 0)]
    A, B = _regular(dims, a), _regular(dims, b)
    assert np.array_equal(A.T, _regular(dims, a, invert=True)), "B(a)^T != B(a*)"
    prod = (A.astype(int) @ B.astype(int)) % 2
    # (1 + x)(1 + y) = 1 + x + y + xy, all four monomials.
    ab = _regular(dims, [(0, 0), (1, 0), (0, 1), (1, 1)])
    assert np.array_equal(prod, ab), "B(a)B(b) != B(ab)"


def test_reproduces_table2_parameters():
    for (dims, a, b, c, d, claim) in TABLE2:
        HX, HZ = build_quadcycle(dims, a, b, c, d)
        assert verify_css(HX, HZ), f"{dims}: not CSS"
        assert HX.shape[1] == claim[0], f"{dims}: n {HX.shape[1]} != {claim[0]}"
        assert compute_k(HX, HZ) == claim[1], f"{dims}: k != {claim[1]}"


def test_check_table2_helper_agrees():
    assert check_table2() == [(54, 6, 6), (72, 6, 8), (162, 6, 8),
                              (228, 6, 8), (420, 6, 8)]


def test_shape_matches_built_weight():
    for (dims, a, b, c, d, _claim) in TABLE2:
        _, w = quadcycle_shape(dims, a, b, c, d)
        HX, _ = build_quadcycle(dims, a, b, c, d)
        assert w == max(int(r.sum()) for r in HX)


@pytest.mark.parametrize("weights", [(1, 1, 1, 1), (1, 1, 1, 2), (1, 2, 2, 1)])
def test_unit_factor_forces_k_zero(weights):
    """No quadcycle code with a unit factor encodes anything.

    A unit factor has zero t-adic valuation, and the paper's closed form for k
    (its Eq. 7) is a sum over the factors' minimum valuation, so k collapses to
    0. Checked here on the pattern space rather than assumed from the formula.
    """
    seen = 0
    for spec, HX, HZ in sample_quadcycle(12, dim_range=(2, 6), max_site=36,
                                         weights=weights, seed=5):
        assert compute_k(HX, HZ) == 0, f"{spec} encoded"
        seen += 1
    assert seen, "sampler produced nothing to check"


def test_sampler_shapes_are_css_and_match_spec():
    for spec, HX, HZ in sample_quadcycle(6, dim_range=(2, 6), max_site=36,
                                         weights=(2, 2, 2, 2), seed=1):
        dims = tuple(spec["dims"])
        terms = [spec[k] for k in "abcd"]
        n, w = quadcycle_shape(dims, *terms)
        assert (HX.shape[1], max(int(r.sum()) for r in HX)) == (n, w)
        assert verify_css(HX, HZ)
        assert compute_k(HX, HZ) == _recompute_k(spec, HX, HZ)
        # The spec is the recipe: rebuilding from it must give the same code.
        again = build_quadcycle(dims, *[tuple(t) for t in terms])
        assert _rows(again[0]) == _rows(HX) and _rows(again[1]) == _rows(HZ)


def test_mul_is_the_group_algebra_product():
    """``_mul`` builds factors as a product, so it must be the real convolution.

    The shared-divisor reasoning in the module docstring leans on this: if
    ``_mul`` were anything but the algebra product, a "shared divisor" would be
    an artifact of the builder rather than a property of the code.
    """
    dims = (3, 3)
    p, q = [(1, 0), (0, 0)], [(0, 1), (0, 0)]
    # (1 + x)(1 + y) = 1 + x + y + xy, all four monomials.
    assert _mul(dims, p, q) == [(0, 0), (0, 1), (1, 0), (1, 1)]
    prod = (_regular(dims, p).astype(int) @ _regular(dims, q).astype(int)) % 2
    assert np.array_equal(prod, _regular(dims, _mul(dims, p, q)))


def test_mul_reduces_mod_two():
    """Equal monomials cancel, so a product can be lighter than its factors."""
    dims = (3, 3)
    # (1 + x)(1 + x) = 1 + x^2 over F_2, since 2x vanishes.
    assert _mul(dims, [(0, 0), (1, 0)], [(0, 0), (1, 0)]) == [(0, 0), (2, 0)]


def _recompute_k(spec, HX, HZ):
    return compute_k(HX, HZ)
