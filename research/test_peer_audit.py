"""The matched-depth peer audit a d-only gain owes, as one rule for both packaging paths.

research/kit/promote.py and ./qldpc submit both call research/kit/peer_audit.py
(issue #4236), so what is tested here is the rule itself: which board entries
count as d-only peers (the gate's definition), what a missing audit is refused
with, and what a recorded audit has to say to discharge the gain.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "kit"))
import peer_audit as PA  # noqa: E402

PEER = "[[72,6,6]] w=6 72-6-6.json"
CAND = {"n": 72, "k": 6, "d": 7, "w": 6, "code_type": "CSS",
        "weight_class": "weight-6", "locality_class": "unrestricted"}


def _row(slug, **over):
    n, k, d = (int(x) for x in slug.split("-")[:3])
    row = {"slug": slug, "n": n, "k": k, "d": d, "w": 6, "code_type": "CSS",
           "weight_class": "weight-6", "locality_class": "unrestricted", "eff": 1.0}
    row.update(over)
    return row


def _audit(**over):
    rec = {"schema": PA.AUDIT_SCHEMA, "candidate": "cand.json",
           "peers": ["codes/72-6-6.json"], "trials": 2_000_000, "seeds": [51, 52],
           "pair_depth": 10, "threads": 8, "decision": "credible: both claims held",
           "exit_code": 0, "results": [], "recorded": "2026-11-05"}
    rec.update(over)
    return rec


def test_a_peer_is_named_the_same_way_in_every_form():
    for form in (PEER, "codes/72-6-6.json", "72-6-6.json", "72-6-6",
                 "/abs/path/codes/72-6-6.json"):
        assert PA.peer_slug(form) == "72-6-6", form
    assert PA.peer_slug("") == ""


def test_describe_writes_the_gates_own_descriptor():
    """The string must equal the gate's d_only_peers entry so the two compare."""
    assert PA.describe(_row("72-6-6")) == PEER
    assert PA.describe({"name": "72-6-6.json", "n": 72, "k": 6, "d": 6, "w": 6}) == PEER


def test_d_only_peers_follow_the_gates_rule():
    board = [_row("72-6-6"),                                   # same n, k, w, lower d
             _row("72-6-7"),                                   # equal d: not beaten
             _row("72-6-6-b", w=8, weight_class="weight-8"),   # looser weight class
             _row("72-6-5-c", locality_class="local-2d-single"),  # stricter cell: counts
             _row("72-6-6-d", code_type="stabilizer"),         # the other board
             _row("71-6-6"),                                   # n differs: not d-only
             _row("72-6-6-e", w=None)]                         # no weight recorded
    assert PA.d_only_peers(CAND, board) == [PEER, "[[72,6,5]] w=6 72-6-5-c.json"]
    local = dict(CAND, locality_class="local-2d-single")
    assert PA.d_only_peers(local, [_row("72-6-6")]) == []     # an unrestricted peer is in a looser cell
    assert PA.d_only_peers(dict(CAND, w=None), board) == []


def test_no_peers_means_nothing_to_discharge():
    assert PA.blockers([], None) == []
    assert PA.blockers([], _audit(decision="drop: x")) == []


def test_a_missing_audit_is_refused_with_the_command_to_run():
    out, = PA.blockers([PEER], None, required_trials=5_000_000, required_pair_depth=8,
                       candidate_path="research/candidates/run/72-6-7.json",
                       attach="re-run with --peer-audit <file>")
    assert PEER in out and PA.RULE in out
    assert ("research/audits/leader_audit.py pair research/candidates/run/72-6-7.json "
            "--trials 5000000 --seeds 51 52 --pair-depth 8") in out
    assert "--json-out" in out and out.endswith("re-run with --peer-audit <file>")


def test_prose_is_accepted_but_not_checkable():
    assert PA.blockers([PEER], "credible at 10M trials, seeds 4242, 5353") == []
    assert not PA.is_checkable("credible at 10M trials")
    assert PA.is_checkable(_audit())


def test_a_credible_record_at_depth_covering_the_peer_discharges_the_gain():
    assert PA.blockers([PEER], _audit(), required_trials=2_000_000, required_pair_depth=10) == []
    assert PA.blockers([PEER], _audit(peers=["72-6-6"]), required_trials=1_000) == []


@pytest.mark.parametrize("over, needle", [
    ({"decision": "drop: the candidate's d is inflated"}, "do not package it"),
    ({"decision": "redirect: the board peer's d is inflated"}, "distance revision"),
    ({"decision": "inconclusive: neither claim was reached"}, "no information"),
    ({"decision": ""}, "'missing'"),
    ({"trials": 1_000_000}, "shallower than the 2,000,000 the claim rests on"),
    ({"trials": None}, "carries no trials"),
    ({"pair_depth": 4}, "pair depth 4, shallower than the 8"),
    ({"pair_depth": True}, "carries no pair_depth"),
    ({"seeds": []}, "carries no seeds"),
    ({"peers": ["codes/72-6-5.json"]}, "does not cover [[72,6,6]] w=6 72-6-6.json; it audited 72-6-5"),
    ({"peers": []}, "it audited no peer"),
])
def test_each_shortfall_is_named(over, needle):
    problems = PA.blockers([PEER], _audit(**over), required_trials=2_000_000,
                           required_pair_depth=8)
    assert any(needle in p for p in problems), problems


def test_shortfalls_accumulate_rather_than_stopping_at_the_first():
    problems = PA.blockers([PEER], _audit(decision="inconclusive: x", trials=10,
                                          peers=[]), required_trials=2_000_000)
    assert len(problems) == 3


def test_the_record_round_trips_through_the_loader(tmp_path):
    rec = PA.record("cand.json", ["codes/72-6-6.json"], [{"stem": "cand"}],
                    "credible: both claims held", trials=2_000_000, seeds=[51, 52],
                    pair_depth=64, threads=8, exit_code=0, today="2026-11-05")
    path = tmp_path / "audit.json"
    path.write_text(json.dumps(rec), encoding="utf-8")
    loaded = PA.load_audit(str(path))
    assert loaded == rec and loaded["schema"] == PA.AUDIT_SCHEMA
    assert PA.blockers([PEER], loaded, required_trials=2_000_000, required_pair_depth=64) == []
    assert "2,000,000 trials per seed, seeds 51, 52, pair depth 64" in PA.summary(loaded)


def test_the_loader_refuses_what_is_not_a_record(tmp_path):
    bad = tmp_path / "x.json"
    bad.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(PA.PeerAuditError, match="one JSON object"):
        PA.load_audit(str(bad))
    bad.write_text(json.dumps({"decision": "credible"}), encoding="utf-8")
    with pytest.raises(PA.PeerAuditError, match="schema is None"):
        PA.load_audit(str(bad))
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(PA.PeerAuditError, match="not readable as JSON"):
        PA.load_audit(str(bad))
    with pytest.raises(PA.PeerAuditError, match="not readable"):
        PA.load_audit(str(tmp_path / "missing.json"))
