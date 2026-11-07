"""
Tests for research/circuit_autogen.py (issue #1848): the memory-circuit
generator behind `qldpc submit`.

The property that matters is that every schedule it emits is a circuit the
trusted tier accepts: parallel layers, deterministic detectors, the canonical
noise recipe as a fixed point, witnesses that hold in GF(2). The two-block
decomposition is checked on the kit's own bivariate-bicycle and non-abelian
2BGA constructions, and each schedule family runs end to end through
verify/circuit_verify.py on the same small board codes the circuit-tier tests
already use ([[12,4,2]] BB, [[25,1,5]] surface, Steane [[7,1,3]]).

Run: uv run pytest research/test_circuit_autogen.py
"""

import copy
import json
import os

import numpy as np
import pytest

import circuit_autogen as ca
import circuit_tools as ct
import circuit_verify as cv
from bb import build_bb
from group_algebra import build_2bga, perm_group
from qldpc_verify import _matrix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUICK = dict(seconds=3.0, max_candidates=2)


def _doc(slug):
    doc = json.load(open(os.path.join(ROOT, "codes", f"{slug}.json")))
    doc.pop("circuit", None)
    return doc


def _mats(doc):
    n = doc["n"]
    return _matrix(doc["checks"]["X"], n), _matrix(doc["checks"]["Z"], n)


def _steane():
    return {
        "schema_version": "0.1", "name": "[[7,1,3]]", "code_type": "CSS",
        "n": 7, "k": 1,
        "checks": {"X": [[0, 1, 2, 3], [1, 2, 4, 5], [2, 3, 5, 6]],
                   "Z": [[0, 1, 2, 3], [1, 2, 4, 5], [2, 3, 5, 6]]},
        "distance": {
            "d": 3,
            "X": {"value": 3, "confidence": "upper_bound",
                  "witness": [0, 4, 6]},
            "Z": {"value": 3, "confidence": "upper_bound",
                  "witness": [0, 4, 6]}},
        "provenance": {"authors": ["@me"], "construction": "Steane",
                       "origin": "submission", "date": "2026-09-22"},
    }


def _verify(doc, block, files, tmp_path):
    d = tmp_path / "circuits"
    d.mkdir()
    for name, text in files.items():
        (d / name).write_text(text)
    doc = copy.deepcopy(doc)
    doc["circuit"] = block
    doc["schema_version"] = "0.2"
    return cv.verify_circuit(doc, str(d))


# ------------------------------------------------------- two-block structure

def test_gross_code_decomposes_into_commuting_monomials():
    HX, HZ = build_bb(6, 6, [(3, 0), (0, 1), (0, 2)], [(0, 3), (1, 0), (2, 0)])
    A, B, zrow = ca.two_block_split(HX, HZ)
    PA, PB = ca.commuting_decomposition(A, B)
    assert len(PA) == 3 and len(PB) == 3
    m = A.shape[0]
    for perms, M in ((PA, A), (PB, B)):
        S = np.zeros_like(M)
        for p in perms:
            assert sorted(p) == list(range(m))          # a permutation
            S[np.arange(m), p] += 1
        assert (S == M).all()
    for pa in PA:
        for pb in PB:
            assert (pa[pb] == pb[pa]).all()


def test_split_tolerates_permuted_z_rows_and_rejects_other_codes():
    HX, HZ = build_bb(6, 6, [(3, 0), (0, 1), (0, 2)], [(0, 3), (1, 0), (2, 0)])
    perm = np.random.default_rng(1).permutation(HZ.shape[0])
    A, B, zrow = ca.two_block_split(HX, HZ[perm])
    want = np.concatenate([B.T, A.T], axis=1)
    assert (HZ[perm][zrow] == want).all()
    assert ca.two_block_split(*_mats(_steane())) is None
    assert ca.two_block_split(*_mats(_doc("25-1-5"))) is None


def test_non_abelian_2bga_needs_the_cross_commuting_search():
    """The kit's A4 example: left and right terms commute with each other
    but not among themselves, so the abelian labeling fails and the
    cross-only one must still produce a deterministic interleaving."""
    mul, els = perm_group([(1, 2, 0, 3), (1, 0, 3, 2)], 4)
    xi, yi = els.index((1, 2, 0, 3)), els.index((1, 0, 3, 2))
    inv = [els.index(tuple(np.argsort(g))) for g in els]

    def gm(*gs):
        r = 0
        for g in gs:
            r = int(mul[r, g])
        return r

    a = sorted({0, xi, yi, gm(inv[xi], yi, xi)})
    b = sorted({0, xi, yi, gm(yi, xi)})
    HX, HZ = build_2bga(mul, a, b)
    A, B, zrow = ca.two_block_split(HX, HZ)
    assert ca.commuting_decomposition(A, B, abelian=True) is None
    PA, PB = ca.commuting_decomposition(A, B, abelian=False)
    sx, sz = next(ca.interleaved_slots(len(PA), len(PB),
                                       np.random.default_rng(0)))
    layers = ca.interleaved_layers(PA, PB, zrow, sx, sz)
    assert ca.layers_parallel(layers)
    for basis in ("Z", "X"):
        assert ca.deterministic(ca.build_memory(HX, HZ, 2, basis, layers))


