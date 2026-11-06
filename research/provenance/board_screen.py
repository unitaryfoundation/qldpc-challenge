#!/usr/bin/env python3
"""Screen every CSS board entry against the board's own seeded and literature entries (issue #4024).

``derived.json`` says whether the literature index was run against an entry;
for most of the board it was not, and the index is not shipped. This is the
part of that backlog the repository can settle by itself. The reference set is
every entry with ``provenance.origin: baseline`` (seeded from the literature)
plus every entry the index already matched (bucket ``literature`` in
derived.json), and each CSS entry is compared with that set using the two
primitives the gate already uses for dedup:

* the exact fingerprint (``css_fingerprint`` in verify/qldpc_verify.py): the
  reduced row echelon forms of H_X and H_Z, so equal fingerprints mean the
  same stabilizer group on the same qubit labels;
* the Weisfeiler-Leman (WL) signature (``signature`` in the same module):
  invariant under qubit permutations, a necessary condition for permutation
  equivalence and never a sufficient one, which is why TRACKS.md treats a
  collision as a review item.

One verdict per entry, read as follows.

``exact_match``
    the fingerprint equals a reference entry's: the same code on the same
    labels.
``review``
    the WL signature equals a reference entry's and the fingerprint does not.
    Possibly permutation-equivalent, possibly not. Each such pair is listed,
    and where the newest ``research/audits/permutation_audit-<date>.json``
    has decided the pair (``equivalent``, ``inequivalent``, ``gb_family_no``,
    ``undecided``) that verdict is carried along; a pair the audit has not
    seen is an item for its next run.
``distinct``
    the WL signature matches no reference entry: not permutation-equivalent
    to any seeded or literature entry on the board. A statement about the
    board, not about the literature; the index-only backlog stays in
    derived.json as ``not_derived``.

Reference entries are screened against the rest of the reference set, so a
seeded entry that duplicates another seeded entry shows up too. Stabilizer
(non-CSS) entries are outside the screen, as they are outside the derived
table. Nothing here is a gate input, changes a ``novelty`` value, or ranks
anything.

    uv run python research/provenance/board_screen.py run
    uv run python research/provenance/board_screen.py check
"""
import argparse
import collections
import datetime
import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "verify"))
import qldpc_verify as V  # noqa: E402

DERIVED = os.path.join(HERE, "derived.json")
SCREEN = os.path.join(HERE, "board_screen.json")
AUDITS = os.path.join(ROOT, "research", "audits")
CODES = os.path.join(ROOT, "codes")
VERDICTS = ("exact_match", "review", "distinct")
RULE = {
    "exact_match": "the fingerprint (rref of H_X and H_Z) equals a reference "
                   "entry's: the same stabilizer group on the same qubit labels",
    "review": "the Weisfeiler-Leman signature equals a reference entry's and the "
              "fingerprint does not: possibly permutation-equivalent; a review "
              "item, carrying the permutation audit's verdict where it has one",
    "distinct": "the Weisfeiler-Leman signature matches no reference entry: not "
                "permutation-equivalent to any seeded or literature entry on "
                "the board; says nothing about codes the board does not carry",
}


