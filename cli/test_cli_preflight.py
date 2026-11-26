"""Smoke tests for the `qldpc preflight` subcommand."""

import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_preflight_help():
    r = subprocess.run(
        [sys.executable, os.path.join(_ROOT, "cli", "qldpc.py"), "preflight", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert "pre-submission" in r.stdout or "preflight" in r.stdout.lower()
