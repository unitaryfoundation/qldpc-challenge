"""Tests for the measured logical-error-rate tier.

The known-good artifact is generated in-test with the toolkit's own builder
and measurement, then each tamper must be caught by its specific check:
misreported failures (the gaming direction: claiming a lower rate than the
circuit earns), broken block arithmetic, and an unpinned decoder. Statistical
checks use budgets far inside the Z_GATE = 4 acceptance band, so these tests
are deterministic in practice for a fixed stim version.

Needs ldpc; skips as a module without it (the CI verify job installs the
`research` extra, so there the tier is exercised, not skipped).
"""

import copy
import json
import os
import tempfile

import numpy as np
import pytest

pytest.importorskip("ldpc", reason="ler tier needs the `research` extra")
import stim

import circuit_tools as ct
import ler_measure as lm
import ler_receipts as lr
import ler_tools as lt
import ler_verify as lv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = 12_000          # >= lt.MIN_SHOTS, and ~1s per measurement on Steane
ROUNDS = 3


def _steane():
    doc = json.load(open(os.path.join(ROOT, "codes", "7-1-3.json")))
    n = doc["n"]

    def M(sup):
        H = np.zeros((len(sup), n), dtype=np.int8)
        for r, s in enumerate(sup):
            for q in s:
                H[r, q] ^= 1
        return H
    return doc, M(doc["checks"]["X"]), M(doc["checks"]["Z"])


def _artifact(tmp):
    """A codes/-shaped doc plus committed circuits, with a genuine measured
    ler block per basis."""
    doc, HX, HZ = _steane()
    slug = "7-1-3"
    cdir = os.path.join(tmp, "circuits", slug)
    os.makedirs(cdir)
    ler = {}
    for basis, fname in (("X", "memory_x"), ("Z", "memory_z")):
        skel = ct.build_css_memory(HX, HZ, ROUNDS, basis=basis, sched_seed=0)
        noisy = ct.apply_noise(skel, doc["n"])
        with open(os.path.join(cdir, fname + ".stim"), "w") as f:
            f.write(str(noisy))
        dem = ct.derive_dem(noisy)
        with open(os.path.join(cdir, fname + ".dem"), "w") as f:
            f.write(str(dem))
        # two points of the curve (issue #1278): the canonical rate and a
        # higher one where failures are common, which is the gate point
        ler[basis] = [
            lm.measure_point(noisy, doc["n"], ROUNDS, 0.005, 7, shots=SHOTS,
                             log=lambda s: None),
            lt.ler_block(dem, ROUNDS, SHOTS, seed=7, p_ref=ct.P_REF)]
    doc = copy.deepcopy(doc)
    doc["schema_version"] = "0.5"
    doc["circuit"] = {"d_circ": {}, "rounds": ROUNDS,
                      "stim_version": stim.__version__, "ler": ler}
    return doc, cdir


def _legacy(doc):
    """The same artifact in the pre-0.5 single-object form at schema 0.4."""
    leg = copy.deepcopy(doc)
    leg["schema_version"] = "0.4"
    leg["circuit"]["ler"] = {
        s: next(q for q in doc["circuit"]["ler"][s] if q["p"] == ct.P_REF)
        for s in ("X", "Z")}
    return leg


def _recompute(blk):
    p = blk["failures"] / blk["shots"]
    blk["ler_per_round"] = round(lt.per_round(p, ROUNDS), 9)
    lo, hi = lt.wilson_ci(blk["failures"], blk["shots"])
    blk["ci95"] = [round(lt.per_round(lo, ROUNDS), 9),
                   round(lt.per_round(hi, ROUNDS), 9)]


@pytest.fixture(scope="module")
def artifact():
    with tempfile.TemporaryDirectory() as tmp:
        yield _artifact(tmp)


def test_honest_claim_verifies(artifact):
    doc, cdir = artifact
    rep = lv.verify_ler(doc, cdir)
    assert rep["ok"], [c for c in rep["checks"] if not c["ok"]]


