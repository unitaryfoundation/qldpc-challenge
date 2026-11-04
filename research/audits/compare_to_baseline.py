#!/usr/bin/env python
"""Compare a candidate code entry to a named surface-code baseline entry.

Usage:
    python research/audits/compare_to_baseline.py codes/CAND.json codes/BASE.json

Prints a structured, read-only comparison. Does not modify the board or any
entry. Intended for Tier B/C documented comparisons (issue #4601).
"""
import json
import sys


def load(path):
    with open(path) as f:
        return json.load(f)


def summary(d, path):
    dist = d.get("distance", {})
    dval = dist.get("d")
    if dval is None and "P" in dist:
        dval = dist["P"].get("value")
    if dval is None:
        dval = dist.get("X", {}).get("value")
    return {
        "slug": __import__("os").path.basename(path).replace(".json", ""),
        "n": d.get("n"),
        "k": d.get("k"),
        "d": dval,
        "family": d.get("family"),
        "confidence": dist.get("X", {}).get("confidence") or dist.get("P", {}).get("confidence"),
    }


def main():
    if len(sys.argv) != 3:
        print("usage: compare_to_baseline.py CANDIDATE.json BASELINE.json", file=sys.stderr)
        sys.exit(2)
    cand = load(sys.argv[1])
    base = load(sys.argv[2])
    c = summary(cand, sys.argv[1])
    b = summary(base, sys.argv[2])
    print(f"{'metric':24}{'candidate':>14}{'baseline':>14}")
    print("-" * 52)
    for key in ("n", "k", "d"):
        print(f"{key:24}{str(c[key]):>14}{str(b[key]):>14}")
    print(f"{'family':24}{str(c['family']):>14}{str(b['family']):>14}")
    # derived
    def kd2(d):
        n, k, dd = d["n"], d["k"], d["d"]
        if n and dd:
            return (k * dd * dd) / n
        return None
    print(f"{'kd^2/n':24}{str(round(kd2(c),3) if kd2(c) is not None else 'n/a'):>14}{str(round(kd2(b),3) if kd2(b) is not None else 'n/a'):>14}")
    # circuit tier
    cc = cand.get("circuit", {})
    bb = base.get("circuit", {})
    print(f"{'d_circ.X':24}{str(cc.get('d_circ',{}).get('X',{}).get('value')):>14}{str(bb.get('d_circ',{}).get('X',{}).get('value')):>14}")
    print(f"{'d_circ.Z':24}{str(cc.get('d_circ',{}).get('Z',{}).get('value')):>14}{str(bb.get('d_circ',{}).get('Z',{}).get('value')):>14}")


if __name__ == "__main__":
    import os
    main()