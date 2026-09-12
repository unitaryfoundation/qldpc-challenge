"""Audit and optionally compress a DistQLDPC run, including every raw witness."""

import argparse
import hashlib
import io
import json
import tarfile
from pathlib import Path

from common import atomic_json, benchmark_schema_status, matrix_hash, sha256
from distqldpc_adapter import gf2, np, validate_pauli

SUMMARY_FILES = {
    "REPORT.md",
    "manifest.json",
    "environment.json",
    "results.json",
    "evidence.json",
    "audit.json",
    "raw.tar.gz",
}


def audit(directory, pack=False):
    """Support original files and the portable raw archive without extracting."""
    directory = Path(directory)
    archive_path = directory / "raw.tar.gz"
    archive = tarfile.open(archive_path) if archive_path.exists() else None

    def read(name):
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe evidence path")
        path = directory / relative
        if path.is_file():
            return path.read_bytes()
        if archive is None:
            raise FileNotFoundError(path)
        stream = archive.extractfile(name)
        if stream is None:
            raise ValueError(f"Missing artifact: {name}")
        return stream.read()

    try:
        recorded = json.loads(read("evidence.json"))
        for name, expected in recorded.items():
            if hashlib.sha256(read(name)).hexdigest() != expected:
                raise ValueError(f"Evidence hash mismatch: {name}")
        manifest = json.loads(read("manifest.json"))
        indexed = {case["id"]: case for case in manifest["cases"]}
        rows = json.loads(read("results.json"))
        keys = {(row["case"], row["repeat"]) for row in rows}
        if len(keys) != len(rows) or {row["case"] for row in rows} != set(indexed):
            raise ValueError("Incomplete or duplicate run grid")
        counts = {case: sum(row["case"] == case for row in rows) for case in indexed}
        if len(set(counts.values())) != 1:
            raise ValueError("Unequal repeat counts")
        documents, paulis = 0, 0
        for row in rows:
            case = indexed[row["case"]]
            with np.load(io.BytesIO(read(f"matrices/{case['file']}")), allow_pickle=False) as data:
                hx, hz = data["hx"], data["hz"]
            if matrix_hash(hx, hz) != case["matrix_sha256"]:
                raise ValueError("Input matrix hash mismatch")
            prefix = f"{row['case']}/r{row['repeat']}"
            result = row["result"]
            if json.loads(read(f"{prefix}/result.json")) != result:
                raise ValueError("Aggregate differs from individual run")
            if result["status"] != "preparation_timeout":
                raw_bytes = read(f"{prefix}/witnesses.jsonl")
                if raw_bytes and not raw_bytes.endswith(b"\n"):
                    raw_bytes = raw_bytes[: raw_bytes.rfind(b"\n") + 1]
                raw = [json.loads(line) for line in raw_bytes.splitlines()]
                if raw != result["raw_witnesses"]:
                    raise ValueError("Raw export differs from retained witnesses")
            validated = [validate_pauli(raw, hx, hz) for raw in result["raw_witnesses"]]
            if validated != result["validated_witnesses"]:
                raise ValueError("Validated components differ from raw Pauli operators")
            paulis += len(validated)
            docs = {}
            for entry in result["candidate_documents"]:
                content = read(f"{prefix}/{entry['file']}")
                if hashlib.sha256(content).hexdigest() != entry["sha256"]:
                    raise ValueError("Candidate hash mismatch")
                doc = json.loads(content)
                benchmark_schema_status(doc)
                if doc["n"] != hx.shape[1] or doc["distance"]["d"] != min(
                    doc["distance"][side]["value"] for side in ("X", "Z")
                ):
                    raise ValueError("Candidate parameters disagree with its witness")
                for side, own, opposite in (("X", hx, hz), ("Z", hz, hx)):
                    if doc["checks"][side] != [np.flatnonzero(check).tolist() for check in own]:
                        raise ValueError("Candidate checks differ from the benchmark input")
                    support = doc["distance"][side]["witness"]
                    vector = np.zeros(hx.shape[1], dtype=np.int8)
                    vector[support] = 1
                    if (
                        not support
                        or len(support) != len(set(support))
                        or len(support) != doc["distance"][side]["value"]
                        or not gf2.commutes(vector, opposite)
                        or gf2.in_rowspace(vector, own)
                    ):
                        raise ValueError("Invalid saved candidate witness")
                docs[entry["file"]] = doc
                documents += 1
            for index, event in enumerate(validated):
                for side, support in event["components"].items():
                    doc = docs[f"candidates/witness-{index}-{side}.json"]
                    if doc["distance"][side]["witness"] != support:
                        raise ValueError("Saved candidate differs from exported support")
        summary = {
            "status": "passed",
            "configurations": len(rows),
            "raw_pauli_witnesses": paulis,
            "candidate_documents": documents,
            "late_configurations": sum(not row["within_budget"] for row in rows),
            "scope": "Hash, matrix, witness identity and validity audit; no optimality proof or candidate gate",
        }
    finally:
        if archive is not None:
            archive.close()
    atomic_json(directory / "audit.json", summary)
    if pack:
        if archive_path.exists():
            raise FileExistsError(f"Archive already exists: {archive_path}")
        with tarfile.open(archive_path, "w:gz") as packed:
            for path in sorted(directory.rglob("*")):
                if path.is_file() and str(path.relative_to(directory)) not in SUMMARY_FILES:
                    packed.add(path, arcname=str(path.relative_to(directory)))
    # Retain hashes of archived paths when running against a packaged checkout.
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.name != "evidence.json":
            recorded[str(path.relative_to(directory))] = sha256(path)
    atomic_json(directory / "evidence.json", recorded)
    print(json.dumps(summary))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--pack", action="store_true")
    args = parser.parse_args()
    audit(args.directory, args.pack)
