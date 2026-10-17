"""Tests for the permutation audit (research/audits/permutation_audit.py, issue #3427).

Pinned: a refutation by a basis-independent invariant is sound (the invariant
really differs), an equivalence found through the Tanner graph is verified on
the row spaces and survives the negative control, a pair of different
generating sets of one stabilizer group is decided equivalent through the
hypergraph encoding although the Tanner graphs are not isomorphic, a QECDB
record's Pauli rows become CSS matrices, and the committed record re-checks
from the blob hashes it cites.
"""
import glob
import json
import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import permutation_audit as PA  # noqa: E402

STEANE = [[0, 2, 4, 6], [1, 2, 5, 6], [3, 4, 5, 6]]


def _doc(X, Z, n, d=3):
    return {"n": n, "k": None, "checks": {"X": X, "Z": Z}, "distance": {"d": d}}


def _code(slug, X, Z, n, d=3):
    return PA.code_from_doc(slug, _doc(X, Z, n, d))


def test_a_permuted_steane_is_decided_equivalent_through_the_tanner_graph():
    perm = [6, 5, 4, 3, 2, 1, 0]
    PX = [[perm[q] for q in r] for r in STEANE]
    a, b = _code("a", STEANE, STEANE, 7), _code("b", PX, PX, 7)
    rec = PA.decide(a, b, _doc(STEANE, STEANE, 7), _doc(PX, PX, 7))
    assert rec["verdict"] == "equivalent" and rec["found_by"] == "tanner"
    assert rec["row_spaces"]["X"] == (3, 3, 3) and rec["negative_control"] == "a perturbed permutation fails"
    assert "distance_conflict" not in rec


def test_two_claims_on_one_code_are_flagged():
    a, b = _code("a", STEANE, STEANE, 7, d=3), _code("b", STEANE, STEANE, 7, d=4)
    rec = PA.decide(a, b, _doc(STEANE, STEANE, 7, 3), _doc(STEANE, STEANE, 7, 4))
    assert rec["verdict"] == "equivalent"
    assert rec["distance_conflict"]["first_d"] == 3 and "over-stated" in rec["distance_conflict"]["note"]


def test_different_generating_sets_of_one_code_are_decided_through_the_hypergraph():
    """Row weights 2,2 against 2,4: the Tanner graphs differ, the row spaces do not."""
    X1, X2 = [[0, 1], [2, 3]], [[0, 1], [0, 1, 2, 3]]
    Z = [[0, 1, 2, 3]]
    a, b = _code("a", X1, Z, 4, 2), _code("b", X2, Z, 4, 2)
    assert PA.I.nauty_permutation(a, b) is None and PA.I.nauty_permutation(a, b, swap=True) is None
    rec = PA.decide(a, b, _doc(X1, Z, 4, 2), _doc(X2, Z, 4, 2))
    assert rec["verdict"] == "equivalent" and rec["found_by"] == "hypergraph"
    assert rec["row_spaces"]["X"] == (2, 2, 2)


def test_an_invariant_difference_refutes_without_a_search():
    # the [[4,2,2]] code against a [[4,1,?]] code with one more Z check: ranks differ
    a = _code("a", [[0, 1, 2, 3]], [[0, 1, 2, 3]], 4, 2)
    b = _code("b", [[0, 1, 2, 3]], [[0, 1, 2, 3], [0, 1]], 4, 2)
    rec = PA.decide(a, b, _doc([[0, 1, 2, 3]], [[0, 1, 2, 3]], 4, 2),
                    _doc([[0, 1, 2, 3]], [[0, 1, 2, 3], [0, 1]], 4, 2))
    assert rec["verdict"] == "inequivalent" and "ranks" in rec["reason"]


def test_the_low_weight_enumerator_separates_what_ranks_do_not():
    # two [[6,2,?]] codes with equal ranks whose X row spaces have different weight-2 counts
    Z = [[0, 1, 2, 3, 4, 5]]
    X1 = [[0, 1], [2, 3]]                 # row space holds two weight-2 vectors
    X2 = [[0, 1, 2, 3], [0, 1, 4, 5]]     # row space holds none
    rec = PA.decide(_code("a", X1, Z, 6, 2), _code("b", X2, Z, 6, 2), _doc(X1, Z, 6, 2), _doc(X2, Z, 6, 2))
    assert rec["verdict"] == "inequivalent" and "low-weight enumerator" in rec["reason"]


def test_qecdb_rows_become_css_matrices():
    HX, HZ = PA.qecdb_matrices(["XXII", "IIXX", "ZZZZ"])
    assert HX.tolist() == [[1, 1, 0, 0], [0, 0, 1, 1]] and HZ.tolist() == [[1, 1, 1, 1]]
    with pytest.raises(ValueError):
        PA.qecdb_matrices(["XZII"])


def test_the_two_bga_rebuild_reads_the_archive_convention():
    HX, HZ = PA.rebuild_2bga("2bga:SmallGroup(6,2):a[3]:b[2,3,6]")
    assert HX.shape == (6, 12) and not ((HX @ HZ.T) % 2).any()
    with pytest.raises(FileNotFoundError):
        PA.rebuild_2bga("2bga:SmallGroup(7,1):a[2]:b[3]")


def test_the_committed_record_rechecks_from_its_blobs():
    records = sorted(glob.glob(os.path.join(HERE, "permutation_audit-*.json")))
    assert records, "no committed audit record"
    with open(records[-1], encoding="utf-8") as f:
        rec = json.load(f)
    assert rec["audit_version"] == PA.AUDIT_VERSION
    assert set(rec["counts"]["board"]) == {"equivalent", "inequivalent", "gb_family_no", "undecided"}
    for p in rec["board_pairs"]:
        assert p["verdict"] in rec["counts"]["board"]
        if p["verdict"] == "equivalent":
            assert len(p["permutation"]) == p["n"] and sorted(p["permutation"]) == list(range(p["n"]))
    assert PA.recheck(records[-1]) == 0


def test_literature_rows_in_the_record_are_kept_for_the_trail():
    records = sorted(glob.glob(os.path.join(HERE, "permutation_audit-*.json")))
    with open(records[-1], encoding="utf-8") as f:
        rec = json.load(f)
    for p in rec["literature"]:
        if p["source"] == "qecdb" and p["verdict"] == "equivalent":
            assert p["record"]["rows"], p["id"]
            assert len(p["record"]["rows"][0]) == np.asarray(PA.qecdb_matrices(p["record"]["rows"])[0]).shape[1]
