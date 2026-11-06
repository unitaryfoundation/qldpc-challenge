"""The schedule search stages every attempt, gates each with the unchanged verifier, and keeps lineage.

Run on the two smallest entries with a circuit tier so the whole loop,
baseline, screen, deep search, staging, verdict, ledger, and summary, runs in
seconds (issue #4032). A survivor must be an attempt the verifier accepted
whose score beats the committed circuits; nothing here is a board change.
"""
import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_HERE, "kit"))

import circuit_search as cs  # noqa: E402

pytestmark = pytest.mark.skipif(
    not os.path.exists(os.path.join(_ROOT, "circuits", "12-4-2", "memory_x.stim")),
    reason="the test entries' circuits are not in this checkout")


def test_score_prefers_the_weaker_basis_then_the_sum():
    assert cs.score_of({"X": {"value": 3}, "Z": {"value": 2}}) == (2, 5)
    assert cs.score_of({"X": {"value": 3}, "Z": {"value": 3}}) > cs.score_of({"X": {"value": 5}, "Z": {"value": 2}})


def test_every_attempt_is_staged_gated_and_journaled(tmp_path):
    out = str(tmp_path / "run")
    s = cs.search("12-4-2", attempts=2, seconds=2.0, only=("two-block",), out=out, log=lambda m: None)
    doc = json.load(open(os.path.join(_ROOT, "codes", "12-4-2.json"), encoding="utf-8"))
    assert s["baseline"]["d_circ"] == {b: doc["circuit"]["d_circ"][b]["value"] for b in ("X", "Z")}
    assert s["rounds"] >= doc["distance"]["d"]
    assert len(s["attempts"]) == 2
    lines = [json.loads(line) for line in open(os.path.join(out, "ledger.jsonl"), encoding="utf-8")]
    assert [row["attempt"] for row in lines] == [1, 2]
    evaluated = [r for r in s["attempts"] if r["score"]]
    assert evaluated, "an interleaved two-block schedule evaluates at this size"
    for r in evaluated:
        adir = os.path.join(_ROOT, r["staged"])
        for name in ("memory_x.stim", "memory_x.dem", "memory_z.stim", "memory_z.dem",
                     "block.json", "candidate.json", "verdict.json", "notes.md"):
            assert os.path.exists(os.path.join(adir, name)), name
        verdict = json.load(open(os.path.join(adir, "verdict.json"), encoding="utf-8"))
        assert verdict["ok"] == r["verdict_ok"]
        cand = json.load(open(os.path.join(adir, "candidate.json"), encoding="utf-8"))
        assert cand["checks"] == doc["checks"] and cand["distance"] == doc["distance"]
        assert cand["circuit"]["d_circ"]["X"]["value"] <= doc["distance"]["d"]
        assert "circuit_search.py" in cand["circuit"]["notes"]
    scores = [tuple(r["score"]) for r in evaluated]
    assert [r for r in s["ranking"]] == [r["attempt"] for r in
                                         sorted(evaluated, key=lambda r: tuple(r["score"]), reverse=True)]
    assert all(tuple(s["attempts"][a - 1]["score"]) > tuple(s["baseline"]["score"])
               and s["attempts"][a - 1]["verdict_ok"] for a in s["survivors"])
    assert json.load(open(os.path.join(out, "summary.json"), encoding="utf-8"))["slug"] == "12-4-2"
    assert scores


def test_a_schedule_the_screen_already_beats_is_recorded_not_evaluated(tmp_path):
    out = str(tmp_path / "run")
    s = cs.search("12-2-3", attempts=1, seconds=1.0, only=("generic",), out=out, log=lambda m: None)
    (row,) = s["attempts"]
    assert row["screen"] is not None
    if row["score"] is None:
        assert row["reason"] and row["staged"] is None
    assert s["survivors"] == [] or all(s["attempts"][a - 1]["verdict_ok"] for a in s["survivors"])
