"""`qldpc submit` enforces the matched-depth peer audit a d-only gain owes (issue #4236).

The board's [[12,4,3]] checks go in as an .npz and the code tier is searched for
real; the board is a stub holding one entry the candidate beats on d alone, so
the test is about the refusal and the record, not about today's board.
"""
import json
import os

import numpy as np
import pytest
import qldpc
from qldpc_verify import _matrix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAST = ["--trials", "300", "--fast-trials", "0", "--no-circuit"]
PEER_ROW = {"slug": "12-4-2", "n": 12, "k": 4, "d": 2, "w": 6, "code_type": "CSS",
            "eff": 0.667, "weight_class": "weight-6", "locality_class": "unrestricted"}
PEER = "[[12,4,2]] w=6 12-4-2.json"


@pytest.fixture(scope="module")
def npz(tmp_path_factory):
    doc = json.load(open(os.path.join(ROOT, "codes", "12-4-3.json")))
    n = doc["n"]
    path = tmp_path_factory.mktemp("in") / "bb12.npz"
    np.savez(path, hx=_matrix(doc["checks"]["X"], n), hz=_matrix(doc["checks"]["Z"], n))
    return str(path)


@pytest.fixture(autouse=True)
def _board_with_a_d_only_peer(monkeypatch, tmp_path):
    monkeypatch.setattr(qldpc, "_load_board_entries", lambda quiet=False: [dict(PEER_ROW)])
    monkeypatch.setattr(qldpc, "_board_identities", lambda: ([], lambda rep: (set(), set())))
    monkeypatch.setattr(qldpc.coordination, "CANDIDATES", str(tmp_path / "staging"))


def _record(capsys):
    captured = capsys.readouterr()
    return json.loads(captured.out), captured.err


def _audit(path, **over):
    rec = {"schema": "qldpc-peer-audit/1", "candidate": "cand.json",
           "peers": ["codes/12-4-2.json"], "trials": 300, "seeds": [51, 52],
           "pair_depth": 10, "threads": 8, "decision": "credible: both claims held",
           "exit_code": 0, "results": [], "recorded": "2026-11-05"}
    rec.update(over)
    path.write_text(json.dumps(rec), encoding="utf-8")
    return str(path)


def test_a_d_only_gain_without_an_audit_is_refused_before_anything_is_written(npz, capsys, tmp_path):
    out = str(tmp_path / "codes")
    rc = qldpc.main(["submit", npz, "--authors", "@me", "--json", "--out", out, *FAST])
    record, _ = _record(capsys)
    assert rc == 1 and not record["ok"]
    assert record["error"]["stage"] == "peer-audit" and record["error"]["class"] == "peer-audit"
    assert PEER in record["error"]["message"]
    assert "leader_audit.py pair" in record["error"]["message"]
    assert "--trials 300" in record["error"]["message"]          # this run's own depth
    assert record["d_only_peers"] == [PEER] and record["peer_audit"] is None
    assert not os.path.exists(out)
    staged = record["staged"]
    assert staged in record["error"]["message"]
    assert staged.startswith(str(tmp_path / "staging"))
    assert json.load(open(staged))["n"] == 12


def test_a_dry_run_reports_what_the_real_run_would_refuse(npz, capsys, tmp_path):
    out = str(tmp_path / "codes")
    rc = qldpc.main(["submit", npz, "--authors", "@me", "--dry-run", "--json",
                     "--out", out, *FAST])
    record, _ = _record(capsys)
    assert rc == 0 and record["ok"] and record["stage"] == "dry-run"
    assert record["d_only_peers"] == [PEER]
    assert any("none is recorded" in p for p in record["would_refuse"])
    assert "staged" not in record and not os.path.exists(str(tmp_path / "staging"))


def test_a_credible_audit_at_depth_lets_the_submission_through(npz, capsys, tmp_path):
    out = str(tmp_path / "codes")
    audit = _audit(tmp_path / "audit.json")
    rc = qldpc.main(["submit", npz, "--authors", "@me", "--json", "--out", out,
                     "--peer-audit", audit, *FAST])
    record, err = _record(capsys)
    assert rc == 0 and record["ok"], record.get("error")
    assert record["d_only_peers"] == [PEER]
    assert record["peer_audit"] == {"path": audit, "decision": "credible: both claims held",
                                    "trials": 300, "seeds": [51, 52], "pair_depth": 10,
                                    "peers": ["codes/12-4-2.json"]}
    assert "matched-depth peer audit covers it" in err
    body = open(record["body_file"], encoding="utf-8").read()
    assert f"- Gain over {PEER} is on d alone; matched-depth peer audit" in body
    assert "300 trials per seed, seeds 51, 52, pair depth 10" in body


@pytest.mark.parametrize("over, needle", [
    ({"trials": 100}, "shallower than the 300"),
    ({"decision": "inconclusive: neither claim was reached"}, "no information"),
    ({"peers": ["codes/12-4-0.json"]}, "does not cover"),
])
def test_an_audit_that_falls_short_is_refused_with_the_reason(npz, capsys, tmp_path, over, needle):
    out = str(tmp_path / "codes")
    audit = _audit(tmp_path / "audit.json", **over)
    rc = qldpc.main(["submit", npz, "--authors", "@me", "--json", "--out", out,
                     "--peer-audit", audit, *FAST])
    record, _ = _record(capsys)
    assert rc == 1 and record["error"]["stage"] == "peer-audit"
    assert needle in record["error"]["message"]
    assert not os.path.exists(out)


def test_a_file_that_is_not_a_record_is_refused(npz, capsys, tmp_path):
    out = str(tmp_path / "codes")
    bad = tmp_path / "note.json"
    bad.write_text(json.dumps({"decision": "credible"}), encoding="utf-8")
    rc = qldpc.main(["submit", npz, "--authors", "@me", "--json", "--out", out,
                     "--peer-audit", str(bad), *FAST])
    record, _ = _record(capsys)
    assert rc == 1 and "schema is None" in record["error"]["message"]


def test_an_audit_without_a_d_only_peer_is_recorded_and_not_required(npz, capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(qldpc, "_load_board_entries", lambda quiet=False: [])
    out = str(tmp_path / "codes")
    audit = _audit(tmp_path / "audit.json")
    rc = qldpc.main(["submit", npz, "--authors", "@me", "--json", "--out", out,
                     "--peer-audit", audit, *FAST])
    record, err = _record(capsys)
    assert rc == 0 and record["d_only_peers"] == [] and record["peer_audit"]["trials"] == 300
    assert "not required" in err
