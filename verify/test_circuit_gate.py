"""
Tests for the circuit-tier refutation gate (RFC 0001 step 6, gate_changed):
an over-claimed d_circ must be caught by the bounded DEM search, an honest
claim must survive it, circuits/-only changes must still trigger the gate,
and unreadable artifacts must fail closed.

The over-claim fixture is organic: the default greedy schedule on the
[[25,1,5]] surface code has a hook error (true d_circ bound 3), and a
shallow 1-trial search returns a heavier valid witness -- exactly the
under-searched submission the gate exists to catch.

The Sisyphus half of the gate is tested on circuits stim generates, with
ris_dem stubbed out, so that what is asserted is that layer alone and no
board entry's value. Those tests need the research extra.

Run: uv run --extra research pytest verify/test_circuit_gate.py
"""

import copy
import json
import os
import time

import circuit_tools as ct
import gate_changed as gc
import pytest
import stim
from qldpc_verify import _matrix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_DOC = json.load(open(os.path.join(ROOT, "codes", "25-1-5.json")))
N = BASE_DOC["n"]


@pytest.fixture(scope="module")
def greedy(tmp_path_factory):
    """(doc, circuits_dir) with the greedy-schedule circuits and, per basis,
    the lightest witness a 1-trial search finds -- an honest artifact carrying
    an under-searched claim wherever that weight exceeds the true bound.
    """
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
        block["d_circ"][basis] = {"value": w, "confidence": "upper_bound", "witness": wit}
    doc["circuit"] = block
    return doc, str(d)


def test_overclaim_refuted(greedy):
    doc, d = greedy
    deep = {}
    for basis in ("Z", "X"):
        circuit = stim.Circuit(open(os.path.join(d, f"memory_{basis.lower()}.stim")).read())
        H, L = ct.dem_matrices(ct.derive_dem(circuit))
        deep[basis], _ = ct.ris_dem(H, L, trials=60, seed=9)
    over = [s for s in ("Z", "X") if doc["circuit"]["d_circ"][s]["value"] > deep[s]]
    assert over, "1-trial search matched the 60-trial bound; fixture is moot"
    hits, _ = gc._circuit_refute(doc, d, seed=9, trials_override=60, sisyphus_seconds=0)
    for s in over:
        assert s in hits
        w, wit, claim = hits[s]
        assert w < claim
        circuit = stim.Circuit(open(os.path.join(d, f"memory_{s.lower()}.stim")).read())
        assert ct.witness_errors(ct.derive_dem(circuit), wit, w) == []


def test_honest_claim_survives(greedy):
    """Claiming the deep-searched bound itself must not be refuted by the
    same search.
    """
    doc, d = greedy
    doc = copy.deepcopy(doc)
    for basis in ("Z", "X"):
        circuit = stim.Circuit(open(os.path.join(d, f"memory_{basis.lower()}.stim")).read())
        H, L = ct.dem_matrices(ct.derive_dem(circuit))
        w, wit = ct.ris_dem(H, L, trials=60, seed=9)
        doc["circuit"]["d_circ"][basis] = {"value": w, "confidence": "upper_bound", "witness": wit}
    hits, notes = gc._circuit_refute(doc, d, seed=9, trials_override=60, sisyphus_seconds=0)
    assert hits == {} and len(notes) == 2


def test_circuits_change_triggers_gate():
    paths = ["circuits/25-1-5/memory_z.stim", "codes/72-6-6.json", "circuits/25-1-5/memory_z.dem", "docs/index.html"]
    assert gc.map_changed(paths) == ["codes/25-1-5.json", "codes/72-6-6.json"]
    assert gc.map_changed(["circuits/25-1-5/memory_z.dem", "docs/index.html"]) == []


def test_orphaned_circuits_fail_closed(tmp_path, capsys):
    circuit_dir = tmp_path / "circuits" / "orphaned"
    circuit_dir.mkdir(parents=True)
    (circuit_dir / "memory_x.stim").write_text("# orphan\n")
    assert (
        gc.main(
            [
                "--code-root",
                str(tmp_path),
                "--seed",
                "1",
                "codes/orphaned.json",
            ]
        )
        == 1
    )
    assert "no corresponding code entry" in capsys.readouterr().out


def test_missing_code_with_empty_circuit_directory_is_skipped(tmp_path):
    (tmp_path / "circuits" / "deleted").mkdir(parents=True)
    assert (
        gc.main(
            [
                "--code-root",
                str(tmp_path),
                "--seed",
                "1",
                "codes/deleted.json",
            ]
        )
        == 0
    )


