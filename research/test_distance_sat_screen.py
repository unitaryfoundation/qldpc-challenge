"""Tests for the SAT-based lower-bound screening helpers (PR #4311)."""
import os
import sys

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "kit"))

from distance import sat_lower_bound, sat_screen, weight_one_logical_exists

STEANE = np.array([[1, 0, 1, 0, 1, 0, 1],
                   [0, 1, 1, 0, 0, 1, 1],
                   [0, 0, 0, 1, 1, 1, 1]], dtype=np.int8)
# A code with a qubit in no check on either side -> distance 1.
D1_HX = np.array([[1, 0]], dtype=np.int8)
D1_HZ = np.array([[0, 0]], dtype=np.int8)


def test_weight_one_logical_on_d1_code():
    assert weight_one_logical_exists(D1_HX, D1_HZ) is True


def test_weight_one_logical_absent_on_steane():
    assert weight_one_logical_exists(STEANE, STEANE) is False


def test_sat_lower_bound_refuted_on_d1_code():
    r = sat_lower_bound(D1_HX, D1_HZ, min_d=2, tlim=30)
    assert r["outcome"] == "refuted"
    assert r["witness"] is not None
    assert sat_screen(D1_HX, D1_HZ, min_d=2, tlim=30) is True


def test_sat_lower_bound_proved_on_steane():
    r = sat_lower_bound(STEANE, STEANE, min_d=2, tlim=60)
    assert r["outcome"] == "proved"
    assert r["both_sides_unsat"] is True
    assert sat_screen(STEANE, STEANE, min_d=2, tlim=60) is False


def test_sat_lower_bound_timeout_is_not_refutation():
    import numpy as np
    from bb import build_bb, KNOWN
    p = KNOWN["[[72,12,6]]"]
    HX, HZ = build_bb(p["l"], p["m"], p["A"], p["B"])
    r = sat_lower_bound(HX, HZ, min_d=6, tlim=0.001)
    assert r["outcome"] == "timeout"
    assert sat_screen(HX, HZ, min_d=6, tlim=0.001) is None


def test_sat_lower_bound_min_d_4_refuted_on_steane():
    r = sat_lower_bound(STEANE, STEANE, min_d=4, tlim=60)
    assert r["outcome"] == "refuted"