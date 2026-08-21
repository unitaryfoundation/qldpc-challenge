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
        ler[basis] = lt.ler_block(dem, ROUNDS, SHOTS, seed=7, p_ref=ct.P_REF)
    doc = copy.deepcopy(doc)
    doc["schema_version"] = "0.2"
    doc["circuit"] = {"d_circ": {}, "rounds": ROUNDS,
                      "stim_version": stim.__version__, "ler": ler}
    return doc, cdir


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
        blk = doc["circuit"]["ler"][s]
        blk["failures"] = max(lt.MIN_FAILURES, blk["failures"] // 2)
        p = blk["failures"] / blk["shots"]
        blk["ler_per_round"] = round(lt.per_round(p, ROUNDS), 9)
        lo, hi = lt.wilson_ci(blk["failures"], blk["shots"])
        blk["ci95"] = [round(lt.per_round(lo, ROUNDS), 9),
                       round(lt.per_round(hi, ROUNDS), 9)]
    rep = lv.verify_ler(doc, cdir)
    assert not rep["ok"]
    bad = [c["check"] for c in rep["checks"] if not c["ok"]]
    assert any(c.endswith("_ler_replicated") for c in bad), bad


def test_broken_arithmetic_rejected(artifact):
    doc, cdir = artifact
    doc = copy.deepcopy(doc)
    doc["circuit"]["ler"]["X"]["ler_per_round"] *= 1.5
    rep = lv.verify_ler(doc, cdir)
    bad = [c["check"] for c in rep["checks"] if not c["ok"]]
    assert "X_ler_arithmetic" in bad


def test_unpinned_decoder_rejected(artifact):
    doc, cdir = artifact
    doc = copy.deepcopy(doc)
    doc["circuit"]["ler"]["Z"]["decoder"] = "mwpm"
    rep = lv.verify_ler(doc, cdir)
    bad = [c["check"] for c in rep["checks"] if not c["ok"]]
    assert "Z_ler_arithmetic" in bad


def test_shots_floor_rejected(artifact):
    doc, cdir = artifact
    doc = copy.deepcopy(doc)
    blk = doc["circuit"]["ler"]["X"]
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
    blk = doc["circuit"]["ler"]["X"]
    blk["shots"], blk["failures"] = 40_000, 30
    p = blk["failures"] / blk["shots"]
    blk["ler_per_round"] = round(lt.per_round(p, ROUNDS), 9)
    lo, hi = lt.wilson_ci(blk["failures"], blk["shots"])
    blk["ci95"] = [round(lt.per_round(lo, ROUNDS), 9),
                   round(lt.per_round(hi, ROUNDS), 9)]
    rep = lv.verify_ler(doc, cdir)
    bad = {c["check"]: c["detail"] for c in rep["checks"] if not c["ok"]}
    assert "X_ler_arithmetic" in bad and "below the floor" in bad["X_ler_arithmetic"]


def test_budget_truncation_fails_unverifiable(artifact, monkeypatch):
    # When the wall budget cannot afford a replica that would catch a 2x
    # under-report, the claim must fail as unverifiable rather than merge
    # weakly checked (the tier's stated budget-vs-statistics choice).
    doc, cdir = artifact
    monkeypatch.setattr(lv, "LER_SECONDS", 0.001)
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
        blk = doc["circuit"]["ler"][s]
        p = blk["failures"] / blk["shots"]
        want = min(max(lt.MIN_SHOTS,
                       -(-lv.REPLICA_FAILURES // 1) and
                       __import__("math").ceil(lv.REPLICA_FAILURES / p)),
                   lv.REPLICA_SHOTS_CAP)
        assert rep["computed"][s]["replica_shots"] == want
        assert rep["computed"][s]["detectable_factor"] <= 2.0


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