def test_missing_artifacts_fail_closed(greedy, tmp_path):
    doc, _ = greedy
    with pytest.raises(Exception):
        gc._circuit_refute(doc, str(tmp_path), seed=0)


def test_circuit_gate_pricing():
    """circuit_gate_needed follows the diff-pricing principle (issue #654):
    search exactly when the circuit claim surface changed or never faced a
    gate; in particular a circuit-block-only edit -- which classifies as
    layout-only for the code tier -- must still be searched, and an untouched
    claim must not be.
    """
    blk = {"circuit": {"rounds": 5}, "distance": {}}
    blk2 = {"circuit": {"rounds": 6}, "distance": {}}
    plain = {"distance": {}}
    assert not gc.circuit_gate_needed(blk, plain, True)  # no claim, no gate
    assert gc.circuit_gate_needed(None, blk, False)  # new entry
    assert gc.circuit_gate_needed(blk2, blk, False)  # block edited
    assert gc.circuit_gate_needed(plain, blk, False)  # block added
    assert gc.circuit_gate_needed(blk, blk, True)  # .stim/.dem edited
    assert not gc.circuit_gate_needed(blk, blk, False)  # untouched claim


def test_circuit_block_edit_skips_code_tier_but_is_searched():
    """The load-bearing conjunction behind the main-loop wiring: a diff that
    only adds a circuit block classifies as layout-only for the CODE tier
    (checks and distance unchanged -- correct, that claim already survived),
    while circuit_gate_needed still demands the circuit search. If either
    half changes, the layout-only skip path must be re-examined so it never
    skips the claim that actually changed.
    """
    base = {"code_type": "CSS", "n": 25, "k": 1, "checks": BASE_DOC["checks"], "distance": BASE_DOC["distance"]}
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
    assert t_small >= 50_000  # small DEMs get deep: the
    # 120 s pays for tens of
    # thousands of trials
    assert t_cap >= gc.CIRCUIT_MIN_TRIALS  # cap sized to stay feasible
    assert 0 < t_py < t_mid <= t_small  # fallback shallower, never zero


