"""Run a fixed-worker, witness-preserving CPU distance-search pilot or study."""

import argparse
import importlib.metadata
import json
import multiprocessing as mp
import os
import platform
import random
import resource
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Set before importing numerical libraries or creating worker processes.
for variable in (
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "NUMBA_NUM_THREADS",
):
    os.environ[variable] = "1"
os.environ.setdefault("MPLCONFIGDIR", "/tmp/qldpc-benchmark-matplotlib")

import numpy as np
from common import (
    HERE,
    ROOT,
    atomic_json,
    benchmark_schema_status,
    code_target,
    matrix_hash,
    sha256,
    submission_validator,
)

sys.path.insert(0, str(HERE / "build"))
import benchmark_native
import gf2
from submit import make_submission, save_submission
from workers import Recorder, initialize, ready, search

METHODS = ["cpp", "cpp-no-pairs", "m4ri", "qdistevol", "qdist-random", "numpy", "cpp-circulant"]


def write_matrix(path, matrix):
    """Write MatrixMarket coordinates; indices in this format are one-based."""
    rows, columns = np.nonzero(matrix)
    with Path(path).open("w") as stream:
        stream.write("%%MatrixMarket matrix coordinate integer general\n")
        stream.write(f"{matrix.shape[0]} {matrix.shape[1]} {len(rows)}\n")
        for row, column in zip(rows, columns, strict=True):
            stream.write(f"{row + 1} {column + 1} 1\n")


def read_codewords(path):
    """Read dist-m4ri's one-based NZLIST supports, retaining all exported words."""
    words = []
    for line in Path(path).read_text().splitlines():
        if not line.strip() or line.startswith("#") or line.startswith("%"):
            continue
        values = list(map(int, line.split()))
        if not values or values[0] != len(values) - 1:
            raise ValueError("Malformed NZLIST weight/support row")
        words.append([value - 1 for value in values[1:]])
    return words


def native_search(prepared, path, seconds, target, seed, threads, pairs):
    """Observe batches of the existing C++ trial kernel with prepared bases."""
    recorder = Recorder(path, seconds, target)
    if not prepared.applicable():
        result = recorder.finish()
        result["status"] = "not_applicable"
        return result
    batch, number = threads, 0
    while True:
        before = time.perf_counter()
        weight, support, completed = prepared.batch(batch, (seed + number * 1000003) % (2**64), pairs, threads, number)
        if recorder.observe(weight, support, completed):
            break
        duration = time.perf_counter() - before
        # Aim for observations every 50ms. The final batch can overrun; its
        # witness is preserved but never credited before it was observed.
        batch = max(threads, min(8192, int(batch * 0.05 / max(duration, 1e-6))))
        number += 1
    return recorder.finish()


def m4ri_search(binary, opposite, logicals, directory, seconds, target, seed, threads):
    """Use the public CLI and its native worker/deadline controls."""
    start = time.perf_counter()
    h_path, l_path = directory / "H.mtx", directory / "L.mtx"
    write_matrix(h_path, opposite)
    write_matrix(l_path, logicals)
    setup_seconds = time.perf_counter() - start
    command = [
        str(binary),
        "method=1",
        f"finH={h_path}",
        f"finL={l_path}",
        f"threads={threads}",
        f"timeout={seconds}",
        "steps=2147483647",
        f"seed={seed % 2147483647}",
        f"wmin={target or 0}",
        f"outC={directory / 'codewords.txt'}",
        "debug=0",
        "dW=0",
    ]
    atomic_json(directory / "command.json", command)
    cpu_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.perf_counter()
    with (directory / "stdout.txt").open("w") as stdout, (directory / "stderr.txt").open("w") as stderr:
        subprocess.run(command, check=True, stdout=stdout, stderr=stderr, timeout=seconds + 120)
    elapsed = time.perf_counter() - start
    cpu_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    lines = (directory / "stdout.txt").read_text().strip().splitlines()
    numeric = [
        line.split()
        for line in lines
        if len(line.split()) == 3 and all(part.lstrip("-").isdigit() for part in line.split())
    ]
    if len(numeric) != 1:
        raise ValueError(f"Unexpected dist-m4ri output in {directory}")
    lower, weight, trials = map(int, numeric[0])
    words = read_codewords(directory / "codewords.txt")
    if weight > 0 and (not words or min(map(len, words)) != weight):
        raise ValueError("dist-m4ri bound has no matching exported witness")
    events = [
        {
            "seconds": elapsed,
            "weight": len(word),
            "support": word,
            "trials": trials,
            "within_budget": elapsed <= seconds,
        }
        for word in words
    ]
    return {
        "status": "completed",
        "setup_seconds": setup_seconds,
        "search_seconds": elapsed,
        "trials": trials,
        "events": events,
        "cpu_seconds": cpu_after.ru_utime + cpu_after.ru_stime - cpu_before.ru_utime - cpu_before.ru_stime,
        "raw_file": str(directory / "codewords.txt"),
        "unused_lower_bound": lower,
    }


