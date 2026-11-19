"""The LER backfill queue opens shallow schedules first (issue #6834).

An entry without a measured rate is queued by TICK layers per round of its
committed memory circuit, shallowest first; one with points is listed apart,
deepest first, with its worst rate at p = 0.001. Fixtures are written to a
temporary codes/ and circuits/ tree, so no board file is read.
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import ler_priority as LP  # noqa: E402


def _doc(n, k, d, d_circ=None, rounds=None, ler=None):
    doc = {"n": n, "k": k, "distance": {"d": d}, "checks": {"X": [], "Z": []}}
    if d_circ is not None:
        side = {"value": d_circ, "confidence": "upper_bound", "witness": list(range(d_circ))}
        doc["circuit"] = {"d_circ": {"X": side, "Z": dict(side)}, "rounds": rounds or d,
                          "stim_version": "1.16.0"}
        if ler is not None:
            doc["circuit"]["ler"] = ler
    return doc


def _stim(ticks):
    return "R 0 1\n" + "H 0\nTICK\n" * ticks + "M 0 1\n"


def _tree(tmp_path):
    codes, circuits = tmp_path / "codes", tmp_path / "circuits"
    codes.mkdir()
    circuits.mkdir()
    entries = {
        "30-2-6": (_doc(30, 2, 6, d_circ=6, rounds=6), 6 * 30),      # deep: 30 per round
        "40-4-6": (_doc(40, 4, 6, d_circ=6, rounds=6), 6 * 6),       # shallow: 6 per round
        "50-4-6": (_doc(50, 4, 6, d_circ=5, rounds=6), 6 * 6),       # shallow, lower d_circ
        "20-2-4": (_doc(20, 2, 4, d_circ=4, rounds=4, ler={
            "X": [{"p": 0.001, "ler_per_round": 0.01}, {"p": 0.005, "ler_per_round": 0.2}],
            "Z": [{"p": 0.001, "ler_per_round": 0.03}]}), 4 * 20),   # measured, 20 per round
        "10-1-3": (_doc(10, 1, 3), None),                            # no circuit
        "60-2-6": (_doc(60, 2, 6, d_circ=6, rounds=6), None),        # circuit, file missing
    }
    for slug, (doc, ticks) in entries.items():
        with open(codes / f"{slug}.json", "w") as fh:
            json.dump(doc, fh)
        if ticks is not None:
            (circuits / slug).mkdir()
            (circuits / slug / "memory_z.stim").write_text(_stim(ticks))
            (circuits / slug / "memory_x.stim").write_text(_stim(ticks + 6))
    return str(codes), str(circuits)


def test_rows_carry_depth_points_and_worst_rate(tmp_path):
    codes, circuits = _tree(tmp_path)
    rows = {r["slug"]: r for r in LP.entries(codes, circuits)}
    assert set(rows) == {"30-2-6", "40-4-6", "50-4-6", "20-2-4", "60-2-6"}, "entries without circuits are not rows"
    assert rows["30-2-6"]["ticks_per_round"] == 30.0
    assert rows["40-4-6"]["ticks_per_round"] == 6.0
    assert rows["60-2-6"]["ticks_per_round"] is None
    assert rows["20-2-4"]["points"] == 3
    assert rows["20-2-4"]["worst_ler_per_round_at_0.001"] == 0.03
    assert rows["40-4-6"]["worst_ler_per_round_at_0.001"] is None
    x_rows = {r["slug"]: r for r in LP.entries(codes, circuits, basis="x")}
    assert x_rows["40-4-6"]["ticks_per_round"] == 7.0


def test_queue_is_shallowest_first_then_highest_d_circ_and_unknown_last(tmp_path):
    codes, circuits = _tree(tmp_path)
    q = [r["slug"] for r in LP.queue(LP.entries(codes, circuits))]
    assert q == ["40-4-6", "50-4-6", "30-2-6", "60-2-6"]


def test_queue_filters(tmp_path):
    codes, circuits = _tree(tmp_path)
    rows = LP.entries(codes, circuits)
    assert [r["slug"] for r in LP.queue(rows, max_depth=20)] == ["40-4-6", "50-4-6"], "unknown depth is not under a cap"
    assert [r["slug"] for r in LP.queue(rows, min_d_circ=6)] == ["40-4-6", "30-2-6", "60-2-6"]
    assert [r["slug"] for r in LP.queue(rows, limit=1)] == ["40-4-6"]


def test_command_names_the_measurement_tool_and_the_grid():
    cmd = LP.command({"slug": "40-4-6"})
    assert cmd == ("uv run --extra research python verify/ler_measure.py codes/40-4-6.json "
                   "--p 0.01 0.005 0.002 0.001")


def test_main_prints_the_queue_the_commands_and_the_measured_list(tmp_path, capsys):
    codes, circuits = _tree(tmp_path)
    out_json = tmp_path / "q.json"
    assert LP.main(["--codes-dir", codes, "--circuits-dir", circuits, "--max-depth", "20",
                    "--json", str(out_json)]) == 0
    out = capsys.readouterr().out
    assert "5 entries with circuits, 4 without a measured rate; 2 queued at depth <= 20" in out
    assert out.index("40-4-6") < out.index("50-4-6")
    payload = json.load(open(out_json))
    assert [r["slug"] for r in payload["rows"]] == ["40-4-6", "50-4-6"]

    assert LP.main(["--codes-dir", codes, "--circuits-dir", circuits, "--commands", "--limit", "1"]) == 0
    out = capsys.readouterr().out
    assert "verify/ler_measure.py codes/40-4-6.json --p 0.01 0.005 0.002 0.001" in out

    assert LP.main(["--codes-dir", codes, "--circuits-dir", circuits, "--measured"]) == 0
    out = capsys.readouterr().out
    assert "1 measured entries, deepest first" in out
    assert "20-2-4" in out and "0.030000" in out


def test_ticks_per_round_handles_missing_files_and_bad_rounds(tmp_path):
    assert LP.ticks_per_round(str(tmp_path / "nope.stim"), 3) is None
    f = tmp_path / "c.stim"
    f.write_text(_stim(9))
    assert LP.ticks_per_round(str(f), 3) == 3.0
    assert LP.ticks_per_round(str(f), 0) is None
    assert LP.ticks_per_round(str(f), None) is None
