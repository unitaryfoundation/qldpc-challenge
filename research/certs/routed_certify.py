#!/usr/bin/env python3
r"""Routed exact-distance certifier: QEDist when it can handle the entry, else tropidist.

Implements the follow-up described in
fieldnotes/2026-11-15-qedist-vs-tropidist-benchmark.md: QEDist for CSS (and
stabilizer) entries with d <= 64, tropidist otherwise.  Neither replaces the
trusted verifier; both file solver-level certificates.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "verify"))
sys.path.insert(0, os.path.join(ROOT, "research", "kit"))
sys.path.insert(0, HERE)

import qedist_certify  # noqa: E402
import qedist_stabilizer_certify  # noqa: E402


def _d(doc):
    dist = doc.get("distance") or {}
    if "d" in dist:
        return int(dist["d"])
    if "P" in dist and isinstance(dist["P"], dict):
        return int(dist["P"]["value"])
    raise ValueError("entry has no distance.d or distance.P.value")


def certify(doc, *, qedist_root=None, tropidist_root=None, tlim=60.0, threads=4, shards=1,
            ladder=None, kmin=None):
    d = _d(doc)
    ctype = doc.get("code_type")
    use_qedist = d <= 65  # QEDist cutoff cap is d-1 <= 64
    if ctype == "stabilizer":
        if use_qedist:
            return qedist_stabilizer_certify.certify(
                doc, root=qedist_root, tlim=tlim, threads=threads, shards=shards)
    elif ctype == "CSS":
        if use_qedist:
            if ladder:
                # ascending cutoffs, so an entry the single cutoff d - 1 cannot
                # close in the budget still files the lower bound it proved
                return qedist_certify.run_ladder(doc, root=qedist_root, budget=ladder,
                                                 threads=threads, kmin=kmin)
            return qedist_certify.certify(doc, root=qedist_root, tlim=tlim, threads=threads)
    else:
        raise ValueError(f"unsupported code_type {ctype!r}")

    # Fallback to tropidist for high distance.
    import tropidist_certify  # noqa: E402
    if tropidist_root is None:
        tropidist_root = os.environ.get("TROPIDIST_ROOT")
    if not tropidist_root:
        raise RuntimeError("entry needs tropidist (d > 64) but no --tropidist root given")
    return tropidist_certify.certify(doc, root=tropidist_root, tlim=tlim, threads=threads)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Routed exact-distance certifier (QEDist or tropidist)")
    ap.add_argument("path")
    ap.add_argument("--qedist", default=None)
    ap.add_argument("--tropidist", default=None)
    ap.add_argument("--tlim", type=float, default=60.0)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--ladder", type=float, default=None, metavar="SECONDS",
                    help="CSS entries: ascending cutoffs with this budget per rung (qedist_certify.run_ladder)")
    ap.add_argument("--kmin", type=int, default=None, help="first rung of the ladder")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    with open(args.path, encoding="utf-8") as f:
        doc = json.load(f)
    cert = certify(doc, qedist_root=args.qedist, tropidist_root=args.tropidist,
                   tlim=args.tlim, threads=args.threads, shards=args.shards,
                   ladder=args.ladder, kmin=args.kmin)
    print(json.dumps(cert, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())