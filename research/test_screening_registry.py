"""Tests for the shared screening registry (issue #2726).

The registry exists because `research/candidates/` is gitignored, so a family
screened and discarded leaves nothing committed and the next session pays for
it again. What is tested here is that the outcome of a screen survives into
the committed summary with the depth it was read at, that the record cannot be
mistaken for a verdict, and that the per-family quality number is a rank
correlation that declines to answer when it has nothing to go on. The gate is
untouched by all of it: a row saying `passed` is a record that
verify/validate_candidate.py once said so, and admits nothing.
"""
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
    spearman,
    validate_summary,
    write_summary,
)


def _campaign(**over):
    obj = {"campaign": {
        "schema_version": 1,
        "id": "reg-test",
        "name": "registry test",
        "objective": {"metric": "kd2_over_n", "direction": "maximize"},
        "methods": {"families": ["generalized-bicycle", "bivariate-bicycle"]},
        "budget": {"candidates_screened": 50},
        "stopping": [{"type": "budget_exhausted"}],
    }}
    obj["campaign"].update(over)
    return Campaign(obj)


def _row(ledger, family, *, d, verdict, trials=2000, params=None, mode=None):
    ledger.start_experiment(family, seed=1, mode=mode, params=params or {})
    ledger.record_screen(trials=trials, d=d, backend="numpy")
    ledger.record_verdict(verdict)
    return ledger.end_experiment()


# -- the row carries the outcome, not only the tally ------------------------

def test_row_carries_params_screened_depth_and_verdict():
    led = Ledger(_campaign())
    exp = _row(led, "generalized-bicycle", d=11, verdict="refuted",
               params={"ring": "Z_341", "a_support": "6+4x2"})
    assert exp["params"]["ring"] == "Z_341"
    assert exp["screened"] == {"trials": 2000, "d": 11, "backend": "numpy"}
    assert exp["verdict"] == "refuted"
    validate_summary(led.summary(status="completed"))


def test_screened_depth_is_required_with_the_reading():
    """A distance without the depth it was read at is not comparable."""
    led = Ledger(_campaign())
    led.start_experiment("bivariate-bicycle")
    with pytest.raises(TypeError):
        led.record_screen(d=8)
    with pytest.raises(CampaignError):
        led.record_screen(trials=0, d=8)


def test_a_screened_member_with_no_gate_run_is_still_a_record():
    """not_run is the row the registry exists to carry."""
    led = Ledger(_campaign())
    exp = _row(led, "bivariate-bicycle", d=4, verdict="not_run",
               params={"l": 6, "m": 6})
    assert exp["verdict"] == "not_run"
    assert exp["survivors"] == 0


def test_unknown_verdict_and_mode_are_refused():
    led = Ledger(_campaign())
    led.start_experiment("bivariate-bicycle")
    with pytest.raises(CampaignError):
        led.record_verdict("looks-promising")
    with pytest.raises(CampaignError):
        led.start_experiment("bivariate-bicycle", mode="vibes")


def test_recording_outside_an_experiment_is_refused():
    led = Ledger(_campaign())
    with pytest.raises(CampaignError):
        led.record_screen(trials=100, d=5)
    with pytest.raises(CampaignError):
        led.record_verdict("passed")


def test_mode_distinguishes_a_swept_family_from_one_mutated_lineage():
    led = Ledger(_campaign())
    _row(led, "bivariate-bicycle", d=6, verdict="not_run", mode="refinement",
         params={"l": 6, "m": 6})
    assert led.experiments[0]["mode"] == "refinement"
    led2 = Ledger(_campaign())
    _row(led2, "bivariate-bicycle", d=6, verdict="not_run")
    assert "mode" not in led2.experiments[0]


# -- estimator quality is a rank correlation --------------------------------

