#!/usr/bin/env python3
"""Direction 5 of issue #7116: distance-revision harvest.

Re-measures high-distance CSS board entries with the depth-proportional ladder
(``screening_trials`` from PR #6195) across several seeds. A strictly lighter
witness than the board's claimed d is a CORRECTION to an existing entry, not a
new find: it is staged with the witness and a recipe, gated, and reported for a
human to turn into a revision PR. This script never opens or edits a PR.

Every distance here is a witness-backed upper bound. Nothing is certified.
"""
import argparse
import collections
import glob
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
for _p in (os.path.join(ROOT, "verify"), os.path.join(ROOT, "research", "kit"),
           os.path.join(ROOT, "research")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from surrogate import lightest_logical  # noqa: E402
from reachability_campaign import screening_trials  # noqa: E402


def load_entries(n_hi, d_lo, limit):
    out = []
    for path in sorted(glob.glob(os.path.join(ROOT, "codes", "*.json"))):
        with open(path) as fh:
            doc = json.load(fh)
        d = doc.get("distance", {}).get("d")
        if doc.get("code_type") != "CSS" or doc["n"] > n_hi:
            continue
        if not isinstance(d, int) or d < d_lo:
            continue
        out.append((os.path.splitext(os.path.basename(path))[0], doc))
        if len(out) >= limit:
            break
    return out


def checks_to_matrices(doc):
    import numpy as np
    n = doc["n"]
    HX = np.zeros((len(doc["checks"]["X"]), n), dtype=int)
    HZ = np.zeros((len(doc["checks"]["Z"]), n), dtype=int)
    for i, sup in enumerate(doc["checks"]["X"]):
        for q in sup:
            HX[i][q] = 1
    for i, sup in enumerate(doc["checks"]["Z"]):
        for q in sup:
            HZ[i][q] = 1
    return HX, HZ


def spread(items, count):
    if count <= 0 or len(items) <= count:
        return list(items)
    step = len(items) / count
    return [items[min(len(items) - 1, int(i * step))] for i in range(count)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-hi", type=int, default=200)
    ap.add_argument("--d-lo", type=int, default=8)
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--entries", type=int, default=24)
    ap.add_argument("--seeds", type=int, nargs="+", default=[51, 211, 307])
    ap.add_argument("--gate-cap", type=int, default=20)
    ap.add_argument("--out", default=os.path.join(_HERE, "campaign.json"))
    args = ap.parse_args()

    from submit import make_submission, save_submission
    from coordination import unique_path, gate_and_record, staging_dir

    entries = spread(load_entries(args.n_hi, args.d_lo, args.limit),
                     args.entries)
    print(f"{len(entries)} board entries, d >= {args.d_lo}, n <= {args.n_hi}",
          flush=True)
    staging = staging_dir()
    os.makedirs(staging, exist_ok=True)
    records = []
    gated = 0
    started = time.time()

    for ei, (slug, doc) in enumerate(entries, 1):
        claimed = doc["distance"]["d"]
        trials = screening_trials(claimed)
        HX, HZ = checks_to_matrices(doc)
        best = None
        per_seed = []
        for seed in args.seeds:
            wx, xwit = lightest_logical(HX, HZ, trials=trials, seed=seed)
            wz, zwit = lightest_logical(HZ, HX, trials=trials, seed=seed + 1)
            per_seed.append({"seed": seed, "wx": wx, "wz": wz})
            cand = (min(wx, wz), wx, xwit, wz, zwit)
            if best is None or cand[0] < best[0]:
                best = cand
        measured, wx, xwit, wz, zwit = best
        rec = {"slug": slug, "n": doc["n"], "k": doc["k"],
               "claimed_d": claimed, "trials": trials,
               "measured_d": measured, "wx": wx, "wz": wz,
               "per_seed": per_seed,
               "tightening": measured < claimed}
        if not rec["tightening"]:
            records.append(rec)
            print(f"  [{ei}/{len(entries)}] {slug}: d={claimed} "
                  f"stays >= {measured} at {trials} trials", flush=True)
            continue
        if gated >= args.gate_cap:
            rec["gate_skipped"] = "gate cap"
            records.append(rec)
            continue
        try:
            sub = make_submission(
                HX, HZ,
                name=f"[[{doc['n']},{doc['k']},{measured}]] revision",
                construction=f"distance revision of codes/{slug}.json "
                             f"(depth-proportional ladder, {trials} trials)",
                authors=["mathysrennela"], family=None,
                confidence="upper_bound", trials=trials,
                witnesses=(wx, xwit, wz, zwit),
                notes=f"Correction from claimed d={claimed} to witnessed d={measured}.")
            path = unique_path(os.path.join(
                staging, f"{doc['n']}-{doc['k']}-{measured}-revision.json"), sub)
            save_submission(sub, path, preflight=False, spec={
                "constructor": "surrogate.lightest_logical",
                "params": {"parent": slug, "trials": trials,
                           "seeds": args.seeds, "claimed_d": claimed},
            })
            verdict, _ = gate_and_record(path)
            gated += 1
            rec.update({
                "gate_passed": verdict.get("passed"),
                "gate": verdict, "path": path})
            print(f"  [{ei}/{len(entries)}] {slug}: d {claimed}->{measured} "
                  f"gate={verdict.get('passed')}", flush=True)
        except Exception as exc:
            rec["gate_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            print(f"  [{ei}/{len(entries)}] {slug}: GATE ERROR "
                  f"{rec['gate_error'][:100]}", flush=True)
        records.append(rec)

    summary = {
        "entries": len(entries),
        "tightenings": sum(1 for r in records if r.get("tightening")),
        "gated": gated,
        "gate_passed": sum(1 for r in records if r.get("gate_passed")),
        "seconds": round(time.time() - started, 1),
        "seeds": args.seeds,
    }
    with open(args.out, "w") as fh:
        json.dump({"summary": summary, "records": records}, fh, indent=2)
    print("SUMMARY", json.dumps(summary), flush=True)
    for rec in records:
        if rec.get("tightening"):
            print("REVISION", rec["slug"], rec["claimed_d"], "->",
                  rec["measured_d"], rec.get("path", ""), flush=True)


if __name__ == "__main__":
    main()