def test_budget_follows_the_check_matrix_not_its_kernel():
    """Issue #2797: the search reduces the r x m check matrix, so the budget
    is r^2 m, not m^3. The old 25,000 cap is now deep, the new cap still
    affordable, and more detectors at the same m cost trials.
    """
    from circuit_verify import MAX_DEM_MECHANISMS

    t_old_cap, _ = gc._circuit_budget(25_000, fast=True, detectors=810)
    t_new_cap, _ = gc._circuit_budget(MAX_DEM_MECHANISMS, fast=True, detectors=MAX_DEM_MECHANISMS // 30)
    t_sparse, _ = gc._circuit_budget(130_000, fast=True, detectors=1000)
    t_dense, _ = gc._circuit_budget(130_000, fast=True, detectors=2300)
    assert t_old_cap >= 1000  # was 38 at m^3 pricing
    assert t_new_cap >= gc.CIRCUIT_MIN_TRIALS
    assert t_dense < t_sparse
    assert gc._circuit_budget(130_000, fast=True) == gc._circuit_budget(130_000, fast=True, detectors=130_000 // 30)


def test_circuit_tier_blocklength_cap():
    """The tier stays on low-n instances (#2797, #2811): an entry above
    MAX_CIRCUIT_N is refused at the first check, before any artifact is
    read, and one at the cap is not.
    """
    import copy

    from circuit_verify import MAX_CIRCUIT_N, verify_circuit

    big = {
        "n": MAX_CIRCUIT_N + 1,
        "k": 1,
        "checks": {"X": [], "Z": []},
        "distance": {"d": 3},
        "circuit": {
            "rounds": 3,
            "stim_version": stim.__version__,
            "d_circ": {"X": {"value": 3, "witness": []}, "Z": {"value": 3, "witness": []}},
        },
    }
    rep = verify_circuit(big, "/nonexistent")
    bad = [c["check"] for c in rep["checks"] if not c["ok"]]
    assert bad == ["circuit_tier_blocklength"]
    edge = copy.deepcopy(big)
    edge["n"] = MAX_CIRCUIT_N
    rep = verify_circuit(edge, "/nonexistent")
    assert "circuit_tier_blocklength" not in [c["check"] for c in rep["checks"] if not c["ok"]]


def test_dem_search_finds_an_undetected_single_mechanism():
    """A mechanism with no detectors that flips an observable is a weight-1
    undetected logical fault; both search paths must return it. On the check
    matrix it is a zero column, i.e. a free column of weight 0 in every
    reduction, which the kernel-side search never saw as a special case.
    """
    import numpy as np

    H = np.zeros((3, 9), dtype=np.int8)
    H[0, 0] = H[0, 1] = H[1, 1] = H[1, 2] = H[2, 3] = H[2, 4] = 1
    L = np.zeros((1, 9), dtype=np.int8)
    L[0, 7] = 1  # column 7 is detector-free
    L[0, 0] = L[0, 2] = 1  # 0 + 1 + 2 is a weight-3 one
    for fast in (True, False):
        saved = ct._GF
        if not fast:
            ct._GF = None
        try:
            w, wit = ct.ris_dem(H, L, trials=4, seed=1)
        finally:
            ct._GF = saved
        assert (w, wit) == (1, [7]), (fast, w, wit)


def test_dem_wall_cap_stops_after_opener(monkeypatch):
    """#684 review regression, load-independent form (the first version
    asserted wall-clock seconds, which asserts the speed of the box and
    flaked on a loaded machine with the fix working correctly): a C++ chunk
    cannot be aborted, so when the opener chunk reveals the cap is already
    unaffordable the loop must stop after that single small chunk -- no
    second chunk, ever. The pre-fix loop issued a blind 64-trial first
    chunk, so this fails against it deterministically, in milliseconds.
    """
    import time
    import types

    import numpy as np

    calls = []

    def stub(H, L, trials, seed, pair_depth, threads):
        calls.append(trials)
        time.sleep(0.05)  # any nonzero cost blows a 1 ms cap
        return None, None

    monkeypatch.setattr(ct, "_GF", types.SimpleNamespace(dem_rand_witness=stub))
    H = np.zeros((2, 8), dtype=np.int8)
    H[0, 0] = H[1, 1] = 1
    L = np.zeros((1, 8), dtype=np.int8)
    L[0, 7] = 1
    ct.ris_dem(H, L, trials=20000, seed=3, max_seconds=0.001)
    assert calls == [8], f"expected only the opener chunk, got {calls}"


# ---------------------------------------------------------------- Sisyphus
#
# The second searcher (gate_changed._sisyphus_propose, verify/sisyphus_propose.py).
# The fixture is a rotated surface-code memory that stim generates: distance 3,
# so no undetected logical fault set is lighter than 3 and one of weight 3
# exists. Nothing here reads a board entry.


@pytest.fixture(scope="module")
def surface3(tmp_path_factory):
    """Return (circuits_dir, doc_for) for a distance-3 surface-code memory pair.

    doc_for(claim) is the least a document needs for _circuit_refute: the
    claimed d_circ per basis.
    """
    d = tmp_path_factory.mktemp("surface3")
    for basis in ("x", "z"):
        circuit = stim.Circuit.generated(
            f"surface_code:rotated_memory_{basis}",
            distance=3,
            rounds=3,
            after_clifford_depolarization=0.001,
            before_measure_flip_probability=0.001,
            after_reset_flip_probability=0.001,
        )
        open(os.path.join(d, f"memory_{basis}.stim"), "w").write(str(circuit) + "\n")

    def doc_for(claim):
        return {"circuit": {"d_circ": {s: {"value": claim} for s in ("X", "Z")}}}

    return str(d), doc_for


def _no_ris(monkeypatch):
    """Make ris_dem find nothing, so a hit can only be Sisyphus's."""
    monkeypatch.setattr(ct, "ris_dem", lambda H, L, trials, **kw: (None, None))


def test_sisyphus_budget_shape():
    from circuit_verify import MAX_DEM_MECHANISMS

    assert gc._sisyphus_seconds(0) == gc.SISYPHUS_MIN_SECONDS
    assert gc._sisyphus_seconds(MAX_DEM_MECHANISMS) == gc.SISYPHUS_MAX_SECONDS
    assert gc._sisyphus_seconds(10 * MAX_DEM_MECHANISMS) == gc.SISYPHUS_MAX_SECONDS  # clamped
    assert gc._sisyphus_seconds(20_000) < gc._sisyphus_seconds(100_000)


def test_sisyphus_refutes_an_overclaim_ris_missed(surface3, monkeypatch):
    """With ris_dem silenced, an over-stated claim is still refuted.

    The fault set that refutes it passes the pinned witness check.
    """
    pytest.importorskip("sisyphus_qec")
    d, doc_for = surface3
    _no_ris(monkeypatch)
    hits, notes = gc._circuit_refute(doc_for(5), d, seed=4, sisyphus_seconds=10)
    assert set(hits) == {"X", "Z"} and notes == []
    for side, (w, wit, claim) in hits.items():
        assert claim == 5 and 3 <= w < 5
        circuit = stim.Circuit(open(os.path.join(d, f"memory_{side.lower()}.stim")).read())
        assert ct.witness_errors(ct.derive_dem(circuit), wit, w) == []


def test_sisyphus_leaves_an_honest_claim_alone(surface3, monkeypatch):
    """Nothing lighter than the distance exists, so nothing is reported.

    The note says the search ran and what it found.
    """
    pytest.importorskip("sisyphus_qec")
    d, doc_for = surface3
    _no_ris(monkeypatch)
    hits, notes = gc._circuit_refute(doc_for(3), d, seed=4, sisyphus_seconds=2)
    assert hits == {}
    assert len(notes) == 2 and all("sisyphus" in n and "lightest 3" in n for n in notes)


def test_sisyphus_skipped_where_nothing_can_be_lighter(surface3, monkeypatch):
    """A claim of 1 cannot be undercut, so the process is not started."""
    d, doc_for = surface3
    _no_ris(monkeypatch)

    def boom(*a, **kw):
        raise AssertionError("the proposer must not run for a claim of 1")

    monkeypatch.setattr(gc, "_sisyphus_propose", boom)
    hits, notes = gc._circuit_refute(doc_for(1), d, seed=0)
    assert hits == {} and len(notes) == 2 and not any("sisyphus" in n for n in notes)


@pytest.mark.parametrize(
    "proposal",
    [
        {"lightest": 2, "witness": [0, 1]},  # not an undetected logical fault set
        {"lightest": 2, "witness": [0, 1, 2]},  # weight does not match the fault set
        {"lightest": 2, "witness": [5, 5]},  # a repeated fault
        {"lightest": 2, "witness": [0, 10**9]},  # out of range
    ],
)
def test_sisyphus_proposal_counts_only_if_the_witness_check_accepts_it(surface3, monkeypatch, proposal):
    """A proposal the pinned witness check rejects is dropped.

    The searcher is not trusted, so the claim stands.
    """
    d, doc_for = surface3
    _no_ris(monkeypatch)
    monkeypatch.setattr(gc, "_sisyphus_propose", lambda *a, **kw: dict(proposal))
    hits, notes = gc._circuit_refute(doc_for(3), d, seed=0)
    assert hits == {} and len(notes) == 2


def _fake_proposer(tmp_path, monkeypatch, body):
    script = tmp_path / "fake_propose.py"
    script.write_text(body)
    monkeypatch.setattr(gc, "SISYPHUS_SCRIPT", str(script))


@pytest.mark.parametrize(
    "body, message",
    [
        ("import sys\nsys.stderr.write('no module named sisyphus_qec\\n')\nsys.exit(1)\n", "exited 1"),
        ("print('nothing useful')\n", "0 result lines"),
        ("print('SISYPHUS_RESULT {}')\nprint('SISYPHUS_RESULT {}')\n", "2 result lines"),
        ("print('SISYPHUS_RESULT not json')\n", "declared shape"),
        ("print('SISYPHUS_RESULT {\"lightest\": 2}')\n", "declared shape"),
        ('print(\'SISYPHUS_RESULT {"lightest": "2", "witness": [0, 1]}\')\n', "declared shape"),
        ('print(\'SISYPHUS_RESULT {"lightest": 2, "witness": [0, "1"]}\')\n', "declared shape"),
    ],
)
def test_sisyphus_that_cannot_answer_fails_closed(surface3, tmp_path, monkeypatch, body, message):
    """A search that did not run is not a search that found nothing.

    The gate raises, and its caller fails the entry closed.
    """
    d, doc_for = surface3
    _no_ris(monkeypatch)
    _fake_proposer(tmp_path, monkeypatch, body)
    with pytest.raises(RuntimeError, match=message):
        gc._circuit_refute(doc_for(3), d, seed=0, sisyphus_seconds=1)


def test_sisyphus_that_hangs_is_killed_with_its_workers(surface3, tmp_path, monkeypatch):
    """The wall cap kills the whole process group.

    A worker the proposer started does not outlive it.
    """
    d, doc_for = surface3
    _no_ris(monkeypatch)
    pidfile = tmp_path / "child.pid"
    _fake_proposer(
        tmp_path,
        monkeypatch,
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])\n"
        f"open({str(pidfile)!r}, 'w').write(str(child.pid))\n"
        "time.sleep(600)\n",
    )
    monkeypatch.setattr(gc, "SISYPHUS_GRACE", 2.0)
    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match="was killed"):
        gc._circuit_refute(doc_for(3), d, seed=0, sisyphus_seconds=1)
    assert time.monotonic() - t0 < 60
    pid = int(pidfile.read_text())
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("the proposer's worker outlived the kill")
