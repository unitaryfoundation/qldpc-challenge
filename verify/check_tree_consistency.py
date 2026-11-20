#!/usr/bin/env python3
"""Refuse artifacts whose board entry does not exist.

Every artifact this board keeps is filed under the slug of the entry it
belongs to: `codes/<slug>.json` is the entry, `notes/<slug>.md` explains how it
was found, `certs/<slug>.json` certifies its distance,
`certs/heuristic/<slug>.json` records an uncertified one, `circuits/<slug>/`
holds its syndrome-extraction experiments, and `receipts/ler/<slug>.json`
records a post-merge rate replication. Remove or rename the entry and each of
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
  unreadable by construction. The same one-way rule covers every other
  location below: this sweep never asks an entry to justify its artifacts, it
  asks an artifact to justify its entry.

  Content. Whether a note's [[n,k,d]] matches its filename, whether its
  citations resolve, and whether a certificate earns its level are
  `check_prose.py` and `check_certs.py`'s jobs; this checker only answers
  "does the entry it names exist", which is the question neither of them asks.
"""

import argparse
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# notes/README.md documents the contract and notes/TEMPLATE.md is the drafting
# placeholder; neither claims to be a code's note. Stems, to match the slugs
# everything here is compared as.
NOTE_DOCS = frozenset({"README", "TEMPLATE"})

# Every per-entry artifact location, in report order. Each entry:
#
#   glob      paths under the tree root that belong to this location
#   prefix    how the report spells the path of a match
#   suffix    how the report spells the end of one ("/" for a directory)
#   exclude   stems that live there without belonging to an entry
#   label     what an orphan here means, printed with the count
#
# `directories: True` marks a location whose matches are directories rather
# than files (circuits/<slug>/); every other location keeps only regular files.
#
# The globs are non-recursive and say exactly what each location is: only
# `certs/*.json` is a certificate to `check_certs.py`, only `receipts/ler/*.json`
# is a receipt to `site/`, and only a directory under `circuits/` is an
# entry's circuit tree. `certs/proof_log_batch.jsonl` and `receipts/ler/README.md`
# are therefore not artifacts of any code, and `certs/heuristic/` is a
# per-entry location in its own right rather than part of the certs glob.
KINDS = {
    "notes": {
        "glob": "notes/*.md",
        "prefix": "notes/",
        "suffix": ".md",
        "exclude": NOTE_DOCS,
        "label": "note with no codes/<slug>.json -- site/build.py resolves "
        "notes through existing entries, so this one renders nowhere",
    },
    "certs": {
        "glob": "certs/*.json",
        "prefix": "certs/",
        "suffix": ".json",
        "exclude": frozenset(),
        "label": "certificate with no codes/<slug>.json -- it still validates, "
        "but it attests to a file that is not here",
    },
    "heuristic": {
        "glob": "certs/heuristic/*.json",
        "prefix": "certs/heuristic/",
        "suffix": ".json",
        "exclude": frozenset(),
        "label": "heuristic certificate with no codes/<slug>.json -- "
        "check_certs.py cannot validate it, but this question "
        "needs no schema",
    },
    "receipts": {
        "glob": "receipts/ler/*.json",
        "prefix": "receipts/ler/",
        "suffix": ".json",
        "exclude": frozenset(),
        "label": "LER receipt with no codes/<slug>.json -- site/ reads "
        "receipts through existing entries, so this one shows nowhere",
    },
    "circuits": {
        "glob": "circuits/*",
        "prefix": "circuits/",
        "suffix": "/",
        "directories": True,
        "exclude": frozenset(),
        "label": "circuits/<slug>/ with no codes/<slug>.json",
    },
}

# A tree without these is not the tree this sweep describes; reading one
# anyway would report a board that looks clean while skipping a location.
REQUIRED = ("codes", "notes", "certs", "certs/heuristic", "receipts/ler", "circuits")


def code_slugs(root):
    """Slugs of the board entries: the thing every other artifact points at.

    Same idiom as the five other entry listings in this repository
    (verify_all.py, gate_changed.py, refute_board.py, certify_all.py and
    site/build.py): a `codes/*.json` glob is what counts as an entry, so a
    future change to that definition stays greppable in one shape.
    """
    return {os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(root, "codes", "*.json"))}


def orphan_slugs(root, kind, codes):
    """Slugs at one artifact location whose entry is gone from `codes`."""
    paths = glob.glob(os.path.join(root, kind["glob"]))
    if kind.get("directories"):
        paths = [p for p in paths if os.path.isdir(p)]
    else:
        paths = [p for p in paths if os.path.isfile(p)]
    slugs = {os.path.splitext(os.path.basename(p))[0] for p in paths}
    return sorted(slugs - kind["exclude"] - codes)


def scan(root=ROOT):
    """Everything orphaned in this tree, keyed by artifact kind.

    `codes/` is read once and every location is measured against that same
    set, so no location can satisfy itself: one missing entry leaves one
    orphan per artifact behind it, counted once per kind.
    """
    codes = code_slugs(root)
    return {name: orphan_slugs(root, kind, codes) for name, kind in KINDS.items()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=ROOT, help="tree to sweep (default: this repository)")
    ap.add_argument("--quiet", action="store_true", help="print counts only, without listing the files")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root)
    missing = [d for d in REQUIRED if not os.path.isdir(os.path.join(root, d))]
    if missing:
        print(f"FAIL: no {', '.join(missing)} under {root}; wrong --root?")
        return 2

    found = scan(root)
    total = sum(len(v) for v in found.values())
    if not total:
        print("ok: every artifact names an existing entry")
        return 0

    print(f"orphaned artifacts ({total}):")
    for name, kind in KINDS.items():
        slugs = found[name]
        if not slugs:
            continue
        print(f"\n  {name}: {len(slugs)}  -- {kind['label']}")
        if args.quiet:
            continue
        for slug in slugs:
            print(f"    {kind['prefix']}{slug}{kind['suffix']}")

    print("\nThe entry was removed or renamed and the artifact was not.")
    print("Either the entry comes back, or the artifact goes with it. A note")
    print("whose method is worth keeping can be reclassified to fieldnotes/,")
    print("where it names no slug and cannot orphan (fieldnotes/README.md).")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
