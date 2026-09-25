"""General (non-CSS) stabilizer codes through the trust anchor (issue #2131).

The fixtures under verify/fixtures/ are the [[5,1,3]] code and the XZZX toric
code at L = 3 and 4; the tests here build the adversarial variants in place:
a CSS code typed "stabilizer" (rejected, with the fix spelled out), a
Hadamard-conjugated copy of a board entry (a duplicate of it, not a new code),
a non-isotropic S (rejected), a Y-carrying witness whose Hamming weight is not
its Pauli weight (the Pauli weight is what counts), and an inflated distance
claim (refuted by the heuristic gate). The last group checks that the two
boards stay separate: a CSS entry never dominates a stabilizer one.
"""
import copy
import json
import os

import check_authorship
import gate_changed as G
import gf2
import heuristic_distance as H
import numpy as np
import pytest
import qldpc_verify as Q
import validate_candidate as V

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "verify", "fixtures")
STABILIZER_FIXTURES = ("5-1-3", "18-2-3", "32-2-4")


def load_fixture(slug):
    with open(os.path.join(FIXTURES, slug + ".json")) as f:
        return json.load(f)


def load_code(slug):
    with open(os.path.join(ROOT, "codes", slug + ".json")) as f:
        return json.load(f)


def failed(report):
    return {c["check"]: c["detail"] for c in report["checks"] if not c["ok"]}


def stabilizer_doc(n, gens, d, witness, name="synthetic", k=None):
    A = Q._matrix([g["X"] for g in gens], n)
    B = Q._matrix([g["Z"] for g in gens], n)
    if k is None:
        k = n - gf2.rank(np.concatenate([A, B], axis=1))
    return {"schema_version": "0.4", "name": name, "code_type": "stabilizer",
            "n": n, "k": int(k), "checks": {"S": gens},
            "distance": {"d": d, "P": {"value": d, "confidence": "upper_bound",
                                       "witness": witness}},
            "provenance": {"authors": ["@test"], "construction": "synthetic"}}


def hadamard_copy(css_doc, qubits, witness_side="X"):
    """Return a stabilizer-typed copy of a CSS doc with a Hadamard on `qubits`.

    Its witness is the CSS side's witness conjugated the same way.
    """
    hq = set(qubits)
    gens = [{"X": sorted(set(s) - hq), "Z": sorted(set(s) & hq)}
            for s in css_doc["checks"]["X"]]
    gens += [{"X": sorted(set(s) & hq), "Z": sorted(set(s) - hq)}
             for s in css_doc["checks"]["Z"]]
    wit = set(css_doc["distance"][witness_side]["witness"])
    if witness_side == "X":
        witness = {"X": sorted(wit - hq), "Z": sorted(wit & hq)}
    else:
        witness = {"X": sorted(wit & hq), "Z": sorted(wit - hq)}
    return stabilizer_doc(css_doc["n"], gens, css_doc["distance"]["d"], witness,
                          name=css_doc["name"] + " with local Hadamards",
                          k=css_doc["k"])


def toric_css(L):
    """Return the plain toric code on an L x L torus, as a CSS doc.

    Same edge labeling as the XZZX fixtures: horizontal edge (i, j) is
    i*L + j, vertical edge (i, j) is L*L + i*L + j.
    """
    def h(i, j):
        return (i % L) * L + (j % L)

    def v(i, j):
        return L * L + (i % L) * L + (j % L)
    X = [sorted({h(i, j), h(i, j - 1), v(i, j), v(i - 1, j)})
         for i in range(L) for j in range(L)]
    Z = [sorted({h(i, j), h(i + 1, j), v(i, j), v(i, j + 1)})
         for i in range(L) for j in range(L)]
    return {"n": 2 * L * L, "k": 2, "distance": {"d": L},
            "code_type": "CSS", "checks": {"X": X, "Z": Z}}


# --- the fixtures verify ----------------------------------------------------

