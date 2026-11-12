"""
Adversarial tests for the circuit-tier verifier (RFC 0001, issue #505): it
must ACCEPT a valid circuit-tier artifact and REJECT every way a circuit
claim can be wrong -- a tampered witness, a stale DEM, non-canonical noise, a
circuit that is not a memory experiment of the declared code, an inflated
round count, an unpinned stim.

The known-good artifact is generated once per run from the board's
[[25,1,5]] surface entry with the toolkit's own builder + searcher (the same
loop a submitter runs), so these tests need no committed circuits/ artifact
and gate the trusted stack independently of any submission. The default
greedy schedule's d_circ is below d (a hook error -- the phenomenon the tier
exists to expose); that is fine here: these tests exercise the validity of
claims, not schedule quality. Each tamper then breaks exactly one thing and
asserts the specific check catches it.

Run: uv run pytest verify/test_circuit_verify.py
"""

import copy
import json
import os
import shutil

import pytest
import stim

import circuit_tools as ct
import circuit_verify as cv
from qldpc_verify import _matrix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_DOC = json.load(open(os.path.join(ROOT, "codes", "25-1-5.json")))
N = BASE_DOC["n"]


@pytest.fixture(scope="module")
def seed(tmp_path_factory):
    """(doc, circuits_dir): a complete valid artifact -- both memory circuits
    with canonical noise, committed DEMs, and a circuit block whose witnesses
    the toolkit search found."""
    d = tmp_path_factory.mktemp("circuits")
    HX = _matrix(BASE_DOC["checks"]["X"], N)
    HZ = _matrix(BASE_DOC["checks"]["Z"], N)
    doc = copy.deepcopy(BASE_DOC)
    doc["schema_version"] = "0.2"
    block = {"d_circ": {}, "rounds": 5, "stim_version": stim.__version__,
             "notes": "test artifact, default greedy schedule"}
    for basis in ("Z", "X"):
        skel = ct.build_css_memory(HX, HZ, rounds=5, basis=basis)
        noisy = ct.apply_noise(skel, N)
        dem = ct.derive_dem(noisy)
        H, L = ct.dem_matrices(dem)
        w, wit = ct.ris_dem(H, L, trials=8, seed=5)
        stem = os.path.join(d, f"memory_{basis.lower()}")
        open(stem + ".stim", "w").write(str(noisy) + "\n")
        open(stem + ".dem", "w").write(str(dem) + "\n")
        block["d_circ"][basis] = {"value": w, "confidence": "upper_bound",
                                  "witness": wit}
    doc["circuit"] = block
    return doc, str(d)


def _status(report, label):
    return next(c["ok"] for c in report["checks"] if c["check"] == label)


def _tampered_dir(seed_dir, tmp_path, filename, edit):
    d = tmp_path / "circuits"
    shutil.copytree(seed_dir, d)
    p = d / filename
    p.write_text(edit(p.read_text()))
    return str(d)


def test_generated_artifact_passes(seed):
    doc, d = seed
    report = cv.verify_circuit(doc, d)
    assert report["ok"], report
    want = min(doc["circuit"]["d_circ"][s]["value"] for s in ("X", "Z"))
    assert report["earned_d_circ"]["d_circ"] == {"value": want,
                                                 "tier": "upper_bound"}


def test_missing_files_rejected(seed, tmp_path):
    doc, _ = seed
    report = cv.verify_circuit(doc, str(tmp_path))
    assert not report["ok"]
    assert not _status(report, "X_circuit_files")


def test_tampered_witness_rejected(seed):
    doc, d = seed
    doc = copy.deepcopy(doc)
    doc["circuit"]["d_circ"]["Z"]["witness"] = \
        doc["circuit"]["d_circ"]["Z"]["witness"][:-1]      # weight != value
    report = cv.verify_circuit(doc, d)
    assert not _status(report, "Z_witness_valid")

    w = doc["circuit"]["d_circ"]["Z"]["value"]
    doc["circuit"]["d_circ"]["Z"]["witness"] = list(range(w))  # detected junk
    report = cv.verify_circuit(doc, d)
    assert not _status(report, "Z_witness_valid")


def test_claim_above_code_distance_rejected(seed):
    doc, d = seed
    doc = copy.deepcopy(doc)
    side = doc["circuit"]["d_circ"]["Z"]
    side["witness"] = side["witness"] + [side["witness"][-1] + 1]
    side["value"] = len(side["witness"])
    while side["value"] <= doc["distance"]["d"]:   # inflate past the clamp
        side["witness"].append(side["witness"][-1] + 1)
        side["value"] += 1
    report = cv.verify_circuit(doc, d)
    assert not _status(report, "Z_witness_valid")


