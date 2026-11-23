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
    "schema_version": "0.2",
    "name": "[[6,4,2]] test code",
    "code_type": "CSS",
    "n": 6,
    "k": 4,
    "checks": {"X": [[0, 1, 2, 3, 4, 5]], "Z": [[0, 1, 2, 3, 4, 5]]},
    "distance": {
        "d": 2,
        "X": {"value": 2, "confidence": "upper_bound", "witness": [0, 1]},
        "Z": {"value": 2, "confidence": "upper_bound", "witness": [0, 1]},
    },
    "provenance": {"authors": ["@tester"], "origin": "submission", "construction": "test", "date": "2026-09-22"},
}
SIX42_LOGICALS = {"X": [[i + 1, 5] for i in range(4)], "Z": [[0, i + 1] for i in range(4)]}


def with_gates(base, logicals, gates):
    """The base code plus a circuit block carrying the gate claims. The
    memory-tier fields are schema-required and inert here: qldpc_verify does
    not open circuit files, circuit_verify does and is not under test.
    """
    doc = copy.deepcopy(base)
    doc["schema_version"] = "0.2"
    d = doc["distance"]["d"]
    doc["circuit"] = {
        "d_circ": {s: {"value": d, "confidence": "upper_bound", "witness": list(range(d))} for s in ("X", "Z")},
        "rounds": d,
        "stim_version": "1.16.0",
        "logicals": logicals,
        "gates": gates,
    }
    return doc


def status(report, label):
    return next(c["ok"] for c in report["checks"] if c["check"] == label)


def test_steane_transversal_hadamard():
    doc = with_gates(
        STEANE,
        STEANE_LOGICALS,
        [{"gate": "H", "name": "logical Hadamard", "logical_action": {"X0": ["Z0"], "Z0": ["X0"]}}],
    )
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
    doc = with_gates(STEANE, STEANE_LOGICALS, [{"gate": "S", "logical_action": {"X0": ["X0", "Z0"]}}])
    r = qv.verify(doc)
    assert r["ok"], [c for c in r["checks"] if not c["ok"]]
    [g] = r["computed"]["transversal_gates"]
    assert g["action"] == {"X0": ["X0", "Z0"], "Z0": ["Z0"]}


def test_block_to_block_cx_on_422():
    # CX from block A (unprimed) to block B (primed), identity pairing:
    # X_i -> X_i X_i', Z_i' -> Z_i Z_i', the rest fixed, for both logicals
    doc = with_gates(
        FOUR22,
        FOUR22_LOGICALS,
        [
            {
                "gate": "CX",
                "logical_action": {
                    "X0": ["X0", "X0'"],
                    "X1": ["X1", "X1'"],
                    "Z0'": ["Z0", "Z0'"],
                    "Z1'": ["Z1", "Z1'"],
                },
            }
        ],
    )
    r = qv.verify(doc)
    assert r["ok"], [c for c in r["checks"] if not c["ok"]]
    [g] = r["computed"]["transversal_gates"]
    assert g["blocks"] == 2 and g["verified"]
    assert g["action"]["Z0"] == ["Z0"] and g["action"]["X1'"] == ["X1'"]
    assert g["action"]["Z1'"] == ["Z1", "Z1'"]


def test_qubit_permutation_is_logical_swap_on_422():
    # swapping qubits 1 and 2 maps X0 X1 <-> X0 X2 and Z0 Z2 <-> Z0 Z1
    doc = with_gates(
        FOUR22,
        FOUR22_LOGICALS,
        [
            {
                "gate": "permutation",
                "permutation": [0, 2, 1, 3],
                "name": "logical SWAP",
                "logical_action": {"X0": ["X1"], "X1": ["X0"], "Z0": ["Z1"], "Z1": ["Z0"]},
            }
        ],
    )
    r = qv.verify(doc)
    assert r["ok"], [c for c in r["checks"] if not c["ok"]]
    [g] = r["computed"]["transversal_gates"]
    assert g["verified"] and not g["permutation_trivial"]


