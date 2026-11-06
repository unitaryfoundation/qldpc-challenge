"""The board screen must never say more than its two primitives can (issue #4024).

An equal fingerprint is the same code on the same labels; an equal WL
signature is a review item and nothing stronger; a different WL signature
rules a permutation out. The committed record has to be well formed and
describe today's codes/, or say so.
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import board_screen as bs  # noqa: E402


def _docs():
    doc = {"provenance": {}}
    return {"ref": (doc, "fpA", "wl1"),
            "twin": (doc, "fpA", "wl1"),      # same rref: the same code
            "perm": (doc, "fpB", "wl1"),      # same WL, other rref: review
            "other": (doc, "fpC", "wl2"),     # nothing in common
            "ref2": (doc, "fpD", "wl1")}      # a second reference with the WL hash


def test_the_three_verdicts_and_what_each_lists():
    audit = {frozenset(("perm", "ref")): "inequivalent"}
    e = bs.screen(_docs(), {"ref", "ref2"}, audit)
    assert e["twin"]["verdict"] == "exact_match"
    assert [m["slug"] for m in e["twin"]["matches"] if m["by"] == "fingerprint"] == ["ref"]
    assert e["perm"]["verdict"] == "review"
    assert {m["slug"]: m.get("audit") for m in e["perm"]["matches"]} == \
        {"ref": "inequivalent", "ref2": None}
    assert e["other"]["verdict"] == "distinct" and e["other"]["matches"] == []
    # a reference entry is screened against the rest of the reference set only
    assert e["ref"]["verdict"] == "review" and e["ref"]["in_reference"]
    assert [m["slug"] for m in e["ref"]["matches"]] == ["ref2"]
    # a fingerprint match is never also listed as a WL match
    assert all(m["by"] == "fingerprint" for m in e["twin"]["matches"] if m["slug"] == "ref")


def test_counts_follow_the_entries():
    e = bs.screen(_docs(), {"ref", "ref2"}, {})
    c = bs.counts(e)
    assert c["screened"] == 5
    assert c["exact_match"] + c["review"] + c["distinct"] == 5
    assert c["wl_matches_by_audit"] == {"not_audited": c["wl_matches"]}


def test_the_committed_record_is_well_formed_and_describes_the_board():
    """check() hard-fails only on a malformed record; staleness exits 0 loudly."""
    assert os.path.exists(bs.SCREEN), "the board screen record is committed beside derived.json"
    assert bs.check() == 0
    with open(bs.SCREEN, encoding="utf-8") as f:
        payload = json.load(f)
    assert set(payload["rule"]) == set(bs.VERDICTS)
    assert "not that the code is unpublished" in payload["caveat"]
    for slug, v in payload["entries"].items():
        for m in v["matches"]:
            assert m["slug"] != slug and m["slug"] in payload["entries"]
            assert payload["entries"][m["slug"]]["in_reference"]
