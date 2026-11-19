#!/usr/bin/env python3
r"""Exact Pauli distances from QEDist for stabilizer entries.

Mirrors research/certs/qedist_certify.py but uses QEDist's certify-stabilizer
command.  CSS entries are handled by qedist_certify.py; this module is for
code_type == "stabilizer" entries only.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "verify"))
sys.path.insert(0, os.path.join(ROOT, "research", "kit"))

from qedist import challenge_stabilizer_to_qedist, find_qedist, solver_string  # noqa: E402

QEDIST_REPO = "github.com/yeon-lee/QEDist"
LEVEL = "solver"
MAX_CUTOFF = 64


class QEDistStabilizerCertifyError(RuntimeError):
    pass


def qedist_root(path=None):
    path = path or os.environ.get("QEDIST")
    if not path:
        return find_qedist()
    path = os.path.abspath(path)
    if os.path.isfile(path):
        return [path]
    if os.path.isdir(path):
        exe = os.path.join(path, ".venv", "bin", "qedist")
        if os.path.isfile(exe):
            return [exe]
        exe = os.path.join(path, "qedist")
        if os.path.isfile(exe):
            return [exe]
    return find_qedist()


def certify(doc, *, root=None, tlim=60.0, threads=1, shards=1):
    if doc.get("code_type") != "stabilizer":
        raise QEDistStabilizerCertifyError("QEDist stabilizer path handles stabilizer codes only")
    d = int(doc["distance"]["d"]) if "d" in (doc.get("distance") or {}) else int(doc["distance"]["P"]["value"])
    if d - 1 > MAX_CUTOFF:
        raise QEDistStabilizerCertifyError(f"entry d={d} exceeds QEDist's cutoff cap ({MAX_CUTOFF})")
    if d - 1 < 1:
        raise QEDistStabilizerCertifyError("entry d must be at least 2")

    prefix = qedist_root(root)
    if prefix is None:
        raise QEDistStabilizerCertifyError(
            "QEDist is not installed; set QEDIST or install from " + QEDIST_REPO
        )

    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="qedist-stab-cert-"))
    inp = challenge_stabilizer_to_qedist(doc, include_witnesses=True)
    input_path = tmp / "input.json"
    input_path.write_text(json.dumps(inp, indent=2) + "\n")
    out_dir = tmp / "run"
    cmd = prefix + [
        "certify-stabilizer", str(input_path),
        "--cutoff", str(d - 1),
        "--seconds", str(float(tlim)),
        "--workers", str(int(threads)),
        "--shards", str(int(shards)),
        "--out", str(out_dir),
    ]
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    wall = round(time.time() - t0, 1)
    if proc.returncode != 0:
        raise QEDistStabilizerCertifyError(
            f"QEDist failed (exit {proc.returncode}): {(proc.stderr or proc.stdout)[-300:]}"
        )
    aproc = subprocess.run(prefix + ["audit-stabilizer", str(out_dir)], capture_output=True, text=True)
    if aproc.returncode != 0:
        raise QEDistStabilizerCertifyError(f"QEDist audit failed: {(aproc.stderr or aproc.stdout)[-300:]}")
    result = json.loads((out_dir / "result.json").read_text())

    claim = d
    exact = False
    status = "TIMEOUT"
    lb = result.get("distance_lower_bound")
    ub = result.get("distance_upper_bound")
    witness = (result.get("witness") or {}).get("support")
    if ub is not None and int(ub) < claim:
        # refuted: a lighter logical exists
        status = "SAT"
    elif lb is not None and int(lb) == claim:
        exact = True
        status = "UNSAT"
    elif lb is not None and int(lb) > claim:
        raise QEDistStabilizerCertifyError(
            f"tool proved d >= {lb} against a verified witness of weight {claim}"
        )

    blk = {
        "value": claim,
        "secs": round(wall, 1),
        "exact": exact,
        "status": status,
    }
    if witness is not None:
        blk["witness"] = [int(x) for x in witness]
    if lb is not None:
        blk["lower_bound"] = int(lb)
    if ub is not None:
        blk["upper_bound"] = int(ub)

    overall = exact
    if result.get("exact_distance") is not None and int(result["exact_distance"]) != d:
        overall = False

    return {
        "name": doc.get("name"),
        "d": d,
        "sides": {"P": blk},
        "d_exact": overall,
        "solver": solver_string(prefix, suffix=" (stabilizer)"),
        "tlim_per_solve": float(tlim),
        "verification": {
            "level": LEVEL,
            "note": "QEDist Pauli-weight exhaustive search; witness re-checked by audit.",
        },
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Certify a stabilizer board entry with QEDist")
    ap.add_argument("path")
    ap.add_argument("--qedist", default=None)
    ap.add_argument("--tlim", type=float, default=60.0)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    with open(args.path, encoding="utf-8") as f:
        doc = json.load(f)
    cert = certify(doc, root=args.qedist, tlim=args.tlim, threads=args.threads, shards=args.shards)
    print(json.dumps(cert, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

