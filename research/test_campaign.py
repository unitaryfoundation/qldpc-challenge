"""Tests for campaign definitions and their ledger (issue #2219).

Two properties matter more than the rest and are tested hardest, because both
protect the board rather than the code: a campaign's constraints are a
screening filter and never a claim about which track cell anything is in, and a
survivor is only a survivor once the gate has said so. Everything else here is
the schema doing its job, which is worth pinning because a campaign that
validates loosely is a task two executors can read differently.
"""
import copy
import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_HERE, "kit"))

from campaign import (  # noqa: E402
    Campaign,
    CampaignError,
    Ledger,
    load_campaign,
    validate_campaign,
    write_summary,
)

GOOD = {
    "campaign": {
        "schema_version": 1,
        "id": "test-campaign",
        "name": "A campaign for the tests",
        "objective": {"metric": "kd2_over_n", "direction": "maximize"},
        "constraints": {"max_check_weight": 8, "n": [100, 400],
                        "locality": "local-2d-bilayer"},
        "methods": {"families": ["bivariate-bicycle"]},
        "budget": {"cpu_hours": 10},
        "stopping": [{"type": "budget_exhausted"}],
    }
}


def camp(**over):
    obj = copy.deepcopy(GOOD)
    obj["campaign"].update(over)
    return obj


def passed_verdict(n=200, k=8, d=12, w=6, advancing=True):
    return {
        "passed": True,
        "candidate": {"n": n, "k": k, "d": d, "max_check_weight": w,
                      "fingerprint": "abc123"},
        "gates": {"novelty": {"board_advancing": advancing,
                              "cell": ["weight-6", "unrestricted"]}},
        "labels": ["advances the weight-6 x unrestricted board"],
    }


def doc(n=200, k=8, d=12):
    return {"n": n, "k": k, "distance": {"d": d}}


# -- the schema -----------------------------------------------------------

def test_a_valid_campaign_loads():
    c = Campaign(validate_campaign(camp()))
    assert c.id == "test-campaign" and c.families == ["bivariate-bicycle"]


def test_an_unknown_field_is_rejected():
    """A typo must not become a silently ignored instruction."""
    with pytest.raises(CampaignError, match="Additional properties|not allowed"):
        validate_campaign(camp(budgett={"cpu_hours": 1}))


def test_an_unknown_family_tag_is_rejected():
    """The Layer-2 vocabulary is shared with the board; a typo cannot match."""
    with pytest.raises(CampaignError, match="methods/families"):
        validate_campaign(camp(methods={"families": ["bivariate-biycle"]}))


def test_an_unknown_stopping_type_is_rejected():
    with pytest.raises(CampaignError, match="stopping"):
        validate_campaign(camp(stopping=[{"type": "when_i_feel_like_it"}]))


@pytest.mark.parametrize("budget", [{}, {"cpu_hours": 0}, {"cpu_hours": -5},
                                    {"cpu_hours": 1, "wall_hours": 2}])
def test_a_malformed_budget_is_rejected(budget):
    """No budget, a zero budget and a negative one are all unbounded."""
    with pytest.raises(CampaignError):
        validate_campaign(camp(budget=budget))


def test_an_empty_blocklength_range_is_rejected():
    with pytest.raises(CampaignError, match="is empty"):
        validate_campaign(camp(constraints={"n": [400, 100]}))


def test_a_stopping_condition_missing_its_number_is_rejected():
    with pytest.raises(CampaignError, match="needs a count"):
        validate_campaign(camp(stopping=[{"type": "candidates_found"}]))
    with pytest.raises(CampaignError, match="needs experiments"):
        validate_campaign(camp(stopping=[{"type": "no_progress"}]))


def test_target_reached_without_a_target_is_rejected():
    with pytest.raises(CampaignError, match="no target to reach"):
        validate_campaign(camp(stopping=[{"type": "target_reached"}]))


def test_a_bad_schema_version_is_rejected():
    with pytest.raises(CampaignError):
        validate_campaign(camp(schema_version=2))


# -- the search space -----------------------------------------------------

def test_constraints_filter_the_search_and_nothing_else():
    """in_scope answers 'is this worth another rung', never 'which cell'.

    The cell is computed by the verifier from the matrices and the layout, so
    nothing this method returns may reach a submission document.
    """
    c = Campaign(validate_campaign(camp()))
    assert c.in_scope(n=200, w=8)
    assert not c.in_scope(n=500)
    assert not c.in_scope(w=12)
    # the locality classes nest: a single-layer code satisfies a bilayer ask
    assert c.in_scope(locality="local-2d-single")
    assert not c.in_scope(locality="unrestricted")
    # an unconstrained axis never excludes anything
    assert c.in_scope(k=10 ** 6)


def test_the_objective_metric_is_computed_from_the_candidate():
    c = Campaign(validate_campaign(camp()))
    assert c.score(n=200, k=8, d=10) == 4.0


# -- the ledger -----------------------------------------------------------

def test_a_candidate_the_gate_did_not_pass_is_refused():
    """The single most important refusal in this module."""
    led = Ledger(Campaign(validate_campaign(camp())))
    with pytest.raises(CampaignError, match="passed: true"):
        led.record_candidate(doc(), {"passed": False, "labels": ["refuted"]})
    with pytest.raises(CampaignError, match="passed: true"):
        led.record_candidate(doc(), {})
    assert led.survivors == []


def test_a_family_outside_the_campaign_is_refused():
    led = Ledger(Campaign(validate_campaign(camp())))
    with pytest.raises(CampaignError, match="not one of this campaign"):
        led.start_experiment("quantum-tanner")


