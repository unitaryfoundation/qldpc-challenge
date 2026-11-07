"""The optional Tier C architecture block of issues #4601 and #4674.

Schema 0.7, the verifier's cross-field checks and computed summary, the tie
to the benchmark block, and the authorship binding for a donated block.
"""
import copy

import check_authorship as A
import qldpc_verify as V
import validation_gate as G
from test_benchmark import _block as _benchmark_block


def _gadget(**over):
    g = {"kind": "lattice-surgery",
         "operation": "joint Z Z measurement of the logical qubits of two blocks",
         "blocks": 2, "fault_distance": 3,
         "resources": {"data_qubits": 17, "ancilla_qubits": 14, "total_qubits": 31,
                       "rounds": 3},
         "logical_error_rate": 0.01,
         "reference": "test fixture"}
    g.update(over)
    return g


def _arch(**over):
    a = {"gadgets": [_gadget()],
         "magic_states": {"protocol": "distillation", "state": "T",
                          "qubits_per_factory": 60, "rounds_per_state": 30,
                          "input_error_rate": 0.01, "output_error_rate": 1e-5},
         "algorithm_estimate": {
             "workload": "test workload: 10 logical qubits and 1000 T gates",
             "logical_qubits": 10, "non_clifford_count": 1000,
             "logical_error_rate_target": 0.01,
             "candidate": {"code_blocks": 10, "physical_qubits": 200, "factories": 2,
                           "runtime_rounds": 30000, "spacetime_volume": 6e6},
             "baseline": {"code_blocks": 10, "physical_qubits": 600, "factories": 2,
                          "runtime_rounds": 30000, "spacetime_volume": 1.8e7}},
         "status": "documented",
         "method": "test fixture: the numbers are illustrative"}
    a.update(over)
    return a


def _doc(benchmark=None, **over):
    """Build the Steane code (n = 7, k = 1, d = 3) with a benchmark block on 25-1-5 and an architecture block."""
    doc = G.steane()
    doc["schema_version"] = "0.7"
    doc["benchmark"] = benchmark or _benchmark_block()
    doc["architecture"] = _arch(**over)
    return doc


def _failed(rep):
    return {c["check"]: c["detail"] for c in rep["checks"] if not c["ok"]}


def _estimate(**over):
    est = copy.deepcopy(_arch()["algorithm_estimate"])
    est.update(over)
    return est


def test_a_consistent_block_passes_and_is_summarized():
    rep = V.verify(_doc(), refute=False)
    assert rep["ok"], _failed(rep)
    a = rep["computed"]["architecture"]
    assert a["status"] == "documented"
    assert a["gadgets"] == [{"kind": "lattice-surgery",
                             "operation": "joint Z Z measurement of the logical qubits of two blocks",
                             "blocks": 2, "fault_distance": 3, "total_qubits": 31}]
    assert a["magic_states"] == {"protocol": "distillation", "state": "T",
                                 "output_error_rate": 1e-5}
    est = a["algorithm_estimate"]
    assert est["baseline_block"] == {"n": 25, "k": 1}
    assert (est["candidate_physical_qubits"], est["baseline_physical_qubits"]) == (200, 600)
    assert est["qubit_ratio"] == 3.0 and est["spacetime_ratio"] == 3.0
    assert est["fewer_qubits"] and est["less_spacetime"]
    assert rep["computed"]["benchmark"]["beats_baseline"]   # the Tier B block still reads


def test_the_block_requires_schema_0_7():
    doc = _doc()
    doc["schema_version"] = "0.6"
    assert "schema_valid" in _failed(V.verify(doc, refute=False))
    assert any("0.7" in e for e in V.structure_errors(doc))


def test_the_block_requires_a_benchmark_block():
    doc = _doc()
    del doc["benchmark"]
    assert "schema_valid" in _failed(V.verify(doc, refute=False))
    assert any("benchmark" in e for e in V.structure_errors(doc))


def test_the_block_needs_at_least_one_part():
    doc = _doc()
    for part in ("gadgets", "magic_states", "algorithm_estimate"):
        del doc["architecture"][part]
    assert "schema_valid" in _failed(V.verify(doc, refute=False))
    assert V.structure_errors(doc)
    one = _doc()
    del one["architecture"]["gadgets"]
    del one["architecture"]["magic_states"]
    rep = V.verify(one, refute=False)
    assert rep["ok"], _failed(rep)
    assert set(rep["computed"]["architecture"]) == {"status", "algorithm_estimate"}


