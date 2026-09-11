"""Freeze validated witnesses from a reference phase for independent-seed runs."""

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
from common import atomic_json, matrix_hash

# isort: split
# common initializes the repository paths before this import.
import gf2


def main(corpus, runs, output):
    """Keep source claims separate while improving held-out witness targets."""
    manifest = json.loads((corpus / "manifest.json").read_text())
    cases = {case["id"]: case for case in manifest["cases"]}
    output.mkdir(parents=True, exist_ok=False)
    for directory in runs:
        run_corpus = json.loads((directory / "corpus.json").read_text())
        hashes = {case["id"]: case["matrix_sha256"] for case in run_corpus["cases"]}
        for path in directory.glob("*/*/result.json"):
            record = json.loads(path.read_text())
            if record["validation_status"] != "passed":
                raise ValueError(f"Unvalidated reference run: {path}")
            case = cases[record["case"]]
            if hashes[case["id"]] != case["matrix_sha256"]:
                raise ValueError("Reference and evaluation matrices differ")
            with np.load(corpus / case["file"], allow_pickle=False) as data:
                hx, hz = data["hx"], data["hz"]
            if matrix_hash(hx, hz) != case["matrix_sha256"]:
                raise ValueError("Matrix hash mismatch")
            for side, workers in record["workers"].items():
                own, opposite = (hx, hz) if side == "X" else (hz, hx)
                for worker in workers:
                    for event in worker["events"]:
                        previous = case.setdefault("reference", {}).get(side)
                        if previous is not None and len(previous) <= event["weight"]:
                            continue
                        support = event["support"]
                        if len(support) != event["weight"] or len(set(support)) != len(support):
                            raise ValueError("Malformed reference support")
                        if not support or any(q < 0 or q >= case["n"] for q in support):
                            raise ValueError("Reference index out of bounds")
                        vector = np.zeros(case["n"], dtype=np.int8)
                        vector[support] = 1
                        if not gf2.commutes(vector, opposite) or gf2.in_rowspace(vector, own):
                            raise ValueError("Invalid logical in reference run")
                        case["reference"][side] = support
                        case.setdefault("reference_provenance", {})[side] = {
                            "method": record["method"],
                            "seed": record["seed"],
                            "threads": record["threads"],
                            "weight": event["weight"],
                            "run": directory.name,
                            "late_in_reference_run": not event["within_budget"],
                        }
    manifest["reference_phase"] = {
        "runs": [directory.name for directory in runs],
        "policy": "Best independently validated witness; not an exact distance",
    }
    for case in cases.values():
        shutil.copyfile(corpus / case["file"], output / case["file"])
    atomic_json(output / "manifest.json", manifest)
    print(f"Froze references for {len(cases)} cases in {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--runs", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.corpus, args.runs, args.output)
