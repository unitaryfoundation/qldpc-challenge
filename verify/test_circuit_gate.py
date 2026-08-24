"""
Tests for the circuit-tier refutation gate (RFC 0001 step 6, gate_changed):
an over-claimed d_circ must be caught by the bounded DEM search, an honest
claim must survive it, circuits/-only changes must still trigger the gate,
and unreadable artifacts must fail closed.

The over-claim fixture is organic: the default greedy schedule on the
[[25,1,5]] surface code has a hook error (true d_circ bound 3), and a
shallow 1-trial search returns a heavier valid witness -- exactly the
under-searched submission the gate exists to catch.

Run: uv run pytest verify/test_circuit_gate.py
"""

import copy
import json
import os

import pytest
import stim

import circuit_tools as ct
import gate_changed as gc
from qldpc_verify import _matrix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_DOC = json.load(open(os.path.join(ROOT, "codes", "25-1-5.json")))
N = BASE_DOC["n"]


@pytest.fixture(scope="module")
def greedy(tmp_path_factory):
    """(doc, circuits_dir) with the greedy-schedule circuits and, per basis,
    the lightest witness a 1-trial search finds -- an honest artifact carrying
    an under-searched claim wherever that weight exceeds the true bound."""
    d = tmp_path_factory.mktemp("circuits")
    HX = _matrix(BASE_DOC["checks"]["X"], N)
    HZ = _matrix(BASE_DOC["checks"]["Z"], N)
    doc = copy.deepcopy(BASE_DOC)
    doc["schema_version"] = "0.2"
    block = {"d_circ": {}, "rounds": 5, "stim_version": stim.__version__}
    for basis in ("Z", "X"):
        skel = ct.build_css_memory(HX, HZ, rounds=5, basis=basis)
        noisy = ct.apply_noise(skel, N)
        dem = ct.derive_dem(noisy)
        H, L = ct.dem_matrices(dem)
        w, wit = ct.ris_dem(H, L, trials=1, seed=2)
        assert ct.witness_errors(dem, wit, w) == []
        stem = os.path.join(d, f"memory_{basis.lower()}")
        open(stem + ".stim", "w").write(str(noisy) + "\n")
        open(stem + ".dem", "w").write(str(dem) + "\n")
        block["d_circ"][basis] = {"value": w, "confidence": "upper_bound",
                                  "witness": wit}
    doc["circuit"] = block
    return doc, str(d)


def test_overclaim_refuted(greedy):
    doc, d = greedy
    deep = {}
    for basis in ("Z", "X"):
        circuit = stim.Circuit(
            open(os.path.join(d, f"memory_{basis.lower()}.stim")).read())
        H, L = ct.dem_matrices(ct.derive_dem(circuit))
        deep[basis], _ = ct.ris_dem(H, L, trials=60, seed=9)
    over = [s for s in ("Z", "X")
            if doc["circuit"]["d_circ"][s]["value"] > deep[s]]
    assert over, "1-trial search matched the 60-trial bound; fixture is moot"
    hits, _ = gc._circuit_refute(doc, d, seed=9, trials_override=60)
    for s in over:
        assert s in hits
        w, wit, claim = hits[s]
        assert w < claim
        circuit = stim.Circuit(
            open(os.path.join(d, f"memory_{s.lower()}.stim")).read())
        assert ct.witness_errors(ct.derive_dem(circuit), wit, w) == []


def test_honest_claim_survives(greedy):
    """Claiming the deep-searched bound itself must not be refuted by the
    same search."""
    doc, d = greedy
    doc = copy.deepcopy(doc)
    for basis in ("Z", "X"):
        circuit = stim.Circuit(
            open(os.path.join(d, f"memory_{basis.lower()}.stim")).read())
        H, L = ct.dem_matrices(ct.derive_dem(circuit))
        w, wit = ct.ris_dem(H, L, trials=60, seed=9)
        doc["circuit"]["d_circ"][basis] = {
            "value": w, "confidence": "upper_bound", "witness": wit}
    hits, notes = gc._circuit_refute(doc, d, seed=9, trials_override=60)
    assert hits == {} and len(notes) == 2