@pytest.mark.parametrize("slug", STABILIZER_FIXTURES)
def test_fixture_verifies_with_refutation(slug):
    doc = load_fixture(slug)
    rep = Q.verify(doc, refute=True, seed=0)
    assert rep["ok"], failed(rep)
    assert rep["computed"]["code_type"] == "stabilizer"
    assert rep["computed"]["k"] == doc["k"]
    assert rep["earned_distance"]["d"]["value"] == doc["distance"]["d"]
    assert rep["earned_distance"]["P"]["tier"] == "upper_bound"
    assert rep["computed"]["flags"]["stabilizer"] is True
    assert rep["computed"]["flags"]["css"] is False
    assert "stabilizer_commutation" not in failed(rep)
    assert "distance_not_refuted" not in failed(rep)
    assert Q.sides(doc) == ("P",)


def test_five_qubit_parameters():
    doc = load_fixture("5-1-3")
    rep = Q.verify(doc)
    assert rep["computed"]["rank_S"] == 4
    assert rep["computed"]["max_check_weight"] == 4
    assert rep["computed"]["weight_class"] == "weight-4"
    # the perfect code is not CSS under any local Hadamards
    A, B = Q.stabilizer_matrices(doc)
    assert Q.is_css_up_to_local_hadamard(A, B) is None
    assert "css_equivalent" not in rep


# --- Pauli weight, not Hamming weight ----------------------------------------

def test_y_witness_counts_pauli_weight():
    doc = load_fixture("5-1-3")
    wit = doc["distance"]["P"]["witness"]
    hamming = len(wit["X"]) + len(wit["Z"])
    pauli = len(set(wit["X"]) | set(wit["Z"]))
    assert hamming == 4 and pauli == 3          # X Y X: one Y
    assert Q.verify(doc)["ok"]
    inflated = copy.deepcopy(doc)
    inflated["distance"]["P"]["value"] = hamming
    inflated["distance"]["d"] = hamming
    rep = Q.verify(inflated)
    assert not rep["ok"]
    assert "weight=3 (claim 4)" in failed(rep)["distance_P_witness"]
    assert "Y factors: 1" in failed(rep)["distance_P_witness"]


def test_ris_scores_by_pauli_weight():
    doc = load_fixture("5-1-3")
    A, B = Q.stabilizer_matrices(doc)
    w, wit = H.ris_min_pauli_logical(A, B, trials=200, seed=0)
    assert w == 3
    assert H.valid_pauli_logical(wit, A, B)
    assert H.pauli_weight_rows(wit[None, :], 5)[0] == 3


# --- rejections ---------------------------------------------------------------

def test_css_code_typed_stabilizer_is_rejected_with_the_fix():
    steane = load_code("7-1-3")
    gens = [{"X": s, "Z": []} for s in steane["checks"]["X"]]
    gens += [{"X": [], "Z": s} for s in steane["checks"]["Z"]]
    doc = stabilizer_doc(7, gens, 3, {"X": steane["distance"]["X"]["witness"],
                                      "Z": []}, k=1)
    rep = Q.verify(doc)
    assert not rep["ok"]
    msg = failed(rep)["stabilizer_code_is_not_css"]
    assert 'set code_type to "CSS"' in msg and "checks.X" in msg
    # and the same code typed CSS still passes as it always did
    assert Q.verify(steane)["ok"]


def test_non_isotropic_generators_rejected():
    doc = load_fixture("5-1-3")
    bad = copy.deepcopy(doc)
    bad["checks"]["S"][0]["Z"] = sorted(set(bad["checks"]["S"][0]["Z"]) ^ {4})
    rep = Q.verify(bad)
    assert not rep["ok"]
    assert "stabilizer_commutation" in failed(rep)


def test_empty_generator_and_repeated_qubit_rejected():
    doc = load_fixture("5-1-3")
    bad = copy.deepcopy(doc)
    bad["checks"]["S"].append({"X": [], "Z": []})
    assert "schema_valid" in failed(Q.verify(bad))
    bad = copy.deepcopy(doc)
    bad["checks"]["S"][0]["X"] = bad["checks"]["S"][0]["X"] * 2
    assert "no_repeated_qubits_in_a_check" in failed(Q.verify(bad))


def test_schema_splits_the_two_types():
    doc = load_fixture("5-1-3")
    old = copy.deepcopy(doc)
    old["schema_version"] = "0.3"
    assert "schema_valid" in failed(Q.verify(old))
    with_circuit = copy.deepcopy(doc)
    with_circuit["circuit"] = {"d_circ": {}, "rounds": 3, "stim_version": "1.16.0"}
    assert "schema_valid" in failed(Q.verify(with_circuit))
    mixed = copy.deepcopy(doc)
    mixed["distance"]["X"] = {"value": 3, "confidence": "upper_bound", "witness": [0, 1, 2]}
    assert "schema_valid" in failed(Q.verify(mixed))
    css = load_code("7-1-3")
    css_p = copy.deepcopy(css)
    css_p["distance"]["P"] = doc["distance"]["P"]
    assert "schema_valid" in failed(Q.verify(css_p))


