"""Observe native DistQLDPC; validate and retain its exported Pauli witnesses."""

import json
import math
import os
import resource
import signal
import subprocess
import sys
import time
from pathlib import Path

from common import HERE, ROOT, atomic_json, benchmark_schema_status, matrix_hash, sha256

for _variable in (
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "NUMBA_NUM_THREADS",
):
    os.environ[_variable] = "1"

import gf2
import numpy as np
from submit import make_submission, save_submission


def load_build():
    """Require the binary and instrumentation to match their recorded build."""
    record = json.loads((HERE / "build" / "distqldpc.json").read_text())
    if record["upstream"] != json.loads((HERE / "distqldpc" / "source.json").read_text()):
        raise ValueError("DistQLDPC upstream source pin changed; rebuild required")
    binary = Path(record["binary"])
    for path, expected in (
        (binary, record["binary_sha256"]),
        (HERE / "distqldpc" / "observer.h", record["observer_sha256"]),
        (HERE / "distqldpc" / "upstream.patch", record["patch_sha256"]),
    ):
        if sha256(path) != expected:
            raise ValueError(f"DistQLDPC build mismatch: {path}")
    return binary, record


def prepare(hx, hz):
    """Use the existing native GF(2) implementation, without a distance search.

    logicals['X'] contains Z logicals against which an X error is tested.
    This deliberately follows the established benchmark and verifier convention.
    """
    sys.path.insert(0, str(HERE / "build"))
    import benchmark_native

    logicals = {
        "X": benchmark_native.PreparedSearch(hx, hz).opposite_logicals(),
        "Z": benchmark_native.PreparedSearch(hz, hx).opposite_logicals(),
    }
    if not len(logicals["X"]) or len(logicals["X"]) != len(logicals["Z"]):
        raise ValueError("The distance study requires k > 0 and matching logical bases")
    fallback = {
        side: np.flatnonzero(min(logicals[other], key=np.count_nonzero)).tolist()
        for side, other in (("X", "Z"), ("Z", "X"))
    }
    return logicals, fallback


def run_solver(hx, hz, logicals, directory, seconds, binary=None):
    """Run the upstream joint X/Z problem with one active solver thread.

    All input serialization, process setup and exit-time delivery are charged.
    Logical-basis preparation belongs to the caller's same total code budget.
    Numerical bounds are recorded as solver claims, never as verified evidence.
    """
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("A positive finite solver budget is required")
    if binary is None:
        binary, _ = load_build()
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    started, own_cpu = time.perf_counter(), time.process_time()
    n = hx.shape[1]
    for name, matrix in (("Hx", hx), ("Hz", hz), ("Gx", logicals["X"]), ("Gz", logicals["Z"])):
        if matrix.ndim != 2 or matrix.shape[1] != n or not len(matrix) or not np.isin(matrix, (0, 1)).all():
            raise ValueError(f"Invalid {name} matrix")
        np.savetxt(directory / f"input_{name}.txt", matrix, fmt="%d")
    setup_seconds = time.perf_counter() - started
    remaining = seconds - setup_seconds
    if remaining <= 0.1:
        return {
            "status": "preparation_timeout",
            "elapsed_seconds": setup_seconds,
            "setup_seconds": setup_seconds,
            "cpu_seconds": time.process_time() - own_cpu,
            "delivery_seconds": None,
            "raw_witnesses": [],
            "bounds": [],
            "reported_optimum": None,
        }
    # Parent polls every 10 ms. Reserve time for its exit and delivery; still
    # judge all output against the actual deadline, not the requested timeout.
    command = [
        str(binary),
        f"-cpu-lim={remaining - 0.1:.9f}",
        f"-witness-file={directory / 'witnesses.jsonl'}",
        str(directory / "input"),
    ]
    atomic_json(directory / "command.json", command)
    cpu_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    forced = False
    with (directory / "stdout.txt").open("w") as stdout, (directory / "stderr.txt").open("w") as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            process.wait(timeout=max(0.001, seconds - (time.perf_counter() - started)) + 0.5)
        except subprocess.TimeoutExpired:
            # Kill the process group so the solver's fork cannot leak work.
            forced = True
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        except BaseException:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise
    # Read all exported bytes before taking the conservative delivery timestamp.
    witness_path = directory / "witnesses.jsonl"
    raw = witness_path.read_bytes() if witness_path.exists() else b""
    output = (directory / "stdout.txt").read_text()
    delivery = time.perf_counter() - started
    cpu_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    records = []
    partial_tail = b""
    if raw and not raw.endswith(b"\n"):
        split = raw.rfind(b"\n") + 1
        raw, partial_tail = raw[:split], raw[split:]
    for line in raw.splitlines():
        records.append(json.loads(line))
    bounds, optimum = [], None
    for line in output.splitlines():
        words = line.split()
        if len(words) == 3 and words[:2] in (["c", "d_lb:"], ["c", "d_ub:"]) and words[2].isdigit():
            bounds.append({"kind": words[1][2:4], "value": int(words[2])})
        if len(words) == 2 and words[0] == "o" and words[1].isdigit():
            optimum = int(words[1])
    status = "backend_error"
    if forced:
        status = "forced_timeout"
    elif process.returncode == 0 and optimum is not None:
        status = "solver_optimal_claim"
    elif process.returncode == 1 and "s UNKNOWN" in output:
        status = "timeout" if "c status: TIMEOUT" in output else "unknown"
    return {
        "status": status,
        "returncode": process.returncode,
        "setup_seconds": setup_seconds,
        "elapsed_seconds": delivery,
        "delivery_seconds": delivery,
        "within_budget": delivery <= seconds,
        "cpu_seconds": time.process_time()
        - own_cpu
        + cpu_after.ru_utime
        + cpu_after.ru_stime
        - cpu_before.ru_utime
        - cpu_before.ru_stime,
        "cpu_accounting_complete": not forced,
        "raw_witnesses": records,
        "partial_tail_bytes": len(partial_tail),
        "bounds": bounds,
        "reported_optimum": optimum,
    }


