"""Tests for the exhaustive small CSS-code census."""

import os
import sys
import types

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "kit"))
sys.path.insert(0, os.path.join(_HERE, "..", "verify"))

import census_css


def test_rref_subspaces_are_unique_and_complete_through_six_qubits():
    expected = [1, 2, 5, 16, 67, 374, 2825]
    for n, count in enumerate(expected):
        spaces = list(census_css._rref_subspaces(n))
        assert len(spaces) == count
        assert len(set(spaces)) == count
        assert all(census_css._rref_masks(space, n) == space for space in spaces)


def test_small_code_classes_quotient_qubit_permutations_and_global_duality():
    all_classes = list(census_css.iter_css_classes(2, k_min=0))
    encoded_classes = list(census_css.iter_css_classes(2, k_min=1))

    assert len(all_classes) == 6
    assert len(encoded_classes) == 3
    assert all(k == 2 - len(x_rows) - len(z_rows) for x_rows, z_rows, k in all_classes)
    assert all(census_css._orthogonal(x_rows, z_rows) for x_rows, z_rows, _ in all_classes)


def test_exact_distance_retries_with_and_preserves_refuting_witness(monkeypatch):
    doc = {
        "distance": {
            "d": 3,
            "X": {"value": 3, "witness": [0, 1, 2]},
            "Z": {"value": 3, "witness": [0, 1, 2]},
        }
    }
    calls = []

    def make_submission(*args, **kwargs):
        return doc

    def certify(current_doc, tlim):
        calls.append((current_doc["distance"]["d"], tlim))
        if len(calls) == 1:
            return {
                "d_exact": False,
                "sides": {"X": {"status": "SAT", "witness": [1]}},
            }
        return {"d_exact": True, "sides": {"X": {"status": "UNSAT"}, "Z": {"status": "UNSAT"}}}

    monkeypatch.setattr(census_css, "make_submission", make_submission)
    monkeypatch.setattr(census_css, "_load_sat_certifier", lambda: types.SimpleNamespace(certify=certify))

    result = census_css.exact_css_distance(np.zeros((0, 2)), np.zeros((0, 2)), tlim=7)

    assert result["exact"]
    assert result["d"] == 1
    assert result["distance"]["X"]["witness"] == [1]
    assert calls == [(3, 7), (1, 7)]


def test_cli_defaults_and_parameter_ranges():
    defaults = census_css._parse_args([])
    assert (defaults.n_min, defaults.n_max) == (1, 6)
    assert (defaults.k_min, defaults.k_max) == (1, None)
    assert (defaults.d_min, defaults.d_max) == (3, None)

    selected = census_css._parse_args(
        [
            "--n-min",
            "4",
            "--n-max",
            "6",
            "--k-min",
            "2",
            "--k-max",
            "3",
            "--d-min",
            "3",
            "--d-max",
            "5",
        ]
    )
    assert (selected.n_min, selected.n_max) == (4, 6)
    assert (selected.k_min, selected.k_max) == (2, 3)
    assert (selected.d_min, selected.d_max) == (3, 5)


def test_cli_rejects_inconsistent_bounds_and_unsupported_n():
    with pytest.raises(SystemExit):
        census_css._parse_args(["--n-min", "7", "--n-max", "6"])
    with pytest.raises(SystemExit):
        census_css._parse_args(["--n-max", "7"])
    with pytest.raises(ValueError, match="between 1 and 6"):
        list(census_css.iter_css_classes(7))
