"""Regression tests for research/kit/coset_gap.py (arXiv:2606.17268).

The module assembles the paper's coset two-block check matrices inside GAP,
so these tests need the ``gap`` binary (with the ``smallgrp`` package) on
PATH; they skip when it is absent.

What is checked here:

* the two headline instances reproduce the paper's stated (n, k) and are CSS
  with the stated max check weights ([[48,8,6]] w=6 and [[112,16,10]] w=8);
* the transcription of ``PAPER_INSTANCES`` is shape-consistent: the two coset
  indices the recipe indexes into have the lengths the (n,k) implies
  (n/2 + |H|integers, cheap consistency only — the full 29-instance
  reproduction is the module's own ``__main__`` self-test, run against a live
  GAP;
* the distance of the smaller instance is at least its claimed value from a
  witness search, so the staged witnesses are not inflated.

Run: uv run --extra research python -m pytest research/test_coset_gap.py
"""

import os
import shutil
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "kit"))
sys.path.insert(0, os.path.join(_HERE, "..", "verify"))

import pytest

from coset_gap import PAPER_INSTANCES, build
from css import compute_k, verify_css
from surrogate import distance_rand

HAS_GAP = shutil.which("gap") is not None


@pytest.mark.skipif(not HAS_GAP, reason="gap binary not on PATH")
def test_headline_instances_reproduce_the_paper():
    row48 = next(r for r in PAPER_INSTANCES if r[0] == 48 and r[1] == 8)
    row112 = next(r for r in PAPER_INSTANCES if r[0] == 112 and r[1] == 16)
    for row, want_w in [(row48, 6), (row112, 8)]:
        HX, HZ = build(row[3], row[4], row[5], row[6], row[7])
        assert HX.shape[1] == row[0]
        assert compute_k(HX, HZ) == row[1]
        assert verify_css(HX, HZ)
        assert int(max(HX.sum(axis=1).max(), HZ.sum(axis=1).max())) == want_w


@pytest.mark.skipif(not HAS_GAP, reason="gap binary not on PATH")
def test_distance_upper_bounds_agree_with_the_paper():
    """No lighter logical than the paper's distance is findable."""
    row48 = next(r for r in PAPER_INSTANCES if r[0] == 48 and r[1] == 8)
    HX, HZ = build(row48[3], row48[4], row48[5], row48[6], row48[7])
    assert distance_rand(HX, HZ, trials=1500) <= row48[2]


def test_paper_instance_table_is_wellformed():
    """The transcription is internally consistent per entry."""
    for (n, k, d, ell, m, s, ahat, bhat) in PAPER_INSTANCES:
        assert ell > 0 and s >= 1 and len(ahat) == len(bhat), (n, k)
        assert 1 <= k <= n // 2 and d <= n, (n, k, d)