def test_stale_dem_rejected(seed, tmp_path):
    doc, sd = seed
    d = _tampered_dir(sd, tmp_path, "memory_z.dem",
                      lambda t: t.replace("error(0.00", "error(0.01", 1))
    report = cv.verify_circuit(doc, d)
    assert not _status(report, "Z_dem_reproduces")


def test_missing_noise_channel_rejected(seed, tmp_path):
    def drop_first_dep2(t):
        lines = t.splitlines()
        i = next(j for j, l in enumerate(lines)
                 if l.startswith("DEPOLARIZE2"))
        return "\n".join(lines[:i] + lines[i + 1:]) + "\n"
    doc, sd = seed
    d = _tampered_dir(sd, tmp_path, "memory_z.stim", drop_first_dep2)
    report = cv.verify_circuit(doc, d)
    assert not _status(report, "Z_noise_recipe_canonical")


def test_wrong_noise_rate_rejected(seed, tmp_path):
    doc, sd = seed
    d = _tampered_dir(sd, tmp_path, "memory_z.stim",
                      lambda t: t.replace("DEPOLARIZE2(0.001)",
                                          "DEPOLARIZE2(0.002)", 1))
    report = cv.verify_circuit(doc, d)
    assert not _status(report, "Z_noise_recipe_canonical")


def test_nondeterministic_detector_rejected(seed, tmp_path):
    def break_detector(t):
        i = t.index("DETECTOR rec[")
        j = t.index("\n", i)
        return t[:i] + "DETECTOR rec[-1]" + t[j:]   # lone data M: random
    doc, sd = seed
    d = _tampered_dir(sd, tmp_path, "memory_z.stim", break_detector)
    report = cv.verify_circuit(doc, d)
    assert not _status(report, "Z_detectors_deterministic")


def test_inflated_round_count_rejected(seed):
    doc, d = seed
    doc = copy.deepcopy(doc)
    doc["circuit"]["rounds"] = 6            # circuit only performs 5
    report = cv.verify_circuit(doc, d)
    assert not _status(report, "Z_code_binding")


def test_unpinned_stim_version_rejected(seed):
    doc, d = seed
    doc = copy.deepcopy(doc)
    doc["circuit"]["stim_version"] = "1.0.0"
    report = cv.verify_circuit(doc, d)
    assert not _status(report, "stim_version_pinned")


def test_stabilizer_observable_rejected(seed, tmp_path):
    """An observable that is a product of declared stabilizers protects
    nothing; binding must reject it even though it is deterministic."""
    doc, sd = seed
    text = open(os.path.join(sd, "memory_z.stim")).read()
    lines = [l for l in text.splitlines()
             if not l.startswith("OBSERVABLE_INCLUDE")]
    row = BASE_DOC["checks"]["Z"][0]        # final data M of qubit q: rec[q-n]
    lines.append("OBSERVABLE_INCLUDE(0) " +
                 " ".join(f"rec[{q - N}]" for q in row))
    d = tmp_path / "circuits"
    shutil.copytree(sd, d)
    noisy = stim.Circuit("\n".join(lines))
    (d / "memory_z.stim").write_text(str(noisy) + "\n")
    (d / "memory_z.dem").write_text(str(ct.derive_dem(noisy)) + "\n")
    report = cv.verify_circuit(doc, str(d))
    assert not _status(report, "Z_code_binding")


