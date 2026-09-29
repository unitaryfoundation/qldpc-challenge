"""Derive each board entry's provenance from the isomorphism check, not from its label.

The board cannot currently answer "did this come from the literature or from a
search run here", which is what a literature-versus-discovered comparison needs
(issue #1279). The declared fields do not support it: of 1,560 entries, 1,280
say ``provenance.origin: submission`` and 1,074 carry no ``novelty`` at all,
while 556 of them cite a paper in their own construction text. ``submission``
records the path an entry arrived by, not where the code came from, and
relabelling by hand would reproduce the same problem the first time someone
forgets a field.

So the tag is computed instead. ``research/provenance/iso_check.py`` decides
permutation
equivalence of the given generating sets with nauty's canonical form of the
typed Tanner graph and re-verifies every hit by mapping row spaces with the
recovered qubit permutation. This module turns that output into one bucket per
slug:

``literature``
    isomorphic to a published code, with the source and its reference.
``parameters_only``
    a published code shares its (n, k, d) but no matrices are indexed for it,
    so equivalence cannot be decided either way. The non-abelian 2BGA rows are
    here until a GAP run, and codetables.de bounds are here permanently.
``no_match``
    nothing in the index matches. **Not a proof of independence**: two sparse
    generating sets of the same stabilizer group can have non-isomorphic Tanner
    graphs, so this bucket means "not found", not "not published".

Two things this deliberately does not do. It does not write to ``codes/``,
because a derived field that lives in the submission document would drift from
the derivation the moment the index grows; the table is the artifact and the
entry is joined to it by slug. And it does not touch ``verify/``: nothing here
gates a submission, it only reports.

    # regenerate (needs the literature index and pynauty; see provenance/README.md)
    LITERATURE_INDEX=/path/to/index python research/provenance/iso_check.py
    python research/derive_provenance.py --from-matches isomorphism_matches.csv

    # check the committed table still describes codes/ (no index needed)
    python research/derive_provenance.py --check
"""
import argparse
import collections
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROV = os.path.join(HERE, "provenance")
SOURCES = os.path.join(PROV, "sources.json")
DERIVED = os.path.join(PROV, "derived.json")

BUCKETS = ("literature", "parameters_only", "no_match")


def load_sources():
    with open(SOURCES, encoding="utf-8") as f:
        s = json.load(f)
    return s["literature"], s["not_literature"], s.get("parameters_only", {})


def board_slugs():
    d = os.path.join(ROOT, "codes")
    return sorted(os.path.splitext(f)[0] for f in os.listdir(d)
                  if f.endswith(".json"))


def derive(matches_csv, param_csv=None):
    """Bucket every board slug from the isomorphism and parameter tables."""
    lit_sources, not_lit, param_sources = load_sources()
    hits = collections.defaultdict(list)
    params_from_iso = collections.defaultdict(list)
    unknown_sources = collections.Counter()
    with open(matches_csv, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            src = r["other_source"]
            if src in not_lit:
                continue
            if src in param_sources:
                params_from_iso[r["board_slug"]].append(
                    {"source": src, "ref": param_sources[src],
                     "id": r["other_id"]})
                continue
            if src not in lit_sources:
                # An unclassified source is never promoted to literature; it is
                # reported so the list can be extended deliberately.
                unknown_sources[src] += 1
                continue
            if r["permutation_verified"] != "True":
                continue
            hits[r["board_slug"]].append(
                {"source": src, "ref": lit_sources[src], "id": r["other_id"],
                 "xz_swapped": r["xz_swapped"] == "True"})

    # A same-(n, k, d) hit whose source ships no matrices cannot be decided
    # either way, so it lands in parameters_only rather than in either
    # certainty. lit_has_matrix is the index's own flag for that.
    params = collections.defaultdict(list, params_from_iso)
    if param_csv and os.path.exists(param_csv):
        with open(param_csv, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                src = r.get("lit_source") or ""
                if r.get("lit_has_matrix") == "True":
                    continue
                if src in lit_sources or src in param_sources:
                    ref = lit_sources.get(src) or param_sources.get(src)
                    params[r["slug"]].append(
                        {"source": src, "ref": ref, "id": r.get("lit_id")})

    out = {}
    for slug in board_slugs():
        if slug in hits:
            out[slug] = {"bucket": "literature", "matches": hits[slug]}
        elif slug in params:
            out[slug] = {"bucket": "parameters_only",
                         "matches": params[slug][:4]}
        else:
            out[slug] = {"bucket": "no_match", "matches": []}
    return out, unknown_sources


def counts(table):
    c = collections.Counter(v["bucket"] for v in table.values())
    return {b: c.get(b, 0) for b in BUCKETS}


def write(table, unknown):
    payload = {
        "derivation_version": 1,
        "method": ("permutation equivalence of the given generating sets, by "
                   "nauty canonical form of the typed Tanner graph, every hit "
                   "re-verified by mapping row spaces with the recovered "
                   "permutation"),
        "caveat": ("no_match means the index holds no match, not that the code "
                   "is unpublished: two sparse generating sets of one "
                   "stabilizer group can have non-isomorphic Tanner graphs"),
        "counts": counts(table),
        "entries": table,
    }
    os.makedirs(PROV, exist_ok=True)
    with open(DERIVED, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=1, sort_keys=True)
        f.write("\n")
    if unknown:
        print("unclassified index sources (treated as not-literature):")
        for s, n in unknown.most_common():
            print(f"  {n:>5}  {s}")
    return payload


def check():
    """Confirm the committed table covers exactly today's codes/."""
    if not os.path.exists(DERIVED):
        print(f"missing {DERIVED}")
        return 1
    with open(DERIVED, encoding="utf-8") as f:
        payload = json.load(f)
    table = payload["entries"]
    have, want = set(table), set(board_slugs())
    problems = []
    for slug in sorted(want - have):
        problems.append(f"  {slug}: on the board, absent from the table")
    for slug in sorted(have - want):
        problems.append(f"  {slug}: in the table, no longer on the board")
    for slug, v in sorted(table.items()):
        if v["bucket"] not in BUCKETS:
            problems.append(f"  {slug}: unknown bucket {v['bucket']!r}")
        if v["bucket"] == "literature" and not v["matches"]:
            problems.append(f"  {slug}: literature with no match recorded")
    if payload.get("counts") != counts(table):
        problems.append("  counts block disagrees with the entries")
    if problems:
        print(f"derived provenance is stale ({len(problems)} problems):")
        print("\n".join(problems[:40]))
        if len(problems) > 40:
            print(f"  ... and {len(problems) - 40} more")
        print("\nregenerate with --from-matches; see "
              "research/provenance/README.md.")
        return 1
    c = payload["counts"]
    print(f"ok: derived provenance covers {len(table)} entries "
          f"({c['literature']} literature, {c['parameters_only']} "
          f"parameters-only, {c['no_match']} no-match)")
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from-matches", help="isomorphism_matches.csv from iso_check.py")
    ap.add_argument("--from-params", help="param_matches.csv from param_check.py")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    if a.check or not a.from_matches:
        return check()
    table, unknown = derive(a.from_matches, a.from_params)
    payload = write(table, unknown)
    c = payload["counts"]
    print(f"wrote {DERIVED}: {c['literature']} literature, "
          f"{c['parameters_only']} parameters-only, {c['no_match']} no-match")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
