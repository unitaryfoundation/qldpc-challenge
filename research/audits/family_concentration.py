#!/usr/bin/env python3
"""Record the frontier's declared-family concentration as of today (issue #4025).

The metric itself lives in site/build.py (``family_concentration``), computed
from the same per-cell and global Pareto frontiers that award the star, and
the site publishes it in docs/stats.json and beside the frontier map's
legend. This script is the recorder: it loads the board the way the site
does, writes the measurement with the date and the commit it describes to
``research/audits/family_concentration-<date>.json``, and prints the table a
fieldnote quotes, so successive runs make a time series out of a snapshot.

``family`` is the board's one self-declared label (research/AUTORESEARCH.md:
filterable, never ranked). Every number here measures the declared tag, not a
property recovered from H; the derived provenance buckets are the computed
axis wherever they cover an entry. Nothing here ranks anything.

    uv run python research/audits/family_concentration.py
    uv run python research/audits/family_concentration.py --out path.json --markdown
"""
import argparse
import datetime
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def load_site_build():
    spec = importlib.util.spec_from_file_location(
        "site_build_family", os.path.join(ROOT, "site", "build.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _head():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def markdown(rec):
    """Render the fieldnote's tables: the global frontier, then one row per cell."""
    g = rec["global"]
    top = ", ".join(f"{t['family']} {t['records']} ({100 * t['share']:.0f}%)" for t in g["top"])
    lines = [f"Global CSS frontier: {g['records']:,} records, {g['families']} named families and "
             f"{g['untagged']} untagged ({100 * g['untagged_share']:.0f}%); top {top}; "
             f"top two {100 * g['top2_share']:.0f}%; HHI {g['hhi']:.3f}.",
             f"Cells moved: {rec['cells_moved']} of {rec['cells_total']}.", "",
             "| cell | members | records | top family (share) | top two | HHI | incumbent -> leader | moved |",
             "|---|---|---|---|---|---|---|---|"]
    for key, c in rec["cells"].items():
        t1 = c["top"][0] if c["top"] else {"family": "-", "share": 0}
        inc = c["incumbent"]["family"] if c["incumbent"] else "(no baseline)"
        lines.append(f"| {key} | {c['members']:,} | {c['records']:,} | {t1['family']} "
                     f"({100 * t1['share']:.0f}%) | {100 * c['top2_share']:.0f}% | {c['hhi']:.3f} | "
                     f"{inc} -> {c['leader']['family']} | {'yes' if c['moved'] else 'no'} |")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    ap.add_argument("--out", default=os.path.join(HERE, f"family_concentration-{today}.json"))
    ap.add_argument("--markdown", action="store_true", help="print the fieldnote tables")
    a = ap.parse_args(argv)
    build = load_site_build()
    entries = build.load_entries()
    rec = build.family_concentration(entries)
    payload = {"audit_version": 1, "issue": 4025, "date": today, "head": _head(),
               "board": {"entries": len(entries),
                         "css": sum(1 for e in entries if e.get("code_type", "CSS") == "CSS")},
               **rec}
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=1, sort_keys=True)
        f.write("\n")
    g = rec["global"]
    print(f"wrote {os.path.relpath(a.out, ROOT)}: global frontier {g['records']} records, "
          f"top {g['top'][0]['family'] if g['top'] else '-'} {100 * g['top1_share']:.0f}%, "
          f"top two {100 * g['top2_share']:.0f}%, HHI {g['hhi']:.3f}; "
          f"{rec['cells_moved']} of {rec['cells_total']} cells moved")
    if a.markdown:
        print()
        print(markdown(rec))
    return 0


if __name__ == "__main__":
    sys.exit(main())
