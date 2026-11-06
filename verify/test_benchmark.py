"""The optional Tier B benchmark block of issues #4601 and #4603.

Schema 0.6, the verifier's cross-field checks and computed summary, and the
authorship binding for a donated comparison.
"""
import copy

import check_authorship as A
import qldpc_verify as V
import validation_gate as G


def _block(**over):
    b = {"hardware_track": "2d-nearest-neighbor",
         "noise_model": {"kind": "circuit-level-depolarizing", "p": 0.001},
         "surface_baseline": {"slug": "25-1-5"},
         "decoder": {"name": "pymatching", "implementation": "pymatching 2.2.1"},
         "resources": {"candidate": {"data_qubits": 7, "ancilla_qubits": 6,
                                     "total_qubits": 13, "rounds": 3},
                       "baseline": {"data_qubits": 25, "ancilla_qubits": 24,
                                    "total_qubits": 49, "rounds": 5}},
         "logical_error_rate": {"target": 0.01, "candidate": 0.004, "baseline": 0.003,
                                "per": "round"},
         "status": "documented",
         "method": "test fixture: the numbers are illustrative"}
    b.update(over)
    return b


def _doc(**over):
    doc = G.steane()
    doc["schema_version"] = "0.6"
    doc["benchmark"] = _block(**over)
    return doc


def _failed(rep):
    return {c["check"]: c["detail"] for c in rep["checks"] if not c["ok"]}


def test_a_consistent_block_passes_and_is_summarized():
    rep = V.verify(_doc(), refute=False)
    assert rep["ok"], _failed(rep)
    b = rep["computed"]["benchmark"]
    assert b["baseline"] == {"slug": "25-1-5", "n": 25, "k": 1}
    assert (b["candidate_total_qubits"], b["baseline_total_qubits"]) == (13, 49)
    assert b["meets_target"] and b["fewer_qubits"] and b["beats_baseline"]
    assert b["status"] == "documented"


def test_the_block_requires_schema_0_6():
    doc = _doc()
    doc["schema_version"] = "0.5"
    assert "schema_valid" in _failed(V.verify(doc, refute=False))
    assert V.structure_errors(doc)
    doc["schema_version"] = "0.7"
    assert V.verify(doc, refute=False)["ok"]


def test_entries_without_the_block_are_untouched():
    rep = V.verify(G.steane(), refute=False)
    assert rep["ok"]
    assert "benchmark" not in rep["computed"]
    assert not any(c["check"].startswith("benchmark_") for c in rep["checks"])


def test_candidate_data_qubits_must_be_n():
    doc = _doc()
    doc["benchmark"]["resources"]["candidate"].update(data_qubits=9, total_qubits=15)
    assert "benchmark_candidate_data_qubits" in _failed(V.verify(doc, refute=False))


def test_totals_must_add_up():
    doc = _doc()
    doc["benchmark"]["resources"]["baseline"]["total_qubits"] = 50
    failed = _failed(V.verify(doc, refute=False))
    assert "benchmark_qubit_totals" in failed and "baseline" in failed["benchmark_qubit_totals"]


def test_baseline_slug_must_be_on_the_board():
    failed = _failed(V.verify(_doc(surface_baseline={"slug": "999-1-3"}), refute=False))
    assert "benchmark_baseline_on_board" in failed
    assert "benchmark_baseline_data_qubits" not in failed   # nothing to compare against


def test_baseline_must_encode_at_least_k():
    doc = G.css_doc("[[4,2,2]] (benchmark test)", [[1, 1, 1, 1]], [[1, 1, 1, 1]], 2,
                    construction="the four-qubit code", confidence="upper_bound")
    doc["schema_version"] = "0.6"
    doc["benchmark"] = _block(resources={"candidate": {"data_qubits": 4, "ancilla_qubits": 2},
                                         "baseline": {"data_qubits": 25, "ancilla_qubits": 24}})
    failed = _failed(V.verify(doc, refute=False))
    assert "benchmark_baseline_k" in failed, failed


def test_patches_baseline_counts_k_d_squared_data_qubits():
    good = _doc(surface_baseline={"patches": {"d": 5}},
                resources={"candidate": {"data_qubits": 7, "ancilla_qubits": 6},
                           "baseline": {"data_qubits": 25, "ancilla_qubits": 24}})
    rep = V.verify(good, refute=False)
    assert rep["ok"], _failed(rep)
    assert rep["computed"]["benchmark"]["baseline"] == {"patches": {"count": 1, "d": 5},
                                                         "n": 25, "k": 1}
    bad = copy.deepcopy(good)
    bad["benchmark"]["resources"]["baseline"]["data_qubits"] = 24
    assert "benchmark_baseline_data_qubits" in _failed(V.verify(bad, refute=False))


def test_the_schema_holds_the_vocabulary_and_ranges():
    for over in ({"surface_baseline": {"slug": "25-1-5", "patches": {"d": 5}}},
                 {"status": "verified"},
                 {"hardware_track": "3d"},
                 {"logical_error_rate": {"target": 0.6, "candidate": 0.004, "per": "round"}},
                 {"noise_model": {"kind": "circuit-level-depolarizing", "p": 0}},
                 {"method": ""}):
        assert "schema_valid" in _failed(V.verify(_doc(**over), refute=False)), over


def test_a_non_author_may_add_a_first_benchmark_block():
    base = G.steane()
    new = _doc(contributed_by={"by": ["@bench"], "date": "2026-11-04"})
    ok, why = A.benchmark_binding("bench", base, new)
    assert ok, why
    assert A.evident_binding(base, new) == "benchmark"
    assert V.verify(new, refute=False)["ok"]
    other = copy.deepcopy(new)
    other["k"] = 2
    assert not A.benchmark_binding("bench", base, other)[0]
    assert not A.benchmark_binding("someone", base, new)[0]
    assert not A.benchmark_binding("bench", new, new)[0]   # replacing one stays with the authors