def test_slot_assignments_obey_the_interleaving_rules():
    for wA, wB in ((3, 3), (4, 2), (2, 6)):
        terms = [("A", a) for a in range(wA)] + [("B", b) for b in range(wB)]
        w = wA + wB
        seen = set()
        for k, (sx, sz) in enumerate(ca.interleaved_slots(
                wA, wB, np.random.default_rng(3))):
            if k == 40:
                break
            assert sorted(sx.values()) == list(range(1, w + 1))
            assert sorted(sz.values()) == list(range(w))
            x_at = {s: t[0] for t, s in sx.items()}
            z_at = {s: t[0] for t, s in sz.items()}
            assert all(x_at[s] == z_at[s] for s in range(1, w))
            for a in terms[:wA]:
                for b in terms[wA:]:
                    assert (sx[a] < sz[b]) == (sx[b] < sz[a])
            key = (tuple(sx[t] for t in terms), tuple(sz[t] for t in terms))
            assert key not in seen
            seen.add(key)


def test_interleaved_schedule_is_a_canonical_deterministic_circuit():
    doc = _doc("12-4-2")
    HX, HZ = _mats(doc)
    A, B, zrow = ca.two_block_split(HX, HZ)
    PA, PB = ca.commuting_decomposition(A, B)
    sx, sz = next(ca.interleaved_slots(3, 3, np.random.default_rng(0)))
    layers = ca.interleaved_layers(PA, PB, zrow, sx, sz)
    assert len(layers) == 7 and ca.layers_parallel(layers)
    for basis in ("Z", "X"):
        skel = ca.build_memory(HX, HZ, 3, basis, layers)
        assert ca.deterministic(skel)
        assert ct.layer_conflict_errors(skel) == []
        noisy = ct.apply_noise(skel, doc["n"])
        assert ct.noise_recipe_errors(noisy, doc["n"]) == []
        # one joint reset layer, 7 CX layers, one joint measurement layer
        ticks = str(skel).count("TICK")
        assert ticks == 1 + 3 * 9


# ---------------------------------------------------------- end to end

def test_generate_two_block_verifies_at_full_distance(tmp_path):
    doc = _doc("12-4-2")
    block, files, family = ca.generate(doc, **QUICK)
    assert family.startswith("two-block interleaved")
    assert set(files) == {"memory_x.stim", "memory_x.dem",
                          "memory_z.stim", "memory_z.dem"}
    report = _verify(doc, block, files, tmp_path)
    assert report["ok"], report
    assert report["earned_d_circ"]["d_circ"]["value"] == doc["distance"]["d"]
    assert block["rounds"] == doc["distance"]["d"]
    assert "interleaved two-block extraction" in block["notes"]


def test_generate_layout_schedule_verifies(tmp_path):
    doc = _doc("25-1-5")
    coords = doc["locality"]["coordinates"]
    block, files, family = ca.generate(doc, coords=coords, max_candidates=4,
                                       seconds=3.0)
    assert family == "layout zigzag"
    report = _verify(doc, block, files, tmp_path)
    assert report["ok"], report
    assert "zigzag" in block["notes"]


def test_generate_generic_fallback_verifies(tmp_path):
    doc = _steane()
    block, files, family = ca.generate(doc, **QUICK)
    assert family == "generic sequential"
    report = _verify(doc, block, files, tmp_path)
    assert report["ok"], report
    assert 1 <= report["earned_d_circ"]["d_circ"]["value"] <= 3


# ------------------------------------------------------------- flags (#4231)

def test_flag_intervals_are_the_coil_plus_the_outer_spans():
    assert ca.flag_intervals(6) == [(0, 3), (1, 4), (2, 5)]
    assert ca.flag_intervals(6, max_flags=1) == [(0, 5)]
    assert ca.flag_intervals(6, span_flags=4) == \
        [(0, 3), (1, 4), (2, 5), (0, 5), (0, 4), (1, 5)]   # (1, 4) is a coil flag
    assert ca.flag_intervals(1) == [] and ca.flag_intervals(6, 0) == []


