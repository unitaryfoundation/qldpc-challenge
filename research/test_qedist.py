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

from qedist import (  # noqa: E402
    challenge_to_qedist,
    challenge_stabilizer_to_qedist,
    find_qedist,
    qedist_commit,
    solver_string,
    tanner_symmetry_generators,
)


def _css_doc():
    # Synthetic [[7,1,3]] Steane code so tests do not depend on mutable board slugs.
    checks = [[0, 1, 2, 3], [0, 1, 4, 5], [0, 2, 4, 6]]
    return {
        "schema": "qldpc-challenge/v1",
        "code_type": "CSS",
        "name": "steane-7-1-3",
        "n": 7,
        "k": 1,
        "checks": {"X": checks, "Z": checks},
        "distance": {
            "d": 3,
            "X": {"value": 3, "witness": [4, 5, 6]},
            "Z": {"value": 3, "witness": [4, 5, 6]},
        },
    }


def _stabilizer_doc():
    # Synthetic [[5,1,3]] five-qubit stabilizer code.
    return {
        "schema": "qldpc-challenge/v1",
        "code_type": "stabilizer",
        "name": "five-qubit-5-1-3",
        "n": 5,
        "k": 1,
        "checks": {
            "S": [
                {"X": [0, 3], "Z": [1, 2]},
                {"X": [1, 4], "Z": [2, 3]},
                {"X": [0, 2], "Z": [3, 4]},
                {"X": [1, 3], "Z": [0, 4]},
            ]
        },
        "distance": {
            "d": 3,
            "P": {"value": 3, "witness": {"X": [0, 1, 2], "Z": []}},
        },
    }


class ConversionTests(unittest.TestCase):
    def test_css_conversion_includes_witnesses(self):
        doc = _css_doc()
        out = challenge_to_qedist(doc)
        self.assertEqual(out["schema"], "cssdist.code.v1")
        self.assertEqual(out["n"], 7)
        self.assertEqual(len(out["hx"]), 3)
        self.assertEqual(len(out["hz"]), 3)
        self.assertIn("witnesses", out)
        self.assertEqual(out["witnesses"]["X"][0], doc["distance"]["X"]["witness"])
        self.assertEqual(out["witnesses"]["Z"][0], doc["distance"]["Z"]["witness"])

    def test_no_witnesses_option(self):
        doc = _css_doc()
        out = challenge_to_qedist(doc, include_witnesses=False)
        self.assertNotIn("witnesses", out)

    def test_stabilizer_rejected(self):
        doc = _stabilizer_doc()
        with self.assertRaises(ValueError):
            challenge_to_qedist(doc)

    def test_missing_checks_rejected(self):
        with self.assertRaises(ValueError):
            challenge_to_qedist({"code_type": "CSS", "n": 4, "checks": {}})

    def test_stabilizer_conversion(self):
        doc = _stabilizer_doc()
        out = challenge_stabilizer_to_qedist(doc)
        self.assertEqual(out["schema"], "qedist.stabilizer.v1")
        self.assertEqual(out["n"], 5)
        self.assertEqual(out["stabilizers"], ["XZZXI", "IXZZX", "XIXZZ", "ZXIXZ"])
        self.assertEqual(out["witnesses"], ["XXXII"])

    def test_stabilizer_wrong_type_rejected(self):
        doc = _css_doc()
        with self.assertRaises(ValueError):
            challenge_stabilizer_to_qedist(doc)


@unittest.skipUnless(
    os.environ.get("QEDIST_RUN_TESTS") == "1" and find_qedist() is not None,
    "QEDist not available or QEDIST_RUN_TESTS not set",
)
class EndToEndTests(unittest.TestCase):
    def test_certify_small_code(self):
        import tempfile
        from qedist import certify_challenge

        with tempfile.TemporaryDirectory() as td:
            doc_path = Path(td) / "steane.json"
            doc_path.write_text(json.dumps(_css_doc()))
            summary = certify_challenge(doc_path, Path(td) / "run", seconds=30)
        self.assertEqual(summary["status"], "EXACT_DISTANCE")
        self.assertEqual(summary["exact_distance"], 3)


if __name__ == "__main__":
    unittest.main()


def _row_set(rows):
    return {tuple(sorted(r)) for r in rows}


class SymmetryAndStampTests(unittest.TestCase):
    """Tanner-graph symmetry generators and the commit-stamped solver string (issue #6867)."""

    def test_steane_generators_preserve_both_check_sets(self):
        doc = _css_doc()
        gens = tanner_symmetry_generators(doc["n"], doc["checks"]["X"], doc["checks"]["Z"])
        self.assertTrue(gens, "the Steane code has a nontrivial automorphism group")
        for g in gens:
            self.assertEqual(sorted(g), list(range(7)), "a generator is a permutation of the qubits")
            self.assertNotEqual(g, list(range(7)))
            for side in ("X", "Z"):
                rows = doc["checks"][side]
                self.assertEqual(_row_set([[g[q] for q in r] for r in rows]), _row_set(rows))

    def test_conversion_carries_generators_only_when_asked_and_present(self):
        doc = _css_doc()
        self.assertNotIn("symmetry_generators", challenge_to_qedist(doc))
        out = challenge_to_qedist(doc, symmetries=True)
        self.assertTrue(out["symmetry_generators"])
        # a rigid code: a path of weight-2 X checks pinned at one end by a Z check
        rigid = {"code_type": "CSS", "n": 4, "k": 1,
                 "checks": {"X": [[0, 1], [1, 2], [2, 3]], "Z": [[0]]},
                 "distance": {"d": 1}}
        self.assertEqual(tanner_symmetry_generators(4, rigid["checks"]["X"], rigid["checks"]["Z"]), [])
        self.assertNotIn("symmetry_generators", challenge_to_qedist(rigid, symmetries=True))

    def test_commit_is_read_from_the_checkout_behind_the_executable(self):
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "QEDist"
            (repo / ".venv" / "bin").mkdir(parents=True)
            exe = repo / ".venv" / "bin" / "qedist"
            exe.write_text("#!/bin/sh\necho QEDist 9.9\n")
            exe.chmod(0o755)
            git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                   "-c", "commit.gpgsign=false"]
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "README").write_text("x\n")
            subprocess.run(git + ["add", "README"], check=True)
            subprocess.run(git + ["commit", "-q", "-m", "x"], check=True)
            sha = subprocess.check_output(git + ["rev-parse", "--short=12", "HEAD"], text=True).strip()
            self.assertEqual(qedist_commit([str(exe)]), sha)
            self.assertEqual(solver_string([str(exe)]),
                             f"QEDist 9.9 {sha} (yeon-lee/QEDist) exhaustive search")
            self.assertTrue(solver_string([str(exe)], suffix=" (stabilizer)").endswith(" (stabilizer)"))
        self.assertIsNone(qedist_commit(["/bin/sh"]))
        self.assertIsNone(qedist_commit(["no-such-qedist-command"]), "a bare name is looked up on PATH, not the cwd")

    @unittest.skipUnless(find_qedist() and os.environ.get("QEDIST_RUN_TESTS") == "1",
                         "needs an installed QEDist and QEDIST_RUN_TESTS=1")
    def test_end_to_end_steane_with_symmetries(self):
        sys.path.insert(0, str(ROOT / "research" / "certs"))
        import qedist_certify as QC
        cert = QC.certify(_css_doc(), tlim=30, threads=1)
        self.assertTrue(cert["d_exact"])
        self.assertIn("symmetry generators supplied", cert["verification"]["note"])
        self.assertIn("(yeon-lee/QEDist)", cert["solver"])