def test_underreported_failures_rejected(artifact):
    # The gaming direction: claim HALF the real failures, i.e. a 2x better
    # code than the circuit earns. Arithmetic is kept consistent and the
    # count stays above MIN_FAILURES, so only the replication check can
    # catch it -- and a 2x under-report is precisely the case a fixed-size
    # replica let through before the replica was sized to discriminate.
    doc, cdir = artifact
    doc = copy.deepcopy(doc)
    for s in ("X", "Z"):
        for blk in doc["circuit"]["ler"][s]:
            blk["failures"] = max(lt.MIN_FAILURES, blk["failures"] // 2)
            _recompute(blk)
    rep = lv.verify_ler(doc, cdir)
    assert not rep["ok"]
    bad = [c["check"] for c in rep["checks"] if not c["ok"]]
    assert any(c.endswith("_ler_replicated") for c in bad), bad


def test_broken_arithmetic_rejected(artifact):
    doc, cdir = artifact
    doc = copy.deepcopy(doc)
    doc["circuit"]["ler"]["X"][0]["ler_per_round"] *= 1.5
    rep = lv.verify_ler(doc, cdir)
    bad = [c["check"] for c in rep["checks"] if not c["ok"]]
    assert "X_ler_arithmetic" in bad


def test_unregistered_decoder_rejected(artifact):
    doc, cdir = artifact
    doc = copy.deepcopy(doc)
    doc["circuit"]["ler"]["Z"][1]["decoder"] = "foo"
    rep = lv.verify_ler(doc, cdir)
    bad = [c["check"] for c in rep["checks"] if not c["ok"]]
    assert "Z_ler_arithmetic" in bad


def _noisy(cdir, basis, p):
    circuit = stim.Circuit.from_file(os.path.join(cdir, lv.SIDE_FILES[basis] + ".stim"))
    return ct.apply_noise(ct.strip_noise(circuit), 7, p=p)


@pytest.fixture(scope="module")
def multi(artifact):
    """The artifact plus a second curve per basis under the other registry
    decoders, one point each at p = 0.005 (issue #5804)."""
    doc, cdir = artifact
    doc = copy.deepcopy(doc)
    for basis in ("X", "Z"):
        circuit = stim.Circuit.from_file(os.path.join(cdir, lv.SIDE_FILES[basis] + ".stim"))
        for dec in ("bplsd-cs-10", "bp-ms-30", "mwpm"):
            doc["circuit"]["ler"][basis].append(
                lm.measure_point(circuit, doc["n"], ROUNDS, 0.005, 7, shots=SHOTS,
                                 log=lambda s: None, decoder=dec))
    return doc, cdir


def test_registry_decoders_measure_and_verify(multi):
    doc, cdir = multi
    for basis in ("X", "Z"):
        decs = [q["decoder"] for q in doc["circuit"]["ler"][basis]]
        assert sorted(decs) == sorted(["bposd-cs-10", "bposd-cs-10", "bplsd-cs-10",
                                       "bp-ms-30", "mwpm"])
    rep = lv.verify_ler(doc, cdir)
    assert rep["ok"], [c for c in rep["checks"] if not c["ok"]]
    labels = {c["check"] for c in rep["checks"]}
    assert {"Z_ler_replicated", "Z_ler_replicated_bplsd-cs-10",
            "Z_ler_replicated_bp-ms-30", "Z_ler_replicated_mwpm"} <= labels
    pts = rep["computed"]["Z"]["points"]
    assert "0.005" in pts and "0.005@mwpm" in pts and "0.005@bp-ms-30" in pts
    assert pts["0.005@mwpm"]["decoder"] == "mwpm"
    # the headline reads the reference decoder only
    assert lv.summary_rate(doc) == lv.summary_rate(_artifact_doc_only(doc))
    assert lv.gate_point(doc["circuit"]["ler"]["Z"])["decoder"] == "bposd-cs-10"
    assert lv.gate_point(doc["circuit"]["ler"]["Z"], "mwpm")["decoder"] == "mwpm"


def _artifact_doc_only(doc):
    """The same document with every non-reference point removed."""
    d = copy.deepcopy(doc)
    for basis in ("X", "Z"):
        d["circuit"]["ler"][basis] = [q for q in d["circuit"]["ler"][basis]
                                      if q["decoder"] == lt.DECODER_ID]
    return d


def test_each_decoder_gets_its_own_gate_budget(multi, monkeypatch):
    doc, cdir = multi
    calls = []
    real = lv.replicate_point

    def spy(dem, point, **kw):
        calls.append((point["p"], point["decoder"]))
        return real(dem, point, **kw)
    monkeypatch.setattr(lv, "replicate_point", spy)
    rep = lv.verify_ler(doc, cdir, budget=60)
    assert rep["ok"]
    # every decoder's top point was tried in the gate, each with its own budget
    assert {(0.005, d) for d in ("bposd-cs-10", "bplsd-cs-10", "bp-ms-30", "mwpm")} <= set(calls)


def test_same_rate_and_decoder_twice_rejected(multi):
    doc, cdir = multi
    doc = copy.deepcopy(doc)
    doc["circuit"]["ler"]["X"].append(copy.deepcopy(doc["circuit"]["ler"]["X"][-1]))
    rep = lv.verify_ler(doc, cdir)
    bad = {c["check"]: c["detail"] for c in rep["checks"] if not c["ok"]}
    assert "X_ler_arithmetic" in bad and "appears twice" in bad["X_ler_arithmetic"]


def test_matching_is_refused_where_stim_cannot_decompose(multi, monkeypatch):
    doc, cdir = multi
    circuit = stim.Circuit("""
        X_ERROR(0.1) 0
        CX 0 1 0 2
        M 0 1 2
        DETECTOR rec[-1]
        DETECTOR rec[-2]
        DETECTOR rec[-3]
        OBSERVABLE_INCLUDE(0) rec[-1]
    """)
    ok, why = lt.decoder_admits("mwpm", circuit)
    assert not ok and "decompose" in why
    assert lt.decoder_admits("bposd-cs-10", circuit) == (True, "")
    # the canonical recipe re-noises a circuit before measuring, so stand in
    # for a model stim cannot decompose from here on
    monkeypatch.setattr(lt, "decomposed_dem",
                        lambda c: (_ for _ in ()).throw(ValueError("Failed to decompose")))
    fixture = stim.Circuit.from_file(os.path.join(cdir, "memory_z.stim"))
    with pytest.raises(ValueError):
        lm.measure_point(fixture, doc["n"], ROUNDS, 0.005, 1, shots=SHOTS,
                         log=lambda s: None, decoder="mwpm")
    # a claim under mwpm on a circuit the registry does not admit fails as a claim
    rep = lv.verify_ler(doc, cdir)
    bad = [c["check"] for c in rep["checks"] if not c["ok"]]
    assert "Z_ler_decoder_mwpm" in bad and "Z_ler_arithmetic" not in bad
    assert rep["computed"]["Z"]["points"]["0.005@mwpm"]["status"] == "inadmissible"


def test_receipt_keys_points_by_decoder(multi, tmp_path):
    doc, cdir = multi
    rep = lv.verify_ler(doc, cdir, mode="all", budget=60, seeds=1)
    digest = lr.claim_digest(doc, cdir)
    receipt = lr.make_receipt("7-1-3", digest, rep, head_sha="deadbeef")
    lr.write_receipt(str(tmp_path), receipt)
    back = lr.load_receipt(str(tmp_path), "7-1-3")
    assert "0.005@mwpm" in back["points"]["X"] and "0.005" in back["points"]["X"]
    assert lr.point_status(back, digest, "X", 0.005, "mwpm") == "verified"
    assert lr.point_status(back, digest, "X", 0.005) == "verified"
    assert lr.point_status(back, digest, "X", 0.002, "mwpm") == "pending"


def test_measure_cli_takes_a_registry_decoder(artifact, tmp_path):
    doc, cdir = artifact
    path = tmp_path / "7-1-3.json"
    path.write_text(json.dumps(doc, indent=1) + "\n")
    rc = lm.main([str(path), "--p", "0.005", "--shots", str(SHOTS), "--seed", "7",
                  "--decoder", "bp-ms-30", "--circuits-dir", cdir])
    assert rc == 0
    out = json.loads(path.read_text())
    for basis in ("X", "Z"):
        decs = [q["decoder"] for q in out["circuit"]["ler"][basis]]
        assert decs.count("bp-ms-30") == 1 and decs.count("bposd-cs-10") == 2
    assert lv.verify_ler(out, cdir)["ok"]
    with pytest.raises(SystemExit):
        lm.main([str(path), "--p", "0.005", "--decoder", "nope", "--circuits-dir", cdir])


def test_shots_floor_rejected(artifact):
    doc, cdir = artifact
    doc = copy.deepcopy(doc)
    blk = doc["circuit"]["ler"]["X"][0]
    blk["shots"], blk["failures"] = 500, 3
    rep = lv.verify_ler(doc, cdir)
    bad = [c["check"] for c in rep["checks"] if not c["ok"]]
    assert "X_ler_arithmetic" in bad


def test_measurement_deterministic(artifact):
    # Same seed, same platform, same stim: the measurement must reproduce
    # exactly. (Cross-platform exactness is deliberately NOT claimed; the
    # verifier is statistical for that reason.)
    doc, cdir = artifact
    circuit = stim.Circuit.from_file(os.path.join(cdir, "memory_x.stim"))
    dem = ct.derive_dem(circuit)
    assert (lt.measure_failures(dem, 4000, seed=11)
            == lt.measure_failures(dem, 4000, seed=11))


def test_failures_floor_rejected(artifact):
    # A claim below MIN_FAILURES certifies an order of magnitude, not a
    # comparison; the arithmetic check refuses it outright.
    doc, cdir = artifact
    doc = copy.deepcopy(doc)
    blk = doc["circuit"]["ler"]["X"][1]
    blk["shots"], blk["failures"] = 40_000, 30
    _recompute(blk)
    rep = lv.verify_ler(doc, cdir)
    bad = {c["check"]: c["detail"] for c in rep["checks"] if not c["ok"]}
    assert "X_ler_arithmetic" in bad and "below the floor" in bad["X_ler_arithmetic"]


def _starve_replica(monkeypatch):
    """Make every replica come back truncated to a handful of shots, as a
    wall budget that expires mid-run does. Patched rather than timed: the
    parallel decode loop stops on a chunk boundary, and a chunk on a
    many-core box is small enough to be unverifiable while the same chunk
    on a four-core runner already verifies a high-rate point, so a test
    that sets a tiny LER_SECONDS asserts the core count of the machine."""
    def starved(dem, shots, seed, max_seconds=None, workers=None, **kw):
        return 1, 20
    monkeypatch.setattr(lv.lt, "measure_failures", starved)


def test_budget_truncation_fails_unverifiable(artifact, monkeypatch):
    # When the wall budget cannot afford a replica that would catch a 2x
    # under-report, the claim must fail as unverifiable rather than merge
    # weakly checked (the tier's stated budget-vs-statistics choice).
    doc, cdir = artifact
    _starve_replica(monkeypatch)
    rep = lv.verify_ler(doc, cdir)
    bad = {c["check"]: c["detail"] for c in rep["checks"] if not c["ok"]}
    assert any(k.endswith("_ler_replicated") for k in bad)
    assert any("unverifiable within budget" in v for v in bad.values())


def test_replica_sized_to_discriminate(artifact):
    # The replica targets REPLICA_FAILURES expected failures, so its shot
    # count must scale with 1/p_claim, not sit at a constant.
    doc, cdir = artifact
    rep = lv.verify_ler(doc, cdir)
    assert rep["ok"]
    for s in ("X", "Z"):
        for blk in doc["circuit"]["ler"][s]:
            p = blk["failures"] / blk["shots"]
            want = min(max(lt.MIN_SHOTS,
                           __import__("math").ceil(lv.REPLICA_FAILURES / p)),
                       lv.REPLICA_SHOTS_CAP)
            got = rep["computed"][s]["points"][str(blk["p"])]
            assert got["replica_shots"] == want
            assert got["detectable_factor"] <= 2.0


# ---- the curve form (issue #1278) ------------------------------------------

def test_gate_verifies_every_affordable_point_top_down(artifact):
    """Both points of the Steane curve are cheap, so the PR gate verifies
    both; the record names them from the highest rate down."""
    doc, cdir = artifact
    rep = lv.verify_ler(doc, cdir)
    assert rep["ok"]
    for s in ("X", "Z"):
        pts = rep["computed"][s]["points"]
        assert [q["status"] for q in pts.values()] == ["verified", "verified"]
        assert list(pts) == ["0.005", "0.001"]


def test_lower_points_are_deferred_when_the_budget_runs_out(artifact,
                                                              monkeypatch):
    """A budget that pays for the first point only leaves the rest to the
    weekly replication; the claim still passes on the point it checked."""
    doc, cdir = artifact
    real = lv.replicate_point

    def fake(dem, point, *, budget, seeds=1, **kw):
        if point["p"] < 0.005:                   # the second point, each basis
            return {"status": "unverifiable", "p": point["p"],
                    "replica_shots": 0, "replica_failures": 0, "runs": [],
                    "detectable_factor": None}
        return real(dem, point, budget=budget, seeds=seeds, **kw)
    monkeypatch.setattr(lv, "replicate_point", fake)
    rep = lv.verify_ler(doc, cdir)
    assert rep["ok"], [c for c in rep["checks"] if not c["ok"]]
    x = rep["computed"]["X"]["points"]
    assert x["0.005"]["status"] == "verified"
    assert x["0.001"]["status"] == "deferred"
    assert any(c["check"] == "X_ler_p0.001_deferred" for c in rep["checks"])


def test_no_affordable_point_fails_as_unverifiable(artifact, monkeypatch):
    doc, cdir = artifact
    _starve_replica(monkeypatch)
    rep = lv.verify_ler(doc, cdir)
    bad = {c["check"]: c["detail"] for c in rep["checks"] if not c["ok"]}
    assert any(k.endswith("_ler_replicated") for k in bad)
    assert any("unverifiable within budget" in v for v in bad.values())
    assert all(r["status"] == "deferred"
               for r in rep["computed"]["X"]["points"].values())


def test_saturated_point_rejected(artifact):
    """A per-shot failure fraction above 1/2 clamps the per-round conversion
    and says nothing about the circuit; the arithmetic check refuses it."""
    doc, cdir = artifact
    doc = copy.deepcopy(doc)
    blk = doc["circuit"]["ler"]["X"][0]
    blk["shots"], blk["failures"] = 10_000, 7_000
    _recompute(blk)
    rep = lv.verify_ler(doc, cdir)
    bad = {c["check"]: c["detail"] for c in rep["checks"] if not c["ok"]}
    assert "saturated" in bad.get("X_ler_arithmetic", "")


def test_off_grid_and_duplicate_rates_rejected(artifact):
    doc, cdir = artifact
    doc = copy.deepcopy(doc)
    doc["circuit"]["ler"]["X"][0]["p"] = 0.003
    rep = lv.verify_ler(doc, cdir)
    bad = {c["check"]: c["detail"] for c in rep["checks"] if not c["ok"]}
    assert "not on the rate grid" in bad.get("X_ler_arithmetic", "")
    doc = copy.deepcopy(artifact[0])
    doc["circuit"]["ler"]["Z"][0]["p"] = 0.001
    _recompute(doc["circuit"]["ler"]["Z"][0])
    rep = lv.verify_ler(doc, cdir)
    bad = {c["check"]: c["detail"] for c in rep["checks"] if not c["ok"]}
    assert "appears twice" in bad.get("Z_ler_arithmetic", "")


def test_legacy_form_accepted_at_0_4_and_refused_at_0_5(artifact):
    doc, cdir = artifact
    leg = _legacy(doc)
    rep = lv.verify_ler(leg, cdir)
    assert rep["ok"], [c for c in rep["checks"] if not c["ok"]]
    assert lv.summary_rate(leg) == leg["circuit"]["ler"]["X"]["ler_per_round"] \
        or lv.summary_rate(leg) == leg["circuit"]["ler"]["Z"]["ler_per_round"]
    leg["schema_version"] = "0.5"
    rep = lv.verify_ler(leg, cdir)
    assert [c["check"] for c in rep["checks"] if not c["ok"]] == ["ler_form"]


def test_summary_rate_is_the_gate_point(artifact):
    doc, _ = artifact
    want = max(doc["circuit"]["ler"][s][0]["ler_per_round"] for s in ("X", "Z"))
    assert lv.summary_rate(doc) == want
    assert lv.gate_point(doc["circuit"]["ler"]["X"])["p"] == 0.005


def test_all_mode_replicates_every_point_with_seeds(artifact):
    doc, cdir = artifact
    rep = lv.verify_ler(doc, cdir, mode="all", budget=60, seeds=3)
    assert rep["ok"], [c for c in rep["checks"] if not c["ok"]]
    for s in ("X", "Z"):
        for p, got in rep["computed"][s]["points"].items():
            assert got["status"] == "verified", (s, p, got)
            assert len(got["runs"]) == 3
            assert got["replica_shots"] == sum(r["shots"] for r in got["runs"])


def test_receipt_roundtrip_and_staleness(artifact, tmp_path):
    doc, cdir = artifact
    rep = lv.verify_ler(doc, cdir, mode="all", budget=60, seeds=2)
    digest = lr.claim_digest(doc, cdir)
    receipt = lr.make_receipt("7-1-3", digest, rep, head_sha="deadbeef")
    path = lr.write_receipt(str(tmp_path), receipt)
    assert path.endswith(os.path.join("receipts", "ler", "7-1-3.json"))
    back = lr.load_receipt(str(tmp_path), "7-1-3")
    assert back["claim_digest"] == digest and back["ok"]
    assert lr.point_status(back, digest, "X", 0.001) == "verified"
    assert lr.point_status(back, digest, "X", 0.002) == "pending"
    # an edited claim no longer matches its receipt
    edited = copy.deepcopy(doc)
    edited["circuit"]["ler"]["X"][1]["seed"] += 1
    assert lr.point_status(back, lr.claim_digest(edited, cdir), "X", 0.001) \
        == "pending"
    assert lr.point_status(None, digest, "X", 0.001) == "pending"


def test_measure_point_raises_shots_to_the_failure_floor(artifact):
    doc, cdir = artifact
    circuit = stim.Circuit.from_file(os.path.join(cdir, "memory_z.stim"))
    q = lm.measure_point(circuit, doc["n"], ROUNDS, 0.001, 3,
                         log=lambda s: None)
    assert q["p"] == 0.001 and q["failures"] >= lt.MIN_FAILURES
    assert q["shots"] in lm.SHOT_STEPS
    assert lv.point_errors(q, ROUNDS) == []


def test_conversion_sanity():
    # per-round rate below per-shot rate, single round is identity, and the
    # Wilson interval brackets the point estimate.
    assert lt.per_round(0.3, 1) == pytest.approx(0.3)
    assert lt.per_round(0.3, 10) < 0.3
    lo, hi = lt.wilson_ci(50, 1000)
    assert lo < 0.05 < hi


def test_main():
    """pytest entry point kept for run_tests.py parity; the suite body is the
    granular tests above."""
    assert True


def _dem_from(cdir):
    circuit = stim.Circuit.from_file(os.path.join(cdir, "memory_x.stim"))
    return ct.derive_dem(circuit)


def test_parallel_decode_matches_serial_exactly(artifact):
    """Distributing the decode loop must not move the answer.

    Shots are independent and the total is a sum, so neither the worker count
    nor the chunking can change the result. This is the property that lets the
    tier parallelize at all: a claim is reproducible from its seed, and that
    guarantee cannot depend on how many cores the verifier happened to have.
    """
    _doc, cdir = artifact
    dem = _dem_from(cdir)
    serial = lt.measure_failures(dem, 400, 11, workers=1)
    for w in (2, 3, 8):
        assert lt.measure_failures(dem, 400, 11, workers=w) == serial, (
            f"{w} workers disagreed with serial: "
            f"{lt.measure_failures(dem, 400, 11, workers=w)} != {serial}")


def test_parallel_is_reproducible_across_runs(artifact):
    """Same seed, same answer, twice, on the parallel path."""
    _doc, cdir = artifact
    dem = _dem_from(cdir)
    first = lt.measure_failures(dem, 400, 5)
    second = lt.measure_failures(dem, 400, 5)
    assert first == second


def test_worker_count_does_not_change_shots_done(artifact):
    """An untruncated run reports every shot regardless of worker count."""
    _doc, cdir = artifact
    dem = _dem_from(cdir)
    for w in (1, 2, 5):
        _, done = lt.measure_failures(dem, 250, 3, workers=w)
        assert done == 250
