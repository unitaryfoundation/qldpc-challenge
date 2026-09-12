"""Check solver projection, known distances, deadlines, and evidence retention."""

import json
import sys
import uuid

import pytest
from distqldpc_adapter import load_build, np, persist_witnesses, prepare, run_solver, validate_pauli


def steane():
    """Return the [[7,1,3]] CSS code's parity checks."""
    h = np.array([[1, 1, 1, 1, 0, 0, 0], [1, 1, 0, 0, 1, 1, 0], [1, 0, 1, 0, 1, 0, 1]], dtype=np.int8)
    return h, h.copy()


def checked_run(hx, hz, directory, seconds=2):
    """Retain all real solver output, including failed-test evidence."""
    logicals, fallback = prepare(hx, hz)
    result = run_solver(hx, hz, logicals, directory, seconds)
    persist_witnesses(hx, hz, result, fallback, directory, f"test-{uuid.uuid4().hex}")
    return result


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_reconstructs_eliminated_variables(tmp_path, seed):
    """Known distance survives qubit permutations and redundant check rows."""
    hx, hz = steane()
    permutation = np.random.default_rng(seed).permutation(7)
    hx = np.vstack([hx, hx[0] ^ hx[1]])[:, permutation]
    hz = hz[:, permutation]
    result = checked_run(hx, hz, tmp_path / "run")
    assert result["reported_optimum"] == 3
    assert result["solver_best_weight"] == 3
    assert result["within_budget"]
    assert result["status"] == "solver_optimal_claim"
    assert result["candidate_documents"]
    assert (tmp_path / "run" / "witnesses.jsonl").read_text().endswith("\n")


def test_asymmetric_sectors(tmp_path):
    """This code has X distance two and Z distance one."""
    hx = np.array([[1, 1, 0, 0]], dtype=np.int8)
    hz = np.array([[1, 1, 0, 0], [0, 0, 1, 1]], dtype=np.int8)
    result = checked_run(hx, hz, tmp_path / "run")
    assert result["solver_best_weight"] == result["reported_optimum"] == 1
    assert any(len(event["components"].get("Z", [])) == 1 for event in result["validated_witnesses"])


def test_joint_y_projection():
    """A mixed logical's pure CSS components can both be retained."""
    hx, hz = steane()
    result = validate_pauli({"x": "0000000", "z": "1111111", "solver_cost": 7}, hx, hz)
    assert set(result["components"]) == {"Z"}
    result = validate_pauli({"x": "1111111", "z": "1111111", "solver_cost": 7}, hx, hz)
    assert result["components"] == {"X": list(range(7)), "Z": list(range(7))}


@pytest.mark.parametrize(
    "record",
    [
        {"x": "1111000", "z": "0000000", "solver_cost": 4},  # stabilizer
        {"x": "1000000", "z": "0000000", "solver_cost": 1},  # detected error
        {"x": "1111111", "z": "0000000", "solver_cost": 3},  # wrong reported cost
        {"x": "111111", "z": "0000000", "solver_cost": 6},  # wrong length
    ],
)
def test_rejects_invalid_exports(record):
    """A numerical bound alone cannot pass the witness checks."""
    with pytest.raises(ValueError):
        validate_pauli(record, *steane())


def test_no_budget_for_setup(tmp_path):
    """A budget consumed during setup never launches uncharged search."""
    result = checked_run(*steane(), tmp_path / "run", seconds=1e-9)
    assert result["status"] == "preparation_timeout"
    assert result["raw_witnesses"] == []
    assert not (tmp_path / "run" / "command.json").exists()


def test_save_failure_is_fatal(tmp_path, monkeypatch):
    """Do not continue a study after a candidate-persistence failure."""
    import distqldpc_adapter as adapter

    hx, hz = steane()
    _, fallback = prepare(hx, hz)
    monkeypatch.setattr(adapter, "save_submission", lambda *_: ["simulated save failure"])
    with pytest.raises(ValueError, match="Failed to save"):
        persist_witnesses(
            hx, hz, {"raw_witnesses": [], "reported_optimum": None}, fallback, tmp_path, "test-save-failure"
        )


