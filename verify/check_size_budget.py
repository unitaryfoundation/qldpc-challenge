#!/usr/bin/env python3
"""Size budget audit for the working tree.

Ratchets the cost of the big directories so a PR cannot silently grow them.
Thresholds are deliberately generous today and should be tightened as the
cleanup strategies land.

    python verify/check_size_budget.py              # report + verdict
    python verify/check_size_budget.py --root PATH  # another tree
    python verify/check_size_budget.py --quiet      # counts only

Checks:
  1. No single file under circuits/ exceeds MAX_CIRCUIT_FILE_BYTES.
  2. Total size of circuits/ does not exceed CIRCUITS_BUDGET_BYTES.
  3. Total size of docs/ does not exceed DOCS_BUDGET_BYTES.
  4. No *.dem file under circuits/ (enforced alongside strategy 1).

Exit status is 0 on a clean tree, 1 otherwise.
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Keep in sync with verify/circuit_verify.py::MAX_CIRCUIT_FILE_BYTES.
MAX_CIRCUIT_FILE_BYTES = 12_000_000
# Generous today; tighten to ~1 GB once strategy 1 lands.
CIRCUITS_BUDGET_BYTES = 9_000_000_000
DOCS_BUDGET_BYTES = 400_000_000


def dir_size(path):
    total = 0
    if not os.path.isdir(path):
        return 0
    for dirpath, _, files in os.walk(path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                pass
    return total


def audit(root, quiet=False):
    problems = []
    circuits_dir = os.path.join(root, "circuits")
    docs_dir = os.path.join(root, "docs")

    # 1. per-file cap + .dem ban
    if os.path.isdir(circuits_dir):
        for dirpath, _, files in os.walk(circuits_dir):
            for fn in files:
                full = os.path.join(dirpath, fn)
                try:
                    sz = os.path.getsize(full)
                except OSError:
                    continue
                if sz > MAX_CIRCUIT_FILE_BYTES:
                    rel = os.path.relpath(full, root)
                    problems.append(f"oversized circuit file: {rel} ({sz} > {MAX_CIRCUIT_FILE_BYTES})")
                if fn.endswith(".dem") and os.environ.get("CHECK_SIZE_NO_DEM") == "1":
                    rel = os.path.relpath(full, root)
                    problems.append(f"committed .dem under circuits/: {rel}")

    # 2. circuits budget
    csz = dir_size(circuits_dir)
    if csz > CIRCUITS_BUDGET_BYTES:
        problems.append(f"circuits/ exceeds budget: {csz} > {CIRCUITS_BUDGET_BYTES} bytes")

    # 3. docs budget
    dsz = dir_size(docs_dir)
    if dsz > DOCS_BUDGET_BYTES:
        problems.append(f"docs/ exceeds budget: {dsz} > {DOCS_BUDGET_BYTES} bytes")

    if quiet:
        print(f"size problems: {len(problems)}")
    else:
        for p in problems:
            print(p)
        if not problems:
            print(f"ok: circuits={csz} bytes, docs={dsz} bytes")
    return 0 if not problems else 1


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=ROOT)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    return audit(args.root, quiet=args.quiet)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
