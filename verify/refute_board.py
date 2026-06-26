"""Weekly whole-board distance refutation (CI cron).

Re-runs the bounded RIS refutation over EVERY codes/ + examples/ entry, using a
fresh RANDOM seed each run. The per-PR gate (gate_changed.py) uses a fixed seed
so it is reproducible and non-flaky; this job does the opposite on purpose --
because the seed varies week to week, each run tries different random information
sets, so over time the board accumulates search coverage and an over-claim that
any single fixed-seed run missed can finally surface.

This is the safety net for distance claims that never paid the per-PR gate
(seeded baselines, direct commits, pre-gate codes) and for the back-catalogue as
the refuter improves.

FAILS CLOSED: a code whose refuter ERRORS is reported as a failure (manual review
needed), never silently skipped -- a broken check must not read as "all clear".

Exit 0 only if nothing was refuted and nothing errored.

Usage:
  python verify/refute_board.py [--seed N]    # --seed only to reproduce a run
"""
import glob
import json
import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import heuristic_distance as H

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv):
    seed = None
    if "--seed" in argv:
        seed = int(argv[argv.index("--seed") + 1])
    if seed is None:
        seed = secrets.randbelow(2**31)        # fresh, non-deterministic each run
    print(f"weekly board refutation -- random seed = {seed}")
    print(f"(reproduce this run with: python verify/refute_board.py --seed {seed})\n")

    paths = (sorted(glob.glob(os.path.join(ROOT, "codes", "*.json")))
             + sorted(glob.glob(os.path.join(ROOT, "examples", "*.json"))))
    refuted, errored, checked = [], [], 0
    for p in paths:
        rel = os.path.relpath(p, ROOT)
        doc = json.load(open(p))
        if "distance" not in doc or "d" not in doc.get("distance", {}):
            continue
        checked += 1
        # per-file seed varies but is derived from the run seed, so the whole run
        # reproduces from one number.
        file_seed = (seed + hash(rel)) % (2**31)
        try:
            is_refuted, d_found, wit, trials = H.refute_check(doc, seed=file_seed)
        except Exception as e:                 # FAIL CLOSED
            errored.append((rel, f"{type(e).__name__}: {e}"))
            print(f"ERROR    {rel}: refuter failed ({type(e).__name__}: {e}) "
                  f"-- fails closed, manual review")
            continue
        if is_refuted:
            refuted.append((rel, d_found, doc["distance"]["d"], wit))
            print(f"REFUTED  {rel}: found weight-{d_found} logical < claimed "
                  f"{doc['distance']['d']}\n         witness = {wit}")
        else:
            print(f"ok       {rel}: no logical lighter than {doc['distance']['d']} "
                  f"({trials} RIS trials)")

    print(f"\n{checked} codes checked; {len(refuted)} refuted, {len(errored)} errored.")
    if refuted or errored:
        print("FAIL: distance claims need review (see REFUTED/ERROR above).")
        return 1
    print("PASS: no over-claim found this run.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
