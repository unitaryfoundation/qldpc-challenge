"""Dedup a batch of candidate submissions before opening PRs.

Usage:
    uv run python research/kit/dedup_submissions.py candidate1.json candidate2.json ...
    uv run python research/kit/dedup_submissions.py --dir research/candidates/<run>/

Prints groups of candidates that share (n,k,d,w) or a canonical symplectic form.
A batch should contain at most one representative per group before submission.
"""

import argparse
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in ("verify", os.path.join("research", "kit")):
    _full = os.path.join(ROOT, _p)
    if _full not in sys.path:
        sys.path.insert(0, _full)

import gf2
import numpy as np
import qldpc_verify as V


def canon(doc):
    A, B = V.stabilizer_matrices(doc) if doc.get("code_type") == "stabilizer" else (None, None)
    if A is None:
        # CSS: fall back to (n,k,d,w) only
        return None
    A, B = A.astype(np.int8), B.astype(np.int8)
    S = np.concatenate([A, B], axis=1).astype(np.int8)
    R, _ = gf2.rref(S)
    R = np.asarray(R)
    R = R[np.any(R, axis=1)]
    return R.tobytes() + bytes([S.shape[1] % 251])


def axes(doc):
    n = doc["n"]
    k = doc["k"]
    d = doc["distance"]["d"]
    w = doc.get("w")
    if w is None:
        w = max((r.get("weight", 0) for r in doc.get("checks", {}).get("S", [])), default=0)
    # CSS fallback: max check weight from Hx/Hz
    if w is None or w == 0:
        hx = doc.get("checks", {}).get("Hx", [])
        hz = doc.get("checks", {}).get("Hz", [])
        ws = [len(r) for r in hx + hz]
        w = max(ws) if ws else 0
    return (n, k, d, w)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files", nargs="*", help="candidate JSON files")
    ap.add_argument("--dir", help="directory of candidate JSON files")
    args = ap.parse_args()

    files = list(args.files)
    if args.dir:
        files += glob.glob(os.path.join(args.dir, "*.json"))
    files = [f for f in files if not f.endswith(".verdict.json")]
    if not files:
        print("no candidate files given", file=sys.stderr)
        sys.exit(2)

    groups = {}
    for f in files:
        doc = json.load(open(f))
        key = axes(doc)
        groups.setdefault(key, []).append(f)

    distinct = True
    for key, members in groups.items():
        if len(members) > 1:
            distinct = False
            print(f"DUPLICATE (n,k,d,w)={key}: {len(members)} candidates")
            for m in members:
                print(f"  - {m}")
    # canonical form dedup (stabilizer only)
    canon_groups = {}
    for f in files:
        doc = json.load(open(f))
        if doc.get("code_type") != "stabilizer":
            continue
        c = canon(doc)
        if c is None:
            continue
        canon_groups.setdefault(c, []).append(f)
    for c, members in canon_groups.items():
        if len(members) > 1:
            distinct = False
            print(f"CANONICAL DUPLICATE: {len(members)} candidates")
            for m in members:
                print(f"  - {m}")

    if distinct:
        print(f"OK: {len(files)} candidates, all distinct by (n,k,d,w) and canonical form.")
    else:
        print("NOT DISTINCT: collapse duplicates before submitting.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