def test_wrong_logical_action_rejected():
    # H swaps X and Z; claiming it fixes them is a wrong claim about a gate
    # that does preserve the code, so preservation passes and the action
    # check fails, and the entry fails with it
    doc = with_gates(STEANE, STEANE_LOGICALS, [{"gate": "H", "logical_action": {"X0": ["X0"], "Z0": ["Z0"]}}])
    r = qv.verify(doc)
    assert not r["ok"]
    assert status(r, "gate_0_preserves_stabilizers")
    assert not status(r, "gate_0_logical_action")
    assert not r["computed"]["transversal_gates"][0]["verified"]

    # and a wrong CX claim (target's Z claimed fixed)
    doc = with_gates(
        FOUR22, FOUR22_LOGICALS, [{"gate": "CX", "logical_action": {"X0": ["X0", "X0'"], "X1": ["X1", "X1'"]}}]
    )
    r = qv.verify(doc)
    assert not r["ok"] and not status(r, "gate_0_logical_action")


def test_s_phase_condition_rejects_non_doubly_even_code():
    # weight-6 X check: S^6 sends X^6 to i^6 X^6 Z^6 = -(stabilizer), so the
    # gate leaves the code space although the GF(2) image is a stabilizer
    doc = with_gates(
        SIX42, SIX42_LOGICALS, [{"gate": "S", "logical_action": {f"X{i}": [f"X{i}", f"Z{i}"] for i in range(4)}}]
    )
    r = qv.verify(doc)
    assert not r["ok"]
    assert not status(r, "gate_0_preserves_stabilizers")
    assert "0 mod 4" in next(c["detail"] for c in r["checks"] if c["check"] == "gate_0_preserves_stabilizers")
    # the same code's transversal H is fine (H_X = H_Z, no phase). In this
    # basis H sends X_i = X_{i+1} X_5 to Z_{i+1} Z_5 = Z_i (Z_0 Z_5), and
    # Z_0 Z_5 = Z^6 Z_1 Z_2 Z_3 Z_4 is the product of every Z_j modulo the
    # stabilizer, so X_i goes to the product of the Z_j with j != i; the
    # naive claim X_i -> Z_i is wrong in this basis and must be rejected
    others = lambda p, i: [f"{p}{j}" for j in range(4) if j != i]  # noqa: E731
    doc = with_gates(
        SIX42,
        SIX42_LOGICALS,
        [
            {
                "gate": "H",
                "logical_action": {
                    **{f"X{i}": others("Z", i) for i in range(4)},
                    **{f"Z{i}": others("X", i) for i in range(4)},
                },
            }
        ],
    )
    r = qv.verify(doc)
    assert r["ok"], [c for c in r["checks"] if not c["ok"]]
    doc["circuit"]["gates"][0]["logical_action"] = {
        **{f"X{i}": [f"Z{i}"] for i in range(4)},
        **{f"Z{i}": [f"X{i}"] for i in range(4)},
    }
    r = qv.verify(doc)
    assert not r["ok"] and not status(r, "gate_0_logical_action")


def test_bad_logical_basis_rejected():
    # X0 and Z0 commuting (even overlap) is not a symplectic pair
    doc = with_gates(
        FOUR22,
        {"X": [[0, 1], [0, 2]], "Z": [[0, 1], [0, 2]]},
        [{"gate": "H", "logical_action": {"X0": ["Z0"], "Z0": ["X0"]}}],
    )
    r = qv.verify(doc)
    assert not r["ok"] and not status(r, "transversal_logicals_valid")
    # an operator that is not a logical (anticommutes with a check)
    doc = with_gates(
        STEANE, {"X": [[0]], "Z": [list(range(7))]}, [{"gate": "H", "logical_action": {"X0": ["Z0"], "Z0": ["X0"]}}]
    )
    r = qv.verify(doc)
    assert not r["ok"] and not status(r, "transversal_logicals_valid")


def test_malformed_permutation_and_unknown_labels_rejected():
    doc = with_gates(
        STEANE,
        STEANE_LOGICALS,
        [{"gate": "permutation", "permutation": [0, 0, 2, 3, 4, 5, 6], "logical_action": {"X0": ["X0"]}}],
    )
    r = qv.verify(doc)
    assert not r["ok"] and not status(r, "gate_0_preserves_stabilizers")
    # a primed label needs a CX; X1 needs k >= 2
    for claim in ({"X0'": ["X0"]}, {"X1": ["Z1"]}):
        doc = with_gates(STEANE, STEANE_LOGICALS, [{"gate": "H", "logical_action": claim}])
        r = qv.verify(doc)
        assert not r["ok"] and not status(r, "gate_0_logical_action")


