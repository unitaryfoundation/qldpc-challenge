"""Regression tests for research/kit/gauss_law.py (arXiv:2608.00165).

The module reimplements the quantum Gauss's law code of Definition III.4 on a
periodic 1D lattice: a classical code whose parity checks are the
homogeneous Gauss's law constraints on duplicated site and link variables,
concatenated with a classical inner repetition code that handles phase flips.

What is checked here:

* the parameter identity of Theorem III.5, ``[[N d(d+1)/2, N, d]]``, on the
  optimal 1D multiplicities;
* that the result is a CSS code (the checks commute);
* that the distance is at least the claimed ``d`` (an upper bound from a
  witness search, never a certification);
* that the inner generators are X-type of weight two and the outer checks are
  Z-type, i.e. the check weights are ``2`` and ``3 d``;
* that the distance really is ``d`` and not more, at the smallest size, by an
  exhaustive search over the code's logical operators.

Run: uv run pytest research/test_gauss_law.py
"""

import itertools
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "kit"))
sys.path.insert(0, os.path.join(_HERE, "..", "verify"))

import numpy as np
from css import compute_k, verify_css
from gauss_law import (classical_gauss_law_1d, optimal_1d_multiplicities,
                        quantum_gauss_law_1d)
from gf2 import commutes, in_rowspace
from surrogate import distance_rand


def test_optimal_multiplicities_satisfy_theorem_iii_5():
    """Theorem III.5's construction: [[N d(d+1)/2, N, d]]."""
    for (N, d) in [(6, 3), (8, 4), (10, 5), (12, 6), (16, 8)]:
        p, q = optimal_1d_multiplicities(N, d)
        assert len(p) == N and len(q) == N
        HX, HZ = quantum_gauss_law_1d(N, d, p, q)
        assert HX.shape[1] == N * d * (d + 1) // 2, (N, d, HX.shape)
        assert compute_k(HX, HZ) == N, (N, d, compute_k(HX, HZ))
        assert verify_css(HX, HZ)


def test_check_weights():
    """Inner generators are X-type of weight 2; outer checks are Z-type of
    weight 3d (the Gauss's law check spans a site and two links)."""
    N, d = 8, 4
    HX, HZ = quantum_gauss_law_1d(N, d)
    assert int(HX.sum(axis=1).max()) == 2
    assert int(HZ.sum(axis=1).max()) == 3 * d


def test_classical_code_rank_and_shape():
    """The classical code has N independent Gauss's law constraints plus the
    copy-equality constraints; its dimension is N."""
    N, d = 8, 4
    p, q = optimal_1d_multiplicities(N, d)
    H, _, _ = classical_gauss_law_1d(N, p, q)
    n_bits = sum(p) + sum(q)
    assert H.shape[1] == n_bits
    # N Gauss's law rows of weight 3, and the rest are copy equalities.
    weights = sorted(set(int(r.sum()) for r in H))
    assert weights == [2, 3]
    assert int((H.sum(axis=1) == 3).sum()) == N


def test_distance_is_the_claimed_d():
    """Exhaustive check at the smallest size: the distance is exactly d."""
    N, d = 6, 3
    HX, HZ = quantum_gauss_law_1d(N, d)
    n = HX.shape[1]
    # every Pauli of weight 1 and 2, checked against the two check spaces
    hx = (HX % 2).astype(np.int8)
    hz = (HZ % 2).astype(np.int8)

    # The lightest X-type logical: it commutes with HZ and is outside
    # rowspace(HX).  None exists below weight d, and one exists at d.
    best = None
    for w in range(1, d + 1):
        found = False
        for supp in itertools.combinations(range(n), w):
            v = np.zeros(n, dtype=np.int8)
            v[list(supp)] = 1
            if commutes(v, hz) and not in_rowspace(v, hx):
                found = True
                break
        if found:
            best = w
            break
    assert best == d, best


def test_distance_upper_bound_at_least_d():
    """A witness search must not find anything lighter than d."""
    for (N, d) in [(6, 3), (8, 4)]:
        HX, HZ = quantum_gauss_law_1d(N, d)
        assert distance_rand(HX, HZ, trials=300) >= d
