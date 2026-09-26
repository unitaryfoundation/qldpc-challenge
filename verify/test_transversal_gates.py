"""
Tests for the transversal-gate claims of the circuit block (issue #1850,
stage 1): the verifier must ACCEPT a gate that preserves the stabilizer group
and induces the claimed logical action, and REJECT a claim that is wrong in
any one way -- a wrong action, a basis that is not symplectic, a permutation
that is not one, an S on a code whose X checks are not doubly even, a
claimed gate that fixes every logical operator.

Known-good claims come from textbook facts: the Steane code has transversal
H (X <-> Z) and S (X -> Y), any CSS code has a block-to-block CX, and the
[[4,2,2]] code's qubit swap 1 <-> 2 is a logical SWAP. Each is checked through
qldpc_verify.verify, the same path CI and the site take, so the claims also
exercise the schema. The site test renders one code page with verified gates.

Run: uv run pytest verify/test_transversal_gates.py
"""

import copy
import glob
import importlib.util
import json
import os

import qldpc_verify as qv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STEANE = json.load(open(os.path.join(ROOT, "codes", "7-1-3.json")))
FOUR22 = json.load(open(os.path.join(ROOT, "codes", "4-2-2.json")))

# a symplectic logical basis for each test code: X_i and Z_j anticommute iff
# i == j (odd overlap exactly on the diagonal)
STEANE_LOGICALS = {"X": [list(range(7))], "Z": [list(range(7))]}
FOUR22_LOGICALS = {"X": [[0, 1], [0, 2]], "Z": [[0, 2], [0, 1]]}

# the S phase condition needs a code with an X check of weight 2 mod 4: the
# [[6,4,2]] code with one weight-6 check per side, and the basis
# X_i = X_{i+1} X_5, Z_i = Z_0 Z_{i+1} (overlap {i+1} iff i == j)
SIX42 = {
    "schema_version": "0.2", "name": "[[6,4,2]] test code", "code_type": "CSS",
    "n": 6, "k": 4,
    "checks": {"X": [[0, 1, 2, 3, 4, 5]], "Z": [[0, 1, 2, 3, 4, 5]]},
    "distance": {"d": 2,
                 "X": {"value": 2, "confidence": "upper_bound", "witness": [0, 1]},
                 "Z": {"value": 2, "confidence": "upper_bound", "witness": [0, 1]}},
    "provenance": {"authors": ["@tester"], "origin": "submission",
                   "construction": "test", "date": "2026-09-22"},
}
SIX42_LOGICALS = {"X": [[i + 1, 5] for i in range(4)],
                  "Z": [[0, i + 1] for i in range(4)]}


def with_gates(base, logicals, gates):
    """The base code plus a circuit block carrying the gate claims. The
    memory-tier fields are schema-required and inert here: qldpc_verify does
    not open circuit files, circuit_verify does and is not under test."""
    doc = copy.deepcopy(base)
    doc["schema_version"] = "0.2"
    d = doc["distance"]["d"]
    doc["circuit"] = {
        "d_circ": {s: {"value": d, "confidence": "upper_bound",
                       "witness": list(range(d))} for s in ("X", "Z")},
        "rounds": d, "stim_version": "1.16.0",
        "logicals": logicals, "gates": gates,
    }
    return doc


def status(report, label):
    return next(c["ok"] for c in report["checks"] if c["check"] == label)


def test_steane_transversal_hadamard():
    doc = with_gates(STEANE, STEANE_LOGICALS, [
        {"gate": "H", "name": "logical Hadamard",
         "logical_action": {"X0": ["Z0"], "Z0": ["X0"]}}])
    r = qv.verify(doc)
    assert r["ok"], [c for c in r["checks"] if not c["ok"]]
    assert status(r, "transversal_logicals_valid")
    assert status(r, "gate_0_preserves_stabilizers")
    assert status(r, "gate_0_logical_action")
    [g] = r["computed"]["transversal_gates"]
    assert g["verified"] and g["gate"] == "H" and g["blocks"] == 1
    assert g["action"] == {"X0": ["Z0"], "Z0": ["X0"]}


def test_steane_transversal_s():
    # S on every qubit sends X^7 to Y^7 = X^7 Z^7 up to phase; Z is fixed
    # and may be left out of the claim
    doc = with_gates(STEANE, STEANE_LOGICALS, [
        {"gate": "S", "logical_action": {"X0": ["X0", "Z0"]}}])
    r = qv.verify(doc)
    assert r["ok"], [c for c in r["checks"] if not c["ok"]]
    [g] = r["computed"]["transversal_gates"]
    assert g["action"] == {"X0": ["X0", "Z0"], "Z0": ["Z0"]}