def test_code_automorphism_with_trivial_action_rejected():
    # swapping bits 0 and 1 of q+1 permutes the Steane code's checks among
    # themselves and fixes X^7 and Z^7: an automorphism, not a logical gate
    doc = with_gates(
        STEANE,
        STEANE_LOGICALS,
        [{"gate": "permutation", "permutation": [1, 0, 2, 3, 5, 4, 6], "logical_action": {"X0": ["X0"]}}],
    )
    r = qv.verify(doc)
    assert not r["ok"]
    assert status(r, "gate_0_preserves_stabilizers")
    assert not status(r, "gate_0_logical_action")


def test_schema_requires_logicals_and_permutation():
    doc = with_gates(STEANE, STEANE_LOGICALS, [{"gate": "H", "logical_action": {"X0": ["Z0"], "Z0": ["X0"]}}])
    del doc["circuit"]["logicals"]
    assert qv.structure_errors(doc)
    doc = with_gates(STEANE, STEANE_LOGICALS, [{"gate": "permutation", "logical_action": {"X0": ["Z0"]}}])
    assert qv.structure_errors(doc)
    doc = with_gates(STEANE, STEANE_LOGICALS, [{"gate": "T", "logical_action": {"X0": ["Z0"]}}])
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
    spec = importlib.util.spec_from_file_location("site_build", os.path.join(ROOT, "site", "build.py"))
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    codes = tmp_path / "codes"
    codes.mkdir()
    hostile = '"><img src=x onerror=globalThis.qldpcXssRegression=3>'
    doc = with_gates(
        STEANE,
        STEANE_LOGICALS,
        [
            {"gate": "H", "name": "logical Hadamard", "logical_action": {"X0": ["Z0"], "Z0": ["X0"]}},
            {
                "gate": "CX",
                "name": f"CX {hostile}",
                "notes": hostile,
                "logical_action": {"X0": ["X0", "X0'"], "Z0'": ["Z0", "Z0'"]},
            },
            {"gate": "permutation", "permutation": [1, 0, 2, 3, 5, 4, 6], "logical_action": {"X0": ["X0"]}},
        ],
    )
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


# ---------------------------------------------------------------------------
# stage 2 (issue #2894): W <= 2 diagonal layers, gate type "match"
# ---------------------------------------------------------------------------

import itertools

import numpy as np


def _dense_truth(n, HX, HZ, support, pairs, clifford):
    """Ground truth for a match claim by dense conjugation: does the layer
    send every stabilizer generator to a +1 element of the stabilizer group?
    Enumerates the group with signs, so no modelling and no convention: the
    only inputs are the 2x2 gates and the CZ matrix.
    """
    I2 = np.eye(2, dtype=complex)
    X = np.array([[0, 1], [1, 0]], dtype=complex)
    Z = np.diag([1, -1]).astype(complex)
    Hd = np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2)
    S = np.diag([1, 1j])
    single = {"S": S, "SHS": S @ Hd @ S, "HSH": Hd @ S @ Hd}[clifford]

    def kron(ops):
        out = np.array([[1]], dtype=complex)
        for o in ops:
            out = np.kron(out, o)
        return out

    def pauli(x, z):
        return kron([(X @ Z if (x[q] and z[q]) else X if x[q] else Z if z[q] else I2) for q in range(n)])

    def cz(i, j):
        M = np.eye(2**n, dtype=complex)
        for b in range(2**n):
            if (b >> (n - 1 - i)) & 1 and (b >> (n - 1 - j)) & 1:
                M[b, b] = -1
        if clifford == "S":
            return M
        Hn = kron([Hd if q in (i, j) else I2 for q in range(n)])
        return Hn @ M @ Hn

    U = kron([single if q in support else I2 for q in range(n)])
    for i, j in pairs:
        U = U @ cz(i, j)
    zero = np.zeros(n, dtype=int)
    gens = [pauli(a, zero) for a in HX] + [pauli(zero, b) for b in HZ]
    group = []
    for bitsel in itertools.product([0, 1], repeat=len(gens)):
        G = np.eye(2**n, dtype=complex)
        for b, g in zip(bitsel, gens):
            if b:
                G = G @ g
        group.append(G)
    Ud = U.conj().T
    return all(any(np.allclose(U @ g @ Ud, G, atol=1e-9) for G in group) for g in gens)


