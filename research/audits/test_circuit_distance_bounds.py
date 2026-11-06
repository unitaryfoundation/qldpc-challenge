"""The circuit annotator names each detector's check, round, and type from the measurements alone (#4717).

On the reference memory circuit the coordinates are the ones the builder
would have written; a flag qubit is its own check; a tool witness maps back
to the committed error instructions by its (detectors, observables) pair.
"""
import importlib.util
import os
import sys

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_ROOT, "verify"))
import circuit_tools as CT  # noqa: E402

stim = pytest.importorskip("stim")


def _module():
    spec = importlib.util.spec_from_file_location("circuit_distance_bounds_mod",
                                                  os.path.join(_HERE, "circuit_distance_bounds.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


STEANE = [[0, 1, 2, 3], [1, 2, 4, 5], [2, 3, 5, 6]]


def _steane_circuit(rounds=3, basis="Z"):
    H = np.zeros((3, 7), dtype=np.int8)
    for i, row in enumerate(STEANE):
        H[i, row] = 1
    return CT.apply_noise(CT.build_css_memory(H, H, rounds, basis=basis), 7)


def test_the_reference_memory_circuit_gets_the_builders_coordinates():
    M = _module()
    rounds = 3
    circ = _steane_circuit(rounds, "Z")
    coords = M.detector_coordinates(circ, 7, "Z")
    assert len(coords) == circ.num_detectors == 3 + 2 * 3 * (rounds - 1) + 3
    anchors, comparisons, closures = coords[:3], coords[3:3 + 6 * (rounds - 1)], coords[-3:]
    # anchors: the Z checks at round 0; closures: the same checks one round after the last extraction
    assert all(c[1] == 0 and c[2] == 0 and c[3] == M.TYPE_Z for c in anchors)
    assert all(c[2] == rounds and c[3] == M.TYPE_Z for c in closures)
    assert [c[0] for c in anchors] == [c[0] for c in closures] == [7 + 3 + i for i in range(3)]
    # comparisons: each round r >= 1 has the three X checks (type 0, shifted one round later since X is not
    # the memory basis here) then the three Z checks (type 3)
    for r in range(1, rounds):
        block = comparisons[6 * (r - 1):6 * r]
        assert [c[2] for c in block] == [r + 1] * 3 + [r] * 3
        assert [c[3] for c in block] == [M.TYPE_X] * 3 + [M.TYPE_Z] * 3
        assert [c[0] for c in block] == list(range(7, 13))
    assert {c[3] for c in coords if c[2] == 0} == {M.TYPE_Z}, "only the memory basis sits at round 0"
    # the annotated circuit is the same circuit with coordinates, and stim reads them back
    ann = M.annotate(circ, 7, "Z")
    assert ann.num_detectors == circ.num_detectors and ann.num_observables == circ.num_observables
    got = ann.get_detector_coordinates()
    assert [tuple(int(x) for x in got[i]) for i in range(len(coords))] == coords
    assert str(ann.detector_error_model(decompose_errors=False)).count("error(") == \
        str(circ.detector_error_model(decompose_errors=False)).count("error(")


def test_a_flag_is_its_own_check_and_takes_the_type_the_policy_says():
    M = _module()
    # a Z check (ancilla 7) on data 0..3 with a flag (qubit 8) measured each round, two rounds
    c = stim.Circuit()
    c.append("R", [0, 1, 2, 3])
    for _ in range(2):
        c.append("R", [7])
        c.append("RX", [8])
        c.append("CX", [0, 7, 8, 7, 1, 7, 2, 7, 8, 7, 3, 7])
        c.append("MX", [8])
        c.append("M", [7])
    c.append("M", [0, 1, 2, 3])
    c.append("DETECTOR", [stim.target_rec(-7)])                               # Z check, round 0
    c.append("DETECTOR", [stim.target_rec(-8)])                               # flag, round 0
    c.append("DETECTOR", [stim.target_rec(-6)])                               # flag, round 1
    c.append("DETECTOR", [stim.target_rec(-5), stim.target_rec(-7)])          # Z check, rounds 1 vs 0
    c.append("DETECTOR", [stim.target_rec(-1), stim.target_rec(-2), stim.target_rec(-3), stim.target_rec(-4),
                          stim.target_rec(-5)])                               # closure
    roles = M.ancilla_roles(c, 4)
    assert roles[7] == ("check", "Z") and roles[8] == ("flag", "X", 7)
    by_basis = M.detector_coordinates(c, 4, "Z", "basis")
    assert by_basis == [(7, 0, 0, M.TYPE_Z), (8, 0, 1, M.TYPE_X), (8, 0, 2, M.TYPE_X), (7, 0, 1, M.TYPE_Z),
                        (7, 0, 2, M.TYPE_Z)], "the X-typed flag is shifted one round later"
    assert [c_[3] for c_ in M.detector_coordinates(c, 4, "Z", "check")] == [M.TYPE_Z] * 5
    assert [c_[2:] for c_ in M.detector_coordinates(c, 4, "X", "memory")] == \
        [(1, M.TYPE_Z), (0, M.TYPE_X), (1, M.TYPE_X), (2, M.TYPE_Z), (3, M.TYPE_Z)]


def test_a_tool_witness_maps_back_to_the_committed_error_instructions(tmp_path):
    M = _module()
    circ = _steane_circuit(2, "Z")
    dem = CT.derive_dem(circ)
    cols = CT.dem_columns(dem)
    # write the tool's full problem as it would: the same mechanisms, here in a shuffled order
    order = list(range(len(cols)))[::-1]
    for name, part in (("H", 0), ("L", 1)):
        nnz = sum(len(cols[j][part]) for j in order)
        rows = dem.num_detectors if part == 0 else dem.num_observables
        with open(tmp_path / f"full.{name}.mtx", "w", encoding="utf-8") as f:
            f.write("%%MatrixMarket matrix coordinate pattern general\n")
            f.write(f"{rows} {len(order)} {nnz}\n")
            for c_, j in enumerate(order):
                for r in sorted(cols[j][part]):
                    f.write(f"{r + 1} {c_ + 1}\n")
    witness_cols = [0, 5]                         # tool columns -> committed indices order[0], order[5]
    mapped = M.map_witness(str(tmp_path), witness_cols, dem)
    assert mapped == sorted(order[c] for c in witness_cols)
    assert M.map_witness(str(tmp_path), [len(order) - 1], dem) == [order[-1]]
