#!/usr/bin/env python3
"""C-ADD-CHECK strict improvement via code-calculus v0.2 admissible_added_checks."""
import argparse, datetime, json, os, sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
for _p in ("verify", os.path.join("research", "kit")):
    if os.path.join(ROOT, _p) not in sys.path:
        sys.path.insert(0, os.path.join(ROOT, _p))
CC = "/home/mathys/github/code-calculus-dev"
if CC not in sys.path:
    sys.path.insert(0, CC)
os.environ.setdefault("QLDPC_RUN_ID", "cc-strict-addition-css")
import coordination
from machine.priced_calculus import (CodeState, DistanceLedger, apply_operation,
    export_challenge_entry, admissible_added_checks, strict_improvement_feasible)

TODAY = datetime.date.today().isoformat()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-cap", type=int, default=20)
    ap.add_argument("--max-weight", type=int, default=4)
    args = ap.parse_args()
    staging = coordination.staging_dir()
    os.makedirs(staging, exist_ok=True)
    import glob
    parents = []
    for p in sorted(glob.glob(os.path.join(ROOT, "codes", "*.json"))):
        doc = json.load(open(p))
        if doc.get("code_type") != "CSS" or doc["n"] > args.n_cap:
            continue
        parents.append((os.path.splitext(os.path.basename(p))[0], doc))
    print(f"{len(parents)} CSS parents with n <= {args.n_cap}", flush=True)
    gated = 0; finds = 0
    for slug, doc in parents:
        st = CodeState.from_challenge(doc)
        ld = DistanceLedger.from_challenge(st, doc)
        base = doc["distance"]["d"]
        for supp, sec in admissible_added_checks(st, max_weight=args.max_weight, sectors=("X", "Z")):
            try:
                r = strict_improvement_feasible(st, added_support=supp, added_sector=sec,
                                                base_distance=base, ledger=ld,
                                                allow_enumeration=True, enumeration_ceiling=st.n())
            except Exception as e:
                continue
            if not (isinstance(r, dict) and r.get("feasible")):
                continue
            # apply move
            op = {"op": "C-ADD-CHECK", "sector": sec, "support": supp}
            try:
                nst = apply_operation(st, op)
            except Exception:
                continue
            # need witness for export; skip if none found by support search? Use ledger propagate with no witness -> no valid witness
            # For now, skip export if ledger cannot provide witness
            print(f"  feasible addition on {slug}: support={supp} sector={sec}", flush=True)
    print(f"done gated={gated} finds={finds}", flush=True)


if __name__ == "__main__":
    main()
