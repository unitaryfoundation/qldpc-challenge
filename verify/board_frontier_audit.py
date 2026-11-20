"""Board-wide audit: the three frontier implementations must agree.

A code is a record of its track cell when no other code in that cell beats it
on all of (n, k, d, w). That one relation is implemented three times:

* ``site/build.py:compute_records`` -- the star rendered on the board;
* ``validate_candidate`` gates.novelty -- what a contributor is told
  ("advances the board cell") and what ``build_receipt`` records;
* ``gate_changed.board_record_slugs`` -- which claims get the deep refutation
  battery instead of the fast pass.

If they disagree, the gate, the receipt, the rendered star, and the refutation
budget name different record-holders. On the 2026-09-29 board the budget's
hand-rolled locality mirror (``gate_changed._locality_rank``) had drifted from
the verifier and flipped the record status of 17 entries -- caught only by
comparing the implementations across all of codes/.

That comparison needs a full structural pass over the board plus one gate
verdict per entry (~5 minutes), so it is not in the PR gate: this file is not
named test_*.py, pytest never auto-collects it, and the weekly refute job
(refute-weekly.yml) runs it as its own step. The per-rule pinning of the
mirror stays in verify/test_frontier_consistency.py (seconds, PR gate).

Run standalone:  uv run --frozen python verify/board_frontier_audit.py
Exit 0 iff all three checks agree.
"""

import importlib.util
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)

import gate_changed as G  # noqa: E402
import qldpc_verify  # noqa: E402
import validate_candidate as V  # noqa: E402

RANK_TO_CLASS = {0: "local-2d-single", 1: "local-2d-bilayer", 2: "unrestricted"}


def load_site_build():
    spec = importlib.util.spec_from_file_location("site_build_board_audit", os.path.join(ROOT, "site", "build.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    failures = 0

    def check(label, bad):
        nonlocal failures
        if bad:
            failures += 1
            print(f"FAIL {label}:")
            for line in bad[:20]:
                print(f"  {line}")
        else:
            print(f"OK   {label}")

    # one memoized structural pass over codes/, shared by every check below
    build = load_site_build()
    entries = build.load_entries()
    reports = {e["slug"]: e for e in qldpc_verify.board_reports(os.path.join(ROOT, "codes"))}
    site_records = {entries[i]["slug"] for i in build.compute_records(entries)}
    print(f"{len(entries)} entries, {len(site_records)} site records")

    # 1. the budget's locality mirror against the verifier's own class,
    #    for every entry -- the input drift the record sets are built on
    bad = []
    for slug, e in sorted(reports.items()):
        doc, rep = e["doc"], e["report"]
        if doc is None or rep is None:
            continue  # reported by verify_all
        want = rep["computed"].get("locality_class", "unrestricted")
        got = RANK_TO_CLASS[G._locality_rank(doc)]
        if got != want:
            bad.append(f"{slug}: _locality_rank={got}, verifier={want}")
    check("_locality_rank == verifier (every entry)", bad)

    # 2. the rendered star against the refutation budget's record set
    gate_records = G.board_record_slugs(ROOT)
    only_site = sorted(site_records - gate_records)
    only_gate = sorted(gate_records - site_records)
    check(
        "site star == board_record_slugs",
        [f"site-only: {only_site[:20]}", f"gate-only: {only_gate[:20]}"] if (only_site or only_gate) else [],
    )

    # 3. the contributor-facing novelty verdict against the rendered star,
    #    each entry validated as if newly submitted (itself excluded from the
    #    board: a code already on the board is its own exact duplicate and
    #    the gate then declines to assess novelty at all)
    full = V._board_entries()
    orig = V._board_entries
    bad = []
    try:
        for entry in entries:
            slug = entry["slug"]
            with open(os.path.join(ROOT, "codes", slug + ".json")) as f:
                doc = json.load(f)
            V._board_entries = lambda slug=slug: [b for b in full if b["name"] != slug + ".json"]
            verdict = V.validate_candidate(doc, refute=False, seed=0)
            adv = (verdict["gates"].get("novelty") or {}).get("board_advancing")
            starred = slug in site_records
            if adv is None:
                bad.append(f"{slug}: novelty not assessed (duplicate match?)")
            elif bool(adv) != starred:
                bad.append(f"{slug}: gate board_advancing={adv}, site star={starred}")
    finally:
        V._board_entries = orig
    check("validate_candidate board_advancing == site star (every entry)", bad)

    print(f"\n{'ALL PASS' if not failures else f'{failures} CHECK(S) FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
