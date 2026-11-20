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
import re
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


OK_EXITS = (0, 10, 75)   # QEDist (docs/usage.md): exact or interval, witness found, incomplete; 2 is an error


def _run_cutoff(doc, prefix, cutoff, tlim, threads, out_dir, symmetries):
    """One `qedist certify` at one cutoff; returns (result.json as a dict, wall seconds, generators used).

    Tanner-graph symmetries cut the search roots to one per orbit (issue
    #6867); the tool verifies them and refuses a wrong one, in which case the
    run is repeated without them. Exit codes 0, 10, and 75 all leave a result
    to read, and `qedist audit` mirrors the run's code.
    """
    out_dir = Path(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    inp = challenge_to_qedist(doc, include_witnesses=True, symmetries=symmetries)
    n_sym = len(inp.get("symmetry_generators") or [])
    input_path = out_dir.parent / (out_dir.name + ".input.json")
    input_path.write_text(json.dumps(inp, indent=2) + "\n")
    cmd = prefix + [
        "certify", str(input_path),
        "--profile", "css",
        "--cutoff", str(int(cutoff)),
        "--seconds-per-shard", str(float(tlim)),
        "--workers", str(int(threads)),
        "--out", str(out_dir),
    ]
    if out_dir.exists():
        cmd.insert(-2, "--resume")
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
    aproc = subprocess.run(prefix + ["audit", str(out_dir)], capture_output=True, text=True)
    if aproc.returncode not in OK_EXITS:
        raise QEDistCertifyError(f"QEDist audit failed: {(aproc.stderr or aproc.stdout)[-300:]}")
    return json.loads((out_dir / "result.json").read_text()), wall, n_sym


def certify(doc, *, root=None, tlim=60.0, threads=1, cutoff=None, work_dir=None,
            symmetries=True, sides=None, intermediate=False):
    """Certify a CSS entry's per-side distances with QEDist; return the certificate record.

    Each side is asked at its own claimed value, as tropidist_certify does, so
    an entry whose sides differ (d_X != d_Z) gets one run per distinct cutoff
    and each side is read from the run at its own value - 1; a symmetric
    entry gets one run. An explicit ``cutoff`` (the ladder's rung) is one run
    for both sides at that cutoff.
    """
    if doc.get("code_type") != "CSS":
        raise QEDistCertifyError("QEDist handles CSS codes only")
    d = int(doc["distance"]["d"])
    sides_in = doc["distance"]
    # a side without its own block is asked at d, as the tropidist certifier does;
    # ``sides`` restricts the record to those sides (the per-side ladder reads one)
    claims = {s: int((sides_in.get(s) or {}).get("value", d))
              for s in ("X", "Z") if sides is None or s in sides}
    if cutoff is None:
        plan = {}
        for side, value in claims.items():
            plan.setdefault(value - 1, []).append(side)
    else:
        plan = {int(cutoff): list(claims)}
    for c in plan:
        if c > MAX_CUTOFF:
            raise QEDistCertifyError(f"cutoff {c} exceeds QEDist's cap ({MAX_CUTOFF})")
        if c < 1:
            raise QEDistCertifyError("cutoff must be at least 1")

    prefix = qedist_root(root)
    if prefix is None:
        raise QEDistCertifyError(
            "QEDist is not installed; set QEDIST or install from " + QEDIST_REPO
        )

    import tempfile
    tmp = Path(work_dir) if work_dir is not None else Path(tempfile.mkdtemp(prefix="qedist-cert-"))
    per_side = {}            # side -> (sector bound, wall)
    results = {}             # cutoff -> result
    n_sym = 0
    for c, side_list in sorted(plan.items()):
        # one directory per cutoff: QEDist resumes only a run with the same
        # cutoff, so a ladder sharing one directory died at its second rung
        out_dir = tmp / f"run-{c}"
        result, wall, used = _run_cutoff(doc, prefix, c, tlim, threads, out_dir, symmetries)
        results[c] = result
        n_sym = max(n_sym, used)
        for side in side_list:
            per_side[side] = ((result.get("sector_bounds") or {}).get(side, {}), wall)

    n = doc["n"]
    HX = HD._matrix(doc["checks"]["X"], n)
    HZ = HD._matrix(doc["checks"]["Z"], n)
    cert_sides = {}
    for side, claim in claims.items():
        sb, wall = per_side[side]
        lb = sb.get("lower")
        ub = sb.get("upper")
        witness = sb.get("witness")
        blk = {"value": claim, "secs": round(wall / len(plan.get(claim - 1, [side])) if cutoff is None
                                             else wall / 2.0, 1)}
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

    base = results.get(d - 1)
    return _assemble(doc, cert_sides, prefix, tlim, n_sym,
                     per_side=len(plan) > 1,
                     tool_exact=(base.get("exact_distance") if base is not None else None),
                     strict=not intermediate)


def _assemble(doc, cert_sides, prefix, tlim, n_sym, *, per_side=False, tool_exact=None, ladder=None,
              strict=True):
    """Build the certificate record from per-side blocks.

    d_exact needs every side exact at its own claim. A record whose sides are
    all proved at least d but not all closed (the minimum side exact, a side
    above d still open) has no certificate shape: it is neither exact nor a
    partial with d_lower < d, so it is refused here rather than filed and
    rejected by verify/check_certs.py (issue #6867).
    """
    d = int(doc["distance"]["d"])
    overall = bool(cert_sides) and all(b.get("exact") for b in cert_sides.values())
    if tool_exact is not None and int(tool_exact) != d:
        overall = False
    verification = {
        "level": LEVEL,
        "note": "QEDist's lower bound is exhaustive search inside its kernel "
                "(tree search with bounds and symmetries); the vector it returned "
                "was re-verified by verify/heuristic_distance.py. Solver verdict only. "
                + (f"{n_sym} Tanner-graph symmetry generators supplied and verified by the tool."
                   if n_sym else "No symmetry generators supplied.")
                + (" Each side asked at its own claimed value." if per_side else ""),
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
    if ladder is not None:
        rec["ladder"] = {"budget_per_side": ladder}
    if not overall:
        side_lbs = [
            int(b["lower_bound"]) if b.get("lower_bound") is not None else (d if b.get("exact") else 1)
            for b in cert_sides.values()
        ]
        lb = min(side_lbs) if side_lbs else 1
        if strict and lb >= d and not any(b.get("status") == "SAT" for b in cert_sides.values()):
            open_sides = [s for s, b in cert_sides.items() if not b.get("exact")]
            raise QEDistCertifyError(
                f"every side is proved >= {d} but side(s) {open_sides} above d did not close; "
                "no certificate shape carries that (issue #6867)"
            )
        rec["d_lower"] = lb
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
    """Ascending cutoffs, keeping the last completed rung per side.

    Both sides climb together to the smaller claim minus one (one run per
    rung, as before); a side whose claim is larger then climbs on alone to
    its own claim minus one, so an entry with d_X != d_Z gets its larger side
    laddered past d instead of stopping where the smaller side's witness
    appears. QEDist runs both sectors at every rung; only the climbing side
    is read from its own runs.
    """
    import tempfile

    d = int(doc["distance"]["d"])
    dist = doc["distance"]
    claims = {s: int((dist.get(s) or {}).get("value", d)) for s in ("X", "Z")}
    low = min(claims.values())
    start = int(kmin) if kmin and int(kmin) > 1 else 1
    n_sym = 0

    def note_sym(c):
        nonlocal n_sym
        m = re.search(r"(\d+) Tanner-graph symmetry generators", (c.get("verification") or {}).get("note", ""))
        n_sym = max(n_sym, int(m.group(1)) if m else 0)

    def completed(blk, w):
        return bool(blk.get("exact")) or (blk.get("lower_bound") or 0) >= w + 1

    with tempfile.TemporaryDirectory(prefix="qedist-ladder-") as td:
        first = last = None
        joint_rungs = range(start, low) if start < low else [low - 1]
        for w in joint_rungs:
            try:
                c = certify(doc, root=root, tlim=budget, threads=threads, cutoff=w, work_dir=td,
                            intermediate=True)
            except QEDistCertifyError as exc:
                print(f"cutoff {w}: {exc}", file=sys.stderr)
                break
            note_sym(c)
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
        if last is None and first is None:
            raise QEDistCertifyError("ladder failed on the first rung")
        base = last if last is not None else first
        blocks = dict(base["sides"])
        reached = last is not None and _rung_completed(last, low - 1) \
            and not any(b.get("status") == "SAT" for b in blocks.values())
        if reached:
            for side, claim in claims.items():
                if claim <= low or blocks[side].get("exact"):
                    continue
                for w in range(low, claim):
                    try:
                        c = certify(doc, root=root, tlim=budget, threads=threads, cutoff=w,
                                    work_dir=os.path.join(td, side), sides=[side], intermediate=True)
                    except QEDistCertifyError as exc:
                        print(f"{side} cutoff {w}: {exc}", file=sys.stderr)
                        break
                    note_sym(c)
                    blk = c["sides"][side]
                    if blk.get("status") == "SAT":
                        blocks[side] = blk
                        break
                    if not completed(blk, w):
                        break
                    blocks[side] = blk
                    if blk.get("exact"):
                        break
    return _assemble(doc, blocks, qedist_root(root), budget, n_sym,
                     per_side=len(set(claims.values())) > 1, ladder=budget)

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