def test_exact_claim_accepted_as_upper_bound():
    doc = copy.deepcopy(load_fixture("5-1-3"))
    doc["distance"]["P"]["confidence"] = "exact"
    rep = Q.verify(doc)
    assert rep["ok"]
    assert rep["earned_distance"]["P"]["tier"] == "upper_bound"
    assert any(c["check"] == "distance_P_exact_flagged" for c in rep["checks"])


# --- dedup: local Hadamards -------------------------------------------------

def test_hadamard_solver_finds_the_subset_and_the_css_image():
    for L in (3, 4):
        doc = load_fixture(f"{2 * L * L}-2-{L}")
        A, B = Q.stabilizer_matrices(doc)
        h = Q.is_css_up_to_local_hadamard(A, B)
        assert h is not None
        images = Q.hadamard_css_images(doc, h)
        toric = toric_css(L)
        n = toric["n"]
        fp_toric = Q.css_fingerprint(Q._matrix(toric["checks"]["X"], n),
                                     Q._matrix(toric["checks"]["Z"], n))
        fps = [Q.css_fingerprint(Q._matrix(im["checks"]["X"], n),
                                 Q._matrix(im["checks"]["Z"], n)) for im in images]
        assert fp_toric in fps
        rep = Q.verify(doc)
        assert fp_toric in rep["css_equivalent"]["fingerprints"]
        assert Q.signature(toric)["hash"] in rep["css_equivalent"]["signatures"]
    # a Y anywhere rules the map out
    five = load_fixture("5-1-3")
    A, B = Q.stabilizer_matrices(five)
    assert Q.is_css_up_to_local_hadamard(A, B) is None


def test_hadamard_copy_of_a_board_code_is_a_duplicate():
    steane = load_code("7-1-3")
    doc = hadamard_copy(steane, [0, 1, 2])
    rep = Q.verify(doc)
    assert rep["ok"], failed(rep)
    assert "stabilizer_code_is_not_css" not in failed(rep)
    verdict = V.validate_candidate(doc, refute=False)
    assert verdict["gates"]["dedup"]["exact_duplicate_of"] == "7-1-3.json"
    assert verdict["gates"]["dedup"]["local_clifford"] == "hadamard"
    assert verdict["passed"] is False
    assert any("up to a Hadamard" in lab for lab in verdict["labels"])
    # a qubit-permuted Hadamard copy is caught by the WL signature instead
    perm = [3, 6, 0, 5, 1, 4, 2]
    permuted = copy.deepcopy(doc)
    permuted["checks"]["S"] = [{"X": sorted(perm[q] for q in g["X"]),
                                "Z": sorted(perm[q] for q in g["Z"])}
                               for g in doc["checks"]["S"]]
    w = doc["distance"]["P"]["witness"]
    permuted["distance"]["P"]["witness"] = {"X": sorted(perm[q] for q in w["X"]),
                                            "Z": sorted(perm[q] for q in w["Z"])}
    verdict = V.validate_candidate(permuted, refute=False)
    assert verdict["gates"]["dedup"]["exact_duplicate_of"] is None
    assert verdict["gates"]["dedup"]["wl_equivalent_of"] == "7-1-3.json"


def test_labeled_signature_separates_letter_patterns():
    """Same supports, different Pauli letters: XZZXI against YZZYI.

    YZZYI is the five-qubit code conjugated by S on the X positions. An
    unlabeled Tanner graph cannot tell them apart; the labeled signature does.
    """
    xzzx = load_fixture("5-1-3")
    yzzy = copy.deepcopy(xzzx)
    for g in yzzy["checks"]["S"]:
        g["Z"] = sorted(set(g["Z"]) | set(g["X"]))      # X -> Y
    A, B = Q.stabilizer_matrices(yzzy)
    assert not ((A @ B.T + B @ A.T) % 2).any()
    w, wit = H.ris_min_pauli_logical(A, B, trials=200, seed=0)
    assert w == 3
    yzzy["distance"]["P"]["witness"] = H.pauli_witness(wit, 5)
    assert Q.verify(yzzy)["ok"]
    assert Q.signature(xzzx)["hash"] != Q.signature(yzzy)["hash"]


