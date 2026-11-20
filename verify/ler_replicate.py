"""Post-merge replication of every measured-rate point on the board (issue
#1278; the D half of its decision).

Usage:
    python verify/ler_replicate.py [--root DIR] [--budget SECS] [--seeds N]
                                   [--job-seconds SECS] [--only-stale]
                                   [--slugs SLUG ...] [--head-sha SHA]

At PR time the gate replicates a claim's highest-rate point inside 120 s per
basis and defers the rest. This runs ler_verify in mode "all" over the
entries that carry a rate: every point, --budget wall seconds per point
split across --seeds independent replicas, and writes one receipt per entry
under receipts/ler/<slug>.json (verify/ler_receipts.py). Entries are taken
stalest first: no receipt, then a receipt for a different claim digest (the
claim or its circuits changed since), then the oldest measured_at; the run
stops opening new entries once --job-seconds have elapsed, so a long board
is covered across runs rather than timing a job out. A point the budget
cannot check records as unverifiable, a disagreeing one as failed; the site
shows both, and neither counts as a verified point.

The scheduled workflow (.github/workflows/ler-weekly.yml) runs this on
Mondays and commits the receipts.
"""

import argparse
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ler_receipts as lr
import ler_verify as lv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def entries_with_rates(root):
    out = []
    for path in sorted(glob.glob(os.path.join(root, "codes", "*.json"))):
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        if (doc.get("circuit") or {}).get("ler"):
            out.append((os.path.splitext(os.path.basename(path))[0], doc))
    return out


def staleness_key(root, slug, doc):
    """(rank, measured_at): rank 0 no receipt, 1 stale digest, 2 current."""
    cdir = os.path.join(root, "circuits", slug)
    rec = lr.load_receipt(root, slug)
    if rec is None:
        return (0, "")
    if rec.get("claim_digest") != lr.claim_digest(doc, cdir):
        return (1, rec.get("measured_at", ""))
    return (2, rec.get("measured_at", ""))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--budget", type=float, default=lv.REPLICATE_SECONDS)
    ap.add_argument("--seeds", type=int, default=lv.REPLICATE_SEEDS)
    ap.add_argument("--job-seconds", type=float, default=5 * 3600)
    ap.add_argument("--only-stale", action="store_true", help="skip entries whose receipt matches the current claim")
    ap.add_argument("--slugs", nargs="*", default=None)
    ap.add_argument("--head-sha", default=None)
    a = ap.parse_args(argv)
    root = os.path.abspath(a.root)
    t0 = time.monotonic()
    todo = entries_with_rates(root)
    if a.slugs:
        todo = [(s, d) for s, d in todo if s in set(a.slugs)]
    todo.sort(key=lambda sd: staleness_key(root, sd[0], sd[1]))
    done, skipped = 0, 0
    for slug, doc in todo:
        rank, _ = staleness_key(root, slug, doc)
        if a.only_stale and rank == 2:
            skipped += 1
            continue
        if time.monotonic() - t0 > a.job_seconds:
            print(f"job budget reached after {done} entries; {len(todo) - done - skipped} left for the next run")
            break
        cdir = os.path.join(root, "circuits", slug)
        print(f"== {slug}", flush=True)
        rep = lv.verify_ler(doc, cdir, mode="all", budget=a.budget, seeds=a.seeds)
        for c in rep["checks"]:
            print(f"  {'ok ' if c['ok'] else 'BAD'} {c['check']}: {c['detail'][:200]}", flush=True)
        receipt = lr.make_receipt(slug, lr.claim_digest(doc, cdir), rep, head_sha=a.head_sha)
        path = lr.write_receipt(root, receipt)
        print(f"  receipt {os.path.relpath(path, root)}", flush=True)
        done += 1
    print(f"replicated {done} entries, skipped {skipped} current, {time.monotonic() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
