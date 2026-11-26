"""The Sisyphus circuit sweep classifies a search's outcome correctly and measures what it claims to.

The search itself is stood in for by a small script wherever the test is about
the sweep's own logic (statuses, the witness check, the kill, the memory
sampling, the summary), so those tests run without Sisyphus installed. One
test runs the real search and is skipped where the package is absent. The
circuit is a distance-3 surface-code memory that stim generates; no board
entry is read.
"""

import importlib.util
import json
import os
import sys
import time

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_ROOT, "verify"))
import circuit_tools as CT  # noqa: E402

stim = pytest.importorskip("stim")


def _module():
    spec = importlib.util.spec_from_file_location(
        "sisyphus_circuit_sweep_mod", os.path.join(_HERE, "sisyphus_circuit_sweep.py")
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


SW = _module()


@pytest.fixture(scope="module")
def surface3(tmp_path_factory):
    """Return (stim_path, dem, a weight-3 undetected logical fault set) for a distance-3 memory."""
    d = tmp_path_factory.mktemp("surface3")
    circuit = stim.Circuit.generated(
        "surface_code:rotated_memory_x",
        distance=3,
        rounds=3,
        after_clifford_depolarization=0.001,
        before_measure_flip_probability=0.001,
        after_reset_flip_probability=0.001,
    )
    path = os.path.join(d, "memory_x.stim")
    open(path, "w").write(str(circuit) + "\n")
    dem = CT.derive_dem(circuit)
    H, L = CT.dem_matrices(dem)
    w, wit = CT.ris_dem(H, L, trials=200, seed=1)
    assert w == 3 and CT.witness_errors(dem, wit, 3) == []
    return path, dem, wit


def _stand_in(tmp_path, body):
    """Return a command that runs `body` as the child."""
    script = tmp_path / "stand_in.py"
    script.write_text(body)
    return [sys.executable, str(script)]


def _answer(lightest, witness, history):
    rec = {
        "version": "stand-in",
        "lightest": lightest,
        "witness": witness,
        "steps": 1,
        "search_seconds": 0.1,
        "setup_seconds": 0.2,
        "matrix_seconds": 0.0,
        "history": history,
    }
    return f"print({(SW.MARKER + json.dumps(rec))!r})\n"


def test_a_lighter_fault_set_the_witness_check_accepts_is_a_refutation(surface3, tmp_path):
    path, _, wit = surface3
    cmd = _stand_in(tmp_path, _answer(3, wit, [[0.4, 5], [1.5, 3]]))
    rec = SW.run_basis(path, 5, seconds=1, command=cmd)
    assert rec["status"] == "refuted" and rec["witness"] == wit and rec["lightest"] == 3
    assert rec["t_reach_claim"] == 0.4 and rec["t_below_claim"] == 1.5


def test_a_fault_set_at_the_claim_is_not_a_refutation(surface3, tmp_path):
    path, _, wit = surface3
    rec = SW.run_basis(path, 3, seconds=1, command=_stand_in(tmp_path, _answer(3, wit, [[0.2, 3]])))
    assert rec["status"] == "ok" and "witness" not in rec
    assert rec["t_reach_claim"] == 0.2 and rec["t_below_claim"] is None


@pytest.mark.parametrize("bad", [[0, 1], [0, 1, 2], [5, 5]])
def test_a_lighter_proposal_the_witness_check_refuses_is_rejected(surface3, tmp_path, bad):
    path, _, _ = surface3
    rec = SW.run_basis(path, 5, seconds=1, command=_stand_in(tmp_path, _answer(len(bad), bad, [[0.1, len(bad)]])))
    assert rec["status"] == "rejected" and "witness" not in rec


@pytest.mark.parametrize(
    "body, code",
    [
        ("import sys\nsys.exit(3)\n", 3),
        ("print('no result line')\n", 0),
        ("import os, signal\nos.kill(os.getpid(), signal.SIGKILL)\n", -9),
    ],
)
def test_a_child_that_fails_is_a_crash_with_its_return_code(surface3, tmp_path, body, code):
    path, _, _ = surface3
    rec = SW.run_basis(path, 3, seconds=1, command=_stand_in(tmp_path, body))
    assert rec["status"] == "crash" and rec["returncode"] == code


def test_a_child_that_hangs_is_killed_with_what_it_started(surface3, tmp_path):
    path, _, _ = surface3
    pidfile = tmp_path / "worker.pid"
    body = (
        "import subprocess, sys, time\n"
        "w = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])\n"
        f"open({str(pidfile)!r}, 'w').write(str(w.pid))\n"
        "time.sleep(600)\n"
    )
    t0 = time.monotonic()
    rec = SW.run_basis(path, 3, seconds=1, grace=1, command=_stand_in(tmp_path, body))
    assert rec["status"] == "timeout" and time.monotonic() - t0 < 60
    assert rec["peak"]["processes"] >= 2  # the sampler saw the child and its worker
    pid = int(pidfile.read_text())
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("the child's worker outlived the kill")


def test_memory_is_sampled_over_the_group(surface3, tmp_path):
    """A child that holds 200 MB for a second shows up as at least that much."""
    path, _, wit = surface3
    body = "import time\nblock = bytearray(200 * 1024 * 1024)\ntime.sleep(1.5)\n" + _answer(3, wit, [[0.1, 3]])
    rec = SW.run_basis(path, 3, seconds=5, command=_stand_in(tmp_path, body), interval=0.1)
    assert rec["status"] == "ok"
    assert rec["peak"]["rss_sum_gb"] >= 0.19 and rec["peak"]["leader_rss_gb"] >= 0.19


def test_shards_partition_the_entries():
    slugs = [f"s{i}" for i in range(11)]
    parts = [SW.shard(slugs, f"{i}/4") for i in range(4)]
    assert sorted(sum(parts, [])) == sorted(slugs)
    assert SW.shard(slugs, None) == slugs
    with pytest.raises(ValueError):
        SW.shard(slugs, "4/4")


def test_summary_counts_and_quantiles():
    def basis(status, setup, mem, reach=None, below=None, lightest=None):
        return {
            "status": status,
            "claim": 5,
            "lightest": lightest,
            "setup_seconds": setup,
            "wall_seconds": (setup or 0) + 10,
            "t_reach_claim": reach,
            "t_below_claim": below,
            "peak": {"processes": 5, "leader_rss_gb": mem, "rss_sum_gb": 2 * mem, "pss_sum_gb": None},
        }

    entries = [
        {
            "slug": "a",
            "bases": {"X": basis("ok", 1.0, 1.0, reach=0.5, lightest=5), "Z": basis("refuted", 3.0, 2.0, 0.1, 2.0, 4)},
        },
        {"slug": "b", "bases": {"X": basis("ok", 2.0, 3.0, lightest=9), "Z": basis("crash", None, 4.0)}},
    ]
    s = SW.summarize(entries)
    assert s["status"] == {"ok": 2, "refuted": 1, "crash": 1} and s["bases"] == 4
    assert s["setup_seconds"] == {"n": 3, "median": 2.0, "p90": 3.0, "max": 3.0}
    assert s["peak_memory_measure"] == "rss_sum_gb" and s["peak_memory_gb"]["max"] == 8.0
    assert s["claim_not_reached"] == 1  # b/X ended ok with its lightest fault set above the claim
    assert s["refuted"] == [["a", "Z", 5, 4, 2.0]]
    assert s["failed"] == [["b", "Z", "crash", None]]


def test_the_real_search_refutes_an_overclaim_and_leaves_an_honest_claim(surface3):
    pytest.importorskip("sisyphus_qec")
    path, dem, _ = surface3
    over = SW.run_basis(path, 5, seconds=3)
    assert over["status"] == "refuted" and 3 <= over["lightest"] < 5
    assert CT.witness_errors(dem, over["witness"], over["lightest"]) == []
    assert over["t_below_claim"] is not None and over["peak"]["processes"] >= 3
    honest = SW.run_basis(path, 3, seconds=3)
    assert honest["status"] == "ok" and honest["lightest"] == 3


def test_merge_keeps_each_entry_once_and_recomputes_the_summary():
    def entry(slug, status):
        peak = {"processes": 5, "leader_rss_gb": 1.0, "rss_sum_gb": 2.0, "pss_sum_gb": 1.5}
        basis = {"status": status, "claim": 5, "lightest": 5, "setup_seconds": 1.0, "wall_seconds": 2.0, "peak": peak}
        return {"slug": slug, "bases": {"X": basis}}

    a = {"seconds_per_basis": 60.0, "shard": "0/2", "entries": [entry("b", "ok"), entry("a", "ok")], "summary": {}}
    b = {"seconds_per_basis": 60.0, "shard": "1/2", "entries": [entry("c", "crash"), entry("a", "ok")], "summary": {}}
    m = SW.merge([a, b])
    assert [e["slug"] for e in m["entries"]] == ["a", "b", "c"] and m["merged_from"] == 2
    assert m["seconds_per_basis"] == 60.0 and "shard" not in m
    assert m["summary"]["status"] == {"ok": 2, "crash": 1} and m["summary"]["peak_memory_measure"] == "pss_sum_gb"