def test_entries_without_the_block_are_untouched():
    doc = G.steane()
    doc["schema_version"] = "0.6"
    doc["benchmark"] = _benchmark_block()
    rep = V.verify(doc, refute=False)
    assert rep["ok"]
    assert "architecture" not in rep["computed"]
    assert not any(c["check"].startswith("architecture_") for c in rep["checks"])


def test_a_gadget_cannot_claim_a_fault_distance_above_d():
    failed = _failed(V.verify(_doc(gadgets=[_gadget(fault_distance=4)]), refute=False))
    assert "architecture_gadget_fault_distance" in failed
    assert "joint Z Z measurement" in failed["architecture_gadget_fault_distance"]


def test_a_gadget_counts_the_data_qubits_of_its_blocks():
    short = _gadget(blocks=3, resources={"data_qubits": 20, "ancilla_qubits": 1})
    assert "architecture_gadget_data_qubits" in _failed(V.verify(_doc(gadgets=[short]), refute=False))
    exact = _gadget(blocks=3, resources={"data_qubits": 21, "ancilla_qubits": 1})
    rep = V.verify(_doc(gadgets=[exact]), refute=False)
    assert rep["ok"], _failed(rep)


def test_gadget_totals_must_add_up():
    bad = _gadget(resources={"data_qubits": 17, "ancilla_qubits": 14, "total_qubits": 30})
    assert "architecture_qubit_totals" in _failed(V.verify(_doc(gadgets=[bad]), refute=False))


def test_a_partner_code_must_be_on_the_board():
    on = _gadget(kind="code-switching", operation="switch to the partner and back",
                 blocks=1, partner="25-1-5",
                 resources={"data_qubits": 32, "ancilla_qubits": 10})
    rep = V.verify(_doc(gadgets=[on]), refute=False)
    assert rep["ok"], _failed(rep)
    assert "architecture_partner_on_board" in {c["check"] for c in rep["checks"]}
    off = dict(on, partner="999-1-3")
    failed = _failed(V.verify(_doc(gadgets=[off]), refute=False))
    assert "architecture_partner_on_board" in failed and "999-1-3" in failed["architecture_partner_on_board"]
    rep = V.verify(_doc(), refute=False)            # no partner: the check is not recorded
    assert "architecture_partner_on_board" not in {c["check"] for c in rep["checks"]}


def test_distillation_must_lower_the_error_rate():
    ms = {"protocol": "distillation", "state": "T", "input_error_rate": 0.01,
          "output_error_rate": 0.01}
    assert "architecture_magic_state_gain" in _failed(V.verify(_doc(magic_states=ms), refute=False))
    injection = {"protocol": "injection", "state": "T", "input_error_rate": 0.001,
                 "output_error_rate": 0.01}            # injection adds error, and may
    rep = V.verify(_doc(magic_states=injection), refute=False)
    assert rep["ok"], _failed(rep)
    assert "architecture_magic_state_gain" not in {c["check"] for c in rep["checks"]}


def test_each_side_holds_its_logical_qubits_in_enough_blocks():
    est = _estimate(candidate={"code_blocks": 9, "physical_qubits": 200})   # 9 x k=1 < 10
    failed = _failed(V.verify(_doc(algorithm_estimate=est), refute=False))
    assert "architecture_blocks_cover_logical_qubits" in failed
    assert "candidate: 9 blocks x k=1 < 10" in failed["architecture_blocks_cover_logical_qubits"]
    est = _estimate(baseline={"code_blocks": 9, "physical_qubits": 600})    # 9 x k_b=1 < 10
    failed = _failed(V.verify(_doc(algorithm_estimate=est), refute=False))
    assert "baseline: 9 blocks x k=1 < 10" in failed["architecture_blocks_cover_logical_qubits"]
    hybrid = _estimate(candidate={"code_blocks": 4, "logical_qubits": 4, "physical_qubits": 200})
    rep = V.verify(_doc(algorithm_estimate=hybrid), refute=False)   # the rest live elsewhere
    assert rep["ok"], _failed(rep)