@pytest.mark.parametrize("w,max_flags", [(12, 6), (16, 4), (8, 4)])
def test_pure_coil_has_a_three_hook_blind_spot_that_one_span_flag_closes(w, max_flags):
    from itertools import combinations
    coil = ca.flag_intervals(w, max_flags)
    hooks = range(w - 1)            # a hook after the last step reaches no data qubit
    unseen = [t for t in combinations(hooks, 3)
              if not any(ca.flag_syndrome(coil, t))]
    m = len(coil)
    assert (0, m - 1 if m == w // 2 else m, w - m) in unseen
    spanned = ca.flag_intervals(w, max_flags, span_flags=1)
    assert all(any(ca.flag_syndrome(spanned, t)) for t in combinations(hooks, 3))
    assert all(any(ca.flag_syndrome(spanned, t)) for t in combinations(hooks, 1))


def _valid_decomposition(dec, A, B):
    PA, PB = dec
    m = A.shape[0]
    for perms, M in ((PA, A), (PB, B)):
        S = np.zeros_like(M)
        for p in perms:
            S[np.arange(m), p] += 1
        assert (S == M).all()
    assert all((pb[pa] == pa[pb]).all() for pa in PA for pb in PB)


@pytest.mark.parametrize("slug", ["64-18-8", "96-40-4"])
def test_invariant_decomposition_solves_the_sweeps_hard_two_block_codes(slug):
    # The non-Abelian [[64,18,8]] and the high-centralizer Abelian [[96,40,4]]
    # of issue #4231, on which commuting_decomposition() runs out of nodes.
    HX, HZ = _mats(_doc(slug))
    A, B, _ = ca.two_block_split(HX, HZ)
    dec = ca.invariant_decomposition(A, B)
    assert dec is not None
    _valid_decomposition(dec, A, B)
    _valid_decomposition(ca.decompose_two_block(A, B), A, B)


def test_flagged_schedule_is_a_canonical_deterministic_circuit():
    doc = _doc("18-4-4")
    HX, HZ = _mats(doc)
    A, B, zrow = ca.two_block_split(HX, HZ)
    PA, PB = ca.decompose_two_block(A, B)
    sx, sz = next(ca.interleaved_slots(len(PA), len(PB),
                                       np.random.default_rng(0)))
    layers = ca.interleaved_layers(PA, PB, zrow, sx, sz)
    sch = ca.flagged(layers, max_flags=2, span_flags=1)
    n_flags = sum(len(v) for v in sch.flags.values())
    assert n_flags == (HX.shape[0] + HZ.shape[0]) * 3
    for basis in ("Z", "X"):
        skel = ca.build_memory(HX, HZ, 3, basis, sch)
        assert ca.deterministic(skel)
        assert skel.num_qubits == doc["n"] + HX.shape[0] + HZ.shape[0] + n_flags
        noisy = ct.apply_noise(skel, doc["n"])
        assert ct.strip_noise(noisy) == skel
        dem = ct.derive_dem(noisy)
        anchor = (HZ if basis == "Z" else HX).shape[0]
        assert dem.num_detectors == \
            ca.closure_detector_base(HX, HZ, 3, basis, sch.flags) + anchor
        bare = ca.build_memory(HX, HZ, 3, basis, layers)
        assert dem.num_detectors == bare.num_detectors + 3 * n_flags
        opp = "X" if basis == "Z" else "Z"
        wit = ca.readout_witness(dem, HX, HZ, 3, basis,
                                 doc["distance"][opp]["witness"], sch.flags)
        assert wit is not None and ct.witness_errors(dem, wit, len(wit)) == []


def test_generate_flagged_steane_reaches_full_distance(tmp_path):
    doc = _steane()
    block, files, family = ca.generate(doc, **QUICK)
    assert family == "generic sequential"
    assert block["notes"].startswith("Johnson-coil")
    report = _verify(doc, block, files, tmp_path)
    assert report["ok"], report
    assert report["earned_d_circ"]["d_circ"]["value"] == 3


def test_generate_flagged_two_block_reaches_full_distance(tmp_path):
    doc = _doc("18-4-4")
    block, files, family = ca.generate(doc, **QUICK)
    assert family.startswith("two-block interleaved")
    assert block["notes"].startswith(
        "Johnson-coil flagged interleaved two-block extraction")
    report = _verify(doc, block, files, tmp_path)
    assert report["ok"], report
    assert report["earned_d_circ"]["d_circ"]["value"] == 4
    assert all(v["value"] == 4 for v in block["d_circ"].values())


def test_readout_flips_along_a_code_logical_are_a_witness():
    doc = _doc("25-1-5")
    HX, HZ = _mats(doc)
    _, cands = ca.generic_candidates(HX, HZ, np.random.default_rng(0))
    _, layers = next(cands)
    for basis, opp in (("Z", "X"), ("X", "Z")):
        skel = ca.build_memory(HX, HZ, 5, basis, layers)
        dem = ct.derive_dem(ct.apply_noise(skel, doc["n"]))
        support = doc["distance"][opp]["witness"]
        wit = ca.readout_witness(dem, HX, HZ, 5, basis, support)
        assert wit is not None
        assert ct.witness_errors(dem, wit, len(support)) == []


def test_over_cap_is_reported_not_written(monkeypatch):
    monkeypatch.setattr(ca, "MAX_DEM_MECHANISMS", 10)
    with pytest.raises(ca.CircuitUnavailable, match="over the circuit-tier"):
        ca.generate(_doc("12-4-2"), **QUICK)


def test_from_files_takes_committed_circuits(tmp_path):
    doc = _doc("12-4-2")
    block, files, family = ca.from_files(
        doc, os.path.join(ROOT, "circuits", "12-4-2"), seconds=3.0)
    assert family == "submitter-provided"
    assert block["rounds"] == 2
    report = _verify(doc, block, files, tmp_path)
    assert report["ok"], report
