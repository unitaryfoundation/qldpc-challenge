"""The batch preflight reads a batch the way promote.py reads one candidate (issue #7450)."""

import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "kit"))

import bulk_preflight as B  # noqa: E402
import dedup_submissions  # noqa: E402


def _doc(n, k, d, rows_x, rows_z, with_prov=True):
    doc = {
        "n": n,
        "k": k,
        "code_type": "CSS",
        "checks": {"X": rows_x, "Z": rows_z},
        "distance": {
            "d": d,
            "X": {"value": d, "confidence": "upper_bound"},
            "Z": {"value": d, "confidence": "upper_bound"},
        },
    }
    if with_prov:
        doc["distance"]["X"]["witness_provenance"] = {"found_at_samples": 20000, "survived_samples": 400000}
    return doc


def _verdict(
    passed=True,
    advancing=True,
    advances=("d", "k", "n"),
    dominated=(),
    d_only=(),
    cell=("weight-4", "unrestricted"),
    dedup=None,
):
    return {
        "passed": passed,
        "gates": {
            "verify": {"ok": True},
            "refute": {"ok": passed},
            "dedup": dedup or {"exact_duplicate_of": None, "wl_equivalent_of": None},
            "novelty": {
                "board_advancing": advancing,
                "advances_by": list(advances),
                "dominated_by": list(dominated),
                "d_only_peers": list(d_only),
                "cell": list(cell),
            },
        },
    }


def _write(tmp_path, name, doc):
    p = tmp_path / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return str(p)


def _fake_gate(table):
    def gate(path, *, seed=None):
        v = table[os.path.basename(path)]
        if v == "preflight":
            return None, None, {"ok": False, "checks": {"construction": False, "packaging": True}}
        return v, path[:-5] + ".verdict.json", None

    return gate


W4 = [[0, 1, 2, 3]]


def test_every_status_is_reached_and_ordered_by_what_settles_it(tmp_path):
    docs = {
        "ready.json": _doc(20, 4, 3, W4, W4),
        # more k than ready.json at a larger n: neither dominates the other
        "tie.json": _doc(21, 5, 3, W4, W4),
        "audit.json": _doc(22, 6, 3, W4, W4),
        "dominated.json": _doc(23, 4, 3, W4, W4),
        "blocked.json": _doc(24, 4, 3, W4, W4),
        "pre.json": _doc(25, 4, 3, W4, W4),
        "dup-board.json": _doc(26, 4, 3, W4, W4),
        # the same point as ready.json, so a repeat inside the batch
        "repeat.json": _doc(20, 4, 3, [[0, 1, 2, 4]], W4),
        # dominated within the batch by big.json (same n, fewer k); big.json has
        # more k than anything else in the batch, so nothing dominates it
        "small.json": _doc(40, 7, 3, W4, W4),
        "big.json": _doc(40, 8, 3, W4, W4),
    }
    paths = {name: _write(tmp_path, name, d) for name, d in docs.items()}
    table = {
        "ready.json": _verdict(),
        "tie.json": _verdict(advances=()),
        "audit.json": _verdict(d_only=["[[22,6,2]] w=4 22-6-2.json"]),
        "dominated.json": _verdict(advancing=False, dominated=["[[20,5,3]] w=4 20-5-3.json"]),
        "blocked.json": _verdict(passed=False),
        "pre.json": "preflight",
        "dup-board.json": _verdict(dedup={"exact_duplicate_of": None, "wl_equivalent_of": "26-4-3"}),
        "repeat.json": _verdict(),
        "small.json": _verdict(),
        "big.json": _verdict(),
    }
    entries = B.preflight([paths[n] for n in docs], gate_fn=_fake_gate(table))
    status = {os.path.basename(e["path"]): e["status"] for e in entries}
    assert status == {
        "ready.json": "ready",
        "tie.json": "tie",
        "audit.json": "needs-audit",
        "dominated.json": "dominated",
        "blocked.json": "blocked",
        "pre.json": "blocked",
        "dup-board.json": "duplicate",
        "repeat.json": "duplicate",
        "small.json": "batch-dominated",
        "big.json": "ready",
    }
    by = {os.path.basename(e["path"]): e for e in entries}
    assert "leader_audit.py pair" in by["audit.json"]["reasons"][0]
    assert by["small.json"]["batch_dominated_by"] == ["[[40,8,3]] w=4 big.json"]
    assert by["repeat.json"]["duplicate_of"] == paths["ready.json"]
    assert "construction" in by["pre.json"]["reasons"][0]
    record = B.report_record(entries, accelerator=True)
    assert record["counts"] == {
        "blocked": 2,
        "duplicate": 2,
        "dominated": 1,
        "batch-dominated": 1,
        "needs-audit": 1,
        "tie": 1,
        "ready": 2,
    }
    assert all(set(r) >= {"path", "slug", "status", "reasons", "cell", "advances_by"} for r in record["candidates"])