def test_spending_accrues_to_the_campaign_and_the_experiment():
    led = Ledger(Campaign(validate_campaign(camp())))
    led.start_experiment("bivariate-bicycle", seed=1)
    led.spend(cpu_hours=3)
    exp = led.end_experiment()
    assert led.spent["cpu_hours"] == 3 and exp["spent"]["cpu_hours"] == 3
    with pytest.raises(CampaignError, match="unknown budget field"):
        led.spend(magic_hours=1)
    with pytest.raises(CampaignError, match="negative"):
        led.spend(cpu_hours=-1)


def test_budget_exhaustion_fires_and_names_the_field():
    led = Ledger(Campaign(validate_campaign(camp())))
    assert led.stop_reason() is None
    led.spend(cpu_hours=10)
    kind, detail = led.stop_reason()
    assert kind == "budget_exhausted" and "cpu_hours" in detail


def test_a_frontier_advance_fires_when_asked_for():
    c = Campaign(validate_campaign(camp(
        stopping=[{"type": "frontier_advance"}, {"type": "budget_exhausted"}])))
    led = Ledger(c)
    led.start_experiment("bivariate-bicycle")
    led.record_candidate(doc(), passed_verdict(advancing=True))
    led.end_experiment()
    assert led.stop_reason()[0] == "frontier_advance"


def test_a_dry_spell_fires_no_progress():
    c = Campaign(validate_campaign(camp(
        stopping=[{"type": "no_progress", "experiments": 2}])))
    led = Ledger(c)
    for _ in range(2):
        led.start_experiment("bivariate-bicycle")
        led.record_negative("wall", "every draw screened above the cap")
        led.end_experiment()
    kind, detail = led.stop_reason()
    assert kind == "no_progress" and "2 experiments" in detail


def test_a_survivor_resets_the_dry_spell():
    c = Campaign(validate_campaign(camp(
        stopping=[{"type": "no_progress", "experiments": 2}])))
    led = Ledger(c)
    led.start_experiment("bivariate-bicycle")
    led.end_experiment()                      # dry
    led.start_experiment("bivariate-bicycle")
    led.record_candidate(doc(), passed_verdict(advancing=False))
    led.end_experiment()                      # not dry
    assert led.stop_reason() is None


def test_the_target_is_read_in_the_objective_direction():
    up = Campaign(validate_campaign(camp(
        objective={"metric": "kd2_over_n", "direction": "maximize",
                   "target": 100},
        stopping=[{"type": "target_reached"}])))
    assert Ledger(up).stop_reason(best_score=99) is None
    assert Ledger(up).stop_reason(best_score=100)[0] == "target_reached"
    down = Campaign(validate_campaign(camp(
        objective={"metric": "distance", "direction": "minimize", "target": 4},
        stopping=[{"type": "target_reached"}])))
    assert Ledger(down).stop_reason(best_score=5) is None
    assert Ledger(down).stop_reason(best_score=4)[0] == "target_reached"


# -- the summary ----------------------------------------------------------

def test_the_summary_records_what_was_spent_and_what_stopped_it():
    led = Ledger(Campaign(validate_campaign(camp())))
    led.start_experiment("bivariate-bicycle", seed=3)
    led.spend(cpu_hours=10)
    led.record_candidate(doc(), passed_verdict())
    led.end_experiment()
    s = led.summary()
    assert s["summary_version"] == 1 and s["campaign_id"] == "test-campaign"
    assert s["stopped_by"]["type"] == "budget_exhausted"
    assert s["budget"]["consumed"]["cpu_hours"] == 10
    assert s["budget"]["remaining"]["cpu_hours"] == 0
    assert len(s["experiments"]) == 1 and len(s["survivors"]) == 1
    assert s["survivors"][0]["cell"] == ["weight-6", "unrestricted"]
    assert "board entry until a human reviews" in s["authority"]


def test_a_campaign_with_no_submission_still_reports():
    """Zero survivors is a complete outcome, not a failure to report."""
    led = Ledger(Campaign(validate_campaign(camp())))
    led.start_experiment("bivariate-bicycle")
    led.record_negative("closed family",
                        "every draw collapsed under the quotient lift")
    led.spend(cpu_hours=10)
    led.end_experiment()
    s = led.summary()
    assert s["survivors"] == [] and s["frontier_advances"] == 0
    assert s["negative_results"][0]["what"] == "closed family"
    assert s["stopped_by"]["type"] == "budget_exhausted"


def test_the_summary_round_trips_through_disk(tmp_path):
    led = Ledger(Campaign(validate_campaign(camp())))
    out = write_summary(led.summary(status="abandoned"),
                        str(tmp_path / "sub" / "summary.json"))
    assert json.load(open(out))["status"] == "abandoned"


# -- the shipped definitions ---------------------------------------------

@pytest.mark.parametrize("cid", ["w8-2dlocal-n700-1000", "smoke-bb-72"])
def test_the_committed_campaigns_validate(cid):
    """A shipped example that does not load is worse than no example."""
    c = load_campaign(os.path.join(_ROOT, "research", "campaigns", cid,
                                   "campaign.json"))
    assert c.id == cid and c.required_outputs


def test_a_definition_that_is_not_json_says_so(tmp_path):
    p = tmp_path / "campaign.json"
    p.write_text("{not json")
    with pytest.raises(CampaignError, match="not valid JSON"):
        load_campaign(str(p))
