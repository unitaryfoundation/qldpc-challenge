"""`qldpc targets --staleness`: when each cell's frontier last changed (issue #4238).

The board is a stub and the history replay is a stub, so these are about the
join: the column, the stalest-first order, and the JSON record. The replay
itself is tested beside research/audits/frontier_history.py.
"""
import datetime
import io
import json
import os
import sys
from contextlib import redirect_stdout

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "cli"))
import coordination  # noqa: E402
import qldpc  # noqa: E402

W6 = {"slug": "100-2-6", "n": 100, "k": 2, "d": 6, "w": 6, "code_type": "CSS",
      "locality_class": "unrestricted", "weight_class": "weight-6"}
W8 = {"slug": "90-2-6", "n": 90, "k": 2, "d": 6, "w": 8, "code_type": "CSS",
      "locality_class": "unrestricted", "weight_class": "weight-8"}
TODAY = datetime.date(2026, 11, 5)


@pytest.fixture(autouse=True)
def _board(monkeypatch, tmp_path):
    monkeypatch.setattr(qldpc, "_load_board_entries", lambda: [dict(W6), dict(W8)])
    monkeypatch.setattr(coordination, "CLAIMS", str(tmp_path / "claims"))
    seen = {}

    def fake_moves(repo, classes):
        seen["classes"] = classes
        w6 = {"frontier": {"date": "2026-11-04", "commit": "abc123456", "landing": 81,
                           "what": "[[100,2,6]] w=6 100-2-6", "kind": "landed"},
              "record": {"date": "2026-10-14", "commit": "abc123450", "landing": 40,
                         "what": "[[100,2,6]] w=6 100-2-6", "kind": "raised",
                         "kd2_over_n": 0.72}}
        w8 = {"frontier": {"date": "2026-11-04", "commit": "def123456", "landing": 81,
                           "what": "[[90,2,6]] w=8 90-2-6", "kind": "revised"},
              "record": {"date": "2026-11-04", "commit": "def123456", "landing": 81,
                         "what": "[[90,2,6]] w=8 90-2-6", "kind": "lowered",
                         "kd2_over_n": 0.8}}
        return {("unrestricted", "weight-6"): w6, ("unrestricted", "weight-8"): w8}, 81

    monkeypatch.setattr(qldpc.frontier_history, "cell_moves", fake_moves)
    monkeypatch.setattr(qldpc, "_history_is_shallow", lambda root: False)
    original = qldpc._cell_staleness
    monkeypatch.setattr(qldpc, "_cell_staleness",
                        lambda entries: original(entries, today=TODAY))
    return seen


def _run(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = qldpc.main(argv)
    return rc, buf.getvalue()


def test_no_staleness_skips_the_replay(_board):
    rc, out = _run(["targets", "--no-staleness"])
    assert rc == 0 and "last moved" not in out
    assert "classes" not in _board


def test_a_shallow_clone_is_not_dated(_board, monkeypatch, capsys):
    monkeypatch.setattr(qldpc, "_history_is_shallow", lambda root: True)
    rc, out = _run(["targets"])
    assert rc == 0 and "last moved" not in out and "never moved" not in out
    assert "history is shallow" in capsys.readouterr().err
    assert "classes" not in _board


def test_the_column_dates_each_cells_frontier_and_record_by_default(_board):
    rc, out = _run(["targets"])
    assert rc == 0
    assert ("frontier last moved 2026-11-04 (1 day ago, 0 landings ago): "
            "[[100,2,6]] w=6 100-2-6 landed") in out
    assert ("record kd2/n last moved 2026-10-14 (22 days ago, 41 landings ago): "
            "[[100,2,6]] w=6 100-2-6 raised to 0.72") in out
    assert ("record kd2/n last moved 2026-11-04 (1 day ago, 0 landings ago): "
            "[[90,2,6]] w=8 90-2-6 lowered to 0.8") in out
    # the weight-any cell holds both entries but the stub dated no move for it
    assert "never moved on record (no landing in codes/ history changed this cell" in out
    assert _board["classes"] == {"codes/100-2-6.json": ("unrestricted", "weight-6", 6, "CSS"),
                                 "codes/90-2-6.json": ("unrestricted", "weight-8", 8, "CSS")}


def test_stale_sorts_by_the_record_date_with_the_undated_first(_board):
    rc, out = _run(["targets", "--stale"])
    assert rc == 0
    order = [ln for ln in out.splitlines() if ln.startswith("unrestricted / ")]
    assert order[0].endswith("any weight")                    # never moved on record: first
    assert order[1].endswith("weight ≤ 6") and order[2].endswith("weight ≤ 8")


def test_the_json_record_carries_staleness_as_data(_board, capsys):
    rc = qldpc.main(["targets", "--json"])
    captured = capsys.readouterr()
    assert rc == 0
    record = json.loads(captured.out)
    assert record["landings"] == 81
    w6 = record["staleness"]["weight-6/unrestricted"]
    assert (w6["record"]["date"], w6["record"]["days"], w6["record"]["landings_ago"],
            w6["record"]["kind"]) == ("2026-10-14", 22, 41, "raised")
    assert (w6["frontier"]["days"], w6["frontier"]["landings_ago"]) == (1, 0)
    assert "weight-any/unrestricted" not in record["staleness"]
    assert "replaying codes/ history" not in captured.out      # the prose went to stderr
