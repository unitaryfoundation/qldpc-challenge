"""Tests for `qldpc negatives`, the memory of closed routes across campaigns (issue #4233).

`screened` says a family member was tried. This command says why a route was
closed, what the closure assumed, and what change would make it worth
retrying, read across every committed summary. What is tested is that a
typed negative comes back whole, that a bare one is reached through its
campaign's families and says what it lacks, that parameter and text queries
narrow as documented, and that a miss is a miss.
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


def _summary(cid, experiments, negatives, direction=None):
    s = {"summary_version": 1, "campaign_id": cid, "status": "completed",
         "experiments": experiments, "negative_results": negatives}
    if direction:
        s["direction"] = direction
    return s


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """Build a repo root with a typed negative, a bare one, and a campaign with none."""
    root = tmp_path / "research" / "campaigns"
    typed = {"what": "Z_341 at l=31 is closed",
             "detail": "two flat rungs at d <= 61 under the bar 78",
             "assumptions": ["weight-6 GB over Z_341", "fast RIS at 300000 trials"],
             "revisit_if": "a backend that reaches 1e6 trials, or a weight-8 variant",
             "family": "generalized-bicycle", "params": {"ring": "Z_341", "l": 31}}
    bare = {"what": "closed family",
            "detail": "every trinomial pair screened below the bar"}
    card = {"family": "bivariate-bicycle",
            "what_a_negative_would_teach": "trinomials at n <= 100 do not reach the bar"}
    for cid, exps, negs, direction in (
            ("cyc-341", [{"family": "generalized-bicycle",
                          "params": {"ring": "Z_341", "l": 31}}], [typed], None),
            ("bb-small", [{"family": "bivariate-bicycle", "params": {"l": 6, "m": 6}}],
             [bare], card),
            ("quiet", [{"family": "lifted-product"}], [], None)):
        d = root / cid
        d.mkdir(parents=True)
        (d / "summary.json").write_text(json.dumps(_summary(cid, exps, negs, direction)),
                                        encoding="utf-8")
    monkeypatch.setattr(qldpc, "_ROOT", str(tmp_path))
    return tmp_path


def _run(**kw):
    args = type("A", (), {"family": "", "param": [], "match": "", "limit": 20,
                          "full": False, "json": False})()
    for k, v in kw.items():
        setattr(args, k, v)
    buf = io.StringIO()
    with redirect_stdout(buf):
        qldpc.cmd_negatives(args)
    return buf.getvalue(), getattr(args, "_result", {})


def test_every_negative_is_listed_with_what_it_assumed(registry):
    out, res = _run()
    assert res["summaries_read"] == 3 and res["matches"] == 2
    assert "2 negative results across 3 campaign summaries, 1 with assumptions" in out
    assert "assumes: weight-6 GB over Z_341; fast RIS at 300000 trials" in out
    assert "revisit if: a backend that reaches 1e6 trials" in out
    assert ("no assumptions or revisit condition recorded; its direction card says a "
            "negative would teach: trinomials at n <= 100") in out


def test_a_family_query_reaches_a_bare_negative_through_its_campaign(registry):
    out, res = _run(family="bivariate-bicycle")
    assert [r["campaign_id"] for r in res["rows"]] == ["bb-small"]
    assert "[bivariate-bicycle (the campaign's)]" in out
    out, res = _run(family="generalized-bicycle")
    assert [r["campaign_id"] for r in res["rows"]] == ["cyc-341"]
    assert "[generalized-bicycle]  l=31, ring=Z_341" in out
    out, res = _run(family="lifted-product")
    assert res["matches"] == 0
    assert "lifted-product: no committed campaign summary records a negative result" in out


def test_a_parameter_query_matches_the_negatives_own_params_as_a_subset(registry):
    _, res = _run(param=["ring=Z_341"])
    assert [r["campaign_id"] for r in res["rows"]] == ["cyc-341"]
    _, res = _run(param=["ring=Z_341", "l=31"])
    assert res["matches"] == 1
    _, res = _run(param=["ring=Z_341", "l=11"])
    assert res["matches"] == 0
    _, res = _run(param=["l=6"])           # bb-small's negative recorded no params
    assert res["matches"] == 0
    with pytest.raises(SystemExit):
        _run(param=["ring"])


def test_a_text_query_searches_the_whole_record(registry):
    _, res = _run(match="weight-8")        # only in revisit_if
    assert [r["what"] for r in res["rows"]] == ["Z_341 at l=31 is closed"]
    _, res = _run(match="TRINOMIAL")
    assert [r["campaign_id"] for r in res["rows"]] == ["bb-small"]
    _, res = _run(match="hexagonal")
    assert res["matches"] == 0


def test_the_listing_is_bounded(registry):
    out, _ = _run(limit=1)
    assert "... 1 more (--limit N, --full)" in out
    out, _ = _run(limit=1, full=True)
    assert "more (--limit" not in out


def test_the_live_registry_reads_without_error():
    """The committed summaries, whatever they hold today, parse into rows."""
    rows, summaries = qldpc.negative_rows()
    assert summaries >= 1
    for r in rows:
        assert r["what"] and r["campaign_id"] and r["path"].startswith("research/campaigns/")
