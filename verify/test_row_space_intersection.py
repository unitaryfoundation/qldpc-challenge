"""Tests for the CSS row-space intersection diagnostic."""

import json
import os
import sys

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from qldpc_verify import (  # noqa: E402
    css_row_space_intersection_dimension,
    verify,
)


def dim(hx, hz):
    return css_row_space_intersection_dimension(np.asarray(hx, dtype=np.uint8), np.asarray(hz, dtype=np.uint8))


def test_known_intersection_dimension():
    # row(HX)=<e0,e1>, row(HZ)=<e1,e2>; the intersection is <e1>.
    assert dim([[1, 0, 0], [0, 1, 0]], [[0, 1, 0], [0, 0, 1]]) == 1


def test_disjoint_and_identical_row_spaces():
    assert dim([[1, 0, 0]], [[0, 1, 0]]) == 0
    assert dim([[1, 0, 1], [0, 1, 1]], [[1, 0, 1], [0, 1, 1]]) == 2


def test_generator_basis_and_redundancy_do_not_change_it():
    hx = [[1, 0, 1, 0], [0, 1, 1, 0]]
    hz = [[1, 1, 0, 0], [0, 0, 0, 1]]
    expected = dim(hx, hz)
    # Replace the second X generator by its XOR with the first, then add
    # duplicate/dependent rows. The generated row spaces are unchanged.
    hx2 = [[1, 0, 1, 0], [1, 1, 0, 0], [1, 0, 1, 0], [0, 1, 1, 0]]
    assert dim(hx2, hz) == expected


def test_qubit_permutation_does_not_change_it():
    hx = np.asarray([[1, 0, 1, 0], [0, 1, 1, 0]], dtype=np.uint8)
    hz = np.asarray([[1, 1, 0, 0], [0, 0, 0, 1]], dtype=np.uint8)
    permutation = [2, 0, 3, 1]
    assert css_row_space_intersection_dimension(hx, hz) == (
        css_row_space_intersection_dimension(hx[:, permutation], hz[:, permutation])
    )


def test_global_x_z_exchange_does_not_change_it():
    hx = [[1, 0, 1, 0], [0, 1, 1, 0]]
    hz = [[1, 1, 0, 0], [0, 0, 0, 1]]
    assert dim(hx, hz) == dim(hz, hx)


def _load_code(slug):
    path = os.path.join(_ROOT, "codes", f"{slug}.json")
    if not os.path.exists(path):
        pytest.skip(f"board entry {slug} has been removed")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


_ROOT = os.path.dirname(_HERE)


def _checks_matrix(rows, n):
    out = np.zeros((len(rows), n), dtype=np.uint8)
    for i, row in enumerate(rows):
        out[i, row] = 1
    return out


def _board_intersection(slug):
    doc = _load_code(slug)
    n = doc["n"]
    return css_row_space_intersection_dimension(
        _checks_matrix(doc["checks"]["X"], n),
        _checks_matrix(doc["checks"]["Z"], n),
    )


def test_real_board_regressions_separate_same_parameter_entries():
    # These entries share the same (n, k, d) inside each cluster, so distance
    # cannot separate them; the diagnostic supplies additional information.
    expected = {
        "144-8-16": 8,
        "144-8-16-b": 34,
        "168-4-14": 24,
        "168-4-14-b": 0,
        "36-10-4": 9,
        "36-10-4-b": 1,
        "12-4-2": 4,
        "12-4-2-b": 0,
        "12-4-2-c": 3,
    }
    for slug, value in expected.items():
        assert _board_intersection(slug) == value


def test_verifier_reports_the_css_diagnostic_without_making_it_a_check():
    report = verify(_load_code("144-8-16"))
    assert report["computed"]["diagnostics"]["row_space_intersection_dimension"] == 8
    assert all(check["check"] != "row_space_intersection_dimension" for check in report["checks"])