# --- refutation ---------------------------------------------------------------

def heavy_pauli_witness(doc, target):
    """Return a genuine nontrivial logical of Pauli weight `target`.

    The stored witness times stabilizer generators until the weight reaches it.
    """
    n = doc["n"]
    A, B = Q.stabilizer_matrices(doc)
    S = np.concatenate([A, B], axis=1)
    x, z = Q.witness_pauli(doc["distance"]["P"]["witness"], n)
    v = np.concatenate([x, z])
    rng = np.random.default_rng(1)
    for _ in range(10000):
        if H.pauli_weight_rows(v[None, :], n)[0] == target:
            return v
        cand = v ^ S[rng.integers(len(S))]
        if H.pauli_weight_rows(cand[None, :], n)[0] <= target:
            v = cand
    raise AssertionError("no witness of the target weight found")


def test_inflated_distance_is_refuted():
    doc = load_fixture("32-2-4")
    v = heavy_pauli_witness(doc, 6)
    bad = copy.deepcopy(doc)
    bad["distance"]["d"] = 6
    bad["distance"]["P"] = {"value": 6, "confidence": "upper_bound",
                            "witness": H.pauli_witness(v, doc["n"])}
    assert Q.verify(bad)["ok"], "the heavy witness is a genuine logical"
    rep = Q.verify(bad, refute=True, seed=0)
    assert not rep["ok"]
    assert "found weight-4 logical" in failed(rep)["distance_not_refuted"]
    refuted, d_found, wit, _ = H.refute_check(bad, seed=0, trials=500)
    assert refuted and d_found == 4
    A, B = Q.stabilizer_matrices(doc)
    x, z = Q.witness_pauli(wit, doc["n"])
    assert H.valid_pauli_logical(np.concatenate([x, z]), A, B)
    if G.GF is not None:
        refuted, d_found, wit, done = G._fast_refute(bad, 3, 20000)
        assert refuted and d_found == 4 and done == 20000
        assert set(wit) == {"X", "Z"}
        x, z = Q.witness_pauli(wit, doc["n"])
        assert H.valid_pauli_logical(np.concatenate([x, z]), A, B)
        assert Q.pauli_weight(x, z) == 4


def test_estimate_reports_one_side():
    doc = load_fixture("18-2-3")
    res = H.estimate(doc, trials=300, seed=0, fast_trials=0)
    assert res["verdict"] == "corroborated"
    assert set(res["sides"]) == {"P"}
    assert res["sides"]["P"]["lightest_found"] == 3


# --- gate plumbing: sides(), classify_diff, authorship binding -----------------

def test_classify_diff_and_binding_on_a_pauli_side():
    doc = load_fixture("32-2-4")
    base = copy.deepcopy(doc)
    base["distance"]["d"] = 6
    base["distance"]["P"] = {"value": 6, "confidence": "upper_bound",
                             "witness": H.pauli_witness(heavy_pauli_witness(doc, 6), 32)}
    new = copy.deepcopy(doc)
    new["distance"]["P"]["witness_provenance"] = {
        "found_by": ["@bob"], "date": "2026-09-25", "found_at_samples": 1000}
    cls, why = G.classify_diff(base, new)
    assert cls == "tightening", why
    ok, why = check_authorship.refutation_binding("bob", base, new)
    assert ok, why
    wrong_d = copy.deepcopy(new)
    wrong_d["distance"]["d"] = 5
    assert G.classify_diff(base, wrong_d)[1] == "distance.d is not P.value"
    assert check_authorship.refutation_binding("bob", base, wrong_d)[1] == \
        "distance.d is not P.value"
    assert G._witness_weight(new["distance"]["P"]) == 4
    assert G._locality_rank(doc) == 2


def test_structural_and_syndrome_passes_skip_stabilizer_codes():
    doc = load_fixture("5-1-3")
    if G.GF is not None:
        assert G._structural_refute(doc, 1, 100) == (False, None, None, 0)


# --- separate leaderboards ----------------------------------------------------

