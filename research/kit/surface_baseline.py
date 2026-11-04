"""Extract a surface-code baseline from a committed board entry into an .npz.

Usage:
    python research/kit/surface_baseline.py codes/598-25-4.json baseline.npz

Writes hx, hz (and coords if a layout exists) so the baseline can be fed to
`./qldpc submit` or compared with research/audits/compare_to_baseline.py.
This does not generate new codes; it packages an existing verified entry as a
reproducible baseline artifact (issue #4601).
"""
import json
import os
import sys

import numpy as np


def extract(path):
    with open(path) as f:
        d = json.load(f)
    checks = d["checks"]
    hx = np.array(checks.get("X", []), dtype=object)
    # store as list of supports in a simple way: write dense arrays
    n = d["n"]
    HX = np.zeros((len(checks.get("X", [])), n), dtype=np.uint8)
    for i, row in enumerate(checks.get("X", [])):
        for q in row:
            HX[i, q] ^= 1
    HZ = np.zeros((len(checks.get("Z", [])), n), dtype=np.uint8)
    for i, row in enumerate(checks.get("Z", [])):
        for q in row:
            HZ[i, q] ^= 1
    out = {"hx": HX, "hz": HZ}
    if "locality" in d and "coordinates" in d["locality"]:
        out["coords"] = np.array(d["locality"]["coordinates"])
    if "layers" in d.get("locality", {}):
        out["layers"] = np.array(d["locality"]["layers"])
    return out, d


def main():
    if len(sys.argv) != 3:
        print("usage: surface_baseline.py CODE.json OUT.npz", file=sys.stderr)
        sys.exit(2)
    data, d = extract(sys.argv[1])
    np.savez(sys.argv[2], **data)
    print(f"wrote {sys.argv[2]}: n={d['n']} k={d['k']} d={d['distance'].get('d')}")


if __name__ == "__main__":
    main()