def test_each_side_counts_at_least_the_data_qubits_of_its_blocks():
    est = _estimate(candidate={"code_blocks": 10, "physical_qubits": 69})   # 10 x n=7 = 70
    failed = _failed(V.verify(_doc(algorithm_estimate=est), refute=False))
    assert "candidate: 69 < 10 blocks x n=7" in failed["architecture_physical_qubits_cover_blocks"]
    est = _estimate(baseline={"code_blocks": 10, "physical_qubits": 249})   # 10 x 25
    failed = _failed(V.verify(_doc(algorithm_estimate=est), refute=False))
    assert "baseline: 249 < 10 blocks x n=25" in failed["architecture_physical_qubits_cover_blocks"]


def test_the_baseline_block_follows_the_benchmark_baseline_or_the_patch_override():
    patches = _benchmark_block(surface_baseline={"patches": {"d": 5}},
                               resources={"candidate": {"data_qubits": 7, "ancilla_qubits": 6},
                                          "baseline": {"data_qubits": 25, "ancilla_qubits": 24}})
    rep = V.verify(_doc(benchmark=patches), refute=False)
    assert rep["ok"], _failed(rep)
    assert rep["computed"]["architecture"]["algorithm_estimate"]["baseline_block"] == {"n": 25, "k": 1}
    deeper = _estimate(baseline_patch_distance=9,
                       baseline={"code_blocks": 10, "physical_qubits": 800})   # 10 x 81 = 810
    failed = _failed(V.verify(_doc(benchmark=patches, algorithm_estimate=deeper), refute=False))
    assert "baseline: 800 < 10 blocks x n=81" in failed["architecture_physical_qubits_cover_blocks"]
    missing = _failed(V.verify(_doc(benchmark=_benchmark_block(surface_baseline={"slug": "999-1-3"})),
                               refute=False))
    assert "benchmark_baseline_on_board" in missing
    assert not any(c.startswith("architecture_") for c in missing)   # nothing to compare against


def test_the_factories_must_fit_in_the_candidate():
    est = _estimate(candidate={"code_blocks": 10, "physical_qubits": 200, "factories": 4})  # 4 x 60
    failed = _failed(V.verify(_doc(algorithm_estimate=est), refute=False))
    assert "architecture_factory_footprint" in failed and "240" in failed["architecture_factory_footprint"]


def test_the_schema_holds_the_vocabulary_and_ranges():
    for over in ({"status": "verified"},
                 {"method": ""},
                 {"gadgets": [_gadget(kind="magic")]},
                 {"gadgets": [_gadget(fault_distance=0)]},
                 {"gadgets": [_gadget(blocks=0)]},
                 {"gadgets": [_gadget(partner="not-a-slug")]},
                 {"gadgets": []},
                 {"magic_states": {"protocol": "distillation", "state": "T", "output_error_rate": 0}},
                 {"magic_states": {"protocol": "distillation", "state": "W", "output_error_rate": 1e-3}},
                 {"algorithm_estimate": _estimate(workload="")},
                 {"algorithm_estimate": _estimate(logical_error_rate_target=2)},
                 {"algorithm_estimate": _estimate(baseline_patch_distance=2)},
                 {"algorithm_estimate": _estimate(candidate={"physical_qubits": 200})},
                 {"extra": 1}):
        assert "schema_valid" in _failed(V.verify(_doc(**over), refute=False)), over


def test_the_gate_classifies_the_broken_artifact_as_the_documents_fault():
    rep = V.verify(G.broken_architecture(), refute=False)
    failed = {c["check"] for c in rep["checks"] if not c["ok"]}
    assert failed == {"architecture_gadget_fault_distance"}
    assert G.kind_of("architecture_gadget_fault_distance") == "architecture"
    assert "architecture" not in G.CODE_KINDS


def test_a_non_author_may_add_a_first_architecture_block():
    base = G.steane()
    base["schema_version"] = "0.6"
    base["benchmark"] = _benchmark_block()
    new = _doc(contributed_by={"by": ["@arch"], "date": "2026-11-05"})
    ok, why = A.architecture_binding("arch", base, new)
    assert ok, why
    assert A.evident_binding(base, new) == "architecture"
    assert V.verify(new, refute=False)["ok"]
    other = copy.deepcopy(new)
    other["k"] = 2
    assert not A.architecture_binding("arch", base, other)[0]
    assert not A.architecture_binding("someone", base, new)[0]
    assert not A.architecture_binding("arch", new, new)[0]   # replacing one stays with the authors
    bare = G.steane()                                         # no benchmark yet: two blocks at once
    assert not A.architecture_binding("arch", bare, new)[0]
    assert not A.benchmark_binding("arch", bare, new)[0]
