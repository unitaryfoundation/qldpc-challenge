"""Tests for campaign definitions and their ledger (issue #2219).

Two properties matter more than the rest and are tested hardest, because both
protect the board rather than the code: a campaign's constraints are a
screening filter and never a claim about which track cell anything is in, and a
survivor is only a survivor once the gate has said so. Everything else here is
the schema doing its job, which is worth pinning because a campaign that
validates loosely is a task two executors can read differently.
"""
import copy
import glob
import json
import os
import sys
import time

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_HERE, "kit"))

from campaign import (  # noqa: E402
    MANIFEST_VERSION,
    MAX_LOG_EXCERPT,
    Campaign,
    CampaignError,
    Ledger,
    load_campaign,
    read_log_excerpt,
    repo_snapshot,
    validate_campaign,
    write_manifest,
    write_summary,
)

GOOD = {
    "campaign": {
        "schema_version": 1,
        "id": "test-campaign",
        "name": "A campaign for the tests",
        "objective": {"metric": "kd2_over_n", "direction": "maximize"},
        "direction": None,
        "constraints": {"max_check_weight": 8, "n": [100, 400],
                        "locality": "local-2d-bilayer"},
        "methods": {"families": ["bivariate-bicycle"]},
        "budget": {"cpu_hours": 10},
        "stopping": [{"type": "budget_exhausted"}],
    }
}


CARD = {
    "hypothesis": "GB codes over Z_341 reach kd^2/n above the cell's bar at weight 6.",
    "cell": "unrestricted~weight-6",
    "family": "generalized-bicycle",
    "bar": {"slug": "682-20-22", "axes": ["kd2_over_n"]},
    "budget": {"cpu_hours": 2, "trials_per_candidate": 400},
    "feasibility": "n = 682 is under BASE_MAX_N and group_algebra.py builds the family.",
    "novelty": {"claim": "a weight-6 GB code above the cell's bar at n = 682",
                "against": "the cyclic GB tables of arXiv:2306.16400"},
    "expected_value": "A weight-6 code above the bar at n = 682 would lead the cell at that size.",
    "abandon_criterion": {"flat_fresh_rungs": 2, "trials_cap": 20000},
    "what_a_negative_would_teach": "That weight-6 GB over Z_341 is exhausted at this depth.",
}


def camp(**over):
    obj = copy.deepcopy(GOOD)
    obj["campaign"].update(over)
    return obj


