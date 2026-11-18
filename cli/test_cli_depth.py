"""`qldpc submit` never skips the accelerator pass silently, and the PR body states the depth.

The generalized-bicycle filings of 2026-11-17 reached CI with claims its own
pass refuted by a factor of two or three: the entries carried 2,000-sample
surrogate witnesses and nothing deeper, because a positive --fast-trials
budget was skipped without a word when the C++ accelerator was not built,
and a --reuse-witnesses budget below the floor only printed a warning.
"""
import argparse
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "cli"))
import qldpc  # noqa: E402


def _ns(**over):
    base = dict(trials=20000, fast_trials=2_000_000, reuse_witnesses=False,
                min_fast_trials=qldpc.REUSE_MIN_FAST_TRIALS)
    base.update(over)
    return argparse.Namespace(**base)


def test_a_positive_budget_is_refused_without_the_accelerator(monkeypatch):
    monkeypatch.setattr(qldpc.hd, "_fast", None)
    with pytest.raises(SystemExit, match="not built"):
        qldpc._accelerator_requirement(_ns())
    qldpc._accelerator_requirement(_ns(fast_trials=0))   # the explicit opt-out


def test_the_requirement_is_silent_when_the_accelerator_is_present(monkeypatch):
    monkeypatch.setattr(qldpc.hd, "_fast", object())
    qldpc._accelerator_requirement(_ns())


def test_reuse_below_the_floor_is_refused_unless_the_floor_is_lowered(monkeypatch):
    monkeypatch.setattr(qldpc.hd, "_fast", object())
    with pytest.raises(SystemExit, match="below the"):
        qldpc._reuse_accelerator_requirement(_ns(reuse_witnesses=True, fast_trials=2000))
    qldpc._reuse_accelerator_requirement(_ns(reuse_witnesses=True, fast_trials=2000,
                                             min_fast_trials=1000))
    qldpc._reuse_accelerator_requirement(_ns(reuse_witnesses=False, fast_trials=2000))


def test_the_depth_line_says_what_ran(monkeypatch):
    monkeypatch.setattr(qldpc.hd, "_fast", object())
    assert qldpc._depth_line(_ns()) == (
        "RIS 20,000 trials per side; accelerator 2,000,000 trials per side at pair depth 8")
    assert qldpc._depth_line(_ns(fast_trials=0)) == (
        "RIS 20,000 trials per side; no accelerator pass (--fast-trials 0)")
    assert qldpc._depth_line(_ns(reuse_witnesses=True)).startswith(
        "witnesses reused from the draft; accelerator 2,000,000")
    monkeypatch.setattr(qldpc.hd, "_fast", None)
    assert qldpc._depth_line(_ns(fast_trials=0)).endswith("no accelerator pass (--fast-trials 0)")