def css_slugs():
    """Every CSS entry under codes/, by slug, read without verifying."""
    out = set()
    for path in glob.glob(os.path.join(CODES, "*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError):
            continue
        if not V.is_stabilizer(doc):
            out.add(os.path.splitext(os.path.basename(path))[0])
    return out


def board():
    """Map each CSS slug to (doc, fingerprint, WL hash), from the verifier's own reports.

    Also returns the CSS slugs the reports could not fingerprint, so they are
    counted rather than silently dropped.
    """
    docs, skipped = {}, []
    for e in V.board_reports(CODES):
        doc, rep = e["doc"], e["report"]
        slug = e.get("slug") or os.path.splitext(os.path.basename(e["path"]))[0]
        if doc is None or V.is_stabilizer(doc):
            continue
        fp = (rep or {}).get("fingerprint")
        sig = ((rep or {}).get("signature") or {}).get("hash")
        if not fp or not sig:
            skipped.append(slug)
            continue
        docs[slug] = (doc, fp, sig)
    return docs, sorted(skipped)


def reference_set(docs):
    """(baseline slugs, literature-bucket slugs), both restricted to screened entries."""
    baseline = {s for s, (doc, _, _) in docs.items()
                if (doc.get("provenance") or {}).get("origin") == "baseline"}
    literature = set()
    try:
        with open(DERIVED, encoding="utf-8") as f:
            table = json.load(f)["entries"]
        literature = {s for s, v in table.items() if v.get("bucket") == "literature"}
    except (OSError, ValueError, KeyError):
        pass
    return baseline, literature & set(docs)


def audit_verdicts():
    """{frozenset({a, b}): verdict} from the newest permutation audit record, and its path."""
    paths = sorted(glob.glob(os.path.join(AUDITS, "permutation_audit-*.json")))
    if not paths:
        return {}, None
    with open(paths[-1], encoding="utf-8") as f:
        rec = json.load(f)
    out = {frozenset((p["first"], p["second"])): p["verdict"]
           for p in rec.get("board_pairs", [])}
    return out, os.path.relpath(paths[-1], ROOT)


def screen(docs, reference, audit):
    """One record per screened entry; see the module docstring for the rule."""
    by_fp, by_wl = collections.defaultdict(set), collections.defaultdict(set)
    for s in reference:
        _, fp, wl = docs[s]
        by_fp[fp].add(s)
        by_wl[wl].add(s)
    entries = {}
    for s, (_, fp, wl) in docs.items():
        same_fp = sorted(by_fp.get(fp, set()) - {s})
        same_wl = sorted(by_wl.get(wl, set()) - {s} - set(same_fp))
        matches = [{"slug": r, "by": "fingerprint"} for r in same_fp]
        for r in same_wl:
            m = {"slug": r, "by": "wl"}
            verdict = audit.get(frozenset((s, r)))
            if verdict:
                m["audit"] = verdict
            matches.append(m)
        entries[s] = {"verdict": "exact_match" if same_fp else "review" if same_wl else "distinct",
                      "in_reference": s in reference, "matches": matches}
    return entries


def counts(entries):
    c = collections.Counter(v["verdict"] for v in entries.values())
    out = {k: c.get(k, 0) for k in VERDICTS}
    out["screened"] = len(entries)
    wl = [m for v in entries.values() for m in v["matches"] if m["by"] == "wl"]
    out["wl_matches"] = len(wl)
    out["wl_matches_by_audit"] = dict(sorted(
        collections.Counter(m.get("audit", "not_audited") for m in wl).items()))
    return out


def _head():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def run(out_path=SCREEN):
    docs, skipped = board()
    baseline, literature = reference_set(docs)
    reference = baseline | literature
    audit, audit_path = audit_verdicts()
    entries = screen(docs, reference, audit)
    payload = {
        "screen_version": 1,
        "issue": 4024,
        "date": datetime.datetime.now(datetime.timezone.utc).date().isoformat(),
        "head": _head(),
        "method": ("each CSS entry against the reference set by exact fingerprint "
                   "(verify/qldpc_verify.py css_fingerprint: rref of H_X and H_Z) and "
                   "Weisfeiler-Leman signature of the typed Tanner graph (signature); "
                   "WL pairs the permutation audit decided carry its verdict"),
        "reference": {"baseline": len(baseline), "literature": len(literature),
                      "total": len(reference),
                      "definition": "provenance.origin baseline, or bucket literature in derived.json"},
        "audit": audit_path,
        "rule": RULE,
        "caveat": ("distinct means not permutation-equivalent to any seeded or literature "
                   "entry on this board, not that the code is unpublished; review is a flag, "
                   "not a verdict; nothing here is a novelty claim"),
        "not_screened": {"stabilizer_entries": len(glob.glob(os.path.join(CODES, "*.json")))
                         - len(docs) - len(skipped),
                         "css_without_report": skipped},
        "counts": counts(entries),
        "entries": entries,
    }
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=1, sort_keys=True)
        f.write("\n")
    c = payload["counts"]
    print(f"wrote {os.path.relpath(out_path, ROOT)}: {c['screened']} CSS entries against "
          f"{len(reference)} reference entries ({len(baseline)} baseline, {len(literature)} "
          f"literature): {c['exact_match']} exact_match, {c['review']} review "
          f"({c['wl_matches']} WL matches, {c['wl_matches_by_audit']}), {c['distinct']} distinct"
          + (f"; {len(skipped)} CSS entries without a report: {' '.join(skipped[:8])}"
             if skipped else ""))
    return 0


def check(path=SCREEN):
    """Confirm the committed screen is well formed and still describes codes/."""
    if not os.path.exists(path):
        print(f"missing {os.path.relpath(path, ROOT)}")
        return 1
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    entries = payload["entries"]
    broken = [f"  {s}: unknown verdict {v['verdict']!r}" for s, v in sorted(entries.items())
              if v["verdict"] not in VERDICTS]
    broken += [f"  {s}: {v['verdict']} with no match listed" for s, v in sorted(entries.items())
               if v["verdict"] != "distinct" and not v["matches"]]
    stored = {k: payload.get("counts", {}).get(k) for k in VERDICTS}
    fresh = {k: counts(entries)[k] for k in VERDICTS}
    if stored != fresh:
        broken.append(f"  counts block disagrees with the entries: says {stored}, entries give {fresh}")
    if broken:
        print(f"board screen is BROKEN ({len(broken)} problems):")
        print("\n".join(broken[:40]))
        return 1
    have, want = set(entries), css_slugs()
    missing, departed = sorted(want - have), sorted(have - want)
    if missing or departed:
        print(f"board screen is STALE: {len(missing)} CSS entries not screened, "
              f"{len(departed)} screened entries no longer on the board.")
        if missing:
            print("  not screened: " + " ".join(missing[:12]) + (" ..." if len(missing) > 12 else ""))
        if departed:
            print("  departed: " + " ".join(departed[:12]) + (" ..." if len(departed) > 12 else ""))
        print("  run `python research/provenance/board_screen.py run` to rescreen the board.")
        return 0
    c = payload["counts"]
    print(f"ok: board screen covers {len(entries)} CSS entries ({c['exact_match']} exact_match, "
          f"{c['review']} review, {c['distinct']} distinct) against "
          f"{payload['reference']['total']} reference entries")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="screen the board and write the record")
    r.add_argument("--out", default=SCREEN)
    sub.add_parser("check", help="validate the committed record against codes/ (staleness is not fatal)")
    a = ap.parse_args(argv)
    if a.cmd == "run":
        return run(a.out)
    return check()


if __name__ == "__main__":
    sys.exit(main())
