"""Tests for the permutation audit (research/audits/permutation_audit.py, issue #3427).

Pinned: a refutation by a basis-independent invariant is sound (the invariant
really differs), an equivalence found through the Tanner graph is verified on
the row spaces and survives the negative control, a pair of different
generating sets of one stabilizer group is decided equivalent through the
hypergraph encoding although the Tanner graphs are not isomorphic, a QECDB
record's Pauli rows become CSS matrices, the committed record re-checks
from the blob hashes it cites, the Brouwer-Zimmermann light-vector lists
agree with full enumeration (partial information sets included), the hull
and intersection enumerators read right on the Steane code, the swapped
orientation compares one side swapped, and three of the pairs the 2026-10-17
record left undecided are decided by the stage the new record names.
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


# -- the light-vector stage and the hull invariants (issue #4057) --------------

def _gray_enumeration(vecs, wmax):
    basis, out, cur = PA.echelon_basis(vecs), set(), 0
    for g in range(1, 2 ** len(basis)):
        cur ^= basis[(g & -g).bit_length() - 1]
        if cur.bit_count() <= wmax:
            out.add(cur)
    return out


def test_the_light_vector_enumeration_is_complete():
    """Brouwer-Zimmermann over the sets agrees with the whole row space, partial sets included."""
    import random
    rng = random.Random(4057)
    for _ in range(40):
        n, k = rng.randint(4, 28), rng.randint(1, 13)
        vecs = [rng.getrandbits(n) for _ in range(k + rng.randint(0, 2))]
        wmax = rng.randint(0, n)
        got, plan = PA.light_vectors(vecs, n, wmax)
        assert set(got) == _gray_enumeration(vecs, wmax), (n, k, wmax, plan)
        assert sum(s["t"] + 1 for s in plan["sets"]) > wmax or any(s["t"] == s["rank"] for s in plan["sets"])


def test_a_partial_information_set_carries_its_kernel():
    import random
    rng = random.Random(1)
    vecs = [rng.getrandbits(20) for _ in range(12)]          # 12 of 20 columns: the second set is partial
    sets = PA.information_sets(PA.echelon_basis(vecs), 20)
    assert len(sets) == 2 and len(sets[1][0]) + len(sets[1][1]) == len(sets[0][0])
    got, _ = PA.light_vectors(vecs, 20, 20)
    assert set(got) == _gray_enumeration(vecs, 20)


def test_the_budget_leaves_a_pair_undecided_instead_of_guessing():
    import random
    rng = random.Random(2)
    vecs = [rng.getrandbits(60) for _ in range(30)]
    got, plan = PA.light_vectors(vecs, 60, 30, budget=10)
    assert got is None and plan["row_sums"] > 10


def test_hull_and_intersection_enumerators_on_the_steane_code():
    code = _code("steane", STEANE, STEANE, 7)
    inv = PA.invariants(code)
    assert (inv["hull_X"], inv["hull_Z"], inv["intersection"]) == (3, 3, 3)
    assert inv["hull_X_weights"] == inv["intersection_weights"] == [[4, 7]]


def test_the_swapped_orientation_compares_one_side_swapped():
    """Ranks (2, 1) against (1, 2) agree under a swap, so ranks must not refute."""
    X1, Z1 = [[0, 1], [2, 3]], [[0, 1, 2, 3]]
    inv_a = PA.invariants(_code("a", X1, Z1, 4, 2))
    inv_b = PA.invariants(_code("b", Z1, X1, 4, 2))
    assert PA.invariants_separate(inv_a, inv_b) is None
    rec = PA.decide(_code("a", X1, Z1, 4, 2), _code("b", Z1, X1, 4, 2), _doc(X1, Z1, 4, 2), _doc(Z1, X1, 4, 2))
    assert rec["verdict"] == "equivalent" and rec["swap"] is True


def _board_pair(sa, sb):
    root = os.path.dirname(os.path.dirname(HERE))
    paths = [os.path.join(root, "codes", s + ".json") for s in (sa, sb)]
    if not all(os.path.exists(p) for p in paths):
        pytest.skip(f"{sa} or {sb} is no longer on the board")
    docs = [json.load(open(p, encoding="utf-8")) for p in paths]
    return PA.decide(PA.code_from_doc(sa, docs[0]), PA.code_from_doc(sb, docs[1]), docs[0], docs[1])


def test_the_formerly_undecided_pairs_are_decided_by_the_stage_the_record_names():
    """Three of the 13 pairs of the 2026-10-17 record, one per separating fact."""
    rec = _board_pair("684-12-45", "684-12-51")
    assert rec["verdict"] == "inequivalent" and rec["reason"].startswith("hull dimensions")
    rec = _board_pair("72-10-10", "72-10-9")
    assert rec["verdict"] == "inequivalent" and "weight enumerator of the intersection" in rec["reason"]
    rec = _board_pair("186-10-16", "186-10-17")
    assert rec["verdict"] == "inequivalent" and "Tanner comparison made decisive" in rec["reason"]
    light = rec["light_vectors"]
    assert light["wmax"] == 7 and light["first"]["counts"]["X"][7] == 93
    assert all(light[k]["checks_only"][s] for k in ("first", "second") for s in ("X", "Z"))
