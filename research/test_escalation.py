"""Tests for the escalation gate.

The gate allocates trial budget; it never judges a code and never suppresses
data. So the properties that matter are:

  * the brief's facts are exact arithmetic on the ladder (a wrong fact is a
    wrong allocation), and
  * every fence holds: a verdict can tilt the choice inside the fences but
    can never open them -- the default is hold, and abandon is honored only
    when the ladder itself proves it safe.

The acceptance ladder is the real one from
fieldnotes/2026-09-20-screening-traps-at-n-900.md: a (3,8) pair-partition
draw whose screen read 22 and whose four fresh deep rungs sat flat at 20,
below the 106.11 bar. 5.3M trials went into it because nothing forced the
early hold/abandon call; the fence tests assert the gate fires on that
ladder, in both directions.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "kit"))
import escalation as E


def _verdict(action, confidence, escaped=False):
    return {"recommendation": {"selected": action, "confidence": confidence,
                               "escaped": escaped}}


def _note_ladder():
    """The 2026-09-20 ladder: screen 22, then four fresh deep rungs flat 20."""
    return [(20_000, 22), (100_000, 20), (200_000, 20),
            (1_000_000, 20), (4_000_000, 20)]


def _below_bar_brief(**kw):
    base = dict(n=904, k=230, rungs=_note_ladder(), bar=106.11,
                family="pair-partition", spec={"P": 113})
    base.update(kw)
    return E.rung_brief(**base)


# ---------------------------------------------------------------- the facts

def test_brief_facts_match_the_fieldnote_arithmetic():
    """Every fact must be recomputable by hand from the raw ladder.

    n=904, k=230, best bound 20: eff = 230*20^2/904 = 101.7699, below the
    106.11 bar; reaching the bar needs d >= 21; the four trailing fresh rungs
    agree at the best bound; the ladder is no longer descending.
    """
    b = _below_bar_brief()
    f = b["facts"]
    assert f["n"] == 904 and f["k"] == 230
    assert f["cumulative_best_bound"] == 20
    assert f["efficiency_at_best"] == 101.7699
    assert f["d_needed_for_bar"] == 21
    assert f["best_at_or_above_bar"] is False
    assert f["margin_to_bar"] == round(101.7699 - 106.11, 4)
    assert f["flat_fresh_rungs_at_best"] == 4
    assert f["ladder_still_descending"] is False
    assert f["trials_spent"] == 5_320_000
    assert f["frontier_flagged"] is False


def test_brief_flags_a_descending_ladder():
    """A last rung that improved the bound must be flagged descending.

    The 2026-09-20 note's lesson: a descending ladder's screen-to-settled
    inflation is unbounded, so nothing may certify it as finished. The flag
    is informational; the flat-tail fence is what actually blocks abandon.
    """
    b = E.rung_brief(n=904, k=230, rungs=[(20_000, 22), (100_000, 20)],
                     bar=106.11)
    assert b["facts"]["ladder_still_descending"] is True
    assert b["facts"]["flat_fresh_rungs_at_best"] == 1


def test_brief_reports_at_or_above_bar_correctly():
    """A candidate at the bar must not read as below it (and vice versa)."""
    at = E.rung_brief(n=72, k=12, rungs=[(20_000, 6)], bar=5.0)
    assert at["facts"]["best_at_or_above_bar"] is True
    assert at["facts"]["d_needed_for_bar"] == 6
    below = E.rung_brief(n=72, k=12, rungs=[(20_000, 6)], bar=10.0)
    assert below["facts"]["best_at_or_above_bar"] is False


def test_efficiency_never_drifts_from_the_search_metric():
    """The gate scores with the board's own kd^2/n.

    A private reimplementation that drifted would misplace every candidate
    relative to the bar, so the agreement is pinned over a grid.
    """
    import search
    for n in (72, 904, 1000):
        for k in (1, 12, 230):
            for d in (2, 6, 20, 38):
                assert E._efficiency(n, k, d) == search.efficiency(n, k, d)


def test_jev_request_stays_inside_the_tool_limits():
    """The brief must survive the jev_decide tool's hard input caps.

    rung_brief asserts this at build time, but asserts vanish under
    ``python -O``; this test re-checks the real brief explicitly.
    """
    big_spec = {"note": "x" * 400, "params": list(range(50))}
    rungs = [(t, d) for t, d in zip((400, 2_000, 20_000, 200_000,
                                     1_000_000, 4_000_000, 8_000_000,
                                     16_000_000), (40, 34, 30, 28, 27, 27, 26, 26))]
    b = E.rung_brief(n=960, k=14, rungs=rungs, bar=30.48,
                     spec=big_spec, family="2bga-metacyclic",
                     context={"frontier": False})
    req = b["jev_request"]
    for key in ("decision", "evidence", "priorities"):
        assert len(req[key]) <= E.JEV_LIMITS[key], key
    for c in req["candidates"]:
        assert len(c["description"]) <= E.JEV_LIMITS["candidate_description"]
    for r in req["requirements"]:
        assert len(r) <= E.JEV_LIMITS["requirement"]
    assert [c["id"] for c in req["candidates"]] == list(E.ACTIONS)


def test_brief_id_is_stable_and_sensitive():
    """Same ladder, same id; a changed rung, a different id.

    The journal keys audits by this id, so it must not depend on dict order
    or on anything but the decision-relevant inputs.
    """
    a = _below_bar_brief()
    b = _below_bar_brief()
    assert a["id"] == b["id"]
    c = _below_bar_brief(rungs=_note_ladder()[:-1])
    assert c["id"] != a["id"]


def test_rung_inputs_are_validated():
    """Garbage rungs must raise, not silently become facts."""
    for bad in ([(0, 20)], [(20_000, 0)], [(-1, 5)], [(20000, True)]):
        try:
            E.rung_brief(n=72, k=12, rungs=bad, bar=5.0)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad}")
    b = E.rung_brief(n=72, k=12, rungs=[(20_000, 20, False)], bar=5.0)
    assert b["facts"]["flat_fresh_rungs_at_best"] == 0  # non-fresh never counts


# ------------------------------------------------------------ the fences

def test_missing_verdict_holds():
    """No judgment available -> hold and deepen. Never guess."""
    d = E.apply_verdict(_below_bar_brief(), None)
    assert d["action"] == "hold-deepen"
    assert d["advisories"] == ["no-verdict"]


def test_malformed_verdict_holds():
    """Anything unparsable holds; the journal shows why."""
    for bad in ({}, {"recommendation": "abandon"},
                {"recommendation": {"selected": "abandon-ladder",
                                    "confidence": "high"}},
                {"recommendation": {"selected": "abandon-ladder",
                                    "confidence": True}}):
        d = E.apply_verdict(_below_bar_brief(), bad)
        assert d["action"] == "hold-deepen" and d["advisories"] == ["no-verdict"]


def test_escaped_verdict_holds():
    """The tool declining to rank is a hold, whatever it leaned toward."""
    d = E.apply_verdict(_below_bar_brief(),
                        _verdict("abandon-ladder", 0.95, escaped=True))
    assert d["action"] == "hold-deepen"
    assert "escaped-verdict" in d["advisories"]


def test_low_confidence_verdict_holds():
    """Below HOLD_CONFIDENCE the harness keeps the decision itself."""
    d = E.apply_verdict(_below_bar_brief(),
                        _verdict("promote-next-rung", E.HOLD_CONFIDENCE - 0.01))
    assert d["action"] == "hold-deepen"
    assert "low-confidence" in d["advisories"]


def test_unknown_action_holds():
    d = E.apply_verdict(_below_bar_brief(), _verdict("ship-it", 0.99))
    assert d["action"] == "hold-deepen"
    assert "unknown-action" in d["advisories"]


def test_abandon_is_fenced_until_the_ladder_proves_it():
    """Abandon needs below-bar + MIN_FLAT_RUNGS fresh agreement.

    The acceptance case, run at each prefix of the real ladder: after the
    screen and the first deep rung (flat=1) abandon must be fenced even at
    confidence 1.0; it becomes legal only on the second consecutive flat
    fresh rung -- exactly the point in the campaign where 2026-09-20 says
    the call should have been made.
    """
    rungs = _note_ladder()
    for i in range(1, len(rungs) + 1):
        brief = _below_bar_brief(rungs=rungs[:i])
        flat = brief["facts"]["flat_fresh_rungs_at_best"]
        d = E.apply_verdict(brief, _verdict("abandon-ladder", 1.0))
        if flat >= E.MIN_FLAT_RUNGS:
            assert d["action"] == "abandon-ladder", i
            assert d["advisories"] == []
        else:
            assert d["action"] == "hold-deepen", i
            assert "abandon-unproven" in d["advisories"]


def test_above_bar_ladder_cannot_be_abandoned_at_any_confidence():
    """If the best bound still clears the bar, abandon is never legal.

    Deeper trials can only lower the bound, so a clearing ladder is live by
    arithmetic; no verdict may spend it into the ground.
    """
    b = E.rung_brief(n=72, k=12, rungs=[(20_000, 8), (100_000, 7)], bar=5.0)
    assert b["facts"]["best_at_or_above_bar"] is True
    d = E.apply_verdict(b, _verdict("abandon-ladder", 1.0))
    assert d["action"] == "hold-deepen"
    assert "abandon-unproven" in d["advisories"]


def test_frontier_flag_blocks_abandon():
    """Frontier membership is worth protecting; the verdict does not outweigh it."""
    d = E.apply_verdict(_below_bar_brief(context={"frontier": True}),
                        _verdict("abandon-ladder", 1.0))
    assert d["action"] == "hold-deepen"
    assert "abandon-unproven" in d["advisories"]


def test_promote_needs_budget_and_honors_a_fresh_budget():
    """Promote beyond the budget holds; a fresh budget in apply wins.

    The brief's budget is a snapshot; the caller may know better at decision
    time, so apply_verdict's override is authoritative.
    """
    brief = _below_bar_brief(next_rung_trials=4_000_000, budget_remaining=1_000_000)
    d = E.apply_verdict(brief, _verdict("promote-next-rung", 0.9))
    assert d["action"] == "hold-deepen" and "budget-exhausted" in d["advisories"]

    brief = _below_bar_brief(next_rung_trials=4_000_000, budget_remaining=100)
    d = E.apply_verdict(brief, _verdict("promote-next-rung", 0.9),
                        budget_remaining=4_000_000)
    assert d["action"] == "promote-next-rung" and d["advisories"] == []


def test_promote_within_budget_is_honored():
    b = E.rung_brief(n=72, k=12, rungs=[(20_000, 8)], bar=5.0,
                     next_rung_trials=100_000, budget_remaining=200_000)
    d = E.apply_verdict(b, _verdict("promote-next-rung", 0.9))
    assert d["action"] == "promote-next-rung" and d["advisories"] == []


def test_promote_with_unknown_budget_is_honored():
    """No budget numbers -> the fence is silent, not blocking.

    A missing next_rung_trials or budget means the caller has not told the
    gate the cost; the fence only fires on a known unaffordable rung.
    """
    d = E.apply_verdict(_below_bar_brief(), _verdict("promote-next-rung", 0.9))
    assert d["action"] == "promote-next-rung" and d["advisories"] == []


# -------------------------------------------------------------- the journal

def test_journal_records_brief_and_decision(tmp_path):
    """One JSONL line per decision, parseable independently, gitignored home.

    The journal is the audit trail for the session ledger: what was judged,
    what the fences did, and the facts the judgment rested on.
    """
    path = str(tmp_path / "escalation.jsonl")
    brief = _below_bar_brief()
    d1 = E.apply_verdict(brief, _verdict("abandon-ladder", 0.5))
    d2 = E.apply_verdict(brief, _verdict("abandon-ladder", 1.0))
    E.append_journal(d1, brief, path=path)
    E.append_journal(d2, brief, path=path)
    with open(path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    assert len(rows) == 2
    assert rows[0]["decision"]["action"] == "hold-deepen"
    assert rows[1]["decision"]["action"] == "abandon-ladder"
    for row in rows:
        assert row["brief_id"] == brief["id"]
        assert row["facts"]["cumulative_best_bound"] == 20
        assert "timestamp" in row


def test_decision_never_mutates_the_brief():
    """apply_verdict with a budget override must not rewrite the snapshot.

    The journal stores the brief as built; a decision-time budget override is
    part of the decision, not a revision of history.
    """
    brief = _below_bar_brief(budget_remaining=1_000_000)
    before = dict(brief["facts"])
    E.apply_verdict(brief, _verdict("promote-next-rung", 0.9),
                    budget_remaining=5_000_000)
    assert brief["facts"] == before
