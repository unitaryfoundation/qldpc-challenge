#!/usr/bin/env python3
"""Record who opened each primary-track cell, and each declared family within it, and when (issue #4029).

Issue #4029 asked whether the board should carry an ``opens`` flag for the
entry that first populates a cell, a family, or a geometry. This script is
the data behind the decision and the record that replaces the flag: for every
populated cell key (locality class, weight class, code type), the first entry
by ``provenance.date`` (ties by slug), the first entry per declared family tag,
and the first modular and 3D-layout entries, written as a dated JSON record
under research/audits/ with a table a reader can quote.

What it shows on today's board is why the flag was declined: cells nest, so
the smallest, lowest-weight, most local code opens every cell it belongs to
(three entries open all 24 cells, the Steane code every CSS cell in 1996), and
the family half rests on the one self-declared label. First-arrival is a fact
about the board's history, not a property the verifier can prove about a code,
so it is recorded here and never shown as a badge, ranked, or scored.

    uv run python research/audits/cell_openings.py
    uv run python research/audits/cell_openings.py --out research/audits/cell_openings-<date>.json --markdown
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
    spec = importlib.util.spec_from_file_location("site_build_openings", os.path.join(ROOT, "site", "build.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _head():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _row(e):
    return {"slug": e["slug"], "date": e.get("date") or None, "family": e["family"], "origin": e["origin"],
            "n": e["n"], "k": e["k"], "d": e["d"]}


def openings(entries, cells_by_key):
    """Per cell: the first entry, the first per declared family, and the first modular and 3D entries."""
    def order(i):
        return (entries[i].get("date") or "~", entries[i]["slug"])
    out = {}
    for cell, idxs in cells_by_key.items():
        ranked = sorted(idxs, key=order)
        first = entries[ranked[0]]
        fams, modular, three_d = {}, None, None
        for i in ranked:
            e = entries[i]
            fams.setdefault(e["family"], _row(e))
            if modular is None and e.get("modular"):
                modular = _row(e)
            if three_d is None and e.get("geo_dim") == 3:
                three_d = _row(e)
        key = "~".join(str(c) for c in cell)
        out[key] = {"members": len(idxs), "first": _row(first),
                    "first_by_declared_family": dict(sorted(fams.items())),
                    "first_modular": modular, "first_3d_layout": three_d}
    return dict(sorted(out.items()))


def record(entries, cells_by_key):
    table = openings(entries, cells_by_key)
    openers = {v["first"]["slug"] for v in table.values()}
    fam_openers = {r["slug"] for v in table.values() for r in v["first_by_declared_family"].values()}
    return {"audit_version": 1, "issue": 4029,
            "date": datetime.datetime.now(datetime.timezone.utc).date().isoformat(), "head": _head(),
            "definitions": {
                "cell": "a populated primary-track cell key: locality class, weight class, and code type for a "
                        "stabilizer entry (site/build.py cells_by_key); cells nest, so an entry is in every "
                        "cell it qualifies for",
                "first": "the member with the earliest provenance.date, ties broken by slug; a seeded baseline "
                         "carries its publication date, a submission its submission date",
                "family": "the entry's declared family tag, the board's one self-declared label",
                "modular": "the verifier's modular-layout flag", "3d_layout": "the verifier's layout dimension"},
            "caveat": ("first arrival is a fact about the board's history, not a property of a code; nothing "
                       "here is a flag, a rank, or a score (decision on issue #4029)"),
            "counts": {"cells": len(table), "entries": len(entries), "distinct_cell_openers": len(openers),
                       "distinct_family_in_cell_openers": len(fam_openers)},
            "cells": table}


def markdown(rec):
    c = rec["counts"]
    lines = [f"{c['cells']} cells, {c['entries']} entries; {c['distinct_cell_openers']} distinct entries opened "
             f"a cell, {c['distinct_family_in_cell_openers']} opened a declared family within a cell.", "",
             "| cell | members | first entry (date, family, origin) | declared families | first modular "
             "| first 3D |",
             "|---|---|---|---|---|---|"]
    for key, v in rec["cells"].items():
        f = v["first"]
        lines.append(f"| {key} | {v['members']:,} | {f['slug']} ({f['date']}, {f['family']}, {f['origin']}) | "
                     f"{len(v['first_by_declared_family'])} | "
                     f"{(v['first_modular'] or {}).get('slug', '-')} | "
                     f"{(v['first_3d_layout'] or {}).get('slug', '-')} |")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    ap.add_argument("--out", default=os.path.join(HERE, f"cell_openings-{today}.json"))
    ap.add_argument("--markdown", action="store_true")
    a = ap.parse_args(argv)
    build = load_site_build()
    entries = build.load_entries()
    rec = record(entries, build.cells_by_key(entries))
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rec, f, indent=1, sort_keys=True)
        f.write("\n")
    print(f"wrote {os.path.relpath(a.out, ROOT)}")
    print(markdown(rec) if a.markdown else markdown(rec).splitlines()[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