def test_spearman_matches_a_hand_computed_case():
    assert spearman([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)
    assert spearman([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert spearman([1, 2, 3, 4], [1, 3, 2, 4]) == pytest.approx(0.8)


def test_spearman_is_undefined_rather_than_zero_without_spread():
    assert spearman([5, 5, 5], [1, 0, 1]) is None
    assert spearman([1, 2, 3], [1, 1, 1]) is None
    assert spearman([1], [1]) is None


def test_screen_quality_is_per_family_and_reports_its_pair_count():
    led = Ledger(_campaign())
    for d, verdict in ((12, "passed"), (11, "passed"), (5, "refuted"),
                       (4, "refuted")):
        _row(led, "generalized-bicycle", d=d, verdict=verdict)
    _row(led, "bivariate-bicycle", d=6, verdict="passed")
    quality = {q["family"]: q for q in led.screen_quality()}
    assert quality["generalized-bicycle"]["pairs"] == 4
    # A perfect ordering against a two-valued verdict tops out below 1: the
    # verdict side is all ties, so the ceiling is the rank-biserial value and
    # not 1.0. Pinned because a reader comparing two families needs to know
    # that 0.89 here is the best this shape of evidence can produce.
    assert quality["generalized-bicycle"]["spearman"] == pytest.approx(
        0.8944271909999159)
    # One row, and one verdict value: no evidence about ordering.
    assert quality["bivariate-bicycle"]["spearman"] is None
    assert "undefined" in quality["bivariate-bicycle"]["note"]


def test_quality_ignores_verdicts_that_say_nothing_about_ordering():
    """A duplicate is a fact about the board, not about the screen."""
    led = Ledger(_campaign())
    _row(led, "generalized-bicycle", d=12, verdict="duplicate")
    _row(led, "generalized-bicycle", d=4, verdict="dominated")
    _row(led, "generalized-bicycle", d=9, verdict="not_run")
    assert led.screen_quality() == []


def test_quality_ignores_rows_with_no_screened_distance():
    led = Ledger(_campaign())
    led.start_experiment("generalized-bicycle")
    led.record_screen(trials=500)
    led.record_verdict("refuted")
    led.end_experiment()
    assert led.screen_quality() == []


# -- the summary validates, and says what it is -----------------------------

def test_summary_validates_and_carries_the_quality_block():
    led = Ledger(_campaign())
    _row(led, "generalized-bicycle", d=12, verdict="passed")
    _row(led, "generalized-bicycle", d=5, verdict="refuted")
    summ = led.summary(status="completed")
    validate_summary(summ)
    assert summ["screen_quality"][0]["pairs"] == 2


def test_write_summary_refuses_a_summary_that_does_not_validate(tmp_path):
    led = Ledger(_campaign())
    _row(led, "generalized-bicycle", d=7, verdict="passed")
    summ = led.summary(status="completed")
    summ["experiments"][0]["verdict"] = "probably fine"
    with pytest.raises(CampaignError):
        write_summary(summ, str(tmp_path / "summary.json"))
    assert not (tmp_path / "summary.json").exists()


def test_a_sampled_reading_must_say_how_deep_it_went():
    """A trial count is what makes two readings comparable."""
    base = {"summary_version": 1, "campaign_id": "depth-test",
            "status": "completed", "experiments": []}
    for screened in ({"d": 24, "backend": "numpy"}, {"d": 24}):
        doc = dict(base, experiments=[{"family": "f", "screened": screened}])
        with pytest.raises(CampaignError):
            validate_summary(doc)


def test_a_structural_reading_carries_no_trial_count():
    """A search of one block's kernel took no samples, so it borrows none."""
    doc = {"summary_version": 1, "campaign_id": "depth-test",
           "status": "completed",
           "experiments": [{"family": "f",
                            "screened": {"d": 24, "backend": "structural"}}]}
    validate_summary(doc)


def test_a_row_cannot_carry_an_unknown_field():
    """Typos in a registry are worse than absences: they read as data."""
    led = Ledger(_campaign())
    _row(led, "generalized-bicycle", d=7, verdict="passed")
    summ = led.summary(status="completed")
    summ["experiments"][0]["screend"] = {"trials": 10}
    with pytest.raises(CampaignError):
        validate_summary(summ)


def test_every_committed_summary_validates():
    """The registry is only readable if what is in it conforms."""
    root = os.path.join(_ROOT, "research", "campaigns")
    found = 0
    for cid in sorted(os.listdir(root)):
        path = os.path.join(root, cid, "summary.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            validate_summary(json.load(f))
        found += 1
    assert found, "no committed campaign summary to validate"
