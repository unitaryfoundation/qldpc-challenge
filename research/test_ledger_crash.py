"""Tests for telling a crashed sweep from a genuine negative (issue #2761).

Two broken sweeps in this repo's own campaign pattern read as clean
negatives at summary level: one whose sampler raised on a malformed
parameter and filed the exception as a negative result, and one whose worker
died on a deleted helper and recorded nothing at all. Both closed with zero
screened and both looked exactly like a search that ran and found nothing.
What is tested here is that the ledger now refuses to let a zero close
without saying which kind of zero it is, that a crash lands under errors and
not negatives, and that a crash can neither reset nor advance the
no-progress streak.
"""

import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "kit"))

from campaign import (  # noqa: E402
    JOURNAL_VERSION,
    Campaign,
    CampaignError,
    Ledger,
    validate_summary,
)


def _campaign(**over):
    obj = {
        "campaign": {
            "schema_version": 1,
            "id": "crash-test",
            "name": "crash test",
            "objective": {"metric": "kd2_over_n", "direction": "maximize"},
            "methods": {"families": ["bivariate-bicycle"]},
            "budget": {"candidates_screened": 100},
            "stopping": [{"type": "no_progress", "experiments": 2}, {"type": "budget_exhausted"}],
        }
    }
    obj["campaign"].update(over)
    return Campaign(obj)


def test_a_zero_filed_as_a_negative_is_refused():
    """The driver pattern that hid both crashes no longer closes."""
    led = Ledger(_campaign())
    led.start_experiment("bivariate-bicycle", seed=1)
    led.record_negative("sweep failed", "ValueError: invalid literal for int() with base 10")
    with pytest.raises(CampaignError, match="screened zero"):
        led.end_experiment()


def test_a_silent_zero_is_refused():
    """The worker that produced nothing and recorded nothing."""
    led = Ledger(_campaign())
    led.start_experiment("bivariate-bicycle", seed=1)
    with pytest.raises(CampaignError):
        led.end_experiment()


def test_a_crash_closes_as_aborted_and_lands_under_errors():
    led = Ledger(_campaign())
    led.start_experiment("bivariate-bicycle", seed=1)
    led.record_error("sweep failed", "NameError: name 'dominators' is not defined")
    exp = led.end_experiment()
    assert exp["aborted"] is True
    assert led.errors == [
        {"what": "sweep failed", "detail": "NameError: name 'dominators' is not defined", "experiment": 0}
    ]
    assert led.negative_results == []


def test_a_legitimate_zero_closes_when_it_says_so():
    led = Ledger(_campaign())
    led.start_experiment("bivariate-bicycle", seed=1)
    led.record_negative("empty at these parameters", "the sampler yields nothing for l=3, m=3")
    exp = led.end_experiment(empty_ok=True)
    assert "aborted" not in exp
    assert led.errors == []


def test_a_crash_does_not_feed_the_no_progress_stop():
    """A campaign cannot stop for lack of progress on the strength of a crash."""
    led = Ledger(_campaign())
    for _ in range(3):
        led.start_experiment("bivariate-bicycle", seed=1)
        led.record_error("sweep failed", "generator raised")
        led.end_experiment()
    assert led.stop_reason() is None
    # Two real empty experiments do fire it.
    for _ in range(2):
        led.start_experiment("bivariate-bicycle", seed=1)
        led.spend(candidates_screened=10)
        led.end_experiment()
    assert led.stop_reason()[0] == "no_progress"


def test_a_crash_does_not_reset_the_streak_either():
    led = Ledger(_campaign())
    led.start_experiment("bivariate-bicycle", seed=1)
    led.spend(candidates_screened=10)
    led.end_experiment()
    led.start_experiment("bivariate-bicycle", seed=2)
    led.record_error("sweep failed", "x")
    led.end_experiment()
    led.start_experiment("bivariate-bicycle", seed=3)
    led.spend(candidates_screened=10)
    led.end_experiment()
    assert led.stop_reason()[0] == "no_progress"


def test_the_summary_separates_measured_from_attempted():
    led = Ledger(_campaign())
    led.start_experiment("bivariate-bicycle", seed=1)
    led.spend(candidates_screened=10)
    led.end_experiment()
    led.start_experiment("bivariate-bicycle", seed=2)
    led.record_error("sweep failed", "generator raised")
    led.end_experiment()
    summ = led.summary(status="completed")
    validate_summary(summ)
    assert len(summ["experiments"]) == 2
    assert summ["aborted_experiments"] == 1
    assert len(summ["errors"]) == 1
    assert summ["negative_results"] == []


def test_record_error_outside_an_experiment_is_refused():
    led = Ledger(_campaign())
    with pytest.raises(CampaignError):
        led.record_error("x", "y")


def test_errors_survive_the_journal_and_a_merge(tmp_path):
    path = str(tmp_path / "journal.jsonl")
    led = Ledger(_campaign(), journal=path)
    led.start_experiment("bivariate-bicycle", seed=1)
    led.record_error("sweep failed", "generator raised")
    led.end_experiment()
    with open(path, encoding="utf-8") as f:
        rec = json.loads(f.readline())
    assert rec["record_version"] == JOURNAL_VERSION == 2
    assert rec["errors"][0]["what"] == "sweep failed"
    assert rec["experiment"]["aborted"] is True

    back = Ledger.from_journal(_campaign(), path)
    assert back.errors == led.errors
    assert back.experiments[0]["aborted"] is True
    assert back.stop_reason() is None

    other = Ledger(_campaign())
    other.start_experiment("bivariate-bicycle", seed=2)
    other.spend(candidates_screened=5)
    other.end_experiment()
    merged = back.merge(other)
    assert len(merged.errors) == 1 and len(merged.experiments) == 2


def test_a_version_one_journal_still_replays():
    """Records written before the distinction read as having no errors."""
    led = Ledger(_campaign())
    path = None
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
        path = f.name
        f.write(
            json.dumps(
                {
                    "record_version": 1,
                    "campaign_id": "crash-test",
                    "recorded_at": "2026-10-01T00:00:00+00:00",
                    "experiment": {
                        "family": "bivariate-bicycle",
                        "seed": 1,
                        "spent": {"candidates_screened": 10},
                        "survivors": 0,
                    },
                    "survivors": [],
                    "negative_results": [],
                }
            )
            + "\n"
        )
    back = Ledger.from_journal(_campaign(), path)
    os.unlink(path)
    assert back.errors == []
    assert len(back.experiments) == 1
    del led