def test_a_credible_peer_audit_beside_the_candidate_discharges_a_d_only_gain(tmp_path):
    import peer_audit

    p = _write(tmp_path, "49-7-3.json", _doc(49, 7, 3, W4, W4))
    audits = tmp_path / "audits"
    audits.mkdir()
    rec = peer_audit.record(
        p,
        ["49-7-2"],
        [{"entry": "49-7-3", "claim": 3, "d_ub": 3}, {"entry": "49-7-2", "claim": 2, "d_ub": 2}],
        "credible: both claims held at matched depth",
        trials=2_000_000,
        seeds=[51, 52],
        pair_depth=64,
    )
    (audits / "peer-audit-49-7-3.json").write_text(json.dumps(rec), encoding="utf-8")
    table = {"49-7-3.json": _verdict(d_only=["[[49,7,2]] w=4 49-7-2.json"])}
    (e,) = B.preflight([p], gate_fn=_fake_gate(table))
    assert e["status"] == "ready", e["reasons"]
    assert e["peer_audit"] == str(audits / "peer-audit-49-7-3.json")


def test_no_gate_reads_the_verdict_beside_the_file_or_says_ungated(tmp_path):
    p = _write(tmp_path, "a.json", _doc(20, 4, 3, W4, W4))
    q = _write(tmp_path, "b.json", _doc(21, 4, 3, W4, W4))
    (tmp_path / "a.verdict.json").write_text(json.dumps(_verdict()), encoding="utf-8")
    a, b = B.preflight([p, q], gate=False)
    assert a["status"] == "ready" and b["status"] == "ungated"


def test_the_file_list_skips_reports_and_repeats(tmp_path):
    for name in ("x.json", "x.verdict.json", "x.preflight.json", "x.recipe.json", "x.peer-audit.json", "y.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    got = B.candidate_files([str(tmp_path / "y.json")], str(tmp_path))
    assert [os.path.basename(p) for p in got] == ["y.json", "x.json"]


def test_main_refuses_the_shallow_gate_unless_asked(tmp_path, monkeypatch, capsys):
    p = _write(tmp_path, "a.json", _doc(20, 4, 3, W4, W4))
    monkeypatch.setattr(B, "accelerator_available", lambda: False)
    assert B.main([p]) == 2
    assert "gf2_fast" in capsys.readouterr().err
    monkeypatch.setattr(B, "gate_one", _fake_gate({"a.json": _verdict()}))
    out = tmp_path / "rec.json"
    assert B.main([p, "--allow-python-gate", "--json", str(out)]) == 0
    text = capsys.readouterr().out
    assert "ready" in text and "shallow" in text
    assert json.loads(out.read_text())["accelerator"] is False


def test_exit_status_follows_blocked_only(tmp_path, monkeypatch):
    p = _write(tmp_path, "a.json", _doc(20, 4, 3, W4, W4))
    q = _write(tmp_path, "b.json", _doc(21, 4, 3, W4, W4))
    monkeypatch.setattr(B, "accelerator_available", lambda: True)
    monkeypatch.setattr(
        B, "gate_one", _fake_gate({"a.json": _verdict(advancing=False, dominated=["x"]), "b.json": _verdict()})
    )
    assert B.main([p, q]) == 0
    monkeypatch.setattr(B, "gate_one", _fake_gate({"a.json": _verdict(passed=False), "b.json": _verdict()}))
    assert B.main([p, q]) == 1


def test_dedup_axes_reads_the_schema_field_names():
    doc = _doc(20, 4, 3, [[0, 1, 2, 3, 4, 5]], W4)
    assert dedup_submissions.axes(doc) == (20, 4, 3, 6)
    assert B.code_axes(doc) == (20, 4, 3, 6)


@pytest.mark.parametrize("w,cls", [(4, "weight-4"), (6, "weight-6"), (8, "weight-8"), (9, "weight-9plus")])
def test_weight_class_matches_the_gate(w, cls):
    assert B.weight_class(w) == cls