def _matchings(n):
    out = {()}

    def rec(avail, cur):
        if len(avail) < 2:
            return
        first = avail[0]
        for other in avail[1:]:
            m = tuple(sorted(cur + [(first, other)]))
            out.add(m)
            rec([a for a in avail if a not in (first, other)], list(m))
        rec(avail[1:], cur)

    rec(list(range(n)), [])
    return [list(map(list, m)) for m in out]


def _match_verdict(base, logicals, clifford, support, pairs):
    """The verifier's preservation verdict for a match claim with a dummy
    action (the action check is separate; a trivial action is rejected
    only on the action label, which this helper ignores).
    """
    doc = with_gates(
        base,
        logicals,
        [
            {
                "gate": "match",
                "clifford": clifford,
                "support": list(support),
                "pairs": [list(p) for p in pairs],
                "logical_action": {"X0": ["X0", "Z0"]},
            }
        ],
    )
    r = qv.verify(doc)
    return status(r, "gate_0_preserves_stabilizers")


def _rows(code):
    n = code["n"]
    return (
        [[1 if q in r else 0 for q in range(n)] for r in code["checks"]["X"]],
        [[1 if q in r else 0 for q in range(n)] for r in code["checks"]["Z"]],
    )


def test_match_rule_matches_dense_conjugation_on_422_and_642():
    # T1: every support x every matching, S and SHS families, against 16x16
    # ([[4,2,2]]) and 64x64 ([[6,4,2]], whose weight-6 check makes the phase
    # term decisive) conjugation. 160 + 160 cases on [[4,2,2]], 4864 + 4864
    # on [[6,4,2]].
    for base, logicals in ((FOUR22, FOUR22_LOGICALS), (SIX42, SIX42_LOGICALS)):
        n = base["n"]
        HX, HZ = _rows(base)
        subsets = [list(c) for r in range(n + 1) for c in itertools.combinations(range(n), r)]
        for clifford in ("S", "SHS"):
            disagreements = []
            positives = 0
            for sup in subsets:
                for pairs in _matchings(n):
                    if not sup and not pairs:
                        continue  # the identity is rejected as a claim
                    truth = _dense_truth(n, HX, HZ, sup, pairs, clifford)
                    verdict = _match_verdict(base, logicals, clifford, sup, pairs)
                    positives += truth
                    if truth != verdict:
                        disagreements.append((sup, pairs, truth, verdict))
            assert not disagreements, (base["name"], clifford, disagreements[:3])
            assert positives > 0


def _agl15_core():
    """The [[20,2,6]] core of arXiv:2606.13521 Construction 4: self-dual
    group-algebra code over AGL(1,5), c = {0,1,2,4,6,7,10,16} in the paper's
    indexing ((a, b) -> 4b + j with a = 2^j mod 5; M(c)[g, h] = 1 iff
    g h^-1 in c), H a row basis of rowspan M(c), with the paper's canonical
    logicals.
    """
    import gf2

    elems, index = [], {}
    for b in range(5):
        for j in range(4):
            a = pow(2, j, 5)
            elems.append((a, b))
            index[(a, b)] = 4 * b + j

    def mul(g, h):
        (a, b), (c, d) = g, h
        return ((a * c) % 5, (a * d + b) % 5)

    def inv(g):
        a, b = g
        ai = pow(a, -1, 5)
        return (ai, (-ai * b) % 5)

    c = {0, 1, 2, 4, 6, 7, 10, 16}
    M = np.zeros((20, 20), dtype=np.int8)
    for g in elems:
        for h in elems:
            if index[mul(g, inv(h))] in c:
                M[index[g], index[h]] = 1
    R, piv = gf2.rref(M)
    H = R[: len(piv)]
    rows = [sorted(np.flatnonzero(r).tolist()) for r in H]
    assert len(rows) == 9
    LX = [[0, 2, 5, 6, 8, 10], [1, 3, 4, 5, 9, 11]]
    LZ = [[1, 3, 4, 5, 9, 11], [0, 2, 5, 6, 8, 10]]
    doc = {
        "schema_version": "0.2",
        "name": "[[20,2,6]] AGL(1,5) core (test)",
        "code_type": "CSS",
        "n": 20,
        "k": 2,
        "checks": {"X": rows, "Z": rows},
        "distance": {
            "d": 6,
            "X": {"value": 6, "confidence": "upper_bound", "witness": LX[0]},
            "Z": {"value": 6, "confidence": "upper_bound", "witness": LZ[0]},
        },
        "provenance": {"authors": ["@tester"], "origin": "submission", "construction": "test", "date": "2026-10-08"},
    }
    return doc, {"X": LX, "Z": LZ}


