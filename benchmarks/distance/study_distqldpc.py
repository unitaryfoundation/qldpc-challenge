"""Run a portable, single-worker DistQLDPC integration screen on frozen inputs."""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

from common import HERE, ROOT, atomic_json, code_target, matrix_hash, sha256
from distqldpc_adapter import load_build, np, persist_witnesses, prepare, run_solver

CASES = [
    "board-72-12-6",
    "board-144-12-12",
    "board-700-222-28",
    "board-682-172-79",
    "regression-690-182",
    "tanner-432_8_33",
    "mitten-975-195",
    "toric-1000",
    "fresh-bb-960",
]


def report(directory, results):
    """Separate solver-generated witnesses from the preparation fallback."""
    lines = [
        "# DistQLDPC integration screen",
        "",
        "Single active solver thread; upstream joint X/Z formulation. Preparation, input serialization, "
        "process startup and exit-time delivery count toward the total code budget. Independent witness "
        "validation and candidate saving happen after each run, before the next search.",
        "",
        "Preparation retains the lightest individual logical-basis row on each side. It does not enumerate "
        "combinations, run a structural search, inject an incumbent, or pass reference witnesses to the solver. "
        "This is an integration screen, not the Linux external-refresh comparison. Numerical solver bounds "
        "are unverified claims; all reported witness weights are independently checked upper bounds.",
        "",
        "| Code | Budget (s) | Preparation bound | Solver witness | Timely solver witness | Reported lower bound "
        "| Status |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in results:
        result = row["result"]
        lower = [b["value"] for b in result["bounds"] if b["kind"] == "lb"]
        best = result["solver_best_weight"]
        timely = best if row["within_budget"] else None
        values = [
            row["case"],
            row["budget_seconds"],
            row["initialization_bound"],
            best,
            timely,
            lower[-1] if lower else None,
            result["status"],
        ]
        lines.append("| " + " | ".join("—" if v is None else str(v) for v in values) + " |")
    lines += [
        "",
        "The solver's random policy is unchanged. Repeats use identical inputs and are not independent "
        "RIS seeds. On macOS, CPU affinity is unavailable; these timings must not be ranked against Linux "
        "measurements. Failed searches, late output, raw mixed Pauli operators, "
        "and candidate documents are retained.",
        "",
        "No result here is a full candidate-gate pass or a portable proof certificate.",
        "",
    ]
    (directory / "REPORT.md").write_text("\n".join(lines))


def main(args):
    """Freeze metadata and run methods serially, preserving evidence per code."""
    if args.seconds <= 0 or not np.isfinite(args.seconds) or args.repeats < 1:
        raise ValueError("Positive finite budget and positive repeats required")
    if len(set(args.cases)) != len(args.cases):
        raise ValueError("Duplicate cases")
    if args.cpu is not None:
        if not hasattr(os, "sched_setaffinity"):
            raise ValueError("CPU affinity is unavailable on this platform")
        os.sched_setaffinity(0, {args.cpu})
    binary, build = load_build()
    sys.path.insert(0, str(HERE / "build"))
    import benchmark_native

    manifest_path = args.corpus / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    indexed = {row["id"]: row for row in manifest["cases"]}
    if set(args.cases) - indexed.keys():
        raise ValueError("Unknown case")
    args.output.mkdir(parents=True, exist_ok=False)
    atomic_json(
        args.output / "manifest.json", {"sources": manifest["sources"], "cases": [indexed[key] for key in args.cases]}
    )
    source_files = [
        HERE / name
        for name in (
            "bootstrap_distqldpc.py",
            "distqldpc_adapter.py",
            "study_distqldpc.py",
            "test_distqldpc.py",
            "common.py",
            "native.cpp",
            "setup_native.py",
        )
    ]
    source_files += sorted((HERE / "distqldpc").glob("*"))
    source_files = [p for p in source_files if p.is_file()]
    with tarfile.open(args.output / "sources.tar.gz", "w:gz") as archive:
        for path in source_files:
            archive.add(path, arcname=str(path.relative_to(ROOT)))
    atomic_json(
        args.output / "environment.json",
        {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": sys.version,
            "cpu": args.cpu,
            "search_threads": 1,
            "seconds_per_code": args.seconds,
            "basis_preparer": "existing benchmark_native.PreparedSearch (no distance search)",
            "preparer_binary_sha256": sha256(benchmark_native.__file__),
            "formulation": "joint X/Z, total per-code deadline",
            "reference_policy": "evaluation only",
            "initialization_policy": "single basis rows, no incumbent injection",
            "build": {**build, "binary": str(binary.relative_to(ROOT))},
            "source_hashes": {str(p.relative_to(ROOT)): sha256(p) for p in source_files},
            "corpus_manifest_sha256": sha256(manifest_path),
            "base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    )
    results = []
    for case_id in args.cases:
        case = indexed[case_id]
        with np.load(args.corpus / case["file"], allow_pickle=False) as data:
            hx, hz = data["hx"], data["hz"]
        if matrix_hash(hx, hz) != case["matrix_sha256"]:
            raise ValueError("Input matrix hash mismatch")
        matrix_directory = args.output / "matrices"
        matrix_directory.mkdir(exist_ok=True)
        shutil.copyfile(args.corpus / case["file"], matrix_directory / case["file"])
        for repeat in range(args.repeats):
            run_id = f"{args.output.name}-{case_id}-r{repeat}"
            directory = args.output / case_id / f"r{repeat}"
            started, cpu_started = time.perf_counter(), time.process_time()
            logicals, fallback = prepare(hx, hz)
            preparation = time.perf_counter() - started
            prep_cpu = time.process_time() - cpu_started
            remaining = args.seconds - preparation
            if remaining > 0:
                result = run_solver(hx, hz, logicals, directory, remaining, binary)
            else:
                directory.mkdir(parents=True)
                result = {
                    "status": "preparation_timeout",
                    "elapsed_seconds": 0,
                    "setup_seconds": 0,
                    "cpu_seconds": 0,
                    "delivery_seconds": None,
                    "raw_witnesses": [],
                    "bounds": [],
                    "reported_optimum": None,
                }
            elapsed = time.perf_counter() - started
            save_started = time.perf_counter()
            persist_witnesses(hx, hz, result, fallback, directory, run_id)
            row = {
                "case": case_id,
                "repeat": repeat,
                "budget_seconds": args.seconds,
                "preparation_seconds": preparation,
                "delivery_seconds": elapsed,
                "within_budget": elapsed <= args.seconds,
                "cpu_seconds": prep_cpu + result["cpu_seconds"],
                "validation_and_save_seconds": time.perf_counter() - save_started,
                "initialization_bound": min(map(len, fallback.values())),
                "initialization_within_budget": preparation <= args.seconds,
                "evaluation_target": code_target(case),
                "result": result,
            }
            results.append(row)
            atomic_json(args.output / "results.json", results)
            report(args.output, results)
            print(
                f"{case_id}: {result['status']}, solver witness {result['solver_best_weight']}, "
                f"{elapsed:.3f}s including preparation",
                flush=True,
            )
    evidence = {
        str(path.relative_to(args.output)): sha256(path)
        for path in sorted(args.output.rglob("*"))
        if path.is_file() and path.name != "evidence.json"
    }
    atomic_json(args.output / "evidence.json", evidence)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=HERE / "results" / "reference-corpus")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", nargs="+", default=CASES)
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--cpu", type=int)
    main(parser.parse_args())