def test_circuits_change_triggers_gate():
    paths = ["circuits/25-1-5/memory_z.stim", "codes/72-6-6.json",
             "circuits/25-1-5/memory_z.dem", "docs/index.html"]
    assert gc.map_changed(paths) == ["codes/25-1-5.json", "codes/72-6-6.json"]


def test_missing_artifacts_fail_closed(greedy, tmp_path):
    doc, _ = greedy
    with pytest.raises(Exception):
        gc._circuit_refute(doc, str(tmp_path), seed=0)


def test_circuit_gate_pricing():
    """circuit_gate_needed follows the diff-pricing principle (issue #654):
    search exactly when the circuit claim surface changed or never faced a
    gate; in particular a circuit-block-only edit -- which classifies as
    layout-only for the code tier -- must still be searched, and an untouched
    claim must not be."""
    blk = {"circuit": {"rounds": 5}, "distance": {}}
    blk2 = {"circuit": {"rounds": 6}, "distance": {}}
    plain = {"distance": {}}
    assert not gc.circuit_gate_needed(blk, plain, True)     # no claim, no gate
    assert gc.circuit_gate_needed(None, blk, False)         # new entry
    assert gc.circuit_gate_needed(blk2, blk, False)         # block edited
    assert gc.circuit_gate_needed(plain, blk, False)        # block added
    assert gc.circuit_gate_needed(blk, blk, True)           # .stim/.dem edited
    assert not gc.circuit_gate_needed(blk, blk, False)      # untouched claim


def test_circuit_block_edit_skips_code_tier_but_is_searched():
    """The load-bearing conjunction behind the main-loop wiring: a diff that
    only adds a circuit block classifies as layout-only for the CODE tier
    (checks and distance unchanged -- correct, that claim already survived),
    while circuit_gate_needed still demands the circuit search. If either
    half changes, the layout-only skip path must be re-examined so it never
    skips the claim that actually changed."""
    base = {"code_type": "CSS", "n": 25, "k": 1,
            "checks": BASE_DOC["checks"], "distance": BASE_DOC["distance"]}
    new = copy.deepcopy(base)
    new["circuit"] = {"rounds": 5}
    cls, _ = gc.classify_diff(base, new)
    assert cls == "layout-only"
    assert gc.circuit_gate_needed(base, new, False)


def test_budget_shape():
    t_small, _ = gc._circuit_budget(1700, fast=True)
    t_mid, _ = gc._circuit_budget(8000, fast=True)
    t_cap, _ = gc._circuit_budget(25_000, fast=True)
    t_py, _ = gc._circuit_budget(8000, fast=False)
    assert t_small == gc.CIRCUIT_MAX_TRIALS      # small DEMs get full depth
    assert t_cap >= gc.CIRCUIT_MIN_TRIALS        # cap sized to stay feasible
    assert 0 < t_py < t_mid <= t_small           # fallback shallower, never zero


def test_dem_wall_cap_stops_after_opener(monkeypatch):
    """#684 review regression, load-independent form (the first version
    asserted wall-clock seconds, which asserts the speed of the box and
    flaked on a loaded machine with the fix working correctly): a C++ chunk
    cannot be aborted, so when the opener chunk reveals the cap is already
    unaffordable the loop must stop after that single small chunk -- no
    second chunk, ever. The pre-fix loop issued a blind 64-trial first
    chunk, so this fails against it deterministically, in milliseconds."""
    import time
    import types
    import numpy as np
    calls = []

    def stub(H, L, trials, seed, pair_depth, threads):
        calls.append(trials)
        time.sleep(0.05)              # any nonzero cost blows a 1 ms cap
        return None, None

    monkeypatch.setattr(ct, "_GF",
                        types.SimpleNamespace(dem_rand_witness=stub))
    H = np.zeros((2, 8), dtype=np.int8)
    H[0, 0] = H[1, 1] = 1
    L = np.zeros((1, 8), dtype=np.int8)
    L[0, 7] = 1
    ct.ris_dem(H, L, trials=20000, seed=3, max_seconds=0.001)
    assert calls == [8], f"expected only the opener chunk, got {calls}"