def validate_and_stage(hx, hz, case, sides, fallback, run_id):
    """Validate every returned support and package improvements using the kit."""
    start = time.perf_counter()
    retained = dict(fallback)
    paths = []
    sequence = 0
    for side in ("X", "Z"):
        own, opposite = (hx, hz) if side == "X" else (hz, hx)
        seen = set()
        for worker in sides[side]:
            for event in worker["events"]:
                support = event["support"]
                if (
                    event["weight"] != len(support)
                    or len(support) != len(set(support))
                    or any(q < 0 or q >= case["n"] for q in support)
                ):
                    raise ValueError("Malformed benchmark witness")
                vector = np.zeros(case["n"], dtype=np.int8)
                vector[support] = 1
                if not support or not gf2.commutes(vector, opposite) or gf2.in_rowspace(vector, own):
                    raise ValueError(f"Invalid {side} witness: {case['id']}, {run_id}")
                key = tuple(support)
                if key in seen:
                    continue
                seen.add(key)
                # Each distinct returned support gets its own saved candidate;
                # the other side uses a valid basis witness only for packaging.
                retained[side] = support
                document = make_submission(
                    hx,
                    hz,
                    name=f"Benchmark witness: {case['id']}",
                    authors=["qldpc-challenge CPU benchmark"],
                    construction=f"Distance benchmark {run_id}; input SHA256 {case['matrix_sha256']}",
                    witnesses=retained,
                    confidence="upper_bound",
                )
                directory = (
                    ROOT / "research" / "candidates" / "distance-benchmark" / case["id"] / run_id / str(sequence)
                )
                directory.mkdir(parents=True, exist_ok=True)
                path = directory / f"{document['n']}-{document['k']}-{document['distance']['d']}.json"
                errors = save_submission(document, path)
                schema_status = benchmark_schema_status(document)
                if errors and schema_status != "above_size_cap":
                    raise ValueError(f"Candidate save reported schema errors: {errors}")
                # The benchmark JSON is the durable audit trail; this path is
                # local working output and is deliberately omitted from reports.
                paths.append(str(path))
                sequence += 1
    return time.perf_counter() - start, len(paths)


def summarize_side(workers, target, seconds):
    """Compute deadline-censored results without dropping missed targets."""
    events = [event for worker in workers for event in worker["events"]]
    timely = [event for event in events if event["seconds"] <= seconds]
    hits = [event["seconds"] for event in timely if target is not None and event["weight"] <= target]
    return {
        "target": target,
        "best_in_budget": min((event["weight"] for event in timely), default=None),
        "best_returned": min((event["weight"] for event in events), default=None),
        "target_hit": bool(hits) if target is not None else None,
        "time_to_target": min(hits, default=None),
        "completed_trials": sum(worker["trials"] for worker in workers),
        "cpu_seconds": sum(worker["cpu_seconds"] for worker in workers),
        "elapsed_seconds": max(worker["search_seconds"] for worker in workers),
        "status": "not_applicable" if all(worker["status"] == "not_applicable" for worker in workers) else "completed",
    }


