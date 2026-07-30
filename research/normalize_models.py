#!/usr/bin/env python3
"""One-time migration: normalize model-name variants in codes/*.json.

The provenance.model field accumulated several string aliases for the same
underlying model (e.g. "hy3", "Hy3", "Tencent: Hy3", "Tencent: Hy3 (free)"
all describe Hy3). This script rewrites every codes/*.json in-place to use
the canonical name.

Canonical         → Aliases
───────────────────────────────────────────────────
Claude Opus 4.8   — (already consistent)
Claude Opus 5     — (already consistent)
Claude Fable 5    — (already consistent)
Tencent Hy3       hy3, Hy3, Tencent: Hy3, Tencent: Hy3 (free)
OpenAI 5.6 Sol    — (already consistent, single entry)

Usage:  python research/normalize_models.py
        # dry-run:  python research/normalize_models.py --dry-run
        # verbose: python research/normalize_models.py --verbose
"""

import argparse
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODES_DIR = os.path.join(ROOT, "codes")

# Map from raw (as-written) value → canonical name.
# Keys are sorted by specificity so an exact match wins before a substring.
NORMALIZE = {
    "hy3": "Tencent Hy3",
    "Hy3": "Tencent Hy3",
    "Tencent: Hy3": "Tencent Hy3",
    "Tencent: Hy3 (free)": "Tencent Hy3",
}

# Provider grouping for potential future use (not written to the data,
# but tracked here so this becomes the canonical taxonomy).
PROVIDER = {
    "Claude Opus 4.8": "anthropic",
    "Claude Opus 5": "anthropic",
    "Claude Fable 5": "anthropic",
    "Tencent Hy3": "tencent",
    "OpenAI 5.6 Sol": "openai",
}

CANONICAL = set(PROVIDER)


def normalize_model(raw: str) -> str:
    """Return the canonical name for a raw model string, or the original if
    no mapping exists (new models should be added to NORMALIZE)."""
    return NORMALIZE.get(raw, raw)


def fix_file(p: str, dry_run: bool, verbose: bool) -> int:
    """Apply model-name normalizations to one JSON file via line-level
    string replacement (no JSON round-trip, preserving formatting)."""
    slug = os.path.splitext(os.path.basename(p))[0]
    try:
        with open(p) as f:
            text = f.read()
    except OSError as exc:
        print(f"  ERROR  {slug}: {exc}")
        return 1

    # Validate the file is parseable before we touch it.
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"  ERROR  {slug}: invalid JSON — {exc}")
        return 1

    prov = doc.get("provenance", {})
    raw = prov.get("model")
    if raw is None:
        if verbose:
            print(f"  skip  {slug}: no model field")
        return 0

    canonical = normalize_model(raw)
    if canonical == raw:
        if raw not in CANONICAL and verbose:
            print(f"  note  {slug}: unrecognised model \"{raw}\", left as-is")
        elif verbose:
            print(f"  ok    {slug}: \"{raw}\"")
        return 0

    # Text-level replacement: match the raw model string as a JSON string
    # value on a line like  "model": "hy3",
    # We look for the exact raw value to avoid false matches.
    pattern = r'("model"\s*:\s*")' + re.escape(raw) + r'(")'
    new_text, n = re.subn(pattern, r'\g<1>' + canonical + r'\g<2>', text)
    if n == 0:
        print(f"  ERROR  {slug}: could not find model string \"{raw}\" in text "
              f"(JSON parses but text doesn't match — encoding issue?)")
        return 1
    if n > 1:
        print(f"  ERROR  {slug}: matched {n} times (expected 1); "
              f"aborting to avoid corrupting data")
        return 1

    if dry_run:
        print(f"  WOULD  {slug}: \"{raw}\" → \"{canonical}\"")
        return 2  # would-change marker

    with open(p, "w") as f:
        f.write(new_text)
    print(f"  FIXED  {slug}: \"{raw}\" → \"{canonical}\"")
    return 2  # changed marker


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", "-n", action="store_true",
                    help="print what would change without modifying files")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="show every file scanned, not just those changed")
    args = ap.parse_args()

    paths = sorted(glob.glob(os.path.join(CODES_DIR, "*.json")))
    if not paths:
        print(f"error: no JSON files found in {CODES_DIR}")
        sys.exit(1)

    changed = 0
    unchanged = 0
    errors = 0
    total = len(paths)

    for p in paths:
        ret = fix_file(p, dry_run=args.dry_run, verbose=args.verbose)
        if ret == 1:
            errors += 1
        elif ret == 2:
            changed += 1
        else:
            unchanged += 1

    print()
    print(f"Scanned {total} files.")
    print(f"  Changed:  {changed}")
    print(f"  Skipped:  {unchanged}")
    if errors:
        print(f"  Errors:   {errors}")
        sys.exit(1)


if __name__ == "__main__":
    main()