AGL_LAYERS = {
    # the five depth-1 generators of Construction 4 and the logical action
    # each should induce: S on logical 0 and 1, CZ on the pair, and the
    # SHS mirrors (all actions modulo stabilizers)
    "S0": (
        "S",
        [0, 1, 4, 6, 9, 10, 11, 12, 13, 15, 16, 17, 18, 19],
        [[0, 1], [4, 6], [9, 16], [10, 12], [11, 17], [13, 19], [15, 18]],
        {"X0": ["X0", "Z0"]},
    ),
    "S1": (
        "S",
        [2, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14, 15, 16, 19],
        [[2, 3], [4, 5], [8, 9], [10, 15], [11, 12], [13, 14], [16, 19]],
        {"X1": ["X1", "Z1"]},
    ),
    "CZ01": ("S", list(range(20)), [], {"X0": ["X0", "Z1"], "X1": ["X1", "Z0"]}),
    "SHS0": (
        "SHS",
        [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 17, 18],
        [[0, 4], [1, 18], [2, 8], [3, 9], [5, 17], [6, 15], [7, 10]],
        {"Z0": ["X0", "Z0"]},
    ),
    "SHS1": (
        "SHS",
        [0, 1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 18, 19],
        [[0, 10], [1, 5], [2, 19], [3, 9], [4, 11], [6, 18], [7, 12]],
        {"Z1": ["X1", "Z1"]},
    ),
}


def test_construction_4_layers_verify_on_the_agl15_core():
    # T2: all five depth-1 generators of the paper's [[20,2,6]] core pass
    # end to end with the textbook actions (logical S_0, S_1, CZ_01, and
    # the SHS mirrors); the uniform-S layer is the logical CZ
    doc, logicals = _agl15_core()
    gates = [
        {"gate": "match", "name": name, "clifford": cl, "support": sup, "pairs": pairs, "logical_action": act}
        for name, (cl, sup, pairs, act) in AGL_LAYERS.items()
    ]
    r = qv.verify(doc | {"circuit": with_gates(doc, logicals, gates)["circuit"]})
    assert r["ok"], [c for c in r["checks"] if not c["ok"]]
    comps = r["computed"]["transversal_gates"]
    assert [g["verified"] for g in comps] == [True] * 5
    assert comps[0]["clifford"] == "S" and comps[0]["support_size"] == 14
    assert comps[0]["pairs"] == 7 and comps[2]["pairs"] == 0
    assert comps[3]["action"] == {"X0": ["X0"], "X1": ["X1"], "Z0": ["X0", "Z0"], "Z1": ["Z1"]}
    # a wrong action on the same layer is rejected
    gates[0]["logical_action"] = {"X0": ["X0", "Z1"]}
    r = qv.verify(doc | {"circuit": with_gates(doc, logicals, gates)["circuit"]})
    assert not r["ok"] and not status(r, "gate_0_logical_action")


