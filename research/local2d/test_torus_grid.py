"""Tests for the torus-grid layout scan.

The construction is exact, so these assert exact numbers rather than bounds.
They use `verify/fixtures/72-6-6.json`: the weight-6 BB form
f = 1 + xy + x^-1 y^2, g = 1 + x^-1 y + x^-2 y^-1 on a (6,6) lattice with open
boundaries. The bulk checks sit inside a small window of the grid, but the
boundary-completion engine adds checks that are shaped differently -- one of
them spans a 1 x 4 window, and it is the one that sets the interaction radius
below. That is the point worth pinning: the radius is whatever the widest check
actually is, not what the bulk construction suggests it should be.
"""
import json
import math
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FIXTURE = os.path.join(ROOT, "verify", "fixtures", "72-6-6.json")

import torus_grid as tg                                          # noqa: E402


@pytest.fixture(scope="module")
def doc():
    with open(FIXTURE) as f:
        return json.load(f)


def test_grid_is_two_blocks_stacked_on_one_site():
    """n = 2*l*m and qubit (i,j) of each block shares site (i,j)."""
    pts = tg.grid(6, 6)
    assert len(pts) == 72
    assert pts[0] == pts[36]          # index i*m + j, second block offsets by l*m
    assert pts[13] == pts[49]
    assert pts[35] == pts[71]
    assert len(set(pts)) == 36        # 36 sites, 72 qubits: occupancy 2


def test_occupancy_and_spacing_are_the_verifier_honesty_checks():
    occ, spacing = tg.honesty(tg.grid(6, 6))
    assert occ == 2
    assert spacing == 1.0


def test_radius_is_set_by_the_widest_boundary_check_not_the_bulk():
    """The bulk checks sit in small windows; a boundary-completed check does not."""
    doc = json.load(open(FIXTURE))
    sup = tg.supports(doc)
    pts = tg.grid(6, 6)
    all_r = tg.radius(sup, pts)
    # sqrt(17) = the 1 x 4 span of check [28, 62, 66, 70], the widest one here
    assert math.isclose(all_r, math.sqrt(17), abs_tol=1e-9)
    # the Z side alone is tighter: sqrt(10), a 1 x 3 span
    assert math.isclose(tg.radius(doc["checks"]["Z"], pts), math.sqrt(10),
                        abs_tol=1e-9)
    assert all_r > tg.radius(doc["checks"]["Z"], pts)


def test_scan_finds_the_right_factorisation_and_reports_the_class_cap():
    got = tg.scan(json.load(open(FIXTURE)), occupancy=2, top=1)
    assert len(got) == 1
    (c,) = got
    assert (c["l"], c["m"]) == (6, 6)
    assert c["layers"] == 2
    assert c["radius"] == 4.1231
    assert c["spacing"] == 1.0
    assert c["within_cap"] is True      # 4.1231 <= the bilayer cap 7.0


def test_occupancy_one_rejects_the_stacked_layout():
    """Folding an axis shrinks the radius but raises occupancy past any cap."""
    assert tg.scan(json.load(open(FIXTURE)), occupancy=1, top=3) == []


def test_folded_convention_raises_occupancy_to_four():
    occ, spacing = tg.honesty(tg.grid(6, 6, fold_i=True))
    assert occ == 4
    assert spacing == 1.0


def test_scan_rejects_odd_n_and_non_css():
    """Neither has a two-block Z_l x Z_m index convention to scan."""
    assert tg.scan({"code_type": "CSS", "n": 71, "checks": {"X": [[0]],
                    "Z": [[0]]}}, occupancy=2) == []
    assert tg.scan({"code_type": "stabilizer", "n": 72,
                    "checks": {"S": [{"X": [0], "Z": []}]}}, occupancy=2) == []


def test_divisors_cover_both_orders():
    assert tg.divisors(36)[:4] == [(1, 36), (2, 18), (3, 12), (4, 9)]
    assert all(w * h == 36 for w, h in tg.divisors(36))
    assert (6, 6) in tg.divisors(36)