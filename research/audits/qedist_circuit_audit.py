#!/usr/bin/env python3
"""Audit a challenge circuit entry's fault distance with QEDist.

Imports each side's Stim circuit into QEDist's detector model, excludes
undetected logical faults through d_circ - 1, and reports the resulting
lower bound against the claimed d_circ.  Evidence only; not board certification.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "research" / "kit") not in sys.path:
    sys.path.insert(0, str(ROOT / "research" / "kit"))

from qedist import find_qedist  # noqa: E402

SIDE_FILES = {"X": "memory_x", "Z": "memory_z"}


def _run(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"QEDist failed: {(proc.stderr or proc.stdout)[-300:]}")


def audit(code_path, circuits_dir, *, seconds=60.0):
    doc = json.loads(Path(code_path).read_text())
    cb = doc.get("circuit") or {}
    d_circ = cb.get("d_circ") or {}
    prefix = find_qedist()
    if prefix is None:
        raise RuntimeError("QEDist not installed; set QEDIST or install it")
    out = {"code": str(code_path), "sides": {}}
    for side in ("X", "Z"):
        claim = int((d_circ.get(side) or {}).get("value", doc["distance"]["d"]))
        base = Path(circuits_dir) / SIDE_FILES[side]
        with tempfile.TemporaryDirectory(prefix=f"qedist-circ-{side}-") as td:
            td = Path(td)
            model = td / "model.json"
            run_dir = td / "run"
            _run(prefix + ["import-circuit", str(base.with_suffix(".stim")),
                           "--output", str(model)])
            _run(prefix + ["certify-circuit", str(model), "--out", str(run_dir),
                           "--cutoff", str(claim - 1), "--seconds", str(seconds)])
            result = json.loads((run_dir / "result.json").read_text())
            out["sides"][side] = {
                "claimed_d_circ": claim,
                "lower_bound": result.get("distance_lower_bound"),
                "exact": result.get("exact_distance"),
                "status": result.get("status"),
                "completed": result.get("completed_within_budget"),
                "nodes": (result.get("terminal") or {}).get("nodes"),
            }
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("code")
    ap.add_argument("--circuits-dir", default=None)
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    code_path = Path(args.code)
    circuits_dir = args.circuits_dir
    if circuits_dir is None:
        slug = code_path.stem
        circuits_dir = ROOT / "circuits" / slug
    result = audit(code_path, circuits_dir, seconds=args.seconds)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for side, info in result["sides"].items():
            print(f"{side}: claimed={info['claimed_d_circ']} lower_bound={info['lower_bound']} "
                  f"status={info['status']} completed={info['completed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