def test_match_phase_clause_is_load_bearing():
    # T3: on the [[6,4,2]] code, S on {0,1} with CZ on (2,3),(4,5) maps the
    # weight-6 X check to X^6 Z^6 (a stabilizer over GF(2)) with phase
    # i^2 (-1)^2 = -1, so the GF(2) image passes and the phase clause must
    # be what rejects it; the dense truth agrees
    HX, HZ = _rows(SIX42)
    assert not _dense_truth(6, HX, HZ, [0, 1], [[2, 3], [4, 5]], "S")
    doc = with_gates(
        SIX42,
        SIX42_LOGICALS,
        [
            {
                "gate": "match",
                "clifford": "S",
                "support": [0, 1],
                "pairs": [[2, 3], [4, 5]],
                "logical_action": {f"X{i}": [f"X{i}", f"Z{i}"] for i in range(4)},
            }
        ],
    )
    r = qv.verify(doc)
    assert not r["ok"] and not status(r, "gate_0_preserves_stabilizers")
    detail = next(c["detail"] for c in r["checks"] if c["check"] == "gate_0_preserves_stabilizers")
    assert "phase" in detail and "0 mod 4" in detail
    # adding S on all six qubits with three CZ pairs: count 6 + 6 = 12,
    # phase +1, GF(2) image zero: accepted by both
    assert _dense_truth(6, HX, HZ, list(range(6)), [[0, 1], [2, 3], [4, 5]], "S")
    assert _match_verdict(SIX42, SIX42_LOGICALS, "S", list(range(6)), [[0, 1], [2, 3], [4, 5]])


def test_uniform_match_equals_gate_s():
    # T4: {clifford S, support all, pairs []} is today's gate "S": same
    # verdict and action on the Steane code (accepted) and on [[6,4,2]]
    # (rejected on the phase clause)
    for base, logicals, action in (
        (STEANE, STEANE_LOGICALS, {"X0": ["X0", "Z0"]}),
        (SIX42, SIX42_LOGICALS, {f"X{i}": [f"X{i}", f"Z{i}"] for i in range(4)}),
    ):
        n = base["n"]
        r_s = qv.verify(with_gates(base, logicals, [{"gate": "S", "logical_action": action}]))
        r_m = qv.verify(
            with_gates(
                base,
                logicals,
                [{"gate": "match", "clifford": "S", "support": list(range(n)), "pairs": [], "logical_action": action}],
            )
        )
        assert r_s["ok"] == r_m["ok"]
        for label in ("gate_0_preserves_stabilizers", "gate_0_logical_action"):
            assert status(r_s, label) == status(r_m, label), label
        if r_s["ok"]:
            assert (
                r_s["computed"]["transversal_gates"][0]["action"] == r_m["computed"]["transversal_gates"][0]["action"]
            )


def test_malformed_match_claims_rejected():
    # T5: overlapping pairs, a self-pair, support out of range, a
    # permutation on a match, and match fields on a non-match gate
    # S on qubits 0 and 1 with CZ on (2, 3): the X check 1111 goes to
    # X^4 Z^{1100 ^ 0011} = X^4 Z^4 with count 2 + 2 = 4, phase +1; in the
    # basis X0 = X_0 X_1, X1 = X_0 X_2, Z0 = Z_0 Z_2, Z1 = Z_0 Z_1 the layer
    # sends X0 to X0 Z1 and X1 to X1 Z_0 Z_3 = X1 Z0 Z1 modulo Z^4
    good = {
        "gate": "match",
        "clifford": "S",
        "support": [0, 1],
        "pairs": [[2, 3]],
        "logical_action": {"X0": ["X0", "Z1"], "X1": ["X1", "Z0", "Z1"]},
    }
    for bad in (
        {**good, "pairs": [[2, 3], [3, 1]]},
        {**good, "pairs": [[2, 2]]},
        {**good, "support": [0, 1, 7]},
        {**good, "pairs": [[2, 9]]},
        {**good, "support": [], "pairs": []},
        {**good, "permutation": [1, 0, 2, 3]},
        {**good, "clifford": "H"},
        {"gate": "S", "support": [0, 1], "logical_action": {"X0": ["X0", "Z0"]}},
        {"gate": "match", "support": [0, 1], "pairs": [[2, 3]], "logical_action": {"X0": ["X0", "Z1"]}},
    ):
        r = qv.verify(with_gates(FOUR22, FOUR22_LOGICALS, [bad]))
        assert not r["ok"], bad
    HX, HZ = _rows(FOUR22)
    assert _dense_truth(4, HX, HZ, [0, 1], [[2, 3]], "S")
    r = qv.verify(with_gates(FOUR22, FOUR22_LOGICALS, [good]))
    assert r["ok"], [c for c in r["checks"] if not c["ok"]]
    [g] = r["computed"]["transversal_gates"]
    assert g["action"] == {"X0": ["X0", "Z1"], "X1": ["X1", "Z0", "Z1"], "Z0": ["Z0"], "Z1": ["Z1"]}
