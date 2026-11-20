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
from check_certs import checks_sha256  # noqa: E402
from qedist import challenge_to_qedist, find_qedist, solver_string  # noqa: E402

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


def certify(doc, *, root=None, tlim=60.0, threads=1, cutoff=None, work_dir=None,
            symmetries=True):
    if doc.get("code_type") != "CSS":
        raise QEDistCertifyError("QEDist handles CSS codes only")
    d = int(doc["distance"]["d"])
    if cutoff is None:
        cutoff = d - 1
    if cutoff > MAX_CUTOFF:
        raise QEDistCertifyError(f"cutoff {cutoff} exceeds QEDist's cap ({MAX_CUTOFF})")
    if cutoff < 1:
        raise QEDistCertifyError("cutoff must be at least 1")

    prefix = qedist_root(root)
    if prefix is None:
        raise QEDistCertifyError(
            "QEDist is not installed; set QEDIST or install from " + QEDIST_REPO
        )

    import tempfile
    tmp = Path(work_dir) if work_dir is not None else Path(tempfile.mkdtemp(prefix="qedist-cert-"))
    try:
        # Tanner-graph symmetries cut the search roots to one per orbit
        # (issue #6867); the tool verifies them and refuses a wrong one, in
        # which case the run is repeated without them.
        inp = challenge_to_qedist(doc, include_witnesses=True, symmetries=symmetries)
        n_sym = len(inp.get("symmetry_generators") or [])
        input_path = tmp / "input.json"
        input_path.write_text(json.dumps(inp, indent=2) + "\n")
        out_dir = tmp / "run"
        cmd = prefix + [
            "certify", str(input_path),
            "--profile", "css",
            "--cutoff", str(cutoff),
            "--seconds-per-shard", str(float(tlim)),
            "--workers", str(int(threads)),
            "--out", str(out_dir),
        ]
        if out_dir.exists():
            cmd.insert(-2, "--resume")
        # QEDist's exit codes (docs/usage.md): 0 exact or completed interval,
        # 10 a witness lighter than the cutoff, 75 an incomplete search, 2 an
        # invalid input or a failure. The first three leave a result.json to
        # read; only the last is an error here.
        OK_EXITS = (0, 10, 75)
        t0 = time.time()
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode not in OK_EXITS and n_sym and "symmetr" in (proc.stderr + proc.stdout).lower():
            inp.pop("symmetry_generators", None)
            n_sym = 0
            input_path.write_text(json.dumps(inp, indent=2) + "\n")
            if out_dir.exists():
                import shutil
                shutil.rmtree(out_dir)
            cmd = [a for a in cmd if a != "--resume"]
            proc = subprocess.run(cmd, capture_output=True, text=True)
        wall = round(time.time() - t0, 1)
        if proc.returncode not in OK_EXITS:
            raise QEDistCertifyError(
                f"QEDist failed (exit {proc.returncode}): {(proc.stderr or proc.stdout)[-300:]}"
            )
        # audit (its exit code mirrors the run's: 75 for an incomplete search is not a failure)
        aproc = subprocess.run(prefix + ["audit", str(out_dir)], capture_output=True, text=True)
        if aproc.returncode not in OK_EXITS:
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
        proved = int(lb) if lb is not None and int(lb) > 1 else None   # a bound of 1 is the trivial one
        blk.update(exact=False, status="TIMEOUT", lower_bound=proved,
                   note=(f"lower bound {proved}" if proved is not None else "nothing proved"))
        cert_sides[side] = blk

    overall = bool(cert_sides) and all(b.get("exact") for b in cert_sides.values())
    # also require QEDist's own exact flag when present
    if result.get("exact_distance") is not None and int(result["exact_distance"]) != d:
        overall = False

    verification = {
        "level": LEVEL,
        "note": "QEDist's lower bound is exhaustive search inside its kernel "
                "(tree search with bounds and symmetries); the vector it returned "
                "was re-verified by verify/heuristic_distance.py. Solver verdict only. "
                + (f"{n_sym} Tanner-graph symmetry generators supplied and verified by the tool."
                   if n_sym else "No symmetry generators supplied."),
    }
    rec = {
        "name": doc.get("name"),
        "d": d,
        "sides": cert_sides,
        "d_exact": overall,
        "solver": solver_string(prefix),
        "tlim_per_solve": float(tlim),
        "verification": verification,
    }
    if not overall:
        side_lbs = [
            int(b["lower_bound"]) if b.get("lower_bound") is not None else (d if b.get("exact") else 1)
            for b in cert_sides.values()
        ]
        rec["d_lower"] = min(side_lbs) if side_lbs else 1
        verification["checks_sha256"] = checks_sha256(doc)
    return rec


def _vector_from_support(support, n):
    v = np.zeros(n, dtype=np.int8)
    for q in support:
        v[int(q)] ^= 1
    return v


def _rung_completed(cert, w):
    """Return True when every side in ``cert`` excluded all logicals up to weight ``w``."""
    sides = (cert.get("sides") or {}).values()
    if not sides:
        return False
    for b in sides:
        if b.get("status") == "SAT":
            return False
        if b.get("exact"):
            continue
        lb = b.get("lower_bound")
        if lb is None or int(lb) < w + 1:
            return False
    return True


def run_ladder(doc, *, root=None, budget=60.0, threads=1, kmin=None):
    """Run ascending cutoffs 1..d-1 (or kmin..d-1), resuming QEDist and keeping the last completed rung."""
    import tempfile

    d = int(doc["distance"]["d"])
    start = int(kmin) if kmin and int(kmin) > 1 else 1
    last = None
    first = None
    with tempfile.TemporaryDirectory(prefix="qedist-ladder-") as td:
        for w in range(start, d):
            try:
                c = certify(doc, root=root, tlim=budget, threads=threads, cutoff=w, work_dir=td)
            except Exception as exc:  # noqa: BLE001
                print(f"cutoff {w}: {exc}", file=sys.stderr)
                break
            if first is None:
                first = c
            if any(b.get("status") == "SAT" for b in (c.get("sides") or {}).values()):
                last = c
                break
            if not _rung_completed(c, w):
                break
            last = c
            if c.get("d_exact"):
                break
    if last is None:
        if first is not None:
            cert = first
        else:
            raise QEDistCertifyError("ladder failed on the first rung")
    else:
        cert = last
    cert.setdefault("ladder", {"budget_per_side": budget})
    return cert


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(description="Certify a board entry with QEDist")
    ap.add_argument("path")
    ap.add_argument("--qedist", default=None)
    ap.add_argument("--tlim", type=float, default=60.0)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--ladder", type=float, default=None, metavar="SECONDS")
    ap.add_argument("--kmin", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    with open(args.path, encoding="utf-8") as f:
        doc = json.load(f)
    if args.ladder is None:
        cert = certify(doc, root=args.qedist, tlim=args.tlim, threads=args.threads)
    else:
        cert = run_ladder(doc, root=args.qedist, budget=args.ladder, threads=args.threads, kmin=args.kmin)
    print(json.dumps(cert, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
