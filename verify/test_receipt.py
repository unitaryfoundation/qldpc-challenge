"""Regression tests for additive verification receipts."""

import json
import os
import tempfile

from build_receipt import make_receipt, write_receipt
from validate_candidate import validate_candidate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(ROOT, "verify", "fixtures", "72-6-6.json")


def main():
    with open(FIXTURE) as f:
        doc = json.load(f)
    verdict = validate_candidate(doc, seed=123, refute=False)
    with tempfile.TemporaryDirectory() as td:
        source = os.path.join(td, "code.json")
        with open(source, "w") as f:
            json.dump(doc, f)
        receipt = make_receipt(
            doc,
            source,
            verdict,
            gate={"refuted": False, "seed": 123, "methods": ["RIS"]},
            repo_root=td,
            pr_number=7,
            pr_author="alice",
            base_sha="base",
            head_sha="head",
        )
        path = write_receipt(receipt, os.path.join(td, "receipts"), "code")
        loaded = json.load(open(path))
        assert loaded["receipt_version"] == "1"
        assert loaded["submission"]["pull_request"] == 7
        assert loaded["submission"]["sha256"]
        assert loaded["trusted_validation"]["validator_source_sha256"]
        assert loaded["trusted_validation"]["distance_gate"]["seed"] == 123
        assert loaded["provenance"]["model"]["status"] == "self_reported"
        assert "board_advancing" in loaded["frontier"]
    print("receipt tests passed")


def test_main():
    """Pytest entry point. main() returns None and signals failure by raising,
    so a clean return is the pass condition.
    """
    main()


if __name__ == "__main__":
    main()
