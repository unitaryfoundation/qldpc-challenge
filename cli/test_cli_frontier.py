"""`qldpc submit` refuses a code its track cell already dominates (issue #5700).

The board's [[12,4,2]] goes in as an .npz and is searched for real; the board is
a stub holding a [[12,4,3]] at the same check weight, which dominates it, a twin
that ties, and a heavier entry in a looser cell, so the test is about the
refusal, the opt-in, and the record rather than about today's board.
"""
import json
import os

import numpy as np
import pytest
import qldpc
from qldpc_verify import _matrix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAST = ["--trials", "300", "--fast-trials", "0", "--no-circuit"]


def _row(slug, n, k, d, w, wc, lc="unrestricted"):
    return {"slug": slug, "n": n, "k": k, "d": d, "w": w, "code_type": "CSS",
            "eff": round(k * d * d / n, 3), "weight_class": wc, "locality_class": lc}


DOMINATOR = _row("12-4-3", 12, 4, 3, 6, "weight-6")
TWIN = _row("12-4-2-b", 12, 4, 2, 6, "weight-6")
HEAVY = _row("10-4-3", 10, 4, 3, 10, "weight-9plus")
DOM = "[[12,4,3]] w=6 12-4-3.json"


@pytest.fixture(scope="module")
def npz(tmp_path_factory):
    doc = json.load(open(os.path.join(ROOT, "codes", "12-4-2.json")))
    n = doc["n"]
    path = tmp_path_factory.mktemp("in") / "bb12.npz"
    np.savez(path, hx=_matrix(doc["checks"]["X"], n), hz=_matrix(doc["checks"]["Z"], n))
    return str(path)


@pytest.fixture(autouse=True)
def _board(monkeypatch, tmp_path):
    monkeypatch.setattr(qldpc, "_load_board_entries",
                        lambda quiet=False: [dict(DOMINATOR), dict(TWIN), dict(HEAVY)])
    monkeypatch.setattr(qldpc, "_board_identities", lambda: ([], lambda rep: (set(), set())))
    monkeypatch.setattr(qldpc.coordination, "CANDIDATES", str(tmp_path / "staging"))


def _record(capsys):
    captured = capsys.readouterr()
    return json.loads(captured.out), captured.err


def test_a_dominated_code_is_refused_before_anything_is_written(npz, capsys, tmp_path):
    out = str(tmp_path / "codes")
    rc = qldpc.main(["submit", npz, "--authors", "@me", "--json", "--out", out, *FAST])
    record, err = _record(capsys)
    assert rc == 1 and not record["ok"]
    assert record["error"]["stage"] == "frontier" and record["error"]["class"] == "frontier"
    msg = record["error"]["message"]
    assert msg.startswith(f"not board-advancing: dominated in its track cell by {DOM}.")
    assert "AGENTS.md" in msg and msg.endswith("re-run submit with --allow-non-frontier "
                                               "to file it as a non-frontier record")
    assert record["novelty"] == {"board_advancing": False, "dominated_by": [DOM],
                                 "filed_as_non_frontier": False}
    assert "submission refused; nothing written to the board" in err
    assert not os.path.exists(out)


def test_a_dry_run_reports_what_the_real_run_would_refuse(npz, capsys, tmp_path):
    out = str(tmp_path / "codes")
    rc = qldpc.main(["submit", npz, "--authors", "@me", "--dry-run", "--json",
                     "--out", out, *FAST])
    record, err = _record(capsys)
    assert rc == 0 and record["ok"] and record["stage"] == "dry-run"
    assert record["novelty"]["dominated_by"] == [DOM]
    assert any(p.startswith("not board-advancing") for p in record["would_refuse"])
    assert "the real run would be refused as not board-advancing" in err
    assert not os.path.exists(out)


def test_a_dry_run_summary_shows_the_frontier_verdict(npz, capsys, tmp_path):
    out = str(tmp_path / "codes")
    rc = qldpc.main(["submit", npz, "--authors", "@me", "--dry-run", "--out", out, *FAST])
    text = capsys.readouterr().out
    assert rc == 0
    assert f"frontier     NOT board-advancing: dominated by {DOM}" in text
    assert "refuses this without --allow-non-frontier" in text


def test_the_opt_in_files_the_code_as_a_non_frontier_record(npz, capsys, tmp_path):
    out = str(tmp_path / "codes")
    rc = qldpc.main(["submit", npz, "--authors", "@me", "--json", "--out", out,
                     "--allow-non-frontier", *FAST])
    record, err = _record(capsys)
    assert rc == 0 and record["ok"], record.get("error")
    assert record["novelty"] == {"board_advancing": False, "dominated_by": [DOM],
                                 "filed_as_non_frontier": True}
    assert "filed as a non-frontier record" in err
    assert os.path.exists(record["code_path"])
    body = open(record["body_file"], encoding="utf-8").read()
    assert (f"- Non-frontier result: dominated in its track cell by {DOM}. Filed with "
            f"--allow-non-frontier as a record of a valid code, not as a frontier "
            f"claim (AGENTS.md, The motto).") in body


def test_a_board_that_does_not_dominate_it_lets_it_through(npz, capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(qldpc, "_load_board_entries",
                        lambda quiet=False: [dict(TWIN), dict(HEAVY)])
    out = str(tmp_path / "codes")
    rc = qldpc.main(["submit", npz, "--authors", "@me", "--json", "--out", out, *FAST])
    record, _ = _record(capsys)
    assert rc == 0 and record["novelty"] == {"board_advancing": True, "dominated_by": [],
                                             "filed_as_non_frontier": False}
    body = open(record["body_file"], encoding="utf-8").read()
    assert "Non-frontier result" not in body


def test_the_opt_in_on_an_advancing_code_is_noted_and_changes_nothing(npz, capsys, tmp_path,
                                                                        monkeypatch):
    monkeypatch.setattr(qldpc, "_load_board_entries", lambda quiet=False: [dict(TWIN)])
    out = str(tmp_path / "codes")
    rc = qldpc.main(["submit", npz, "--authors", "@me", "--json", "--out", out,
                     "--allow-non-frontier", *FAST])
    record, err = _record(capsys)
    assert rc == 0 and record["novelty"]["board_advancing"]
    assert not record["novelty"]["filed_as_non_frontier"]
    assert "the flag is not needed" in err
