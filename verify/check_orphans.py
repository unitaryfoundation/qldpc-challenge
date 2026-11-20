#!/usr/bin/env python3
"""Audit for orphaned circuit artifacts and stray files under repro/.

Standing counterpart to verify/test_orphan_cleanup.py: that test covers the
git-rm scenario, this script sweeps the whole tree so an orphan (or a stray
working directory under repro/) is reported even when nothing in the PR
touches it.

    python verify/check_orphans.py              # list every problem
    python verify/check_orphans.py --root PATH  # another tree
    python verify/check_orphans.py --quiet      # counts only

Checks:
  1. Every circuits/<slug>/ directory has a matching codes/<slug>.json.
  2. If codes/<slug>.json declares a "circuit" block, circuits/<slug>/ exists.
  3. repro/ contains only top-level *.json manifests (no subdirectories,
     no stray files) -- issue #3810.
  4. No .dem files are committed under circuits/ once the derived-DEM policy
     is in force (ratcheted: only enforced when CHECK_ORPHANS_NO_DEM=1).

Exit status is 0 on a clean tree, 1 otherwise.
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def slugs_with_code(root):
    codes_dir = os.path.join(root, "codes")
    out = set()
    if not os.path.isdir(codes_dir):
        return out
    for name in os.listdir(codes_dir):
        if name.endswith(".json"):
            out.add(name[:-5])
    return out


def code_has_circuit(root, slug):
    path = os.path.join(root, "codes", slug + ".json")
    try:
        with open(path) as f:
            doc = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    return bool(doc.get("circuit"))


def audit(root, quiet=False):
    problems = []
    code_slugs = slugs_with_code(root)
    circuits_dir = os.path.join(root, "circuits")

    # 1. orphaned circuit directories
    if os.path.isdir(circuits_dir):
        for name in sorted(os.listdir(circuits_dir)):
            full = os.path.join(circuits_dir, name)
            if not os.path.isdir(full):
                continue
            if name not in code_slugs:
                problems.append(f"orphaned circuits dir: circuits/{name}/ (no codes/{name}.json)")

    # 2. missing circuit evidence
    for slug in sorted(code_slugs):
        if not code_has_circuit(root, slug):
            continue
        cdir = os.path.join(circuits_dir, slug)
        if not os.path.isdir(cdir):
            problems.append(
                f"missing circuits dir for circuit-tier entry: circuits/{slug}/ (codes/{slug}.json declares circuit)"
            )
            continue
        for side in ("memory_x.stim", "memory_z.stim"):
            if not os.path.exists(os.path.join(cdir, side)):
                problems.append(f"missing {side} in circuits/{slug}/")

    # 3. repro/ surface. Legacy tracked working directories are grandfathered
    # (issue #3810: "Directories already tracked stay tracked"); only NEW
    # stray directories / non-manifest files are refused.
    legacy_repro_dirs = {
        "cpm-568-146-18",
        "cyclic-23-1-7",
        "cyclic-25-5-3",
        "cyclic-25-5-5",
        "cyclic-27-3-5",
        "cyclic-29-1-9",
    }
    repro_dir = os.path.join(root, "repro")
    if os.path.isdir(repro_dir):
        for name in sorted(os.listdir(repro_dir)):
            full = os.path.join(repro_dir, name)
            if os.path.isdir(full):
                if name in legacy_repro_dirs:
                    continue
                problems.append(
                    f"stray directory under repro/: repro/{name}/ (only repro/<slug>.json manifests allowed)"
                )
            elif not (name.endswith(".json")):
                problems.append(f"stray file under repro/: repro/{name}")

    # 4. .dem policy (ratcheted)
    if os.environ.get("CHECK_ORPHANS_NO_DEM") == "1" and os.path.isdir(circuits_dir):
        for dirpath, _, files in os.walk(circuits_dir):
            for fn in files:
                if fn.endswith(".dem"):
                    rel = os.path.relpath(os.path.join(dirpath, fn), root)
                    problems.append(f"committed .dem under circuits/: {rel} (DEM is derived from .stim)")

    if quiet:
        print(f"orphans/strays: {len(problems)}")
    else:
        for p in problems:
            print(p)
        if not problems:
            print("clean: no orphaned circuits, stray repro files, or .dem bloat")
    return 0 if not problems else 1


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=ROOT)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    return audit(args.root, quiet=args.quiet)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
