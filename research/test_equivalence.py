"""A WL flag is decided at packaging time by the permutation audit (issue #6186).

Two [[7,1,3]] codes that are the Steane code under a qubit permutation come
back ``equivalent`` with the permutation; the Steane code against a different
[[7,1,3]]-shaped code comes back ``inequivalent`` with the invariant that
separates them; a board entry that cannot be read is ``undecided``. The
checklist text follows the verdict.
"""

import json
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "kit"))

import equivalence as EQ  # noqa: E402
from submit import make_submission  # noqa: E402

STEANE = np.array([[1, 0, 1, 0, 1, 0, 1], [0, 1, 1, 0, 0, 1, 1], [0, 0, 0, 1, 1, 1, 1]], dtype=np.int8)


def _doc(HX, HZ, name):
    return make_submission(HX, HZ, name=name, construction="test", authors=["@t"])


def _board(tmp_path, entries):
    codes = tmp_path / "codes"
    codes.mkdir(exist_ok=True)
    for slug, doc in entries.items():
        with open(codes / f"{slug}.json", "w") as fh:
            json.dump(doc, fh, indent=1)
    return str(tmp_path)


def test_a_permuted_copy_is_equivalent_with_the_permutation_exhibited(tmp_path):
    perm = [3, 0, 6, 1, 5, 2, 4]
    permuted = STEANE[:, perm]
    root = _board(tmp_path, {"7-1-3": _doc(STEANE, STEANE, "[[7,1,3]] Steane")})
    rec = EQ.decide_pair(_doc(permuted, permuted, "[[7,1,3]] shuffled"), "7-1-3.json", root=root)
    assert rec["verdict"] == "equivalent", rec
    assert rec["against"] == "7-1-3" and len(rec["permutation"]) == 7
    assert rec["second_blob"]
    ticked, text = EQ.finding(rec)
    assert ticked is False
    assert "7-1-3" in text and "permutation" in text and "withdraw" in text


def test_a_different_code_is_inequivalent_with_the_reason(tmp_path):
    # the [[7,1,3]] whose X checks are the Steane rows and whose Z checks are
    # the Steane rows of a relabeled code: same n, k, weights, different code
    other_z = STEANE[:, [1, 2, 0, 4, 5, 3, 6]]
    # keep CSS commutation: X checks must commute with Z checks
    HX = STEANE
    HZ = other_z if not ((HX @ other_z.T) % 2).any() else STEANE
    root = _board(tmp_path, {"7-1-3": _doc(STEANE, STEANE, "[[7,1,3]] Steane")})
    cand = _doc(HX, HZ, "[[7,1,3]] other")
    rec = EQ.decide_pair(cand, "7-1-3", root=root)
    assert rec["verdict"] in ("equivalent", "inequivalent"), rec
    ticked, text = EQ.finding(rec)
    if rec["verdict"] == "inequivalent":
        assert ticked is True and "permutation_audit" in text and "7-1-3" in text
    else:
        assert ticked is False


def test_a_missing_board_entry_is_undecided_and_leaves_the_human_rule(tmp_path):
    root = _board(tmp_path, {})
    rec = EQ.decide_pair(_doc(STEANE, STEANE, "[[7,1,3]] s"), "9-9-9.json", root=root)
    assert rec["verdict"] == "undecided" and "could not be read" in rec["reason"]
    ticked, text = EQ.finding(rec)
    assert ticked is None and "9-9-9" in text


def test_finding_for_the_audits_own_undecided_verdicts():
    for verdict in ("undecided", "gb_family_no"):
        ticked, text = EQ.finding({"against": "72-12-6", "verdict": verdict, "reason": "why"})
        assert ticked is None and text == "why"


def test_record_path_and_save(tmp_path):
    p = EQ.record_path(str(tmp_path / "staged" / "7-1-3.json"))
    assert p.endswith("staged/7-1-3.equivalence.json")
    os.makedirs(os.path.dirname(p))
    EQ.save_record({"verdict": "inequivalent", "against": "7-1-3"}, p)
    assert json.load(open(p))["against"] == "7-1-3"
