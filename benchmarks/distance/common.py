"""Shared paths and evidence I/O; mathematical checks come from the verifier."""

import hashlib
import json
import os
import sys
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "research" / "kit"))
sys.path.insert(0, str(ROOT / "verify"))


def atomic_json(path, value):
    """Persist complete JSON before making it visible to a reader."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def sha256(path):
    """Hash the bytes of a pinned input or executable."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def matrix_hash(hx, hz):
    """Hash shape and binary matrix contents, independent of file compression."""
    digest = hashlib.sha256()
    for matrix in (hx, hz):
        digest.update(str(matrix.shape).encode())
        digest.update(matrix.astype("uint8").tobytes())
    return digest.hexdigest()


@lru_cache(maxsize=1)
def submission_validator():
    """Load the actual submission schema, including the current eligibility cap."""
    import jsonschema

    schema = json.loads((ROOT / "schema" / "code.schema.json").read_text())
    return jsonschema.Draft202012Validator(schema)


def benchmark_schema_status(document):
    """Allow only the intentional size-cap violation in larger benchmark fixtures."""
    status = "valid"
    for error in submission_validator().iter_errors(document):
        if list(error.path) == ["n"] and error.validator == "maximum":
            status = "above_size_cap"
        else:
            raise ValueError(f"Unexpected benchmark submission schema error: {error.message}")
    return status


def code_target(case):
    """Use one code-level target without weakening a smaller published target."""
    targets = [len(support) for support in case.get("reference", {}).values()]
    targets.extend(case[key] for key in ("paper_target", "analytic_target") if key in case)
    return min(targets, default=None)