def test_tick_coarsening_rejected():
    """vprusso's #646 review: idle-data mechanisms scale with TICK layer
    count, so deleting TICKs -- pure annotations -- shed fault mechanisms and
    inflated d_circ while staying recipe-conformant. Coarsening that claims
    impossible simultaneity (a qubit operated on twice in one layer) must now
    be rejected; merging genuinely disjoint layers -- real pipelining --
    stays legal."""
    HX = _matrix(BASE_DOC["checks"]["X"], N)
    HZ = _matrix(BASE_DOC["checks"]["Z"], N)
    skel = ct.build_css_memory(HX, HZ, rounds=2, basis="Z")
    lines = str(skel).splitlines()

    # all TICKs deleted: one giant "layer" reusing every ancilla
    coarse = stim.Circuit("\n".join(l for l in lines if l != "TICK"))
    noisy = ct.apply_noise(coarse, N)
    errs = ct.noise_recipe_errors(noisy, N)
    assert errs and "parallel" in errs[0]
    assert ct.derive_dem(noisy).num_errors < \
        ct.derive_dem(ct.apply_noise(skel, N)).num_errors      # the lever

    # merging two DISJOINT layers (MX on X-ancillas, then R on Z-ancillas)
    # is honest pipelining and must stay conformant
    i = next(j for j, l in enumerate(lines) if l.startswith("MX "))
    assert lines[i + 1] == "TICK" and lines[i + 2].startswith("R ")
    merged = stim.Circuit("\n".join(lines[:i + 1] + lines[i + 2:]))
    assert ct.noise_recipe_errors(ct.apply_noise(merged, N), N) == []


def test_dem_matches_unit():
    """Probabilities compare to float tolerance (last ulps are architecture-
    sensitive: an honest artifact from another machine must pass), but any
    structural difference -- and any real probability tamper -- must not."""
    a = stim.DetectorErrorModel("error(0.0044999999999999) D0 D1 L0")
    assert ct.dem_matches(a, stim.DetectorErrorModel(
        "error(0.0045000000000001) D0 D1 L0"))          # ulp drift: honest
    assert not ct.dem_matches(a, stim.DetectorErrorModel(
        "error(0.0046) D0 D1 L0"))                      # real tamper
    assert not ct.dem_matches(a, stim.DetectorErrorModel(
        "error(0.0045) D0 D2 L0"))                      # structure
    assert not ct.dem_matches(a, stim.DetectorErrorModel(
        "error(0.0045) D0 D1"))                         # observable dropped
    assert not ct.dem_matches(a, a + stim.DetectorErrorModel(
        "error(0.0045) D1"))                            # extra mechanism


def test_witness_errors_unit():
    dem = stim.DetectorErrorModel("""
        error(0.1) D0 L0
        error(0.1) D0
        error(0.1) D1
    """)
    assert ct.witness_errors(dem, [0, 1], 2) == []
    assert ct.witness_errors(dem, [0], 1)            # detected
    assert ct.witness_errors(dem, [1, 2], 2)         # flips nothing
    assert ct.witness_errors(dem, [0, 1], 3)         # weight mismatch
    assert ct.witness_errors(dem, [1, 0], 2)         # not sorted
    assert ct.witness_errors(dem, [0, 9], 2)         # out of range


def test_search_matches_witness_check():
    """The toolkit loop an agent runs: build, search, self-check -- the same
    arithmetic CI applies."""
    HX = _matrix(BASE_DOC["checks"]["X"], N)
    HZ = _matrix(BASE_DOC["checks"]["Z"], N)
    skel = ct.build_css_memory(HX, HZ, rounds=2, basis="Z")
    noisy = ct.apply_noise(skel, N)
    assert ct.noise_recipe_errors(noisy, N) == []
    dem = ct.derive_dem(noisy)
    H, L = ct.dem_matrices(dem)
    w, wit = ct.ris_dem(H, L, trials=8, seed=3)
    assert w is not None and w <= 5      # rounds-truncated: can only be <= d
    assert ct.witness_errors(dem, wit, w) == []


def test_dem_lint_clean_on_reference():
    """The reference builder's DEM must pass all three structural checks
    (issue #690); a false positive here would block every honest entry."""
    HX = _matrix(BASE_DOC["checks"]["X"], N)
    HZ = _matrix(BASE_DOC["checks"]["Z"], N)
    dem = ct.derive_dem(ct.apply_noise(
        ct.build_css_memory(HX, HZ, rounds=2, basis="Z"), N))
    assert ct.dem_lint(dem) == []


def test_dem_lint_detectability():
    # a mechanism flipping an observable with no detector = d_circ 1
    dem = stim.DetectorErrorModel("""
        error(0.001) D0 L0
        error(0.001) L0
        error(0.001) D0
    """)
    errs = ct.dem_lint(dem)
    assert any(e.startswith("detectability") and "[1]" in e for e in errs), errs


def test_dem_lint_observable_coverage():
    # L1 declared (via the max observable index) but never flipped
    dem = stim.DetectorErrorModel("""
        error(0.001) D0 L0
        detector D1
        logical_observable L1
    """)
    errs = ct.dem_lint(dem)
    assert any(e.startswith("observable_coverage") and "[1]" in e
               for e in errs), errs


