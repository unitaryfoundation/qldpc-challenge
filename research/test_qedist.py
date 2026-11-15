"""Tests for the QEDist adapter (research/kit/qedist.py).

The conversion tests need no external tool.  End-to-end tests are skipped
unless QEDist is installed and QEDIST_RUN_TESTS=1 is set.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "research" / "kit"))

from qedist import challenge_to_qedist, find_qedist  # noqa: E402


class ConversionTests(unittest.TestCase):
    def test_css_conversion_includes_witnesses(self):
        doc = json.loads((ROOT / "codes" / "10-2-3-b.json").read_text())
        out = challenge_to_qedist(doc)
        self.assertEqual(out["schema"], "cssdist.code.v1")
        self.assertEqual(out["n"], 10)
        self.assertEqual(len(out["hx"]), 4)
        self.assertEqual(len(out["hz"]), 4)
        self.assertIn("witnesses", out)
        self.assertEqual(out["witnesses"]["X"][0], doc["distance"]["X"]["witness"])
        self.assertEqual(out["witnesses"]["Z"][0], doc["distance"]["Z"]["witness"])

    def test_no_witnesses_option(self):
        doc = json.loads((ROOT / "codes" / "10-2-3-b.json").read_text())
        out = challenge_to_qedist(doc, include_witnesses=False)
        self.assertNotIn("witnesses", out)

    def test_stabilizer_rejected(self):
        doc = json.loads((ROOT / "codes" / "52-15-7.json").read_text())
        with self.assertRaises(ValueError):
            challenge_to_qedist(doc)

    def test_missing_checks_rejected(self):
        with self.assertRaises(ValueError):
            challenge_to_qedist({"code_type": "CSS", "n": 4, "checks": {}})


@unittest.skipUnless(
    os.environ.get("QEDIST_RUN_TESTS") == "1" and find_qedist() is not None,
    "QEDist not available or QEDIST_RUN_TESTS not set",
)
class EndToEndTests(unittest.TestCase):
    def test_certify_small_code(self):
        import tempfile
        from qedist import certify_challenge

        doc_path = ROOT / "codes" / "10-2-3-b.json"
        with tempfile.TemporaryDirectory() as td:
            summary = certify_challenge(doc_path, Path(td) / "run", seconds=30)
        self.assertEqual(summary["status"], "EXACT_DISTANCE")
        self.assertEqual(summary["exact_distance"], 3)


if __name__ == "__main__":
    unittest.main()