def test_block_to_block_cx_on_422():
    # CX from block A (unprimed) to block B (primed), identity pairing:
    # X_i -> X_i X_i', Z_i' -> Z_i Z_i', the rest fixed, for both logicals
    doc = with_gates(FOUR22, FOUR22_LOGICALS, [
        {"gate": "CX", "logical_action": {
            "X0": ["X0", "X0'"], "X1": ["X1", "X1'"],
            "Z0'": ["Z0", "Z0'"], "Z1'": ["Z1", "Z1'"]}}])
    r = qv.verify(doc)
    assert r["ok"], [c for c in r["checks"] if not c["ok"]]
    [g] = r["computed"]["transversal_gates"]
    assert g["blocks"] == 2 and g["verified"]
    assert g["action"]["Z0"] == ["Z0"] and g["action"]["X1'"] == ["X1'"]
    assert g["action"]["Z1'"] == ["Z1", "Z1'"]


def test_qubit_permutation_is_logical_swap_on_422():
    # swapping qubits 1 and 2 maps X0 X1 <-> X0 X2 and Z0 Z2 <-> Z0 Z1
    doc = with_gates(FOUR22, FOUR22_LOGICALS, [
        {"gate": "permutation", "permutation": [0, 2, 1, 3],
         "name": "logical SWAP",
         "logical_action": {"X0": ["X1"], "X1": ["X0"],
                            "Z0": ["Z1"], "Z1": ["Z0"]}}])
    r = qv.verify(doc)
    assert r["ok"], [c for c in r["checks"] if not c["ok"]]
    [g] = r["computed"]["transversal_gates"]
    assert g["verified"] and not g["permutation_trivial"]


def test_wrong_logical_action_rejected():
    # H swaps X and Z; claiming it fixes them is a wrong claim about a gate
    # that does preserve the code, so preservation passes and the action
    # check fails, and the entry fails with it
    doc = with_gates(STEANE, STEANE_LOGICALS, [
        {"gate": "H", "logical_action": {"X0": ["X0"], "Z0": ["Z0"]}}])
    r = qv.verify(doc)
    assert not r["ok"]
    assert status(r, "gate_0_preserves_stabilizers")
    assert not status(r, "gate_0_logical_action")
    assert not r["computed"]["transversal_gates"][0]["verified"]

    # and a wrong CX claim (target's Z claimed fixed)
    doc = with_gates(FOUR22, FOUR22_LOGICALS, [
        {"gate": "CX", "logical_action": {
            "X0": ["X0", "X0'"], "X1": ["X1", "X1'"]}}])
    r = qv.verify(doc)
    assert not r["ok"] and not status(r, "gate_0_logical_action")


def test_s_phase_condition_rejects_non_doubly_even_code():
    # weight-6 X check: S^6 sends X^6 to i^6 X^6 Z^6 = -(stabilizer), so the
    # gate leaves the code space although the GF(2) image is a stabilizer
    doc = with_gates(SIX42, SIX42_LOGICALS, [
        {"gate": "S", "logical_action": {f"X{i}": [f"X{i}", f"Z{i}"]
                                         for i in range(4)}}])
    r = qv.verify(doc)
    assert not r["ok"]
    assert not status(r, "gate_0_preserves_stabilizers")
    assert "0 mod 4" in next(c["detail"] for c in r["checks"]
                             if c["check"] == "gate_0_preserves_stabilizers")
    # the same code's transversal H is fine (H_X = H_Z, no phase). In this
    # basis H sends X_i = X_{i+1} X_5 to Z_{i+1} Z_5 = Z_i (Z_0 Z_5), and
    # Z_0 Z_5 = Z^6 Z_1 Z_2 Z_3 Z_4 is the product of every Z_j modulo the
    # stabilizer, so X_i goes to the product of the Z_j with j != i; the
    # naive claim X_i -> Z_i is wrong in this basis and must be rejected
    others = lambda p, i: [f"{p}{j}" for j in range(4) if j != i]  # noqa: E731
    doc = with_gates(SIX42, SIX42_LOGICALS, [
        {"gate": "H", "logical_action": {
            **{f"X{i}": others("Z", i) for i in range(4)},
            **{f"Z{i}": others("X", i) for i in range(4)}}}])
    r = qv.verify(doc)
    assert r["ok"], [c for c in r["checks"] if not c["ok"]]
    doc["circuit"]["gates"][0]["logical_action"] = {
        **{f"X{i}": [f"Z{i}"] for i in range(4)},
        **{f"Z{i}": [f"X{i}"] for i in range(4)}}
    r = qv.verify(doc)
    assert not r["ok"] and not status(r, "gate_0_logical_action")


def test_bad_logical_basis_rejected():
    # X0 and Z0 commuting (even overlap) is not a symplectic pair
    doc = with_gates(FOUR22, {"X": [[0, 1], [0, 2]], "Z": [[0, 1], [0, 2]]}, [
        {"gate": "H", "logical_action": {"X0": ["Z0"], "Z0": ["X0"]}}])
    r = qv.verify(doc)
    assert not r["ok"] and not status(r, "transversal_logicals_valid")
    # an operator that is not a logical (anticommutes with a check)
    doc = with_gates(STEANE, {"X": [[0]], "Z": [list(range(7))]}, [
        {"gate": "H", "logical_action": {"X0": ["Z0"], "Z0": ["X0"]}}])
    r = qv.verify(doc)
    assert not r["ok"] and not status(r, "transversal_logicals_valid")


