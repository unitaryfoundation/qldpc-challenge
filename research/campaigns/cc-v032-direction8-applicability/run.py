#!/usr/bin/env python3
"""code-calculus v0.3.2, direction 8 of issue #7377.

Applicability diagnostics on the v0.2/v0.3.0 negative pilots.

Runs `machine.planner.move_applicability_report` on each parent slug listed in
the v0.3 direction-2 sector-calibration campaign files and aggregates the
per-family domain/derived/usable counts plus refusal/screen reasons.
"""

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
CC = os.environ.get("CODE_CALCULUS_PATH", "/home/mathys/github/code-calculus-dev")
for _p in (CC, ROOT, os.path.join(ROOT, "verify"), os.path.join(ROOT, "research", "kit")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from machine.planner import move_applicability_report
from machine.priced_calculus import CodeState


def load_parents(campaign_path):
    with open(campaign_path) as fh:
        data = json.load(fh)
    return [r["slug"] for r in data["records"]]


def run_one(slug, include_disconnected=False):
    path = os.path.join(ROOT, "codes", slug + ".json")
    with open(path) as fh:
        doc = json.load(fh)
    state = CodeState.from_challenge(doc)
    w = doc.get("weight")
    if not isinstance(w, int):
        w = max(len(c) for s in doc["checks"].values() for c in s)
    t0 = time.time()
    rep = move_applicability_report(state, weight_cap=w, include_disconnected=include_disconnected)
    rep["_meta"] = {
        "slug": slug,
        "n": doc["n"],
        "k": doc["k"],
        "d": doc["distance"]["d"],
        "w": w,
        "seconds": round(time.time() - t0, 2),
    }
    return rep


def aggregate(reports):
    families = {}
    for rep in reports:
        if not rep.get("families"):
            continue
        for fam, entry in rep["families"].items():
            agg = families.setdefault(
                fam,
                {
                    "parents": 0,
                    "domain": 0,
                    "derived": 0,
                    "usable": 0,
                    "refusals": {},
                    "screens": {},
                },
            )
            agg["parents"] += 1
            agg["domain"] += entry["domain"]
            agg["derived"] += entry["derived"]
            agg["usable"] += entry["usable"]
            for reason, count in entry["refusals"].items():
                agg["refusals"][reason] = agg["refusals"].get(reason, 0) + count
            for reason, count in entry["screens"].items():
                agg["screens"][reason] = agg["screens"].get(reason, 0) + count
    return families


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign", default="3")
    ap.add_argument("--out", default=None)
    ap.add_argument("--include-disconnected", action="store_true")
    ap.add_argument("--no-rebase", action="store_true")
    args = ap.parse_args()

    camp_path = os.path.join(
        ROOT, "research", "campaigns", "cc-v03-direction2-sector-calibration", f"campaign{args.campaign}.json"
    )
    slugs = load_parents(camp_path)
    out_path = args.out or os.path.join(HERE, f"result-campaign{args.campaign}.json")

    reports = []
    if os.path.exists(out_path):
        try:
            with open(out_path) as fh:
                prior = json.load(fh)
            reports = prior.get("reports", [])
            done = {r["_meta"]["slug"] for r in reports if "_meta" in r}
            slugs = [s for s in slugs if s not in done]
        except (OSError, ValueError):
            reports = []

    for i, slug in enumerate(slugs, 1):
        print(f"[{i}/{len(slugs)}] {slug}", flush=True)
        try:
            rep = run_one(slug, include_disconnected=args.include_disconnected,
                          rebase=not args.no_rebase)
        except Exception as exc:
            print(f"  ERROR {slug}: {exc!r}", flush=True)
            rep = {"_meta": {"slug": slug, "error": repr(exc)}, "families": {}}
        reports.append(rep)
        with open(out_path, "w") as fh:
            json.dump(
                {"campaign": args.campaign, "reports": reports, "aggregate": aggregate(reports)},
                fh,
                indent=2,
                default=str,
            )

    print("done; aggregate:")
    print(json.dumps(aggregate(reports), indent=2, default=str))


if __name__ == "__main__":
    main()
