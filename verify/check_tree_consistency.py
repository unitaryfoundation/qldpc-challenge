#!/usr/bin/env python3
"""Refuse artifacts whose board entry does not exist.

Every artifact this board keeps is filed under the slug of the entry it
belongs to: `codes/<slug>.json` is the entry, `notes/<slug>.md` explains how it
was found, `certs/<slug>.json` certifies its distance, `circuits/<slug>/` holds
its syndrome-extraction experiments. Remove or rename the entry and each of
those becomes orphaned.

That is not hypothetical. Until this check existed, nothing resolved an
artifact's slug back to `codes/`:

  * 38 notes were left behind by the removals of 2026-09-11 and by distance
    revisions that wrote a new note under the new slug instead of renaming the
    one they had. `site/build.py` resolves a note by slug from an *existing*
    entry, so every one of them rendered nowhere: invisible in production,
    invisible to readers, and invisible to CI.
  * 21 certificates were left behind by the same removals. `check_certs.py`
    validates a certificate's schema, evidence rules and binding hash but never
    asks whether the entry it binds to is still there, so
    `ok: 750 certificates valid` was true with 21 of those 750 attesting to a
    file that is not in the repository.

Both were silent because `check_prose.py` inspects only files a PR *changes*.
An orphan is not a change: it is what a change elsewhere failed to make.

So this is the missing sweep: for each artifact, does its entry exist?

    python verify/check_tree_consistency.py              # list every orphan
    python verify/check_tree_consistency.py --root PATH  # another tree
    python verify/check_tree_consistency.py --quiet      # counts only

What it deliberately does NOT check, and why:

  An entry without a note is not a violation. `notes/README.md` says notes are
  "requested for all new submissions" and literature baselines are exempt;
  roughly 170 entries have no note and that is allowed by design. Checking
  that direction would fail the board on a documented policy choice and
  pressure contributors to file filler. The pairing holds one way only: if a
  note exists, the entry it names must exist, because a note with no entry is
  unreadable by construction.

  It does not re-validate content either. Whether a note's [[n,k,d]] matches
  its filename, whether its citations resolve, and whether a certificate
  earns its level are `check_prose.py` and `check_certs.py`'s jobs; this
  checker only answers "does the entry it names exist", which is the question
  neither of them asks.
"""
import argparse
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# notes/README.md documents the contract and notes/TEMPLATE.md is the drafting
# placeholder; neither claims to be a code's note.
NOTE_DOCS = frozenset({"README.md", "TEMPLATE.md"})


def code_slugs(root):
    """Slugs of the board entries: the thing every other artifact points at."""
    return {os.path.splitext(f)[0]
            for f in os.listdir(os.path.join(root, "codes"))
            if f.endswith(".json")}


def orphan_notes(root):
    """Notes whose slug names no entry. A reader's dead end: they render nowhere."""
    codes = code_slugs(root)
    found = {os.path.splitext(os.path.basename(p))[0]
             for p in glob.glob(os.path.join(root, "notes", "*.md"))
             if os.path.basename(p) not in NOTE_DOCS}
    return sorted(found - codes)


def orphan_certificates(root):
    """Certificates whose entry is gone: evidence bound to nothing.

    Only `certs/*.json` — non-recursive on purpose, matching check_certs.py.
    `certs/heuristic/` holds a different artifact with no schema and
    `proof_log_batch.jsonl` is a batch log, neither one cert per entry.
    """
    codes = code_slugs(root)
    found = {os.path.splitext(os.path.basename(p))[0]
             for p in glob.glob(os.path.join(root, "certs", "*.json"))}
    return sorted(found - codes)


def orphan_circuits(root):
    """Circuit directories whose entry is gone: experiments for a non-code."""
    codes = code_slugs(root)
    found = {os.path.basename(p) for p in
             glob.glob(os.path.join(root, "circuits", "*"))
             if os.path.isdir(p)}
    return sorted(found - codes)


def scan(root=ROOT):
    """Everything orphaned in this tree, keyed by artifact kind."""
    return {
        "notes": orphan_notes(root),
        "certs": orphan_certificates(root),
        "circuits": orphan_circuits(root),
    }


LABEL = {
    "notes": "note with no codes/<slug>.json -- site/build.py resolves notes "
             "through existing entries, so this one renders nowhere",
    "certs": "certificate with no codes/<slug>.json -- it still validates, "
             "but it attests to a file that is not here",
    "circuits": "circuits/<slug>/ with no codes/<slug>.json",
}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=ROOT,
                    help="tree to sweep (default: this repository)")
    ap.add_argument("--quiet", action="store_true",
                    help="print counts only, without listing the files")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root)
    missing = [d for d in ("codes", "notes", "certs", "circuits")
               if not os.path.isdir(os.path.join(root, d))]
    if missing:
        print(f"FAIL: no {'/'.join(missing)} under {root}; wrong --root?")
        return 2

    found = scan(root)
    total = sum(len(v) for v in found.values())
    if not total:
        print("ok: every note, certificate and circuit names an existing entry")
        return 0

    print(f"orphaned artifacts ({total}):")
    for kind in ("notes", "certs", "circuits"):
        slugs = found[kind]
        if not slugs:
            continue
        print(f"\n  {kind}: {len(slugs)}  -- {LABEL[kind]}")
        if args.quiet:
            continue
        suffix = "/" if kind == "circuits" else ".md" if kind == "notes" else ".json"
        indent = "circuits/" if kind == "circuits" else f"{kind}/"
        for slug in slugs:
            print(f"    {indent}{slug}{suffix}")

    print("\nThe entry was removed or renamed and the artifact was not.")
    print("Either the entry comes back, or the artifact goes with it. A note")
    print("whose method is worth keeping can be reclassified to fieldnotes/,")
    print("where it names no slug and cannot orphan (fieldnotes/README.md).")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
