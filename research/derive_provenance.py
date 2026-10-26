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
``not_derived``
    the index has not been run against this entry at all. Distinct from
    ``no_match``, which means it was run and found nothing, and the distinction
    is the whole point: an entry nobody has checked must not be counted as one
    checked and cleared.

Coverage is therefore a state the table can represent rather than an error.
That matters because regenerating needs the literature index, which is not
shipped, so a board that grows cannot be reconciled by whoever merged the code.
``--top-up`` adds ``not_derived`` rows for new entries and drops rows for
entries that left, needs neither the index nor pynauty, and a later
``--from-matches`` promotes those rows. ``--check`` hard-fails only on things
that are wrong (an unknown bucket, ``literature`` with no evidence, counts that
disagree with the entries) and reports mere staleness loudly without failing,
which is what this module docstring promised before it could deliver it.
``--residual`` writes the list of ``not_derived`` entries as a tracking-issue
body: the remainder only an index run can settle, which the weekly
``provenance-top-up`` workflow keeps published (issue #4023).

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
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROV = os.path.join(HERE, "provenance")
SOURCES = os.path.join(PROV, "sources.json")
DERIVED = os.path.join(PROV, "derived.json")

BUCKETS = ("literature", "parameters_only", "no_match", "not_derived")


def load_sources():
    with open(SOURCES, encoding="utf-8") as f:
        s = json.load(f)
    return s["literature"], s["not_literature"], s.get("parameters_only", {})


def board_slugs():
    d = os.path.join(ROOT, "codes")
    return sorted(os.path.splitext(f)[0] for f in os.listdir(d)
                  if f.endswith(".json"))


def stabilizer_slugs():
    """Board entries the index checker has no method for: general stabilizer codes.

    ``iso_check.py`` decides equivalence on the typed Tanner graph of a CSS pair
    and skips every other entry, so no index run can move these out of
    ``not_derived``. The residual list reports them apart and does not wait
    on them.
    """
    d = os.path.join(ROOT, "codes")
    out = set()
    for f in os.listdir(d):
        if not f.endswith(".json"):
            continue
        try:
            with open(os.path.join(d, f), encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            continue
        if doc.get("code_type", "CSS") != "CSS":
            out.add(f[:-5])
    return out


def derive(matches_csv, param_csv=None, covered=None):
    """Bucket every board slug from the isomorphism and parameter tables.

    ``covered`` is the slug set the index run actually looked at. Anything
    outside it is ``not_derived`` rather than ``no_match``: the run cannot
    clear an entry it never saw.
    """
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
        elif covered is None or slug in covered:
            out[slug] = {"bucket": "no_match", "matches": []}
        else:
            out[slug] = {"bucket": "not_derived", "matches": []}
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


def top_up():
    """Reconcile the committed table with today's codes/, without the index.

    New board entries get a ``not_derived`` row and entries that have left are
    dropped. Nothing already derived is touched, so this never launders an
    unchecked code into a checked bucket; it only records what is not yet
    known. Needs no index and no pynauty, so whoever merges a code PR can run
    it, which is the thing that made the previous exact-coverage rule
    unsatisfiable.
    """
    with open(DERIVED, encoding="utf-8") as f:
        payload = json.load(f)
    table = payload["entries"]
    want = set(board_slugs())
    added = sorted(want - set(table))
    gone = sorted(set(table) - want)
    for slug in added:
        table[slug] = {"bucket": "not_derived", "matches": []}
    for slug in gone:
        del table[slug]
    payload["counts"] = counts(table)
    with open(DERIVED, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=1, sort_keys=True)
        f.write("\n")
    print(f"topped up: +{len(added)} not_derived, -{len(gone)} departed, "
          f"{len(table)} entries")
    if added:
        print("  added: " + " ".join(added[:12])
              + (" ..." if len(added) > 12 else ""))
    if gone:
        print("  dropped: " + " ".join(gone[:12])
              + (" ..." if len(gone) > 12 else ""))
    return 0


def residual(path, run_url=None):
    """Write the tracking-issue body listing the entries the index has not seen.

    The list is what a later index run must cover; the weekly top-up only keeps
    it honest as the board changes. General stabilizer entries, which the
    checker cannot test, are listed apart and left out of the count. Prints
    ``not_derived=N stabilizer_outside_method=S entries=M`` for the workflow
    that decides whether the issue stays open.
    """
    with open(DERIVED, encoding="utf-8") as f:
        payload = json.load(f)
    table = payload["entries"]
    c = counts(table)
    stab = stabilizer_slugs()
    pending = sorted(s for s, v in table.items() if v["bucket"] == "not_derived" and s not in stab)
    outside = sorted(s for s, v in table.items() if v["bucket"] == "not_derived" and s in stab)
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    lines = [
        f"As of {today}, the literature index has not been run against "
        f"{len(pending):,} of the board's {len(table):,} entries. "
        "research/provenance/derived.json records them as not_derived: not "
        "checked, which is different from no_match (checked, nothing found). "
        "Only an index run clears this list; the weekly top-up keeps it honest "
        "as the board changes (issue #4023).",
        "",
        "| bucket | entries |",
        "|---|---|",
    ]
    lines += [f"| {b} | {c[b]:,} |" for b in BUCKETS]
    lines += [
        "",
        "To clear it: run research/provenance/iso_check.py with LITERATURE_INDEX "
        "set, then `python research/derive_provenance.py --from-matches "
        "isomorphism_matches.csv --from-params param_matches.csv --covered "
        "<JSON list of the slugs the run saw>` (research/provenance/README.md). "
        "Entries the run does not see stay not_derived.",
        "",
        f"<details><summary>{len(pending):,} entries not yet checked</summary>",
        "",
        " ".join(pending) if pending else "(none)",
        "",
        "</details>",
        "",
    ]
    if outside:
        lines += [
            f"A further {len(outside):,} entries are general stabilizer codes, which the "
            "checker's typed-Tanner-graph test does not cover (it decides CSS pairs only). "
            "They stay not_derived until there is a method for them, and this issue does "
            "not wait on them.",
            "",
            f"<details><summary>{len(outside):,} stabilizer entries outside the checker's method</summary>",
            "",
            " ".join(outside),
            "",
            "</details>",
            "",
        ]
    lines += [
        "Kept current by the provenance-top-up workflow"
        + (f" ([this run]({run_url}))" if run_url else "")
        + ": opened when the list is non-empty, edited in place while it stays "
        "so, closed when it empties.",
    ]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print(f"not_derived={len(pending)} stabilizer_outside_method={len(outside)} entries={len(table)}")
    return 0


def check():
    """Confirm the committed table covers exactly today's codes/."""
    if not os.path.exists(DERIVED):
        print(f"missing {DERIVED}")
        return 1
    with open(DERIVED, encoding="utf-8") as f:
        payload = json.load(f)
    table = payload["entries"]
    have, want = set(table), set(board_slugs())

    # Wrong, as opposed to merely incomplete. These are the only conditions
    # that may fail CI: a table that cannot be regenerated in CI must not gate
    # on being complete, or every merge of a code PR turns main red and the
    # people blocked are exactly the ones who cannot fix it.
    broken = []
    for slug, v in sorted(table.items()):
        if v["bucket"] not in BUCKETS:
            broken.append(f"  {slug}: unknown bucket {v['bucket']!r}")
        if v["bucket"] == "literature" and not v["matches"]:
            broken.append(f"  {slug}: literature with no match recorded")
    # Normalised both sides: a table written before a bucket existed omits it
    # rather than being wrong, and a schema addition must not read as
    # corruption.
    stored = {b: (payload.get("counts") or {}).get(b, 0) for b in BUCKETS}
    if stored != counts(table):
        broken.append(f"  counts block disagrees with the entries: "
                      f"says {stored}, entries give {counts(table)}")
    if broken:
        print(f"derived provenance is BROKEN ({len(broken)} problems):")
        print("\n".join(broken[:40]))
        if len(broken) > 40:
            print(f"  ... and {len(broken) - 40} more")
        return 1

    # Incomplete: reported loudly, never fatal.
    missing, departed = sorted(want - have), sorted(have - want)
    c = payload["counts"]
    if missing or departed:
        print(f"derived provenance is STALE: {len(missing)} board entries "
              f"absent from the table, {len(departed)} table rows no longer "
              "on the board.")
        if missing:
            print("  absent: " + " ".join(missing[:12])
                  + (" ..." if len(missing) > 12 else ""))
        if departed:
            print("  departed: " + " ".join(departed[:12])
                  + (" ..." if len(departed) > 12 else ""))
        print("  run `python research/derive_provenance.py --top-up` to record "
              "them as not_derived (no index needed), then --from-matches when "
              "the index is next run.")
        return 0
    print(f"ok: derived provenance covers {len(table)} entries "
          f"({c['literature']} literature, {c['parameters_only']} "
          f"parameters-only, {c['no_match']} no-match, "
          f"{c.get('not_derived', 0)} not-derived)")
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from-matches", help="isomorphism_matches.csv from iso_check.py")
    ap.add_argument("--from-params", help="param_matches.csv from param_check.py")
    ap.add_argument("--covered", help="JSON list of the slugs the index run "
                                      "looked at; anything outside it is "
                                      "not_derived rather than no_match")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--top-up", action="store_true",
                    help="record new board entries as not_derived and drop "
                         "departed ones; needs no index")
    ap.add_argument("--residual", metavar="PATH",
                    help="write the tracking-issue body listing the "
                         "not_derived entries to PATH and print their count")
    ap.add_argument("--run-url", help="workflow run to link from the --residual body")
    a = ap.parse_args(argv)
    if a.top_up:
        return top_up()
    if a.residual:
        return residual(a.residual, a.run_url)
    if a.check or not a.from_matches:
        return check()
    covered = None
    if a.covered:
        with open(a.covered, encoding="utf-8") as f:
            covered = set(json.load(f))
    table, unknown = derive(a.from_matches, a.from_params, covered)
    payload = write(table, unknown)
    c = payload["counts"]
    print(f"wrote {DERIVED}: {c['literature']} literature, "
          f"{c['parameters_only']} parameters-only, {c['no_match']} no-match")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
