#!/usr/bin/env python3
r"""Exact distances from QEDist (yeon-lee/QEDist) at the solver tier.

QEDist certifies the minimum weight of a logical operator from binary CSS
check matrices by exhaustive search, and ships portable audit bundles.  This
module turns a CSS board entry into QEDist's input, runs the tool, re-checks
the vector it returns with the board's own validators, and writes a
certificate in the shape used by research/certs/tropidist_certify.py.

CSS only: stabilizer entries are not supported (QEDist handles CSS checks).
The tool's cutoff is capped at 64, so entries with d > 65 are refused here and
should use tropidist or the SAT/DRAT path.

    uv run python research/certs/qedist_certify.py codes/<slug>.json \
        --qedist /path/to/qedist [--tlim 60] [--threads 4] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import json
import numpy as np
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "verify"))
sys.path.insert(0, os.path.join(ROOT, "research", "kit"))

import gf2  # noqa: E402
import heuristic_distance as HD  # noqa: E402
from qedist import challenge_to_qedist, find_qedist  # noqa: E402

QEDIST_REPO = "github.com/yeon-lee/QEDist"
LEVEL = "solver"
MAX_CUTOFF = 64


class QEDistCertifyError(RuntimeError):
    """The tool did not run, did not write a record, or returned a vector the board rejects."""


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
    # fall back to discovery
    return find_qedist()


def certify(doc, *, root=None, tlim=60.0, threads=1):
    if doc.get("code_type") != "CSS":
        raise QEDistCertifyError("QEDist handles CSS codes only")
    d = int(doc["distance"]["d"])
    if d - 1 > MAX_CUTOFF:
        raise QEDistCertifyError(f"entry d={d} exceeds QEDist's cutoff cap ({MAX_CUTOFF})")
    if d - 1 < 1:
        raise QEDistCertifyError("entry d must be at least 2")

    prefix = qedist_root(root)
    if prefix is None:
        raise QEDistCertifyError(
            "QEDist is not installed; set QEDIST or install from " + QEDIST_REPO
        )

    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="qedist-cert-"))
    try:
        inp = challenge_to_qedist(doc, include_witnesses=True)
        input_path = tmp / "input.json"
        input_path.write_text(json.dumps(inp, indent=2) + "\n")
        out_dir = tmp / "run"
        cmd = prefix + [
            "certify", str(input_path),
            "--profile", "css",
            "--cutoff", str(d - 1),
            "--seconds-per-shard", str(float(tlim)),
            "--workers", str(int(threads)),
            "--out", str(out_dir),
        ]
        t0 = time.time()
        proc = subprocess.run(cmd, capture_output=True, text=True)
        wall = round(time.time() - t0, 1)
        if proc.returncode != 0:
            raise QEDistCertifyError(
                f"QEDist failed (exit {proc.returncode}): {(proc.stderr or proc.stdout)[-300:]}"
            )
        # audit
        aproc = subprocess.run(prefix + ["audit", str(out_dir)], capture_output=True, text=True)
        if aproc.returncode != 0:
            raise QEDistCertifyError(f"QEDist audit failed: {(aproc.stderr or aproc.stdout)[-300:]}")
        result = json.loads((out_dir / "result.json").read_text())
    finally:
        # leave artifacts for debugging? remove to save space
        pass

    n = doc["n"]
    HX = HD._matrix(doc["checks"]["X"], n)
    HZ = HD._matrix(doc["checks"]["Z"], n)
    sides_in = doc["distance"]
    cert_sides = {}
    sector_bounds = result.get("sector_bounds", {})
    for side in ("X", "Z"):
        if side not in sides_in:
            continue
        claim = int(sides_in[side]["value"])
        sb = sector_bounds.get(side, {})
        lb = sb.get("lower")
        ub = sb.get("upper")
        witness = sb.get("witness")
        blk = {"value": claim, "secs": wall / 2.0}
        blk["secs"] = round(blk["secs"], 1)
        # refuted?
        if ub is not None and int(ub) < claim:
            ok = False
            weight = None
            if witness:
                v = _vector_from_support(witness, n)
                H_same, H_opp = (HX, HZ) if side == "X" else (HZ, HX)
                ok = bool(HD._valid_logical(v, H_opp, H_same))
                weight = int(v.sum())
            if not (ok and weight == int(ub)):
                raise QEDistCertifyError(
                    f"{side} side: the tool's weight-{ub} vector is not a nontrivial logical "
                    f"of weight {ub} (weight {weight}, valid {ok})"
                )
            blk.update(exact=False, status="SAT", witness=[int(x) for x in witness],
                       note=f"REFUTED: logical of weight {ub} exists")
            cert_sides[side] = blk
            continue
        if lb is not None and int(lb) > claim:
            raise QEDistCertifyError(
                f"{side} side: the tool proved d >= {lb} against a verified witness of weight {claim}"
            )
        if lb is not None and int(lb) == claim:
            blk.update(exact=True, status="UNSAT", note=f"no logical < {claim} exists")
            cert_sides[side] = blk
            continue
        blk.update(exact=False, status="TIMEOUT",
                   lower_bound=int(lb) if lb is not None else None,
                   note=(f"lower bound {lb}" if lb is not None else "nothing proved"))
        cert_sides[side] = blk

    overall = bool(cert_sides) and all(b.get("exact") for b in cert_sides.values())
    # also require QEDist's own exact flag when present
    if result.get("exact_distance") is not None and int(result["exact_distance"]) != d:
        overall = False

    return {
        "name": doc.get("name"),
        "d": d,
        "sides": cert_sides,
        "d_exact": overall,
        "solver": "QEDist 0.1 (yeon-lee/QEDist) exhaustive search",
        "tlim_per_solve": float(tlim),
        "verification": {
            "level": LEVEL,
            "note": "QEDist's lower bound is exhaustive search inside its kernel "
                    "(tree search with bounds and symmetries); the vector it returned "
                    "was re-verified by verify/heuristic_distance.py. Solver verdict only.",
        },
    }


def _vector_from_support(support, n):
    v = np.zeros(n, dtype=np.int8)
    for q in support:
        v[int(q)] ^= 1
    return v


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(description="Certify a board entry with QEDist")
    ap.add_argument("path")
    ap.add_argument("--qedist", default=None)
    ap.add_argument("--tlim", type=float, default=60.0)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    with open(args.path, encoding="utf-8") as f:
        doc = json.load(f)
    cert = certify(doc, root=args.qedist, tlim=args.tlim, threads=args.threads)
    print(json.dumps(cert, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
