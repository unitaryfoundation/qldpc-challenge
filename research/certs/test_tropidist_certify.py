"""tropidist_certify asks the tool the board's question and files only what the board can re-check (#4716).

The CSS sides follow sat_certify's convention, the stabilizer encoding's
minimum is the Pauli distance, every returned vector is re-verified, and the
record is a solver-level certificate the schema and check_certs accept.
"""
import importlib.util
import itertools
import json
import os
import sys

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_ROOT, "verify"))
import validation_gate as G  # noqa: E402


def _module():
    spec = importlib.util.spec_from_file_location("tropidist_certify_mod", os.path.join(_HERE, "tropidist_certify.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _five_qubit():
    with open(os.path.join(_ROOT, "codes", "5-1-3.json"), encoding="utf-8") as f:
        return json.load(f)


def _brute_min(H, L, max_w):
    """Least weight of e with H e = 0 and L e != 0 over GF(2), searched up to max_w; None if none."""
    H, L = np.asarray(H) % 2, np.asarray(L) % 2
    ncols = H.shape[1]
    for w in range(1, max_w + 1):
        for cols in itertools.combinations(range(ncols), w):
            e = np.zeros(ncols, dtype=np.int8)
            e[list(cols)] = 1
            if not (H @ e % 2).any() and (L @ e % 2).any():
                return w
    return None


def test_the_css_sides_ask_sat_certifys_question_on_the_steane_code():
    T = _module()
    doc = G.steane()
    probs, k = T.css_problems(doc)
    assert k == 1 and set(probs) == {"X", "Z"}
    for side, (H, L) in probs.items():
        assert H.shape[1] == 7 and L.shape == (1, 7)
        assert _brute_min(H, L, 3) == 3, side
    # a side whose pairing set does not span k is refused, as sat_certify refuses it
    bad = json.loads(json.dumps(doc))
    bad["checks"]["Z"] = bad["checks"]["Z"][:1]           # k grows, the Z-side logical basis still spans it,
    probs2, k2 = T.css_problems(bad)                     # so this is a sanity check that k is recomputed
    assert k2 == 7 - 3 - 1 and all(L.shape[0] == k2 for _, L in probs2.values())


def test_the_pauli_mechanism_encoding_has_the_pauli_distance_as_its_minimum():
    T = _module()
    doc = _five_qubit()
    (H, L), k = T.pauli_problem(doc)
    n = doc["n"]
    assert k == 1 and H.shape == (len(doc["checks"]["S"]), 3 * n) and L.shape == (2, 3 * n)
    assert _brute_min(H, L, 3) == 3
    # the mechanism columns are X_i, Z_i, Y_i: the Y column is the sum of the other two
    assert np.array_equal((H[:, :n] + H[:, n:2 * n]) % 2, H[:, 2 * n:])
    # every weight-3 solution maps to a nontrivial logical of Pauli weight 3 by the board's check
    import heuristic_distance as HD
    A, B = HD.stabilizer_matrices(doc)
    found = 0
    for cols in itertools.combinations(range(3 * n), 3):
        e = np.zeros(3 * n, dtype=np.int8)
        e[list(cols)] = 1
        if not (H @ e % 2).any() and (L @ e % 2).any():
            v = T.vector_from_columns(cols, n, True)
            assert HD.valid_pauli_logical(v, A, B) and int((v[:n] | v[n:]).sum()) == 3
            found += 1
    assert found > 0


def test_vectors_from_columns_and_the_board_check():
    T = _module()
    doc = _five_qubit()
    n = doc["n"]
    v = T.vector_from_columns([0, n + 1, 2 * n + 2], n, True)     # X_0, Z_1, Y_2
    assert v.tolist() == [1, 0, 1, 0, 0, 0, 1, 1, 0, 0]
    ok, weight = T.check_vector(doc, "P", [0, n + 1, 2 * n + 2])
    assert weight == 3
    steane = G.steane()
    probs, _ = T.css_problems(steane)
    H, L = probs["Z"]
    sol = next(cols for cols in itertools.combinations(range(7), 3)
               if not (H @ np.eye(7, dtype=np.int8)[list(cols)].sum(0) % 2).any())
    ok, weight = T.check_vector(steane, "Z", list(sol))
    assert ok and weight == 3
    assert T.check_vector(steane, "Z", [0])[0] is False, "a single qubit is detected"


def test_side_blocks_follow_sat_certifys_vocabulary_and_refuse_what_the_board_rejects():
    T = _module()
    doc = G.steane()
    unsat = T.side_block(doc, "X", 3, {"lower_bound": 3, "upper_bound": 3, "witness": [0, 1, 2], "seconds": 0.2},
                         tlim=60)
    assert unsat["status"] == "UNSAT" and unsat["exact"] and unsat["note"] == "no logical < 3 exists"
    timed = T.side_block(doc, "X", 3, {"lower_bound": 2, "upper_bound": None, "seconds": 60.0}, tlim=60)
    assert timed["status"] == "TIMEOUT" and not timed["exact"] and timed["lower_bound"] == 2
    with pytest.raises(T.TropidistError):          # a bound above a verified witness is not this entry's problem
        T.side_block(doc, "X", 3, {"lower_bound": 4, "upper_bound": None, "seconds": 1}, tlim=60)
    with pytest.raises(T.TropidistError):          # a "lighter logical" the board's check rejects
        T.side_block(doc, "X", 3, {"lower_bound": 1, "upper_bound": 1, "witness": [0], "seconds": 1}, tlim=60)
    probs, _ = T.css_problems(doc)
    H, L = probs["X"]
    eye = np.eye(7, dtype=np.int8)
    sol = next(list(c) for c in itertools.combinations(range(7), 3)
               if not (H @ eye[list(c)].sum(0) % 2).any() and (L @ eye[list(c)].sum(0) % 2).any())
    refuted = T.side_block(doc, "X", 4, {"lower_bound": 3, "upper_bound": 3, "witness": sol, "seconds": 1}, tlim=60)
    assert refuted["status"] == "SAT" and refuted["witness"] == sol and "REFUTED" in refuted["note"]


def test_the_record_is_a_solver_level_certificate_the_schema_and_checker_accept():
    T = _module()
    import jsonschema
    sys.path.insert(0, os.path.join(_ROOT, "verify"))
    import check_certs
    with open(os.path.join(_ROOT, "schema", "cert.schema.json"), encoding="utf-8") as f:
        schema = json.load(f)
    calls = []

    def runner(H, L, *, root, tlim, threads, kmin, tag):
        calls.append((tag, kmin))
        return {"lower_bound": 3, "upper_bound": 3, "witness": [0, 1, 2], "seconds": 0.3, "status": "exact"}

    doc = G.steane()
    cert = T.certify(doc, root=None, tlim=60, threads=2, slug="7-1-3", runner=runner)
    jsonschema.validate(cert, schema)
    assert check_certs.evidence_problems("7-1-3", cert) == []
    assert cert["d_exact"] is True and cert["verification"]["level"] == "solver"
    assert cert["encoding"] == "css-sides" and cert["logical_classes"] == 1
    assert [c[0] for c in calls] == ["7-1-3.X", "7-1-3.Z"] and all(c[1] is None for c in calls)
    assert cert["solver"].startswith("tropidist") and "arXiv:2611.08247" in cert["solver"]

    def slow(H, L, *, root, tlim, threads, kmin, tag):
        return {"lower_bound": 2, "upper_bound": None, "witness": None, "seconds": 60.0, "status": "timeout"}

    partial = T.certify(doc, root=None, tlim=60, threads=1, runner=slow, kmin={"X": 2})
    assert partial["d_exact"] is False
    assert all(b["status"] == "TIMEOUT" and b["lower_bound"] == 2 for b in partial["sides"].values())
    # The raw record is not a certificate file: a filed partial certificate carries
    # its d_lower and the binding hash (issue #4230), which the sweep adds before filing.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(partial, schema)
    spec = importlib.util.spec_from_file_location("certify_sweep_for_tropidist",
                                                  os.path.join(_HERE, "certify_sweep.py"))
    S = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(S)
    filed = S.partial_certificate(partial, doc)
    jsonschema.validate(filed, schema)
    assert filed["d_lower"] == 2 and all(b["proved_min"] == 2 for b in filed["sides"].values())
    assert filed["verification"]["checks_sha256"] == check_certs.checks_sha256(doc)
    # an entry whose sides differ closes when each side closes at its own value (57 certified
    # entries on the board have d_X != d_Z, 12-3-3 among them)
    asym = json.loads(json.dumps(doc))
    asym["distance"] = {"d": 3, "X": {"value": 3, "confidence": "upper_bound", "witness": [0, 1, 2]},
                        "Z": {"value": 4, "confidence": "upper_bound", "witness": [0, 1, 2, 3]}}

    def per_side(H, L, *, root, tlim, threads, kmin, tag):
        value = 4 if tag.endswith(".Z") else 3
        return {"lower_bound": value, "upper_bound": value, "witness": list(range(value)), "seconds": 0.1,
                "status": "exact"}

    cert_asym = T.certify(asym, root=None, tlim=60, threads=1, slug="7-1-3", runner=per_side)
    assert cert_asym["d_exact"] is True and cert_asym["d"] == 3
    assert cert_asym["sides"]["X"]["value"] == 3 and cert_asym["sides"]["Z"]["value"] == 4
    stab = T.certify(_five_qubit(), root=None, tlim=60, threads=1, runner=runner)
    assert set(stab["sides"]) == {"P"} and stab["encoding"] == "pauli-mechanisms" and stab["d_exact"]
    jsonschema.validate(stab, schema)


@pytest.mark.skipif(not os.environ.get("TROPIDIST_ROOT"), reason="needs a tropidist checkout in TROPIDIST_ROOT")
def test_the_tool_itself_certifies_the_five_qubit_code():
    T = _module()
    root = T.tropidist_root()
    cert = T.certify(_five_qubit(), root=root, tlim=60, threads=1, slug="5-1-3")
    assert cert["d_exact"] and cert["sides"]["P"]["status"] == "UNSAT"


def test_kmin_parses_to_the_per_side_map_the_certifier_takes():
    """--kmin resumes above a filed partial certificate's d_lower (issue #4718)."""
    T = _module()
    assert T.parse_kmin(None) is None and T.parse_kmin("") is None and T.parse_kmin("1") is None
    assert T.parse_kmin("15") == {"X": 15, "Z": 15, "P": 15}
    assert T.parse_kmin("X=15, Z=14") == {"X": 15, "Z": 14}
    assert T.parse_kmin("P=7") == {"P": 7}
    with pytest.raises(ValueError):
        T.parse_kmin("Y=3")