def test_dem_lint_probability_bounds():
    # stim refuses NaN at parse time, so construct the edge cases it allows:
    # an exact-zero and an exact-one probability are both meaningless priors.
    dem = stim.DetectorErrorModel("""
        error(0) D0 L0
        error(1) D0
        error(0.001) D0 L0
    """)
    errs = ct.dem_lint(dem)
    assert any(e.startswith("probability_bounds") and "[0, 1]" in e
               for e in errs), errs


def test_dem_lint_gates_the_verifier(seed, monkeypatch):
    """A structurally broken derived DEM must fail circuit_verify at the new
    step 5.5 and stop before the witness check."""
    doc, cdir = seed
    monkeypatch.setattr(ct, "dem_lint",
                        lambda dem: ["detectability: injected failure"])
    rep = cv.verify_circuit(doc, cdir)
    assert not rep["ok"]
    bad = {c["check"]: c["detail"] for c in rep["checks"] if not c["ok"]}
    assert any(k.endswith("_dem_structure") for k in bad), bad
    checked = [c["check"] for c in rep["checks"]]
    assert not any(k.endswith("_witness_valid") for k in checked), (
        "witness check ran on a malformed DEM")


# ---------------------------------------- gate set: every instruction is read

def test_classical_control_is_refused_wherever_it_appears():
    """The gate-set check reads every instruction. It used to read the first
    instruction of each gate name, so a classically controlled gate after a
    plain one of the same name passed it, and the noise recipe step then
    raised on the DEPOLARIZE2 it tried to place."""
    plain = "R 0 1\nTICK\nCX 0 1\nTICK\nM 0\nTICK\n"
    assert ct.skeleton_errors(stim.Circuit(plain + "CX 1 0\nTICK\nM 1")) == []
    for late in ("CX rec[-1] 1", "CZ rec[-1] 1", "CX sweep[0] 1",
                 "CX 0 1 rec[-1] 1"):
        circuit = stim.Circuit(plain + late + "\nTICK\nM 1")
        errs = ct.skeleton_errors(circuit)
        name = late.split()[0]
        assert errs == [f"{name} with a non-qubit target (classical control) "
                        f"is outside the circuit-tier gate set"], (late, errs)
        # the recipe check reports it and does not raise (the mixed
        # instruction also reuses a qubit within its layer, a second error)
        assert ct.noise_recipe_errors(circuit, 2)[:1] == errs, late
    # still refused where it always was: on the first instruction of a name
    assert ct.skeleton_errors(stim.Circuit(
        "R 0 1\nTICK\nCX rec[-1] 1\nTICK\nM 0 1")) != []


def test_gate_set_errors_are_named_once_per_gate():
    """One line per offending gate name, however often it recurs: the report
    of a long circuit stays readable."""
    circuit = stim.Circuit(
        "R 0 1\nTICK\nCX 0 1\nTICK\nM 0\nTICK\nCX rec[-1] 1\nTICK\n"
        "CX rec[-1] 0\nTICK\nMR 0\nTICK\nCZ sweep[1] 0\nTICK\nMR 1\nTICK\n"
        "CX 0 1\nTICK\nM 0 1")
    errs = ct.skeleton_errors(circuit)
    assert len(errs) == 3, errs
    assert sum("CX with a non-qubit target" in e for e in errs) == 1
    assert sum("CZ with a non-qubit target" in e for e in errs) == 1
    assert sum("instruction MR is outside" in e for e in errs) == 1


def test_late_classical_control_fails_the_entry_cleanly(seed, tmp_path):
    """End to end: a feedback gate appended after the final measurements
    leaves every detector deterministic, so the verifier reaches the noise
    recipe step. That step must fail the entry, not raise out of
    verify_circuit, where it would end the whole sweep on a traceback."""
    doc, sd = seed
    d = _tampered_dir(sd, tmp_path, "memory_z.stim",
                      lambda text: text.rstrip("\n") + "\nTICK\nCX rec[-1] 0\n")
    report = cv.verify_circuit(doc, d)
    assert not report["ok"]
    assert _status(report, "Z_detectors_deterministic")
    assert not _status(report, "Z_noise_recipe_canonical")
    detail = next(c["detail"] for c in report["checks"]
                  if c["check"] == "Z_noise_recipe_canonical")
    assert "CX with a non-qubit target" in detail, detail
    assert _status(report, "X_noise_recipe_canonical")     # X is untouched