def test_stabilizer_candidate_is_not_dominated_by_css_entries(monkeypatch):
    doc = load_fixture("5-1-3")
    fake_css = {"name": "4-1-3.json", "n": 4, "k": 1, "d": 3, "code_type": "CSS",
                "fingerprint": "x", "sig": "y", "css_fingerprints": [],
                "css_sigs": [], "weight_class": "weight-4", "w": 2,
                "locality_class": "unrestricted"}
    monkeypatch.setattr(V, "_board_entries", lambda: [fake_css])
    verdict = V.validate_candidate(doc, refute=False)
    assert verdict["gates"]["novelty"]["board"] == "stabilizer"
    assert verdict["gates"]["novelty"]["board_advancing"] is True
    assert verdict["gates"]["novelty"]["dominated_by"] == []
    fake_stab = dict(fake_css, name="4-1-3-s.json", code_type="stabilizer")
    monkeypatch.setattr(V, "_board_entries", lambda: [fake_stab])
    verdict = V.validate_candidate(doc, refute=False)
    assert verdict["gates"]["novelty"]["board_advancing"] is False


def test_record_cells_keep_the_boards_apart(tmp_path):
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "codes"))
    with open(os.path.join(root, "codes", "5-1-3.json"), "w") as f:
        json.dump(load_fixture("5-1-3"), f)
    # a CSS code that beats it on every axis
    css = {"n": 4, "k": 2, "distance": {"d": 3}, "code_type": "CSS",
           "checks": {"X": [[0, 1]], "Z": [[2, 3]]}}
    with open(os.path.join(root, "codes", "4-2-3.json"), "w") as f:
        json.dump(css, f)
    assert G.board_record_slugs(root) == {"5-1-3", "4-2-3"}


def test_site_records_are_per_board():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "site_build", os.path.join(ROOT, "site", "build.py"))
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    css = {"n": 4, "k": 2, "d": 3, "w": 2, "eff": 4.5, "code_type": "CSS",
           "locality_class": "unrestricted", "weight_class": "weight-4"}
    stab = dict(css, n=5, k=1, code_type="stabilizer", eff=1.8)
    assert build.compute_records([css, stab]) == {0, 1}
    keys = set(build.cells_by_key([css, stab]))
    assert ("unrestricted", "weight-4") in keys
    assert ("unrestricted", "weight-4", "stabilizer") in keys


# --- CLI input ----------------------------------------------------------------

def test_cli_loads_a_symplectic_npz_and_refuses_pure_rows(tmp_path):
    import qldpc as cli
    doc = load_fixture("18-2-3")
    A, B = Q.stabilizer_matrices(doc)
    p = os.path.join(str(tmp_path), "xzzx.npz")
    np.savez(p, s=np.concatenate([A, B], axis=1))
    A2, B2, coords, draft = cli.load_checks(p)
    assert draft == {"code_type": "stabilizer"} and coords is None
    assert (A2 == A).all() and (B2 == B).all()
    p2 = os.path.join(str(tmp_path), "xzzx_ab.npz")
    np.savez(p2, a=A, b=B)
    A3, B3, _, draft = cli.load_checks(p2)
    assert draft == {"code_type": "stabilizer"} and (A3 == A).all() and (B3 == B).all()
    steane = load_code("7-1-3")
    HX = Q._matrix(steane["checks"]["X"], 7)
    p3 = os.path.join(str(tmp_path), "steane.npz")
    np.savez(p3, a=HX, b=np.zeros_like(HX))
    a, b, _, draft = cli.load_checks(p3)

    class Args:
        trials, seed, fast_trials = 100, 0, 0
        authors, construction, date, model, notes, name, family = (
            ["@t"], "", "", "", "", "", None)
        _coords, layers, budget_json = None, 1, ""
    args = Args()
    for key in cli.BUDGET_KEYS:
        setattr(args, f"budget_{key}", None)
    with pytest.raises(SystemExit, match="pure X or pure Z"):
        cli.build_stabilizer_submission(a, b, args)
    sub = cli.build_stabilizer_submission(A, B, args)
    assert sub["code_type"] == "stabilizer" and sub["schema_version"] == "0.4"
    assert sub["distance"]["d"] == 3 and Q.verify(sub)["ok"]
    assert cli.schema_version_for(sub) == "0.4"
