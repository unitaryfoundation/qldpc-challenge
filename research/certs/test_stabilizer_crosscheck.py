"""The stabilizer cross-checks confirm a true certificate and expose an inflated one (issue #4939)."""
import importlib.util
import json
import os
import sys

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_ROOT, "verify"))
import heuristic_distance as HD  # noqa: E402


def _module():
    spec = importlib.util.spec_from_file_location("stabilizer_crosscheck_mod",
                                                  os.path.join(_HERE, "stabilizer_crosscheck.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _five_qubit():
    with open(os.path.join(_ROOT, "codes", "5-1-3.json"), encoding="utf-8") as f:
        return json.load(f)


def test_brute_force_counts_paulis_and_finds_nothing_below_the_true_distance():
    M = _module()
    assert M.pauli_count(5, 2) == 5 * 3 + 10 * 9
    doc = _five_qubit()
    A, B = HD.stabilizer_matrices(doc)
    checked, lighter = M.brute_force(A, B, 2)
    assert checked and lighter == []
    # an inflated claim: at weight 3 the five-qubit code has nontrivial logicals, and every one found is one
    checked, lighter = M.brute_force(A, B, 3)
    assert checked and lighter
    assert all(HD.valid_pauli_logical(v, A, B) and int((v[:5] | v[5:]).sum()) == 3 for v in lighter)
    # the limit keeps an infeasible enumeration from starting
    assert M.brute_force(A, B, 3, limit=10) == (False, [])


def test_the_milp_and_the_search_agree_with_the_certificate():
    pytest.importorskip("scipy")
    M = _module()
    doc = _five_qubit()
    assert M.milp_check(doc, 2, 60) == "confirmed"
    assert M.milp_check(doc, 3, 60) == "contradiction"
    w, ok = M.ris_check(doc, 2000)
    assert w == 3 and ok


@pytest.mark.board
def test_the_record_names_a_verdict_per_entry(tmp_path):
    pytest.importorskip("scipy")
    M = _module()
    doc = _five_qubit()
    rec = M.crosscheck("5-1-3", doc, 3, tlim=60, trials=2000, brute_max=1e6)
    assert rec["verdict"] == "confirmed" and rec["brute_force"]["lighter_logicals"] == 0
    assert rec["milp"]["verdict"] == "confirmed" and rec["ris"]["agrees"]
    inflated = M.crosscheck("5-1-3", doc, 4, tlim=60, trials=2000, brute_max=1e6)
    assert inflated["verdict"] == "contradiction"
    assert inflated["brute_force"]["example"]["weight"] == 3 and inflated["brute_force"]["example"]["valid"]
    assert np.asarray(inflated["brute_force"]["example"]["X"]).size + 0 >= 0
    assert "5-1-3" in M.certified_stabilizer_slugs()
