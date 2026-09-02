"""Regression tests for the --dry-run preview (issue #637).

The old preview printed a raw 600-character prefix of the JSON, which
truncated mid-field and never reached the distance block on a board-sized
code. The preview must now be a summary naming the output path, and the full
document must remain available behind --json.
"""

import json

import qldpc


def _doc():
    return {
        "schema_version": "0.1",
        "name": "[[7,1,3]]",
        "code_type": "CSS",
        "n": 7,
        "k": 1,
        "checks": {"X": [[0, 1, 2]], "Z": [[0, 3, 4]]},
        "distance": {
            "d": 3,
            "X": {"value": 3, "confidence": "upper_bound", "witness": [0, 1, 2]},
            "Z": {"value": 3, "confidence": "upper_bound", "witness": [0, 3, 4]},
        },
        "provenance": {
            "authors": ["@me"],
            "construction": "steane construction",
            "origin": "submission",
            "date": "2026-09-02",
        },
        "family": "topological",
    }


def _report():
    return {
        "ok": True,
        "checks": [],
        "computed": {
            "n": 7,
            "k": 1,
            "max_check_weight": 3,
            "weight_class": "weight-4",
            "locality_class": "unrestricted",
        },
        "earned_distance": {"d": {"value": 3, "tier": "upper_bound"}},
    }


def test_dry_run_prints_summary_naming_output_path(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(qldpc, "load_checks", lambda _path: (None, None, None, None))
    monkeypatch.setattr(qldpc, "build_submission", lambda _hx, _hz, args: _doc())
    monkeypatch.setattr(qldpc, "verify", lambda _doc, refute: _report())
    out = str(tmp_path / "codes")

    rc = qldpc.main(["submit", "x.npz", "--authors", "@me", "--dry-run", "--out", out])

    assert rc == 0
    text = capsys.readouterr().out
    assert f"--dry-run: would write {out}/7-1-3.json" in text
    # the fields a contributor is deciding on
    assert "[[7,1,3]]" in text
    assert "kd^2/n" in text
    assert "max weight 3" in text
    assert "unrestricted" in text
    assert "upper_bound" in text
    assert "witness found" in text
    assert "authors" in text and "@me" in text
    assert "topological" in text
    # no truncated field names: the old prefix printed a bare " ..." marker
    assert " ..." not in text
    # nothing is written
    import os

    assert not os.path.exists(out)


def test_dry_run_track_cells_are_labeled(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(qldpc, "load_checks", lambda _path: (None, None, None, None))
    monkeypatch.setattr(qldpc, "build_submission", lambda _hx, _hz, args: _doc())
    monkeypatch.setattr(qldpc, "verify", lambda _doc, refute: _report())
    out = str(tmp_path / "codes")

    qldpc.main(["submit", "x.npz", "--authors", "@me", "--dry-run", "--out", out])

    text = capsys.readouterr().out
    # weight-4 / unrestricted belongs to the nested grid: every weight class
    # cell (<=4, <=6, <=8, any) and the unrestricted locality cell
    assert "weight ≤ 4" in text
    assert "unrestricted" in text


def test_dry_run_json_flag_prints_full_document(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(qldpc, "load_checks", lambda _path: (None, None, None, None))
    monkeypatch.setattr(qldpc, "build_submission", lambda _hx, _hz, args: _doc())
    monkeypatch.setattr(qldpc, "verify", lambda _doc, refute: _report())
    out = str(tmp_path / "codes")

    qldpc.main(["submit", "x.npz", "--authors", "@me", "--dry-run", "--json", "--out", out])

    text = capsys.readouterr().out
    # the full document, parseable and complete (the old prefix cut mid-key)
    start = text.index("{")
    doc = json.loads(text[start:])
    assert doc["distance"]["Z"]["witness"] == [0, 3, 4]


def test_summary_is_screen_sized_for_a_board_scale_code():
    doc = _doc()
    doc["name"] = "[[684,12,81]]"
    doc["n"], doc["k"] = 684, 12
    doc["distance"]["d"] = 81
    doc["checks"] = {"X": [[0, 1]] * 342, "Z": [[0, 1]] * 342}
    doc["distance"]["X"] = {
        "value": 81,
        "confidence": "upper_bound",
        "witness": list(range(81)),
    }
    report = _report()
    report["computed"].update(n=684, k=12, max_check_weight=8)
    report["earned_distance"]["d"] = {"value": 81, "tier": "upper_bound"}

    text = qldpc.dry_run_summary(doc, report, "codes/684-12-81.json")

    lines = text.splitlines()
    assert len(lines) <= 12
    # the distance block must survive on a board-sized code
    assert "d <= 81" in text
    assert "[[684,12,81]]" in text
