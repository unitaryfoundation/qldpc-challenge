"""Tests for the designed-divisor route to cyclic GB codes (issue #2778).

What is pinned: the GF(2) factorization is exact, the divisor it hands back
has the degree asked for, the sampler's codes have the k their divisor
designs, and the thing the sampler exists to avoid is real: random supports
at the same weight encode k = 2 nearly every time.
"""

import os
import random
import sys

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "kit"))

import gf2poly as P  # noqa: E402
from css import compute_k, verify_css  # noqa: E402
from search import sample_cyclic_gb  # noqa: E402


def test_x7_minus_1_factors_as_the_textbook_says():
    facs = P.factor_squarefree(P.x_pow_m_minus_1(7), random.Random(1))
    # (x + 1)(x^3 + x + 1)(x^3 + x^2 + 1)
    assert sorted(facs) == sorted([0b11, 0b1011, 0b1101])


@pytest.mark.parametrize("m", [31, 93, 341])
def test_the_factors_multiply_back_and_are_irreducible(m):
    f = P.x_pow_m_minus_1(m)
    facs = P.factor_squarefree(f, random.Random(m))
    prod = 1
    for p in facs:
        prod = P.mul(prod, p)
    assert prod == f
    # Degrees of the irreducible factors are the 2-cyclotomic coset sizes
    # modulo m, so each one divides the order of 2 modulo m.
    order = next(e for e in range(1, m + 1) if pow(2, e, m) == 1)
    assert all(order % P.deg(p) == 0 for p in facs)
    assert sum(P.deg(p) for p in facs) == m


def test_a_designed_divisor_has_the_degree_asked_for():
    facs = P.factor_squarefree(P.x_pow_m_minus_1(93), random.Random(3))
    g = P.designed_divisor(facs, (20, 30), random.Random(3))
    assert g is not None and 20 <= P.deg(g) <= 30
    assert P.mod(P.x_pow_m_minus_1(93), g) == 0
    # An empty band is reported as None rather than a near miss: the factor
    # degrees here are 1, 2, 5, and 10, and no subset sums to 4.
    assert P.designed_divisor(facs, (4, 4), random.Random(3)) is None


def test_sparse_multiples_are_multiples_in_the_weight_band():
    m = 93
    facs = P.factor_squarefree(P.x_pow_m_minus_1(m), random.Random(5))
    g = P.designed_divisor(facs, (20, 30), random.Random(5))
    words = P.sparse_multiples(m, g, (6, 8), np.random.default_rng(5), trials=50)
    assert words
    for w in words:
        assert 6 <= len(w) <= 8
        assert P.mod(P.from_support(w, m), g) == 0


def test_the_sampler_designs_k_and_the_verifier_agrees():
    audit = {}
    codes = list(sample_cyclic_gb(4, m_range=(93, 93), weight=(6, 8), k_band=(40, 60), seed=11, audit=audit))
    assert len(codes) == 4 and audit["built"] == 4
    for spec, HX, HZ in codes:
        assert verify_css(HX, HZ)
        assert HX.shape == (93, 186)
        assert 40 <= spec["k"] <= 60
        assert compute_k(HX, HZ) == spec["k"] == P.designed_k(93, spec["a"], spec["b"])
        assert 12 <= HX.sum(axis=1).max() <= 16


def test_random_supports_at_the_same_weight_encode_almost_nothing():
    """The measurement the sampler rests on, at a size a test can afford.

    gcd(a, b, x^m - 1) for random a, b is 1 or x + 1 (the latter when both
    weights are even), so k is 0 or 2 nearly every time.
    """
    rng = np.random.default_rng(7)
    ks = [P.designed_k(93, rng.choice(93, 7, replace=False), rng.choice(93, 7, replace=False)) for _ in range(40)]
    assert sum(k <= 2 for k in ks) >= 32, ks