def test_build_matches_source_pin():
    """Require the recorded executable and source pin, not an arbitrary binary."""
    binary, record = load_build()
    assert binary.exists()
    assert record["search_threads"] == 1
    assert len(record["upstream"]["commit"]) == 40
    from common import HERE

    assert json.loads((HERE / "distqldpc" / "source.json").read_text()) == record["upstream"]


def fake_solver(path, delay, exit_code):
    """Emulate a CLI that exports a valid witness before delay or failure."""
    path.write_text(
        f"#!{sys.executable}\n"
        "import json, sys, time\n"
        "from pathlib import Path\n"
        "target = next(a.split('=', 1)[1] for a in sys.argv if a.startswith('-witness-file='))\n"
        "Path(target).write_text(json.dumps({'x': '0000111', 'z': '0000000', 'solver_cost': 3}) + '\\n')\n"
        f"time.sleep({delay})\n"
        "print('o 3', flush=True)\n"
        f"sys.exit({exit_code})\n"
    )
    path.chmod(0o755)


@pytest.mark.parametrize("delay,expected", [(0.3, "solver_optimal_claim"), (10, "forced_timeout")])
def test_late_and_killed_exports_are_retained(tmp_path, delay, expected):
    """A late or forcibly stopped CLI keeps its witness but gets no time credit."""
    binary = tmp_path / "fake"
    fake_solver(binary, delay, 0)
    hx, hz = steane()
    logicals, fallback = prepare(hx, hz)
    directory = tmp_path / "run"
    result = run_solver(hx, hz, logicals, directory, 0.2, binary=binary)
    persist_witnesses(hx, hz, result, fallback, directory, f"test-{uuid.uuid4().hex}")
    assert result["status"] == expected
    assert not result["within_budget"]
    assert result["solver_best_weight"] == 3
    assert len(result["candidate_documents"]) == 2
    assert result["elapsed_seconds"] < 2


def test_child_error_preserves_witness_before_raising(tmp_path):
    """A backend failure is fatal even when it printed an objective value."""
    binary = tmp_path / "fake"
    fake_solver(binary, 0, 2)
    hx, hz = steane()
    logicals, fallback = prepare(hx, hz)
    directory = tmp_path / "run"
    result = run_solver(hx, hz, logicals, directory, 1, binary=binary)
    with pytest.raises(RuntimeError, match="DistQLDPC failed"):
        persist_witnesses(hx, hz, result, fallback, directory, f"test-{uuid.uuid4().hex}")
    saved = json.loads((directory / "result.json").read_text())
    assert saved["solver_best_weight"] == 3
    assert len(saved["candidate_documents"]) == 2


def test_rejects_contradicted_optimality_claim(tmp_path):
    """A mixed Pauli's lighter logical component refutes a claimed optimum."""
    hx, hz = steane()
    _, fallback = prepare(hx, hz)
    result = {
        "status": "solver_optimal_claim",
        "reported_optimum": 7,
        "raw_witnesses": [{"x": "0000111", "z": "1111000", "solver_cost": 7}],
    }
    with pytest.raises(RuntimeError, match="DistQLDPC failed"):
        persist_witnesses(hx, hz, result, fallback, tmp_path, f"test-{uuid.uuid4().hex}")
    assert result["status"] == "contradicted_optimal_claim"
    assert result["solver_best_weight"] == 3


def test_unwitnessed_objective_cannot_hide_backend_failure(tmp_path):
    """Preserve backend errors even if an objective line lacked a witness."""
    hx, hz = steane()
    _, fallback = prepare(hx, hz)
    result = {"status": "backend_error", "reported_optimum": 3, "raw_witnesses": []}
    with pytest.raises(RuntimeError, match="DistQLDPC failed"):
        persist_witnesses(hx, hz, result, fallback, tmp_path, f"test-{uuid.uuid4().hex}")
    assert result["status"] == "backend_error"
