"""Tests for `qldpc brief` (#2955, item 4): one bounded snapshot composed from
the cell frontier, the screening registry, recent codes, and fieldnotes."""
import io
import json
import os
import sys
from contextlib import redirect_stdout

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "cli"))
import qldpc  # noqa: E402

ENTRIES = [
    {"n": 100, "k": 2, "d": 6, "w": 6, "slug": "100-2-6", "family": "bivariate-bicycle",
     "locality_class": "unrestricted", "weight_class": "weight-6", "board_advancing": True},
    {"n": 144, "k": 12, "d": 12, "w": 6, "slug": "144-12-12", "family": "bivariate-bicycle",
     "locality_class": "unrestricted", "weight_class": "weight-6", "board_advancing": True},
    {"n": 90, "k": 8, "d": 10, "w": 8, "slug": "90-8-10", "family": "generalized-bicycle",
     "locality_class": "unrestricted", "weight_class": "weight-8", "board_advancing": True},
]


def _args(**over):
    base = {"cell": "weight-6/unrestricted", "family": "", "days": 30, "top": 6,
            "limit": 8, "json": False}
    base.update(over)
    return type("A", (), base)()


@pytest.fixture
def small_board(monkeypatch):
    monkeypatch.setattr(qldpc, "_load_board_entries", lambda quiet=False: ENTRIES)
    monkeypatch.setattr(qldpc, "screening_rows", lambda family="", params=None, verdicts=(): (
        [{"campaign_id": "c1", "family": family, "params": {"l": 12}, "screened_d": 12,
          "trials": 20000, "verdict": "held", "backend": "", "backfilled": False}] if family else [], [], 1))
    monkeypatch.setattr(qldpc, "_recent_code_rows", lambda days, family: [
        {"date": "2026-10-01", "slug": "144-12-12", "family": "bivariate-bicycle", "name": "gross"}])


def test_brief_reports_the_cell_frontier_and_bar(small_board):
    args = _args(json=True)
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert qldpc.cmd_brief(args) == 0
    res = args._result
    [cell] = res["cells"]
    assert cell["cell"] == "weight-6/unrestricted"
    assert cell["codes"] == 2 and cell["nondominated"] == 2
    assert cell["bar_kd2_over_n"] == 12.0
    assert cell["frontier"][0]["slug"] == "144-12-12"
    assert "bar kd2/n 12.0" in buf.getvalue()


def test_brief_with_a_family_composes_screening_recent_and_notes(small_board):
    args = _args(family="bivariate-bicycle", json=True)
    buf = io.StringIO()
    with redirect_stdout(buf):
        qldpc.cmd_brief(args)
    res = args._result
    assert res["cells"][0]["family_codes"] == 2
    assert res["screened_total"] == 1 and res["screened"][0]["campaign_id"] == "c1"
    assert res["recent_total"] == 1 and res["recent"][0]["slug"] == "144-12-12"
    assert isinstance(res["fieldnotes"], list) and res["fieldnotes_total"] >= len(res["fieldnotes"])
    out = buf.getvalue()
    assert "screened, bivariate-bicycle: 1 record" in out
    assert "landed in 30 days for bivariate-bicycle: 1 code" in out


def test_brief_is_bounded_by_limit_and_top(small_board, monkeypatch):
    many = [dict(ENTRIES[0], n=100 + i, k=2 + i, d=6, slug=f"x{i}") for i in range(20)]
    monkeypatch.setattr(qldpc, "_load_board_entries", lambda quiet=False: many)
    args = _args(top=3, limit=2, json=True)
    buf = io.StringIO()
    with redirect_stdout(buf):
        qldpc.cmd_brief(args)
    assert len(args._result["cells"][0]["frontier"]) == 3
    assert "more nondominated" in buf.getvalue()


def test_brief_rejects_an_unknown_cell(small_board):
    with pytest.raises(SystemExit):
        qldpc.cmd_brief(_args(cell="weight-99/moon"))


def test_brief_json_is_one_record(small_board, capsys):
    rc = qldpc.main(["brief", "--cell", "weight-6/unrestricted", "--json"])
    captured = capsys.readouterr()
    assert rc == 0
    record = json.loads(captured.out)
    assert record["ok"] and record["cells"][0]["cell"] == "weight-6/unrestricted"
