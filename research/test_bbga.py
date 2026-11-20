"""The weighted-shift BBGA constructor must reproduce arXiv:2609.36213.

The A4 x C6 [[144,16,12]] matrices are pinned to the paper's own SHA-256
digests (its Appendix A, row-major uint8), which fixes every convention in
``group_algebra.build_bbga`` at once: group-element order, permutation
composition direction, and which side each shift multiplies on. A convention
drift shows up here as a digest mismatch. The other four instances are checked
on (n, k), CSS, PQ = QP and check weights; the 18-qubit weighted-seed example
is also checked for its weight-3 witness.

Run: uv run pytest research/test_bbga.py
"""

import hashlib

import numpy as np
import pytest
from css import compute_k, verify_css
from group_algebra import A4C6_DIGESTS, PAPER_INSTANCES, build_paper_instance, weighted_shifts
from surrogate import distance_rand


def _sha(H):
    return hashlib.sha256(np.ascontiguousarray(H.astype(np.uint8)).tobytes()).hexdigest()


def test_a4c6_matches_the_papers_digests():
    HX, HZ = build_paper_instance("a4c6-144-16-12")
    assert _sha(HX) == A4C6_DIGESTS["HX"]
    assert _sha(HZ) == A4C6_DIGESTS["HZ"]


@pytest.mark.parametrize("name", sorted(PAPER_INSTANCES))
def test_paper_instances_have_their_stated_n_and_k(name):
    shifts, A_terms, B_terms, (n, k, _d), _note = PAPER_INSTANCES[name]
    mul, a, b = shifts()
    P, Q = weighted_shifts(mul, a, b)
    assert np.array_equal((P.astype(int) @ Q) % 2, (Q.astype(int) @ P) % 2)
    HX, HZ = build_paper_instance(name)
    assert HX.shape == (n // 2, n)
    assert verify_css(HX, HZ)
    assert compute_k(HX, HZ) == k


def test_weighted_seeds_give_mixed_check_weights_and_d3_witness():
    HX, HZ = build_paper_instance("c3w-18-4-3")
    assert sorted(set(HX.sum(1).tolist())) == [6, 8]
    assert sorted(set(HZ.sum(1).tolist())) == [6, 8]
    assert distance_rand(HX, HZ, trials=500, seed=0) == 3