def validate_pauli(record, hx, hz):
    """Use trusted GF(2) predicates; extract nontrivial CSS components only."""
    n = hx.shape[1]
    if set(record) != {"solver_cost", "x", "z"}:
        raise ValueError("Unexpected witness fields")
    vectors = {}
    for side in ("X", "Z"):
        bits = record[side.lower()]
        if not isinstance(bits, str) or len(bits) != n or set(bits) - {"0", "1"}:
            raise ValueError("Malformed Pauli bit string")
        vectors[side] = np.fromiter((int(bit) for bit in bits), dtype=np.int8)
    weight = int(np.count_nonzero(vectors["X"] | vectors["Z"]))
    if type(record["solver_cost"]) is not int or weight != record["solver_cost"] or weight == 0:
        raise ValueError("Exported Pauli weight differs from solver cost")
    logicals = {}
    for side, own, opposite in (("X", hx, hz), ("Z", hz, hx)):
        vector = vectors[side]
        if not gf2.commutes(vector, opposite):
            raise ValueError("Exported Pauli has a nonzero syndrome")
        if not gf2.in_rowspace(vector, own):
            logicals[side] = np.flatnonzero(vector).tolist()
    if not logicals:
        raise ValueError("Exported Pauli is a stabilizer")
    return {"pauli_weight": weight, "components": logicals}


def persist_witnesses(hx, hz, result, fallback, directory, run_id):
    """Save initialization and every returned logical through the research kit.

    Full Pauli records remain in the raw artifact, including trivial components.
    Every nontrivial component gets a separate candidate document and durable copy.
    """
    directory = Path(directory)
    input_hash = matrix_hash(hx, hz)
    retained = dict(fallback)
    documents, events = [], []

    def save(suffix):
        document = make_submission(
            hx,
            hz,
            name="DistQLDPC benchmark witness",
            construction=f"DistQLDPC benchmark {run_id}; input SHA256 {input_hash}",
            authors=["qldpc-challenge CPU benchmark"],
            witnesses=retained,
            confidence="upper_bound",
        )
        destination = ROOT / "research" / "candidates" / "distqldpc-study" / run_id / suffix
        destination.mkdir(parents=True, exist_ok=True)
        path = destination / f"{document['n']}-{document['k']}-{document['distance']['d']}.json"
        errors = save_submission(document, path)
        schema_status = benchmark_schema_status(document)
        if errors and schema_status != "above_size_cap":
            raise ValueError(f"Failed to save benchmark witness: {errors}")
        artifact = directory / "candidates" / f"{suffix}.json"
        atomic_json(artifact, document)
        documents.append({"file": str(artifact.relative_to(directory)), "sha256": sha256(artifact)})

    save("initialization")
    for index, raw in enumerate(result["raw_witnesses"]):
        event = validate_pauli(raw, hx, hz)
        events.append(event)
        for side, support in event["components"].items():
            retained[side] = support
            save(f"witness-{index}-{side}")
    result["validated_witnesses"] = events
    result["candidate_documents"] = documents
    result["solver_best_weight"] = min(
        (len(support) for event in events for support in event["components"].values()), default=None
    )
    optimum = result["reported_optimum"]
    if result["status"] == "solver_optimal_claim" and not any(event["pauli_weight"] == optimum for event in events):
        result["status"] = "unwitnessed_optimal_claim"
    best = result["solver_best_weight"]
    if result["status"] == "solver_optimal_claim" and best is not None and best < optimum:
        result["status"] = "contradicted_optimal_claim"
    atomic_json(directory / "result.json", result)
    if result["status"] in ("backend_error", "contradicted_optimal_claim"):
        raise RuntimeError(f"DistQLDPC failed; retained evidence in {directory}")
    return result
