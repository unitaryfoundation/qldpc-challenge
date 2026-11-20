"""The permutation ledger stays true against the blobs it cites.

The checker must also refuse a wrong permutation, or the ledger proves nothing.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import permutation_equivalence as PE  # noqa: E402


def test_every_recorded_pair_is_equivalent_under_its_permutation():
    assert PE.run_ledger(quiet=True) == 0


def test_a_perturbed_permutation_is_rejected():
    rec = json.load(open(PE.LEDGER))
    p = rec["pairs"][0]
    a, b = PE.load_blob(p["first_blob"]), PE.load_blob(p["second_blob"])
    assert PE.negative_control(a, b, p["permutation"]) is True


def test_the_identity_is_not_accepted_for_a_relabelled_pair():
    rec = json.load(open(PE.LEDGER))
    p = rec["pairs"][0]
    a, b = PE.load_blob(p["first_blob"]), PE.load_blob(p["second_blob"])
    ok, _ = PE.check_pair(a, b, list(range(a["n"])))
    assert not ok