def main(args):
    """Run sequential methods with a fixed total number of CPU workers."""
    manifest_path = args.corpus / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    cases = [case for case in manifest["cases"] if not args.cases or case["id"] in args.cases]
    if not cases or (args.cases and set(args.cases) - {case["id"] for case in cases}):
        raise ValueError("No cases selected, or unknown case IDs")
    if args.threads < 1 or args.seconds <= 0 or args.seeds < 1 or args.seed_start < 0:
        raise ValueError("Threads, seconds, and seed count must be positive; seeds must be nonnegative")
    if len(set(args.methods)) != len(args.methods):
        raise ValueError("Repeated methods would overwrite benchmark evidence")
    if args.cpus is not None:
        if not hasattr(os, "sched_setaffinity"):
            raise ValueError("CPU affinity is unavailable on this platform")
        if len(set(args.cpus)) != args.threads:
            raise ValueError("Choose exactly one CPU per worker")
        os.sched_setaffinity(0, set(args.cpus))
    args.output.mkdir(parents=True, exist_ok=False)
    environment = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version,
        "workers": args.threads,
        "seconds_per_side": args.seconds / 2,
        "seed_start": args.seed_start,
        "seeds": args.seeds,
        "stop_at_target": not args.no_target_stop,
        "target_policy": "Same code-level minimum target on both sides; preserve smaller paper or analytic targets",
        "submission_size_cap": submission_validator().schema["properties"]["n"]["maximum"],
        "methods": args.methods,
        "cases": [case["id"] for case in cases],
        "corpus_manifest_sha256": sha256(manifest_path),
        "source_pins": manifest["sources"],
        "reference_policy": "frozen supplied references; paper targets labeled separately",
        "native_source_sha256": sha256(ROOT / "verify" / "gf2_fast.cpp"),
        "native_binary_sha256": sha256(benchmark_native.__file__),
        "adapter_sha256": sha256(HERE / "native.cpp"),
        "runner_sha256": sha256(HERE / "run.py"),
        "workers_sha256": sha256(HERE / "workers.py"),
        "submit_source_sha256": sha256(ROOT / "research" / "kit" / "submit.py"),
        "m4ri_binary_sha256": sha256(args.m4ri) if "m4ri" in args.methods else None,
        "affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "numba", "scipy", "codedistance", "pybind11", "threadpoolctl")
        },
    }
    atomic_json(args.output / "environment.json", environment)
    atomic_json(args.output / "corpus.json", manifest)
    # Preserve the exact adapter sources and matrix bytes before any search.
    for path in [
        *HERE.glob("*.py"),
        HERE / "native.cpp",
        HERE / "sources.json",
        HERE / "requirements.txt",
        ROOT / "research" / "kit" / "submit.py",
        ROOT / "verify" / "gf2_fast.cpp",
        ROOT / "schema" / "code.schema.json",
    ]:
        destination = args.output / "source_snapshot" / path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    (args.output / "matrices").mkdir()
    atomic_json(args.output / "matrices" / "manifest.json", manifest)
    for case in manifest["cases"]:
        shutil.copyfile(args.corpus / case["file"], args.output / "matrices" / case["file"])
    python_methods = {"qdistevol", "qdist-random", "numpy"}
    pool = None
    if python_methods.intersection(args.methods):
        startup = time.perf_counter()
        context = mp.get_context("spawn")
        barrier, stop = context.Barrier(args.threads), context.Event()
        pool = context.Pool(
            args.threads, initialize, (barrier, stop, bool({"qdistevol", "qdist-random"}.intersection(args.methods)))
        )
        # Wait for every import/JIT to finish before any timed native work.
        pool.map_async(ready, range(args.threads)).get(timeout=180)
        environment["worker_startup_seconds"] = time.perf_counter() - startup
        atomic_json(args.output / "environment.json", environment)
    try:
        for case in cases:
            with np.load(args.corpus / case["file"], allow_pickle=False) as data:
                hx, hz = data["hx"], data["hz"]
            if matrix_hash(hx, hz) != case["matrix_sha256"]:
                raise ValueError(f"Corpus matrix changed: {case['id']}")
            before = time.perf_counter()
            prepared = {"X": benchmark_native.PreparedSearch(hx, hz), "Z": benchmark_native.PreparedSearch(hz, hx)}
            # Full quotient bases supply the required nontriviality tests.
            # Neither paper witnesses nor benchmark target supports are used.
            logicals = {side: prepared[side].opposite_logicals() for side in ("X", "Z")}
            fallback = {"X": np.flatnonzero(logicals["Z"][0]).tolist(), "Z": np.flatnonzero(logicals["X"][0]).tolist()}
            shared_preparation = time.perf_counter() - before
            structural = None
            before = time.perf_counter()
            if "cpp-circulant" in args.methods:
                block_size = benchmark_native.circulant_size(hx)
                structural = {
                    "X": benchmark_native.PreparedSearch(hx, hz, True, block_size),
                    "Z": benchmark_native.PreparedSearch(hz, hx, True, block_size),
                }
            structural_preparation = time.perf_counter() - before
            for seed_index in range(args.seed_start, args.seed_start + args.seeds):
                methods = list(args.methods)
                random.Random(f"{case['id']}:{seed_index}").shuffle(methods)
                for method in methods:
                    run_id = f"{args.output.name}-{method}-t{args.threads}-s{seed_index}"
                    directory = args.output / case["id"] / f"{method}-s{seed_index}"
                    directory.mkdir(parents=True)
                    start = time.perf_counter()
                    results, summaries = {}, {}
                    for side in ("X", "Z"):
                        own, opposite = (hx, hz) if side == "X" else (hz, hx)
                        side_dir = directory / side
                        side_dir.mkdir()
                        target = code_target(case)
                        if args.no_target_stop:
                            stopping_target = None
                        else:
                            stopping_target = target
                        seed = seed_index * 1000003 + (0 if side == "X" else 499979)
                        if method.startswith("cpp"):
                            engine = structural[side] if method == "cpp-circulant" else prepared[side]
                            workers = [
                                native_search(
                                    engine,
                                    side_dir / "events.jsonl",
                                    args.seconds / 2,
                                    stopping_target,
                                    seed,
                                    args.threads,
                                    0 if method == "cpp-no-pairs" else 8,
                                )
                            ]
                        elif method == "m4ri":
                            workers = [
                                m4ri_search(
                                    args.m4ri,
                                    opposite,
                                    logicals[side],
                                    side_dir,
                                    args.seconds / 2,
                                    stopping_target,
                                    seed,
                                    args.threads,
                                )
                            ]
                        else:
                            stop.clear()
                            jobs = [
                                {
                                    "method": method,
                                    "own": own,
                                    "opposite": opposite,
                                    "logicals": logicals[side],
                                    "seconds": args.seconds / 2,
                                    "target": stopping_target,
                                    "seed": seed + worker * 15485863,
                                    "path": str(side_dir / f"worker-{worker}.jsonl"),
                                }
                                for worker in range(args.threads)
                            ]
                            workers = pool.map_async(search, jobs).get(timeout=args.seconds + 180)
                        results[side] = workers
                        summaries[side] = summarize_side(workers, target, args.seconds / 2)
                        summaries[side]["target_evidence"] = (
                            "validated_code_witness"
                            if any(len(support) == target for support in case.get("reference", {}).values())
                            else "analytic"
                            if "analytic_target" in case
                            else "paper_unverified"
                            if target
                            else "none"
                        )
                    search_and_dispatch = time.perf_counter() - start
                    record = {
                        "case": case["id"],
                        "method": method,
                        "seed": seed_index,
                        "threads": args.threads,
                        "budget_seconds": args.seconds,
                        "shared_preparation_seconds": shared_preparation,
                        "structural_preparation_seconds": structural_preparation if method == "cpp-circulant" else 0,
                        "search_and_dispatch_seconds": search_and_dispatch,
                        "workers": results,
                        "sides": summaries,
                        "validation_status": "pending",
                    }
                    atomic_json(directory / "result.json", record)
                    validation_seconds, saved = validate_and_stage(hx, hz, case, results, fallback, run_id)
                    record.update(
                        validation_status="passed",
                        validation_seconds=validation_seconds,
                        saved_candidates=saved,
                        submission_schema_status=(
                            "above_size_cap" if case["n"] > environment["submission_size_cap"] else "valid"
                        ),
                    )
                    atomic_json(directory / "result.json", record)
                    print(
                        f"{case['id']} {method} seed={seed_index}: "
                        f"X={summaries['X']['best_in_budget']} Z={summaries['Z']['best_in_budget']} "
                        f"trials={sum(summaries[s]['completed_trials'] for s in ('X', 'Z'))}",
                        flush=True,
                    )
    finally:
        if pool:
            pool.terminate()
            pool.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=HERE / "cache" / "corpus")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--m4ri", type=Path, default=HERE / "cache" / "deps" / "dist-m4ri" / "src" / "dist_m4ri")
    parser.add_argument("--methods", nargs="+", choices=METHODS, default=METHODS)
    parser.add_argument("--cases", nargs="+")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--cpus", type=int, nargs="+", help="Linux CPU affinity; choose one physical core per worker")
    parser.add_argument("--seconds", type=float, default=10, help="Total per-code budget, split equally by side")
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--seed-start", type=int, default=0)
    parser.add_argument(
        "--no-target-stop", action="store_true", help="Continue beyond reference targets to search for tighter bounds"
    )
    main(parser.parse_args())
