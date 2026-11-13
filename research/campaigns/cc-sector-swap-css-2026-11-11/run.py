#!/usr/bin/env python3
"""CSS children via code-calculus v0.2 sector swap + bounded sector search."""
import argparse, collections, datetime, json, os, sys, time

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
for _p in ("verify", os.path.join("research", "kit")):
    if os.path.join(ROOT, _p) not in sys.path:
        sys.path.insert(0, os.path.join(ROOT, _p))
CC = "/home/mathys/github/code-calculus-dev"
if CC not in sys.path:
    sys.path.insert(0, CC)

os.environ.setdefault("QLDPC_RUN_ID", "cc-sector-swap-css")
import coordination
import qldpc_verify as V

from machine.priced_calculus import CodeState, DistanceLedger, export_challenge_entry
from machine.planner import bounded_sector_search

TODAY = datetime.date.today().isoformat()
N_CAP = 60
BUDGET = 64


import glob
def parents(n_cap):
    out = []
    for p in sorted(glob.glob(os.path.join(ROOT, "codes", "*.json"))):
        try:
            doc = json.load(open(p))
        except Exception:
            continue
        if not isinstance(doc, dict) or doc.get("code_type") != "CSS":
            continue
        if doc.get("n", 0) > n_cap:
            continue
        slug = os.path.splitext(os.path.basename(p))[0]
        out.append((slug, doc))
    out.sort(key=lambda t: t[1]["n"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-cap", type=int, default=N_CAP)
    ap.add_argument("--budget", type=int, default=BUDGET)
    args = ap.parse_args()
    n_cap = args.n_cap
    staging = coordination.staging_dir()
    os.makedirs(staging, exist_ok=True)
    ps = parents(n_cap)
    print(f"{len(ps)} CSS parents with n <= {n_cap}", flush=True)
    gated = 0
    finds = []
    for slug, doc in ps:
        st = CodeState.from_challenge(doc)
        ld = DistanceLedger.from_challenge(st, doc)
        try:
            res = bounded_sector_search(st, ld, target_sector="X", target=doc["distance"]["d"],
                                       budget=args.budget, max_depth=1, sector_swap=True)
        except Exception as e:
            print(f"  {slug}: search error {e}", flush=True)
            continue
        improving = res.get("improving", [])
        print(f"  {slug} n={doc['n']} k={doc['k']} d={doc['distance']['d']}: improving={len(improving)}", flush=True)
        for cand in improving:
            cstate = cand["state"]
            cledger = cand["ledger"]
            try:
                entry = export_challenge_entry(doc, cstate, cledger,
                    f"[[{cstate.n()},{cstate.k()},{cledger.full.upper or doc['distance']['d']}]] sector-swap of {slug}",
                    f"E-LOCAL-HADAMARD/sector-swap chain from codes/{slug}.json",
                    TODAY)
            except Exception as e:
                print(f"    export error {e}", flush=True)
                continue
            path = coordination.unique_path(os.path.join(staging, f"{cstate.n()}-{cstate.k()}-{cledger.full.upper or 0}.json"), entry)
            with open(path, "w") as f:
                json.dump(entry, f, indent=2)
            try:
                verdict, _ = coordination.gate_and_record(path)
            except coordination.PreflightFailure as e:
                print(f"    preflight refused {os.path.basename(path)}", flush=True)
                continue
            gated += 1
            if verdict.get("passed"):
                finds.append((path, slug))
                print(f"    PASS {os.path.basename(path)}", flush=True)
    print(f"gated={gated} finds={len(finds)}", flush=True)


if __name__ == "__main__":
    main()