def test_malformed_permutation_and_unknown_labels_rejected():
    doc = with_gates(STEANE, STEANE_LOGICALS, [
        {"gate": "permutation", "permutation": [0, 0, 2, 3, 4, 5, 6],
         "logical_action": {"X0": ["X0"]}}])
    r = qv.verify(doc)
    assert not r["ok"] and not status(r, "gate_0_preserves_stabilizers")
    # a primed label needs a CX; X1 needs k >= 2
    for claim in ({"X0'": ["X0"]}, {"X1": ["Z1"]}):
        doc = with_gates(STEANE, STEANE_LOGICALS, [
            {"gate": "H", "logical_action": claim}])
        r = qv.verify(doc)
        assert not r["ok"] and not status(r, "gate_0_logical_action")


def test_code_automorphism_with_trivial_action_rejected():
    # swapping bits 0 and 1 of q+1 permutes the Steane code's checks among
    # themselves and fixes X^7 and Z^7: an automorphism, not a logical gate
    doc = with_gates(STEANE, STEANE_LOGICALS, [
        {"gate": "permutation", "permutation": [1, 0, 2, 3, 5, 4, 6],
         "logical_action": {"X0": ["X0"]}}])
    r = qv.verify(doc)
    assert not r["ok"]
    assert status(r, "gate_0_preserves_stabilizers")
    assert not status(r, "gate_0_logical_action")


def test_schema_requires_logicals_and_permutation():
    doc = with_gates(STEANE, STEANE_LOGICALS, [
        {"gate": "H", "logical_action": {"X0": ["Z0"], "Z0": ["X0"]}}])
    del doc["circuit"]["logicals"]
    assert qv.structure_errors(doc)
    doc = with_gates(STEANE, STEANE_LOGICALS, [
        {"gate": "permutation", "logical_action": {"X0": ["Z0"]}}])
    assert qv.structure_errors(doc)
    doc = with_gates(STEANE, STEANE_LOGICALS, [
        {"gate": "T", "logical_action": {"X0": ["Z0"]}}])
    assert qv.structure_errors(doc)


def test_existing_board_files_still_validate():
    # the fields are optional: every committed entry passes the schema
    # unchanged, and none of them has gates, so nothing is computed for them
    bad = []
    for p in sorted(glob.glob(os.path.join(ROOT, "codes", "*.json"))):
        doc = json.load(open(p))
        if qv.structure_errors(doc):
            bad.append(os.path.basename(p))
    assert not bad, bad
    # The shared Steane baseline can itself acquire optional tiers such as
    # circuit.gates. Strip those tiers here to keep this assertion focused on
    # the backward-compatible code-only document shape.
    legacy_steane = copy.deepcopy(STEANE)
    legacy_steane.pop("circuit", None)
    r = qv.verify(legacy_steane)
    assert r["ok"] and "transversal_gates" not in r["computed"]


def test_site_lists_verified_gates_on_code_page(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "site_build", os.path.join(ROOT, "site", "build.py"))
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    codes = tmp_path / "codes"
    codes.mkdir()
    hostile = '"><img src=x onerror=globalThis.qldpcXssRegression=3>'
    doc = with_gates(STEANE, STEANE_LOGICALS, [
        {"gate": "H", "name": "logical Hadamard",
         "logical_action": {"X0": ["Z0"], "Z0": ["X0"]}},
        {"gate": "CX", "name": f"CX {hostile}", "notes": hostile,
         "logical_action": {"X0": ["X0", "X0'"], "Z0'": ["Z0", "Z0'"]}},
        {"gate": "permutation", "permutation": [1, 0, 2, 3, 5, 4, 6],
         "logical_action": {"X0": ["X0"]}}])
    # the third claim is a rejected automorphism: with it the entry fails
    # and never reaches the board
    (codes / "7-1-3.json").write_text(json.dumps(doc))
    build.ROOT = str(tmp_path)
    assert build.load_entries() == []
    doc["circuit"]["gates"].pop()
    (codes / "7-1-3.json").write_text(json.dumps(doc))
    [e] = build.load_entries()
    assert len(e["gates"]) == 2 and all(g["verified"] for g in e["gates"])
    page = "".join(build.detail_page(e))
    assert "transversal gates</b> 2 verified" in page
    assert "logical Hadamard</b> H on every qubit &middot; X0 &rarr; Z0, Z0 &rarr; X0" in page
    # the free-text label renders escaped (site/test_security's coverage
    # list points here), and notes never render
    assert "CX &quot;&gt;&lt;img src=x" in page
    assert hostile not in page and "<img src=x" not in page
    assert "X0 &rarr; X0 X0&#x27;" in page
    assert "logical basis the gate actions refer to" in page
