"""Schedule diagnostics of the committed circuits (issue #5807).

The code page shows, for an entry that ships memory circuits, the qubits the
circuits address, the parallel gate layers, the per-round layer and two-qubit
gate counts, the mean two-qubit gates per two-qubit layer, and qubits times
layers, all computed from the .stim files at build time and never ranked. The
circuits here are built with the verifier's reference skeleton and noise
recipe, so nothing depends on a committed circuit a refutation could later
remove.
"""

import importlib.util
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "verify"))
import circuit_tools as ct  # noqa: E402


def load_site_build():
    spec = importlib.util.spec_from_file_location(
        "site_build_schedule", os.path.join(ROOT, "site", "build.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture(name):
    with open(os.path.join(ROOT, "verify", "fixtures", name)) as f:
        return json.load(f)


def _matrix(supports, n):
    H = np.zeros((len(supports), n), dtype=np.int8)
    for i, sup in enumerate(supports):
        H[i, sup] = 1
    return H


def _memory_pair(doc, rounds):
    """Build the canonical noisy X- and Z-basis memory circuits of a CSS doc."""
    n = doc["n"]
    HX, HZ = _matrix(doc["checks"]["X"], n), _matrix(doc["checks"]["Z"], n)
    return {side: ct.apply_noise(ct.build_css_memory(HX, HZ, rounds, basis=side), n)
            for side in ("X", "Z")}


def test_reference_skeleton_of_the_422_code():
    """[[4,2,2]]: one weight-4 check per side.

    The edge coloring needs four CX layers per side and a round is RX, 4 CX,
    MX, R, 4 CX, M.
    """
    build = load_site_build()
    H = np.ones((1, 4), dtype=np.int8)
    rounds = 2
    skel = ct.build_css_memory(H, H, rounds, basis="Z")
    for circuit in (skel, ct.apply_noise(skel, 4)):
        s = build.schedule_of_circuit(circuit, rounds)
        assert s["qubits"] == 6
        assert s["layers"] == 2 + rounds * 12
        assert s["layers_per_round"] == 12
        assert s["two_qubit_layers"] == rounds * 8
        assert s["two_qubit_layers_per_round"] == 8
        assert s["two_qubit_gates"] == rounds * 8
        assert s["two_qubit_gates_per_round"] == 8
        assert s["max_parallel"] == 1 and s["mean_parallel"] == 1
        assert s["qubit_layers"] == 6 * (2 + rounds * 12)


def test_noise_and_annotations_do_not_count_as_layers_or_gates():
    build = load_site_build()
    import stim
    c = stim.Circuit("""
        R 0 1 2
        X_ERROR(0.01) 0 1 2
        TICK
        DEPOLARIZE1(0.01) 0 1 2
        TICK
        CX 0 1
        DEPOLARIZE2(0.01) 0 1
        TICK
        TICK
        M 0 1 2
        DETECTOR rec[-1]
        OBSERVABLE_INCLUDE(0) rec[-2]
    """)
    s = build.schedule_of_circuit(c, 1)
    assert s["layers"] == 3          # R, CX, M; the noise-only and empty segments are not layers
    assert s["two_qubit_layers"] == 1 and s["two_qubit_gates"] == 1
    assert s["layers_per_round"] == 1
    assert s["qubits"] == 3 and s["qubit_layers"] == 9


def test_per_round_figures_keep_a_decimal_when_rounds_do_not_divide():
    build = load_site_build()
    import stim
    c = stim.Circuit("R 0 1\nTICK\nCX 0 1\nTICK\nCX 0 1\nTICK\nCX 0 1\nTICK\nM 0 1")
    s = build.schedule_of_circuit(c, 2)
    assert s["two_qubit_layers_per_round"] == 1.5
    assert build.schedule_of_circuit(c, None)["two_qubit_layers_per_round"] is None


def test_schedule_table_collapses_equal_bases_and_keeps_unequal_ones():
    build = load_site_build()
    row = {"qubits": 144, "layers": 56, "layers_per_round": 9,
           "two_qubit_layers_per_round": 7, "two_qubit_gates_per_round": 432,
           "mean_parallel": 61.7, "qubit_layers": 8064}
    one = build.schedule_table({"X": row, "Z": dict(row)})
    assert one.count("<tr>") == 2 and "<td>X, Z</td>" in one
    assert "<td class=num>8,064</td>" in one and "<td class=num>61.7</td>" in one
    other = dict(row, layers=57, layers_per_round=9.2)
    two = build.schedule_table({"X": row, "Z": other})
    assert two.count("<tr>") == 3 and "<td>X</td>" in two and "<td>Z</td>" in two
    assert "<td class=num>9.2</td>" in two


def test_code_page_shows_the_schedule_of_the_committed_circuits(tmp_path):
    build = load_site_build()
    doc = _fixture("72-6-6.json")
    doc["schema_version"] = "0.5"   # a circuit block needs 0.5 or later
    rounds = doc["distance"]["d"]
    side = {"value": 6, "confidence": "upper_bound", "witness": [0, 1, 2, 3, 4, 5]}
    doc["circuit"] = {"d_circ": {"X": side, "Z": dict(side)},
                      "rounds": rounds, "stim_version": "1.16.0"}
    plain = _fixture("17-1-7.json")
    (tmp_path / "codes").mkdir()
    for slug, d in (("72-6-6", doc), ("17-1-7", plain)):
        with open(tmp_path / "codes" / f"{slug}.json", "w") as f:
            json.dump(d, f)
    cdir = tmp_path / "circuits" / "72-6-6"
    cdir.mkdir(parents=True)
    pair = _memory_pair(doc, rounds)
    for s, circuit in pair.items():
        circuit.to_file(str(cdir / f"memory_{s.lower()}.stim"))
    build.ROOT = str(tmp_path)
    build.DOCS = str(tmp_path / "docs")
    build.CERTS = str(tmp_path / "certs")
    build.build()

    with open(tmp_path / "docs" / "codes" / "72-6-6.html", encoding="utf-8") as f:
        page = f.read()
    want = build.schedule_of_circuit(pair["Z"], rounds)
    assert want["qubits"] == 72 + 36 + 37
    assert '<table class="lerpts sched">' in page
    assert "<td>X, Z</td>" in page       # same skeleton, read out in the other basis
    assert f'<td class=num>{want["qubits"]}</td>' in page
    assert f'<td class=num>{want["layers"]}</td>' in page
    assert f'<td class=num>{want["two_qubit_layers_per_round"]}</td>' in page
    assert f'<td class=num>{want["two_qubit_gates_per_round"]}</td>' in page
    assert f'<td class=num>{want["qubit_layers"]:,}</td>' in page
    assert "What is the schedule table on a code page?" in open(
        tmp_path / "docs" / "faq.html", encoding="utf-8").read()
    # the depth travels with d_circ (issue #6834): on the code page's d_circ
    # line and in the board row's gear chip
    depth = want["layers_per_round"]
    assert f"&middot; {depth} layers per round" in page
    with open(tmp_path / "docs" / "index.html", encoding="utf-8") as f:
        board = f.read()
    assert f"&#9881;6 &middot; {depth}/rd</span>" in board
    assert f"{depth} TICK layers per round" in board

    # the entry without circuits has no schedule section
    with open(tmp_path / "docs" / "codes" / "17-1-7.html", encoding="utf-8") as f:
        assert "lerpts sched" not in f.read()


def test_missing_circuit_files_give_no_diagnostics(tmp_path):
    build = load_site_build()
    build.ROOT = str(tmp_path)
    doc = {"circuit": {"rounds": 3}}
    assert build.schedule_diagnostics(doc, "nothing-here") == {}
    assert build.schedule_diagnostics({}, "nothing-here") == {}


def test_schedule_depth_label_is_the_deeper_basis():
    build = load_site_build()
    assert build.schedule_depth_label({"X": {"layers_per_round": 10}, "Z": {"layers_per_round": 12}}) == 12
    assert build.schedule_depth_label({"X": {"layers_per_round": 7.5}}) == 7.5
    assert build.schedule_depth_label({"X": {"layers_per_round": None}}) is None
    assert build.schedule_depth_label({}) is None
