"""Tests for the A/B campaign harness's own rung-boundary authority.

``research/campaigns/ab_escalation_gate.py`` runs two arms against one pool:
``base`` chases every survivor through the full ladder, and ``gate`` asks at
each rung boundary whether the ladder's own arithmetic settles the question.
The escalation module enforces the fences; this harness decides what to do
with them when no verdict arrives, which is the case in every recorded run
(146 of 146 journal decisions carried the ``no-verdict`` advisory).

The property under test is the one that made the gate inert: both harness
branches must turn on the same settledness threshold,
``escalation.MIN_FLAT_RUNGS``, and that threshold must be reachable. They
disagreed -- abandon was licensed at 2 flat fresh rungs while the depth
advance demanded 3 -- and since every recorded run took the two-rung
20k-then-200k shape, the one boundary where a rung transition could be
authorized was a boundary at which it was not, and the gate could only ever
say hold.
"""
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "kit"))
import escalation as E  # noqa: E402


def _harness():
    """Import the A/B campaign module by path; it is a script, not a package."""
    path = os.path.join(_HERE, "campaigns", "ab_escalation_gate.py")
    spec = importlib.util.spec_from_file_location("ab_escalation_gate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _facts(rungs, bar, **kw):
    base = dict(n=904, k=230, rungs=rungs, bar=bar, family="pair-partition")
    base.update(kw)
    return E.rung_brief(**base)["facts"]


# The 20k-then-200k shape every recorded run took: two rungs, and a bound
# that has not moved between them.
_TWO_RUNG_SETTLED = [(20_000, 20), (200_000, 20)]
_BAR = 106.11          # below 20^2 * 230 / 904 at that bound: the 2026-09-20 bar


def test_a_settled_ladder_at_the_threshold_advances_its_depth():
    """A settled ladder at the threshold advances its depth.

    The regression: two flat rungs are the documented settledness, and a
    ladder that reached it must be able to change depth rather than replay
    the same one forever.
    """
    facts = _facts(_TWO_RUNG_SETTLED, 6.0, n=108, k=8)
    assert facts["flat_fresh_rungs_at_best"] == E.MIN_FLAT_RUNGS
    action, why = _harness().harness_override("hold-deepen", facts,
                                              level=0, n_levels=4)
    assert action == "promote-next-rung"
    assert why and "own authority" in why


def test_a_settled_ladder_below_the_bar_is_abandoned_at_the_same_threshold():
    """A settled ladder below the bar is abandoned at the same threshold.

    Below the bar, flat, and unflagged, deeper trials cannot rescue it.
    """
    facts = _facts(_TWO_RUNG_SETTLED, _BAR)
    assert not facts["best_at_or_above_bar"]
    action, why = _harness().harness_override("hold-deepen", facts,
                                              level=0, n_levels=4)
    assert action == "abandon-ladder"
    assert E._abandon_is_proven_safe(facts)
    assert why and "can only fall" in why


def test_both_branches_turn_on_one_threshold():
    """Both branches turn on one threshold.

    Neither may demand more evidence than the other, or than the constant
    that names the evidence. This is the invariant the two literals used to
    violate, pinned so they cannot drift apart again.
    """
    mod = _harness()
    below_bar = _facts(_TWO_RUNG_SETTLED, _BAR)
    at_bar = _facts(_TWO_RUNG_SETTLED, 6.0, n=108, k=8)

    def first_flat(action_of):
        """Return the flat-rung count where the harness stops saying hold."""
        for rungs in ([(20_000, 20)], [(20_000, 20), (200_000, 20)]):
            f = _facts(rungs, _BAR)
            if action_of(f) != "hold-deepen":
                return f["flat_fresh_rungs_at_best"]
        return None

    assert first_flat(lambda f: mod.harness_override(
        "hold-deepen", f, level=0, n_levels=4)[0]) == E.MIN_FLAT_RUNGS
    assert mod.harness_override("hold-deepen", below_bar, level=0,
                                n_levels=4)[0] == "abandon-ladder"
    assert mod.harness_override("hold-deepen", at_bar, level=0,
                                n_levels=4)[0] == "promote-next-rung"


def test_a_descending_ladder_is_left_alone():
    """A descending ladder is left alone.

    One fresh rung short of settled is still deciding, and a ladder that
    improved on its last rung may never be abandoned.
    """
    facts = _facts([(20_000, 22), (200_000, 20)], _BAR)
    assert facts["ladder_still_descending"]
    assert facts["flat_fresh_rungs_at_best"] < E.MIN_FLAT_RUNGS
    assert _harness().harness_override("hold-deepen", facts,
                                       level=0, n_levels=4) == ("hold-deepen",
                                                                None)


def test_the_harness_never_widens_a_fence():
    """Whatever it decides, it cannot abandon a ladder the fence forbids.

    And it cannot deepen past the last rung the budget offers.
    """
    mod = _harness()
    for bar in (1.0, 6.0, 106.11, 10_000.0):
        facts = _facts(_TWO_RUNG_SETTLED, bar, n=108, k=8)
        action, _ = mod.harness_override("hold-deepen", facts, level=0,
                                         n_levels=4)
        if action == "abandon-ladder":
            assert E._abandon_is_proven_safe(facts)
    # last level: no deeper rung exists to advance to
    facts = _facts(_TWO_RUNG_SETTLED, 6.0, n=108, k=8)
    assert mod.harness_override("hold-deepen", facts, level=3,
                                n_levels=4) == ("hold-deepen", None)


def test_the_harness_never_reverses_an_abandon_the_verdict_already_earned():
    """apply_verdict may abandon on its own when the fence licenses it.

    The harness must leave that decision alone rather than reopening it.
    """
    facts = _facts(_TWO_RUNG_SETTLED, _BAR)
    assert _harness().harness_override("abandon-ladder", facts,
                                       level=0, n_levels=4)[0] == "abandon-ladder"


def test_no_verdict_still_holds_an_unsettled_ladder():
    """The fence that matters most: nothing arrived, nothing is settled.

    So the default still deepens at the same depth. Uncertainty holds.
    """
    facts = _facts([(20_000, 22)], _BAR)
    assert facts["flat_fresh_rungs_at_best"] == 1 < E.MIN_FLAT_RUNGS
    assert _harness().harness_override("hold-deepen", facts,
                                       level=0, n_levels=4) == ("hold-deepen",
                                                                None)
