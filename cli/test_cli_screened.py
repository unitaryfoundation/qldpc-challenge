"""Tests for `qldpc screened`, the registry reader (issue #2726).

The command answers one question before a ladder is paid for: was this family
member already screened, at what depth, and how did it go. What is tested
here is that the question can be asked in one call, that a parameter query
narrows by subset rather than by exact document, and that a miss is reported
as a miss instead of as an empty success.
"""
import io
import json
import os
import sys
from contextlib import redirect_stdout

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "cli"))
import qldpc  # noqa: E402


def _summary(cid, experiments, quality=None):
    return {"summary_version": 1, "campaign_id": cid, "status": "completed",
            "experiments": experiments,
            "screen_quality": quality or []}


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """Build a repo root holding two committed summaries."""
    root = tmp_path / "research" / "campaigns"
    rows_a = [
        {"family": "generalized-bicycle",
         "params": {"ring": "Z_341", "l": 11},
         "screened": {"d": 78, "trials": 300000, "backend": "fast"},
         "verdict": "passed", "mode": "novel_generation", "survivors": 1},
        {"family": "generalized-bicycle",
         "params": {"ring": "Z_341", "l": 31},
         "screened": {"d": 61, "trials": 300000, "backend": "fast"},
         "verdict": "refuted", "mode": "novel_generation", "survivors": 0},
    ]
    rows_b = [
        {"family": "bivariate-bicycle", "params": {"l": 6, "m": 6},
         "screened": {"d": 6, "trials": 2000, "backend": "numpy"},
         "verdict": "not_run", "survivors": 0},
    ]
    quality = [{"family": "generalized-bicycle", "pairs": 2,
                "spearman": 1.0}]
    for cid, rows, q in (("cyc-341", rows_a, quality), ("bb-small", rows_b, [])):
        d = root / cid
        d.mkdir(parents=True)
        (d / "summary.json").write_text(
            json.dumps(_summary(cid, rows, q)), encoding="utf-8")
    monkeypatch.setattr(qldpc, "_ROOT", str(tmp_path))
    return tmp_path


def _run(**kw):
    args = type("A", (), {"family": "", "param": [], "params": "",
                          "verdict": [], "limit": 20, "full": False,
                          "json": False})()
    for k, v in kw.items():
        setattr(args, k, v)
    buf = io.StringIO()
    with redirect_stdout(buf):
        qldpc.cmd_screened(args)
    return buf.getvalue(), getattr(args, "_result", {})


def test_one_call_answers_was_this_member_screened(registry):
    out, res = _run(family="generalized-bicycle",
                    param=["ring=Z_341", "l=31"])
    assert res["matches"] == 1
    row = res["rows"][0]
    assert row["screened_d"] == 61 and row["trials"] == 300000
    assert row["verdict"] == "refuted"
    assert "refuted" in out


def test_a_parameter_query_matches_as_a_subset(registry):
    """Querying the ring alone finds every member screened over it."""
    _, res = _run(param=["ring=Z_341"])
    assert res["matches"] == 2


def test_values_compare_as_strings_across_campaigns(registry):
    """One campaign wrote l as a number; a query typed as text still hits."""
    _, res = _run(param=["l=11"])
    assert res["matches"] == 1


def test_a_miss_is_reported_as_a_miss(registry):
    out, res = _run(family="generalized-bicycle", param=["ring=Z_255"])
    assert res["matches"] == 0
    assert "no committed campaign summary records screening it" in out
    assert res["summaries_read"] == 2


def test_verdict_filter_narrows_to_what_the_gate_said(registry):
    _, res = _run(verdict=["not_run"])
    assert res["matches"] == 1
    assert res["rows"][0]["family"] == "bivariate-bicycle"


def test_screen_quality_is_reported_beside_the_rows(registry):
    out, res = _run(family="generalized-bicycle")
    assert res["screen_quality"][0]["pairs"] == 2
    assert "Spearman" in out


def test_params_as_json_and_as_pairs_agree(registry):
    _, a = _run(params=json.dumps({"ring": "Z_341"}))
    _, b = _run(param=["ring=Z_341"])
    assert a["matches"] == b["matches"] == 2


def test_a_malformed_param_is_refused(registry):
    with pytest.raises(SystemExit):
        _run(param=["ring"])
