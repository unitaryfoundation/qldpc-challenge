#!/usr/bin/env python3
"""Greedy multi-step campaigns via code-calculus v0.2 run_campaign, gated."""
import argparse, datetime, json, os, sys, glob

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
for _p in ("verify", os.path.join("research", "kit")):
    if os.path.join(ROOT, _p) not in sys.path:
        sys.path.insert(0, os.path.join(ROOT, _p))
CC = "/home/mathys/github/code-calculus-dev"
if CC not in sys.path:
    sys.path.insert(0, CC)
os.environ.setdefault("QLDPC_RUN_ID", "cc-greedy-gated")
import coordination
from machine.priced_calculus import (CodeState, DistanceLedger, apply_operation,
    export_challenge_entry)
from machine.planner import plan, infer_target_sector

TODAY = datetime.date.today().isoformat()


def parents(n_cap):
    out = []
    for p in sorted(glob.glob(os.path.join(ROOT, "codes", "*.json"))):
        d = json.load(open(p))
        if d.get("code_type") != "CSS" or d["n"] > n_cap:
            continue
        out.append((os.path.splitext(os.path.basename(p))[0], d))
    out.sort(key=lambda t: t[1]["n"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-cap", type=int, default=60)
    ap.add_argument("--steps", type=int, default=3)
    ap.add_argument("--budget", type=int, default=64)
    args = ap.parse_args()
    staging = coordination.staging_dir()
    os.makedirs(staging, exist_ok=True)
    ps = parents(args.n_cap)
    print(f"{len(ps)} CSS parents with n <= {args.n_cap}", flush=True)
    gated = 0; finds = 0
    for slug, doc in ps:
        st = CodeState.from_challenge(doc)
        ld = DistanceLedger.from_challenge(st, doc)
        cur_state, cur_ld = st, ld
        cur_doc = doc
        ts = infer_target_sector(cur_ld, doc["distance"]["d"])
        for step in range(args.steps):
            try:
                cands = plan(cur_state, cur_ld, target=doc["distance"]["d"],
                             structural=True, reduce_display=True, reduce_by_domination=True,
                             sector_targeted=True, target_sector=ts,
                             support_search={"budget": args.budget, "max_weight": 3},
                             sector_swap=True, ranking="pareto")
            except Exception as e:
                print(f"  {slug} step{step}: plan error {e}", flush=True)
                break
            survivors = [c for c in cands if c["verdict"] != "prune"]
            if not survivors:
                break
            chosen = survivors[0]
            # export + gate
            try:
                entry = export_challenge_entry(cur_doc, chosen["state"], chosen["ledger"],
                    f"[[{chosen['state'].n()},{chosen['state'].k()},{chosen['ledger'].full.upper or doc['distance']['d']}]] greedy {slug} step{step}",
                    f"greedy multi-step (target {ts}) step {step} from codes/{slug}.json",
                    TODAY)
            except Exception as e:
                print(f"  {slug} step{step}: export error {e}", flush=True)
                break
            path = coordination.unique_path(os.path.join(staging, f"{chosen['state'].n()}-{chosen['state'].k()}-{chosen['ledger'].full.upper or 0}.json"), entry)
            with open(path, "w") as f:
                json.dump(entry, f, indent=2)
            try:
                verdict, _ = coordination.gate_and_record(path)
            except coordination.PreflightFailure as e:
                print(f"  {slug} step{step}: preflight refused", flush=True)
                break
            gated += 1
            if not verdict.get("passed"):
                continue
            # Staged deep-verify for d >= 2: catch inflated screening distances.
            # Try increasing trial counts; stop early on downgrade.
            cand_d = chosen["ledger"].full.upper or doc["distance"]["d"]
            if cand_d >= 2:
                import subprocess as _sp
                downgraded = False
                for trials in (2000, 20000, 200000, 2000000):
                    dr = _sp.run(["./qldpc", "submit", path,
                                  "--authors", "@mathysrennela", "--model", "Beam 1.0",
                                  "--family", "other",
                                  "--construction", "code-calculus v0.2rc greedy gated",
                                  "--reuse-witnesses", "--no-circuit",
                                  "--fast-trials", str(trials), "--dry-run"],
                                 cwd=ROOT, capture_output=True, text=True)
                    out = (dr.stdout or "") + (dr.stderr or "")
                    m = None
                    for line in out.splitlines():
                        if "would write" in line and "codes/" in line:
                            m = line.split("codes/")[-1].replace(".json", "")
                            break
                    deep_d = None
                    if m:
                        parts = m.split("-")
                        if len(parts) >= 3:
                            try:
                                deep_d = int(parts[2])
                            except ValueError:
                                deep_d = None
                    if deep_d is not None and deep_d != cand_d:
                        print(f"  DOWNGRADED {os.path.basename(path)} at {trials} trials: {cand_d} -> {deep_d}, skipping", flush=True)
                        downgraded = True
                        break
                    if deep_d is None:
                        # refused or collision; skip
                        print(f"  REFUSED/COLLISION {os.path.basename(path)} at {trials} trials, skipping", flush=True)
                        downgraded = True
                        break
                if downgraded:
                    continue
            finds += 1
            print(f"  PASS {os.path.basename(path)}", flush=True)
            # advance
            try:
                cur_state = apply_operation(cur_state, chosen["operation"])
            except Exception as e:
                print(f"  {slug} step{step}: apply error {e}", flush=True)
                break
            cur_ld = chosen["ledger"]
            cur_doc = entry
            ts = infer_target_sector(cur_ld, doc["distance"]["d"])
        print(f"  {slug}: done", flush=True)
    print(f"gated={gated} finds={finds}", flush=True)


if __name__ == "__main__":
    main()
