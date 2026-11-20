"""Tests for the best-so-far efficiency curve (issue #2735).

The curve exists to show one disagreement: a screen that inflates at low
depth reads above the cell bar while the gate admits nothing near it. That is
the 2026-09-20 failure, 5.3M trials on a ladder whose deep rungs had already
settled below the bar. What is tested here is that the two series are kept
apart, that the verified series only ever carries numbers the gate accepted,
and that a campaign whose screen reached the bar is distinguishable from one
whose screen never did.
"""

import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_HERE, "kit"))

from campaign import curve_from_summary  # noqa: E402


def _summary(rows, cid="curve-test"):
    return {"summary_version": 1, "campaign_id": cid, "status": "completed", "experiments": rows}


def _row(family="bivariate-bicycle", *, trials=1000, d=None, n=None, k=None, verdict=None, verified=None):
    row = {"family": family, "params": {}}
    if n is not None:
        row["params"]["n"] = n
    if k is not None:
        row["params"]["k"] = k
    row["screened"] = {"trials": trials, "d": d, "backend": "numpy"}
    if verdict:
        row["verdict"] = verdict
    if verified is not None:
        row["verified_kd2_over_n"] = verified
    return row


def test_trials_accumulate_and_the_verified_series_is_monotone():
    curve = curve_from_summary(
        _summary(
            [
                _row(trials=1000, verified=3.0, verdict="passed"),
                _row(trials=2000, verified=1.0, verdict="passed"),
                _row(trials=4000, verified=5.0, verdict="passed"),
            ]
        )
    )
    pts = curve["families"][0]["points"]
    assert [p["trials_cumulative"] for p in pts] == [1000, 3000, 7000]
    assert [p["verified_best_kd2_over_n"] for p in pts] == [3.0, 3.0, 5.0]


def test_the_screened_series_is_each_reading_not_a_running_maximum():
    """A ladder settling downward has to show as a descent."""
    curve = curve_from_summary(
        _summary(
            [
                _row(trials=1000, d=12, n=100, k=4),
                _row(trials=100000, d=6, n=100, k=4),
            ]
        )
    )
    got = [p["screened_kd2_over_n"] for p in curve["families"][0]["points"]]
    assert got == [pytest.approx(5.76), pytest.approx(1.44)]


def test_a_screened_reading_never_becomes_a_verified_one():
    """The gate is the only thing that puts a number on the verified series."""
    curve = curve_from_summary(
        _summary(
            [
                _row(trials=1000, d=12, n=100, k=4, verdict="not_run"),
                _row(trials=1000, d=12, n=100, k=4, verdict="refuted"),
            ]
        )
    )
    pts = curve["families"][0]["points"]
    assert all(p["verified_best_kd2_over_n"] is None for p in pts)
    assert curve["headline"]["best_verified_kd2_over_n"] is None


def test_a_passed_row_without_the_field_derives_from_its_own_parameters():
    """A backfilled summary predating the field still plots."""
    curve = curve_from_summary(_summary([_row(trials=20000, d=4, n=25, k=7, verdict="passed")]))
    assert curve["families"][0]["best_verified_kd2_over_n"] == pytest.approx(4.48)


def test_time_to_bar_is_the_trials_spent_when_the_gate_first_cleared_it():
    curve = curve_from_summary(
        _summary(
            [
                _row(trials=1000, verified=2.0, verdict="passed"),
                _row(trials=5000, verified=9.0, verdict="passed"),
                _row(trials=9000, verified=9.5, verdict="passed"),
            ]
        ),
        bar=8.0,
    )
    f = curve["families"][0]
    assert f["trials_to_bar"] == 6000 and f["reached_bar"]
    assert curve["headline"]["trials_to_bar"] == 6000


def test_a_collapsed_ladder_is_distinguishable_from_one_that_never_climbed():
    """The 2026-09-20 shape: the screen cleared the bar and the gate did not."""
    collapsed = curve_from_summary(
        _summary(
            [
                _row(trials=1000, d=20, n=100, k=4, verdict="not_run"),
                _row(trials=5300000, d=8, n=100, k=4, verdict="refuted"),
            ]
        ),
        bar=8.0,
    )
    assert collapsed["headline"]["screened_reached_bar_but_gate_did_not"]
    assert not collapsed["headline"]["reached_bar"]

    never = curve_from_summary(
        _summary(
            [
                _row(trials=1000, d=6, n=100, k=4, verdict="not_run"),
                _row(trials=5300000, d=5, n=100, k=4, verdict="refuted"),
            ]
        ),
        bar=8.0,
    )
    assert not never["headline"]["screened_reached_bar_but_gate_did_not"]
    assert not never["headline"]["reached_bar"]


def test_families_are_kept_apart():
    curve = curve_from_summary(
        _summary(
            [
                _row("bivariate-bicycle", trials=1000, verified=3.0, verdict="passed"),
                _row("lifted-product", trials=2000, verified=9.0, verdict="passed"),
            ]
        ),
        bar=8.0,
    )
    by = {f["family"]: f for f in curve["families"]}
    assert by["bivariate-bicycle"]["reached_bar"] is False
    assert by["lifted-product"]["trials_to_bar"] == 2000


def test_a_refutation_pass_yields_no_verified_series():
    """Nothing was built, so there is nothing for the gate to have passed."""
    rows = [
        {
            "family": "generalized-bicycle",
            "params": {"entry": "x"},
            "screened": {"d": 77, "trials": 300000000, "backend": "gpu"},
            "verdict": "held",
        }
    ]
    curve = curve_from_summary(_summary(rows))
    assert curve["headline"]["best_verified_kd2_over_n"] is None
    assert curve["families"][0]["points"][0]["screened_kd2_over_n"] is None


def test_rows_without_a_trial_count_do_not_advance_the_axis():
    curve = curve_from_summary(
        _summary(
            [
                {"family": "f", "params": {}, "verdict": "not_run"},
                _row("f", trials=2000, verified=1.0, verdict="passed"),
            ]
        )
    )
    assert [p["trials_cumulative"] for p in curve["families"][0]["points"]] == [0, 2000]


def test_committed_curves_match_what_their_summaries_derive():
    """A committed curve that has drifted from its summary is a wrong record."""
    root = os.path.join(_ROOT, "research", "campaigns")
    found = 0
    for cid in sorted(os.listdir(root)):
        path = os.path.join(root, cid, "curve.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            committed = json.load(f)
        with open(os.path.join(root, cid, "summary.json"), encoding="utf-8") as f:
            summary = json.load(f)
        bar = committed.get("bar") or {}
        assert curve_from_summary(summary, bar=bar.get("kd2_over_n"), bar_source=bar.get("source")) == committed
        found += 1
    assert found, "no committed curve to check"