def passed_verdict(n=200, k=8, d=12, wc="weight-6", advancing=True):
    """Build the verdict shape verify/validate_candidate.py actually returns.

    Its ``candidate`` block carries the verifier's weight and locality CLASSES
    and no raw max check weight, so a ledger that reads one gets None.
    """
    return {
        "passed": True,
        "candidate": {"n": n, "k": k, "d": d, "family": "bivariate-bicycle",
                      "weight_class": wc, "locality_class": "unrestricted",
                      "fingerprint": "abc123", "signature": "def456"},
        "gates": {"verify": {"ok": True, "failed_checks": [],
                             "weight_class": wc,
                             "locality_class": "unrestricted"},
                  "novelty": {"board_advancing": advancing,
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


def test_target_reached_on_a_metric_the_ledger_cannot_score_is_rejected():
    """A stopping condition that can never fire is worse than none at all."""
    with pytest.raises(CampaignError, match="could never fire"):
        validate_campaign(camp(
            objective={"metric": "frontier_entries", "direction": "maximize",
                       "target": 3},
            stopping=[{"type": "target_reached"}]))


def test_an_id_that_is_not_its_directory_is_rejected(tmp_path):
    """A copied definition must not file its ledger under the original."""
    home = tmp_path / "campaigns" / "copied-from-somewhere"
    home.mkdir(parents=True)
    p = home / "campaign.json"
    p.write_text(json.dumps(GOOD))
    with pytest.raises(CampaignError, match="not the directory name"):
        load_campaign(str(p))


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
    # a locality string outside the schema's classes says so
    with pytest.raises(CampaignError, match="unknown locality class"):
        c.in_scope(locality="2D local")


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


def test_a_survivor_outside_an_experiment_is_refused():
    """A survivor no experiment accounts for makes the ledger self-contradicting."""
    led = Ledger(Campaign(validate_campaign(camp())))
    with pytest.raises(CampaignError, match="without start_experiment"):
        led.record_candidate(doc(), passed_verdict())


def test_the_survivor_row_carries_the_verifier_s_weight_class():
    led = Ledger(Campaign(validate_campaign(camp())))
    led.start_experiment("bivariate-bicycle")
    row = led.record_candidate(doc(), passed_verdict())
    assert row["weight_class"] == "weight-6"


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
        led.end_experiment(empty_ok=True)
    kind, detail = led.stop_reason()
    assert kind == "no_progress" and "2 experiments" in detail


def test_a_survivor_resets_the_dry_spell():
    c = Campaign(validate_campaign(camp(
        stopping=[{"type": "no_progress", "experiments": 2}])))
    led = Ledger(c)
    led.start_experiment("bivariate-bicycle")
    led.end_experiment(empty_ok=True)                      # dry
    led.start_experiment("bivariate-bicycle")
    led.record_candidate(doc(), passed_verdict(advancing=False))
    led.end_experiment()                      # not dry
    assert led.stop_reason() is None


def _with_survivor(c, **candidate):
    led = Ledger(c)
    led.start_experiment("bivariate-bicycle")
    led.record_candidate(doc(**candidate), passed_verdict(advancing=False))
    led.end_experiment()
    return led


def test_the_target_is_read_in_the_objective_direction():
    up = Campaign(validate_campaign(camp(
        objective={"metric": "kd2_over_n", "direction": "maximize",
                   "target": 100},
        stopping=[{"type": "target_reached"}])))
    assert _with_survivor(up, n=200, k=8, d=12).stop_reason() is None
    assert _with_survivor(up, n=100, k=10, d=32).stop_reason()[0] \
        == "target_reached"
    # no current metric is naturally minimized; the comparison still honours it
    down = Campaign(validate_campaign(camp(
        objective={"metric": "distance", "direction": "minimize", "target": 4},
        stopping=[{"type": "target_reached"}])))
    assert _with_survivor(down, d=5).stop_reason() is None
    assert _with_survivor(down, d=4).stop_reason()[0] == "target_reached"


def test_the_target_cannot_be_reached_by_a_candidate_the_gate_refused():
    """The refusal that the shipped smoke campaign exercises end to end.

    A screening score for a code the gate went on to reject must not end a
    campaign, and must not appear in its summary as an objective met.
    """
    c = Campaign(validate_campaign(camp(
        objective={"metric": "kd2_over_n", "direction": "maximize",
                   "target": 6},
        stopping=[{"type": "target_reached"}, {"type": "budget_exhausted"}])))
    led = Ledger(c)
    led.start_experiment("bivariate-bicycle")
    with pytest.raises(CampaignError):
        led.record_candidate(doc(n=72, k=12, d=6),          # kd^2/n = 6
                             {"passed": False, "labels": ["duplicate"]})
    led.record_negative("gate rejected", "duplicate of a board entry")
    led.record_verdict("duplicate")
    led.end_experiment()
    assert led.best_score() is None
    assert led.stop_reason() is None
    s = led.summary()
    assert s["stopped_by"]["type"] is None and s["status"] == "paused"


def test_wall_time_is_measured_rather_than_reported():
    """A cap nothing observes is advisory; budget_exhausted must see the clock."""
    c = Campaign(validate_campaign(camp(budget={"walltime_hours": 1e-9})))
    led = Ledger(c)
    # the cap is 3.6 us, which two method calls do not reliably outlast; sleep
    # past it so the assertion tests that the clock is read, not how long the
    # interpreter took to get here
    time.sleep(0.01)
    assert led.consumed()["walltime_hours"] > 0
    assert led.budget_exhausted() == "walltime_hours"
    assert led.stop_reason()[0] == "budget_exhausted"


# -- the summary ----------------------------------------------------------

def test_the_summary_records_what_was_spent_and_what_stopped_it():
    led = Ledger(Campaign(validate_campaign(camp())))
    led.start_experiment("bivariate-bicycle", seed=3)
    led.spend(cpu_hours=10)
    led.record_candidate(doc(), passed_verdict())
    led.end_experiment()
    s = led.summary()
    assert s["summary_version"] == 1 and s["campaign_id"] == "test-campaign"
    assert s["status"] == "completed"
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
    assert s["status"] == "completed"
    assert s["survivors"] == [] and s["frontier_advances"] == 0
    assert s["negative_results"][0]["what"] == "closed family"
    assert s["stopped_by"]["type"] == "budget_exhausted"


def test_an_interrupted_run_does_not_file_itself_as_completed():
    led = Ledger(Campaign(validate_campaign(camp())))
    led.start_experiment("bivariate-bicycle")
    led.spend(cpu_hours=1)
    led.end_experiment()
    assert led.summary()["status"] == "paused"


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


# -- the journal and the merge (issue #2314) ------------------------------

def survivor_verdict(fingerprint, **over):
    v = passed_verdict(**over)
    v["candidate"]["fingerprint"] = fingerprint
    return v


def run_one(journal, family="bivariate-bicycle", *, seed, cpu_hours=1,
            fingerprints=(), negatives=()):
    """Run one experiment of the shared campaign and journal it."""
    led = Ledger(Campaign(validate_campaign(camp())), journal=str(journal))
    led.start_experiment(family, seed=seed)
    led.spend(cpu_hours=cpu_hours)
    for fp in fingerprints:
        led.record_candidate(doc(), survivor_verdict(fp))
    for what, detail in negatives:
        led.record_negative(what, detail)
    led.end_experiment()
    return led


def test_each_closed_experiment_is_journaled_as_it_closes(tmp_path):
    """A kill then costs the experiment in flight, not the whole run."""
    j = tmp_path / "ledger.jsonl"
    led = Ledger(Campaign(validate_campaign(camp())), journal=str(j))
    led.start_experiment("bivariate-bicycle", seed=1)
    led.spend(cpu_hours=2)
    assert not j.exists()                        # nothing is written mid-run
    led.end_experiment()
    led.start_experiment("bivariate-bicycle", seed=2)
    led.record_candidate(doc(), passed_verdict())
    led.end_experiment()
    lines = j.read_text().strip().split("\n")
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["campaign_id"] == "test-campaign"
    assert first["experiment"]["seed"] == 1 and first["survivors"] == []
    assert json.loads(lines[1])["survivors"][0]["cell"] == \
        ["weight-6", "unrestricted"]


def test_a_journal_replays_into_the_ledger_it_came_from(tmp_path):
    j = tmp_path / "ledger.jsonl"
    run_one(j, seed=1, cpu_hours=4, fingerprints=("fp-a",),
            negatives=[("closed family", "every draw collapsed")])
    back = Ledger.from_journal(Campaign(validate_campaign(camp())), str(j))
    assert back.consumed()["cpu_hours"] == 4
    assert [s["fingerprint"] for s in back.survivors] == ["fp-a"]
    assert back.negative_results[0]["what"] == "closed family"
    assert back.frontier_advances == 1


def test_a_truncated_last_line_loses_only_the_tail(tmp_path):
    j = tmp_path / "ledger.jsonl"
    run_one(j, seed=1, cpu_hours=4, fingerprints=("fp-a",))
    with open(j, "a") as f:
        f.write('{"record_version": 1, "campaign_id": "test-camp')
    back = Ledger.from_journal(Campaign(validate_campaign(camp())), str(j))
    assert len(back.experiments) == 1 and back.consumed()["cpu_hours"] == 4


def test_a_corrupt_line_in_the_middle_is_not_quietly_skipped(tmp_path):
    j = tmp_path / "ledger.jsonl"
    run_one(j, seed=1)
    with open(j, "a") as f:
        f.write("{not json\n")
    run_one(j, seed=2)
    with pytest.raises(CampaignError, match="not the last line"):
        Ledger.from_journal(Campaign(validate_campaign(camp())), str(j))


def test_a_journal_for_another_campaign_is_refused(tmp_path):
    j = tmp_path / "ledger.jsonl"
    run_one(j, seed=1)
    other = Campaign(validate_campaign(camp(id="some-other-campaign")))
    with pytest.raises(CampaignError, match="journal is for campaign"):
        Ledger.from_journal(other, str(j))


def test_two_executors_of_the_same_campaign_merge(tmp_path):
    a = run_one(tmp_path / "a.jsonl", seed=1, cpu_hours=3,
                fingerprints=("fp-a",))
    b = run_one(tmp_path / "b.jsonl", seed=2, cpu_hours=5,
                fingerprints=("fp-b",),
                negatives=[("wall", "nothing under weight 8")])
    both = a.merge(b)
    assert len(both.experiments) == 2
    assert both.consumed()["cpu_hours"] == 8
    assert sorted(s["fingerprint"] for s in both.survivors) == ["fp-a", "fp-b"]
    assert both.negative_results[0]["what"] == "wall"
    assert both.frontier_advances == 2
    assert len(a.experiments) == 1 and len(b.experiments) == 1


def test_the_same_seed_is_the_same_work_and_is_charged_once(tmp_path):
    """Replicated execution is the point; paying twice for it is not."""
    a = run_one(tmp_path / "a.jsonl", seed=7, cpu_hours=3,
                fingerprints=("fp-a",))
    b = run_one(tmp_path / "b.jsonl", seed=7, cpu_hours=3,
                fingerprints=("fp-a",))
    both = a.merge(b)
    assert len(both.experiments) == 1
    assert both.consumed()["cpu_hours"] == 3
    assert len(both.survivors) == 1 and both.frontier_advances == 1


def test_an_experiment_with_no_seed_cannot_be_deduplicated(tmp_path):
    """Nothing tells the two apart, so over-count rather than discard work."""
    a = run_one(tmp_path / "a.jsonl", seed=None, cpu_hours=3)
    b = run_one(tmp_path / "b.jsonl", seed=None, cpu_hours=3)
    both = a.merge(b)
    assert len(both.experiments) == 2 and both.consumed()["cpu_hours"] == 6


def test_merging_a_different_campaign_is_refused(tmp_path):
    a = run_one(tmp_path / "a.jsonl", seed=1)
    other = Ledger(Campaign(validate_campaign(camp(id="some-other-campaign"))))
    with pytest.raises(CampaignError, match="different campaign"):
        a.merge(other)


def test_a_merged_ledger_stops_on_the_shared_budget(tmp_path):
    """The budget is the campaign's, not each executor's."""
    a = run_one(tmp_path / "a.jsonl", seed=1, cpu_hours=6)
    b = run_one(tmp_path / "b.jsonl", seed=2, cpu_hours=6)
    assert a.stop_reason() is None and b.stop_reason() is None
    kind, detail = a.merge(b).stop_reason()
    assert kind == "budget_exhausted" and "cpu_hours" in detail


def test_a_merged_ledger_summarizes_like_any_other(tmp_path):
    a = run_one(tmp_path / "a.jsonl", seed=1, cpu_hours=5,
                fingerprints=("fp-a",))
    b = run_one(tmp_path / "b.jsonl", seed=2, cpu_hours=5,
                fingerprints=("fp-b",))
    s = a.merge(b).summary()
    assert s["budget"]["consumed"]["cpu_hours"] == 10
    assert len(s["survivors"]) == 2 and s["frontier_advances"] == 2
    assert "board entry until a human reviews" in s["authority"]


def test_several_journals_load_as_one_ledger(tmp_path):
    run_one(tmp_path / "a.jsonl", seed=1, cpu_hours=2, fingerprints=("fp-a",))
    run_one(tmp_path / "b.jsonl", seed=2, cpu_hours=2, fingerprints=("fp-b",))
    both = Ledger.from_journal(Campaign(validate_campaign(camp())),
                               [str(tmp_path / "a.jsonl"),
                                str(tmp_path / "b.jsonl")])
    assert len(both.experiments) == 2 and both.consumed()["cpu_hours"] == 4
    assert len(both.survivors) == 2


def test_a_ledger_with_no_journal_writes_nothing(tmp_path):
    led = Ledger(Campaign(validate_campaign(camp())))
    led.start_experiment("bivariate-bicycle", seed=1)
    led.end_experiment(empty_ok=True)
    assert list(tmp_path.iterdir()) == []


# -- run contracts (issue #2342) ------------------------------------------
CONTRACT = {
    "template": "python research/cyclic_gb.py --m {m} --trials {trials} "
                "--seed {seed}",
    "parameters": {"m": 337, "trials": 2000000, "seed": [51, 52]},
}


def test_a_campaign_without_a_contract_is_still_valid():
    """run_contract is optional: it cannot retroactively invalidate a campaign."""
    c = Campaign(validate_campaign(camp()))
    assert c.run_contract is None
    assert c.contract_hash is None


def test_a_template_placeholder_with_no_value_is_refused():
    """An invocation that cannot be resolved records nothing."""
    bad = copy.deepcopy(CONTRACT)
    bad["template"] += " --screen {screen}"
    with pytest.raises(CampaignError, match="no value in parameters"):
        validate_campaign(camp(run_contract=bad))


def test_a_parameter_the_template_never_uses_is_refused():
    """A declared depth the invocation ignores is worse than none.

    It reads as the depth that ran while the run used something else, which
    is exactly the confusion the contract exists to remove.
    """
    bad = copy.deepcopy(CONTRACT)
    bad["parameters"]["screen"] = 400
    with pytest.raises(CampaignError, match="never uses"):
        validate_campaign(camp(run_contract=bad))


def test_the_contract_hash_keys_on_template_and_parameters():
    """Either one changing changes what ran, so both are in the hash."""
    base = Campaign(validate_campaign(camp(run_contract=CONTRACT)))
    deeper = copy.deepcopy(CONTRACT)
    deeper["parameters"]["trials"] = 20000000
    other = copy.deepcopy(CONTRACT)
    other["template"] = other["template"].replace("cyclic_gb", "bb_sweep")

    h = base.contract_hash
    assert h and len(h) == 16
    assert h == Campaign(validate_campaign(camp(run_contract=CONTRACT))).contract_hash
    assert h != Campaign(validate_campaign(camp(run_contract=deeper))).contract_hash
    assert h != Campaign(validate_campaign(camp(run_contract=other))).contract_hash


def test_an_experiment_row_records_the_depth_it_ran_at():
    """The point of all this: depth is readable off the summary."""
    c = Campaign(validate_campaign(camp(run_contract=CONTRACT)))
    led = Ledger(c)
    led.start_experiment("bivariate-bicycle", seed=51)
    exp = led.end_experiment(empty_ok=True)
    assert exp["params"]["trials"] == 2000000
    assert exp["contract_hash"] == c.contract_hash
    assert "contract_deviations" not in exp

    s = led.summary()
    assert s["contract_hash"] == c.contract_hash
    assert s["run_contract"]["parameters"]["m"] == 337


def test_an_override_is_applied_and_reported_as_a_deviation():
    """A campaign file nobody may depart from is one nobody passes.

    So the override wins, and the row says it did. What must not happen is
    the override being absorbed silently, which is the state this replaces.
    """
    c = Campaign(validate_campaign(camp(run_contract=CONTRACT)))
    led = Ledger(c)
    led.start_experiment("bivariate-bicycle", seed=51, trials=300)
    exp = led.end_experiment(empty_ok=True)
    assert exp["params"]["trials"] == 300
    assert exp["contract_deviations"] == {
        "trials": {"contract": 2000000, "used": 300}}


def test_an_override_equal_to_the_contract_is_not_a_deviation():
    """Passing the contract's own value back is not a departure from it."""
    c = Campaign(validate_campaign(camp(run_contract=CONTRACT)))
    params, dev = c.resolved_params(trials=2000000)
    assert params["trials"] == 2000000
    assert dev == {}


def test_two_lanes_at_one_contract_are_comparable_by_a_string():
    """Matched depth becomes a field comparison, not an audit.

    AUTORESEARCH.md 5b re-runs both sides at matched depth to repair
    incomparable numbers after the fact. Same hash, same depth.
    """
    c = Campaign(validate_campaign(camp(run_contract=CONTRACT)))
    rows = []
    for seed in (51, 52):
        led = Ledger(c)
        led.start_experiment("bivariate-bicycle", seed=seed)
        rows.append(led.end_experiment(empty_ok=True))
    assert rows[0]["contract_hash"] == rows[1]["contract_hash"]
    assert rows[0]["params"] == rows[1]["params"]


def test_the_contract_cannot_weaken_the_gate():
    """A contract constrains nothing a campaign may claim."""
    c = Campaign(validate_campaign(camp(run_contract=CONTRACT)))
    led = Ledger(c)
    led.start_experiment("bivariate-bicycle", seed=51)
    with pytest.raises(CampaignError, match="passed"):
        led.record_candidate({"n": 200, "k": 8, "distance": {"d": 12}},
                             {"passed": False})


# -- run manifests (issue #2341) ------------------------------------------
def test_snapshot_identifies_the_code_a_run_executed():
    """A snapshot has to distinguish two runs from the same commit.

    HEAD alone does not: a campaign is normally run from a tree with edits
    in it, and two such runs produce different numbers from the same sha.
    """
    snap = repo_snapshot()
    assert set(snap) >= {"head", "dirty", "diff_sha256"}
    if snap["head"] is not None:
        assert len(snap["head"]) == 40
        # dirty and diff_sha256 have to agree, or neither says anything.
        assert bool(snap["dirty"]) == (snap["diff_sha256"] is not None)


def test_snapshot_outside_a_checkout_still_produces_a_manifest(tmp_path):
    """A run outside a repo gets a manifest with nulls, not an exception.

    A manifest that refuses to be written teaches a runner to skip manifests,
    which is the habit this is trying to replace.
    """
    snap = repo_snapshot(str(tmp_path))
    assert snap["head"] is None
    assert "note" in snap


def test_manifest_records_params_seeds_and_spend(tmp_path):
    """The manifest carries what a shell history used to."""
    c = Campaign(validate_campaign(camp()))
    led = Ledger(c, params={"trials": 2_000_000, "workers": 8,
                                        "ladder": [[2000, 12], [20000, 11]]})
    led.start_experiment(c.families[0], seed=51)
    led.spend(cpu_hours=0.25, candidates_screened=10)
    led.end_experiment()
    led.start_experiment(c.families[0], seed=52)
    led.end_experiment(empty_ok=True)

    man = led.manifest()
    assert man["manifest_version"] == MANIFEST_VERSION
    assert man["campaign_id"] == c.id
    assert man["params"]["trials"] == 2_000_000
    assert man["params"]["ladder"] == [[2000, 12], [20000, 11]]
    assert man["seeds"] == [51, 52]
    assert man["experiments"] == 2
    assert man["consumed"]["candidates_screened"] == 10
    assert man["snapshot"]["head"] == repo_snapshot()["head"]

    out = write_manifest(man, str(tmp_path / "manifest.json"))
    assert json.load(open(out))["seeds"] == [51, 52]


def test_manifest_is_written_at_every_experiment_boundary(tmp_path):
    """A run killed mid-campaign still leaves a manifest for what closed."""
    path = tmp_path / "m" / "manifest.json"
    c = Campaign(validate_campaign(camp()))
    led = Ledger(c, manifest=str(path), params={"trials": 300})
    assert not path.exists()
    led.start_experiment(c.families[0], seed=1)
    led.end_experiment(empty_ok=True)
    assert json.load(open(path))["experiments"] == 1
    led.start_experiment(c.families[0], seed=2)
    led.end_experiment(empty_ok=True)
    assert json.load(open(path))["experiments"] == 2


def test_summary_identifies_its_own_run(tmp_path):
    """A summary separated from its manifest still says what produced it."""
    c = Campaign(validate_campaign(camp()))
    led = Ledger(c, params={"trials": 5300000, "seeds": [7]})
    led.start_experiment(c.families[0], seed=7)
    led.end_experiment(empty_ok=True)
    s = led.summary()
    assert s["params"]["trials"] == 5300000
    assert s["snapshot"]["head"] == led.manifest()["snapshot"]["head"]


def test_attached_log_travels_with_the_claim_that_rests_on_it(tmp_path):
    """*.log is gitignored, so the excerpt goes into the committed manifest."""
    log = tmp_path / "run.log"
    log.write_text("rung 2000 -> 12\nrung 20000 -> 11\n5300000 trials spent\n")
    c = Campaign(validate_campaign(camp()))
    led = Ledger(c)
    rec = led.attach_log(str(log), why="the 5.3M trial count in the note")
    assert "5300000 trials spent" in rec["excerpt"]
    assert rec["why"].startswith("the 5.3M")
    assert not rec["truncated"]
    assert led.manifest()["logs"][0]["sha256"] == rec["sha256"]


def test_a_missing_log_is_recorded_rather_than_raised(tmp_path):
    """Attaching a log that is gone must not lose the rest of the manifest."""
    led = Ledger(Campaign(validate_campaign(camp())))
    rec = led.attach_log(str(tmp_path / "nope.log"), why="x")
    assert "error" in rec
    assert led.manifest()["logs"] == [rec]


def test_a_long_log_is_truncated_and_says_so(tmp_path):
    """An excerpt that silently dropped its head would be worse than none."""
    log = tmp_path / "big.log"
    log.write_text("x" * (MAX_LOG_EXCERPT + 500) + "TAIL")
    rec = read_log_excerpt(str(log))
    assert rec["truncated"]
    assert rec["excerpt"].endswith("TAIL")
    assert len(rec["excerpt"]) == MAX_LOG_EXCERPT


def test_the_manifest_carries_the_dead_ends(tmp_path):
    """A stage-only run writes no note, so the manifest must hold them.

    AUTORESEARCH.md counts collapsed ladders and closed routes as required
    content, and the note that used to carry them is now drafted only on the
    contributor path. If they are not in the manifest they go with the
    gitignored staging directory, which is the one place that can never be
    cited as evidence.
    """
    c = Campaign(validate_campaign(camp()))
    led = Ledger(c)
    led.start_experiment("bivariate-bicycle", seed=1)
    led.record_negative("weight-6 at n=72", "ladder collapsed at rung 2")
    led.record_negative("Z_31 quotient", "no survivor below the bar")
    led.end_experiment(empty_ok=True)

    man = led.manifest()
    assert len(man["negative_results"]) == 2
    whats = {n["what"] for n in man["negative_results"]}
    assert whats == {"weight-6 at n=72", "Z_31 quotient"}
    assert any("collapsed" in n["detail"] for n in man["negative_results"])


def test_dead_ends_survive_a_write_and_reload(tmp_path):
    """They have to be in the committed artifact, not just in memory."""
    c = Campaign(validate_campaign(camp()))
    path = tmp_path / "manifest.json"
    led = Ledger(c, manifest=str(path))
    led.start_experiment("bivariate-bicycle", seed=1)
    led.record_negative("closed route", "exhausted at P=113")
    led.end_experiment(empty_ok=True)

    on_disk = json.load(open(path, encoding="utf-8"))
    assert on_disk["negative_results"][0]["what"] == "closed route"


# -- writing a definition (issue #2780) --------------------------------------

def test_a_scaffold_is_a_valid_campaign_with_the_defaults_filled():
    from campaign import scaffold_campaign
    spec = scaffold_campaign("gb-probe", "GB probe", card=CARD, budget={"cpu_hours": 2})
    c = spec["campaign"]
    assert c["schema_version"] == 1 and c["id"] == "gb-probe"
    assert c["objective"] == {"metric": "kd2_over_n", "direction": "maximize"}
    assert c["stopping"] == [{"type": "budget_exhausted"}]
    assert c["status"] == "draft"
    Campaign(spec)                                # constructible in memory


def test_a_scaffold_has_no_default_budget():
    """An unbounded campaign is the thing the object exists to prevent."""
    from campaign import scaffold_campaign
    with pytest.raises(TypeError):
        scaffold_campaign("gb-probe", "GB probe")
    with pytest.raises(CampaignError, match="budget"):
        scaffold_campaign("gb-probe", "GB probe", card=CARD, budget={})


def test_scaffold_fields_pass_through_and_are_validated():
    from campaign import scaffold_campaign
    spec = scaffold_campaign("gb-probe", "GB probe", card=CARD, budget={"candidates_screened": 50},
        families=["generalized-bicycle"],
        objective={"target": 20},
        stopping=[{"type": "target_reached"}, {"type": "budget_exhausted"}],
        constraints={"n": [600, 700]}, notes="one night")
    c = spec["campaign"]
    assert c["methods"] == {"families": ["generalized-bicycle"]}
    assert c["objective"]["target"] == 20 and c["constraints"] == {"n": [600, 700]}
    with pytest.raises(CampaignError):
        scaffold_campaign("gb-probe", "GB probe", card=CARD, budget={"cpu_hours": 1},
                          families=["not-a-family"])
    with pytest.raises(CampaignError):
        scaffold_campaign("gb-probe", "GB probe", card=CARD, budget={"cpu_hours": 1},
                          stopping=[{"type": "target_reached"}])   # no target


def test_a_bare_campaign_dict_is_told_about_the_wrapper():
    with pytest.raises(CampaignError, match="wraps its fields"):
        validate_campaign(copy.deepcopy(GOOD["campaign"]))


def test_write_campaign_round_trips_through_load_campaign(tmp_path):
    from campaign import scaffold_campaign, write_campaign
    spec = scaffold_campaign("gb-probe", "GB probe", card=CARD, budget={"cpu_hours": 2},
                             families=["generalized-bicycle"])
    path = tmp_path / "campaigns" / "gb-probe" / "campaign.json"
    assert write_campaign(spec, str(path)) == str(path)
    back = load_campaign(str(path))
    assert back.to_dict() == spec and back.path == str(path)
    # A Campaign object writes the same bytes as its dict.
    again = tmp_path / "again" / "campaign.json"
    write_campaign(back, str(again))
    assert again.read_text(encoding="utf-8") == path.read_text(encoding="utf-8")


def test_write_campaign_refuses_to_overwrite_unless_told(tmp_path):
    from campaign import scaffold_campaign, write_campaign
    spec = scaffold_campaign("gb-probe", "GB probe", card=CARD, budget={"cpu_hours": 2})
    path = str(tmp_path / "campaign.json")
    write_campaign(spec, path)
    with pytest.raises(CampaignError, match="overwrite=True"):
        write_campaign(spec, path)
    spec["campaign"]["name"] = "GB probe, revised"
    write_campaign(spec, path, overwrite=True)
    assert load_campaign(path).name == "GB probe, revised"


def test_write_campaign_holds_the_directory_to_the_id(tmp_path):
    from campaign import scaffold_campaign, write_campaign
    spec = scaffold_campaign("gb-probe", "GB probe", card=CARD, budget={"cpu_hours": 2})
    wrong = tmp_path / "campaigns" / "other-name" / "campaign.json"
    with pytest.raises(CampaignError, match="directory name"):
        write_campaign(spec, str(wrong))


def test_an_in_memory_campaign_drives_a_ledger_to_a_summary(tmp_path):
    """The documented route for a run that does not want a directory yet."""
    from campaign import scaffold_campaign
    led = Ledger(Campaign(scaffold_campaign(
        "adhoc", "ad hoc", card=CARD, budget={"candidates_screened": 10},
        families=["bivariate-bicycle"])))
    led.start_experiment("bivariate-bicycle", seed=1, params={"l": 6})
    led.record_screen(trials=1000, d=6, backend="numpy")
    led.record_verdict("not_run")
    led.end_experiment()
    out = write_summary(led.summary(), str(tmp_path / "summary.json"))
    with open(out, encoding="utf-8") as f:
        summ = json.load(f)
    assert summ["campaign_id"] == "adhoc"
    assert summ["experiments"][0]["screened"] == {"trials": 1000, "d": 6,
                                                  "backend": "numpy"}


# -- the direction card (issue #4028) -----------------------------------------

def test_a_new_campaign_must_state_its_direction_card():
    from campaign import scaffold_campaign
    with pytest.raises(CampaignError, match="direction card"):
        scaffold_campaign("gb-probe", "GB probe", budget={"cpu_hours": 2})
    spec = scaffold_campaign("gb-probe", "GB probe", card=CARD, budget={"cpu_hours": 2})
    assert spec["campaign"]["direction"] == CARD
    assert Campaign(spec).direction == CARD


@pytest.mark.parametrize("damage", [
    lambda c: c.pop("expected_value"),
    lambda c: c.update(cell="weight-6"),
    lambda c: c.update(family="not-a-family"),
    lambda c: c["bar"].pop("axes"),
    lambda c: c["abandon_criterion"].update(flat_fresh_rungs=1),
    lambda c: c.update(expected_value=7),
])
def test_a_malformed_card_is_rejected(damage):
    from campaign import scaffold_campaign
    card = copy.deepcopy(CARD)
    damage(card)
    with pytest.raises(CampaignError):
        scaffold_campaign("gb-probe", "GB probe", card=card, budget={"cpu_hours": 2})


def test_a_definition_before_the_card_carries_null_and_still_loads():
    obj = copy.deepcopy(GOOD)
    obj["campaign"]["direction"] = None
    assert Campaign(validate_campaign(obj)).direction is None
    obj["campaign"].pop("direction")
    with pytest.raises(CampaignError):
        validate_campaign(obj)                    # the key is required, null or not


def test_the_summary_carries_the_card(tmp_path):
    from campaign import scaffold_campaign
    led = Ledger(Campaign(scaffold_campaign(
        "adhoc", "ad hoc", card=CARD, budget={"candidates_screened": 10},
        families=["generalized-bicycle"])))
    led.start_experiment("generalized-bicycle", seed=1, params={"m": 341})
    led.record_screen(trials=400, d=6, backend="numpy")
    led.record_verdict("not_run")
    led.end_experiment()
    s = led.summary()
    assert s["direction"] == CARD
    write_summary(s, str(tmp_path / "summary.json"))
    assert json.load(open(tmp_path / "summary.json"))["direction"]["bar"]["slug"] == "682-20-22"


def test_the_committed_campaigns_either_state_a_card_or_say_null():
    for f in sorted(glob.glob(os.path.join(_ROOT, "research", "campaigns", "*", "campaign.json"))):
        c = load_campaign(f)
        assert "direction" in c.c, f
        if c.direction is not None:
            assert c.direction["bar"]["slug"] and c.direction["what_a_negative_would_teach"]
    cards = [load_campaign(f).direction for f in
             glob.glob(os.path.join(_ROOT, "research", "campaigns", "*", "campaign.json"))]
    assert any(cards), "one committed campaign ships with the card filled in"
