#!/usr/bin/env python3
"""Greedy weight-shedding campaign using code-calculus PR #624's objective search.

Issue #7116 direction 2 found that the v0.3.0 distance-interval objective was
blind to check weight. This campaign uses the new ``objective="weight"`` with
``rebase=True`` to greedily shed weight from board parents, stages every
survivor through make_submission/save_submission(spec=), and passes it through
the trusted gate. Gate-passing, board-advancing candidates are reported for
human review; this script never submits or opens a PR.

Distances are witness-backed upper bounds, not certified.
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
CC = os.environ.get(
    "CODE_CALCULUS_PATH",
    "/Users/mathysrennela/GitHub/code-calculus-dev-7116-pr",
)
for _p in (CC, ROOT, os.path.join(ROOT, "verify"),
           os.path.join(ROOT, "research", "kit")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from machine.priced_calculus import CodeState, DistanceLedger  # noqa: E402
from machine.planner import bounded_sector_search, infer_target_sector  # noqa: E402
from machine.priced_calculus import apply_operation  # noqa: E402


def check_weight(doc):
    return max([len(c) for side in ("X", "Z")
                for c in doc.get("checks", {}).get(side, [])] + [0])


def load_board():
    out = {}
    for path in glob.glob(os.path.join(ROOT, "codes", "*.json")):
        with open(path) as fh:
            doc = json.load(fh)
        if doc.get("code_type") != "CSS":
            continue
        d = doc.get("distance", {}).get("d")
        if not isinstance(d, int):
            continue
        out[os.path.splitext(os.path.basename(path))[0]] = doc
    return out


def select_parents(board, limit, n_lo, n_hi, order="weight", parent_d=2):
    pool = [s for s, d in board.items()
            if n_lo <= d["n"] <= n_hi
            and d["distance"]["d"] >= parent_d and check_weight(d) >= 5]
    if order == "n":
        pool.sort(key=lambda s: (board[s]["n"], s))
    else:
        # High-weight parents have more room to shed; put them first.
        pool.sort(key=lambda s: (-check_weight(board[s]), board[s]["n"], s))
    if limit > 0 and len(pool) > limit:
        step = len(pool) / limit
        pool = [pool[min(len(pool) - 1, int(i * step))] for i in range(limit)]
    return pool


def state_check_matrices(state):
    import numpy as np
    n = state.n()
    xrows = list(state.sector_rows("X"))
    zrows = list(state.sector_rows("Z"))
    # A sector may be empty; the verifier needs an explicit (0, n) array,
    # not a flat [] that would be read as one-dimensional.
    HX = np.zeros((len(xrows), n), dtype=int)
    HZ = np.zeros((len(zrows), n), dtype=int)
    qidx = {q: i for i, q in enumerate(sorted(state.Q))}
    for i, row in enumerate(xrows):
        for q in row.support:
            HX[i][qidx[q]] = 1
    for i, row in enumerate(zrows):
        for q in row.support:
            HZ[i][qidx[q]] = 1
    return HX, HZ


def child_weight(state):
    return max([len(r.support) for r in state.rows] + [0])


def choose(improving):
    """Prefer lower weight, then larger k, then smaller n, then higher d."""
    def key(c):
        return (child_weight(c["state"]), -c["k"], c["n"],
                -(c["ledger"].full.upper or 0))
    return min(improving, key=key)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--n-lo", type=int, default=10)
    ap.add_argument("--n-hi", type=int, default=120)
    ap.add_argument("--order", choices=("weight", "n"), default="weight")
    ap.add_argument("--parent-d", type=int, default=2)
    ap.add_argument("--min-d", type=int, default=1,
                    help="only gate children whose witnessed distance is >= this")
    ap.add_argument("--min-child-upper", type=int, default=None,
                    help="transport-level distance floor passed to the search")
    ap.add_argument("--no-rebase", action="store_true",
                    help="skip P-REBASE enumeration (faster; it added no hits)")
    ap.add_argument("--steps", type=int, default=3)
    ap.add_argument("--budget", type=int, default=64)
    ap.add_argument("--trials", type=int, default=8000)
    ap.add_argument("--gate-cap", type=int, default=40)
    ap.add_argument("--open-prs", action="store_true")
    ap.add_argument("--out", default=os.path.join(_HERE, "campaign.json"))
    args = ap.parse_args()

    from submit import make_submission, save_submission
    from coordination import unique_path, gate_and_record, staging_dir
    import dedup_oracle

    board = load_board()
    index = dedup_oracle.combined_index(include_open_prs=args.open_prs)
    print(f"dedup index: {len(index)} entries (open_prs={args.open_prs})",
          flush=True)
    parents = select_parents(board, args.limit, args.n_lo, args.n_hi,
                             args.order, args.parent_d)
    print(f"{len(parents)} parents, steps={args.steps}, budget={args.budget}",
          flush=True)

    staging = staging_dir()
    os.makedirs(staging, exist_ok=True)
    records = []
    gated = 0
    for pi, slug in enumerate(parents, 1):
        doc = board[slug]
        state = CodeState.from_challenge(doc)
        ledger = DistanceLedger.from_challenge(state, doc)
        target = doc["distance"]["d"]
        parent_w = check_weight(doc)
        chain = []
        for step in range(args.steps):
            ts = infer_target_sector(ledger, target)
            try:
                search = bounded_sector_search(
                    state, ledger, ts, target=target, budget=args.budget,
                    objective="weight", sector_swap=False,
                    rebase=not args.no_rebase,
                    min_child_upper=args.min_child_upper)
            except Exception as exc:
                chain.append({"step": step, "error": repr(exc)})
                break
            if not search["improving"]:
                chain.append({"step": step, "improving": 0})
                break
            chosen = choose(search["improving"])
            child_w = child_weight(chosen["state"])
            HX, HZ = state_check_matrices(chosen["state"])
            ident = dedup_oracle.identity_matrices(HX, HZ)
            dup = dedup_oracle.check(ident, index)
            entry = {
                "step": step, "operation": chosen["operation"],
                "n": chosen["n"], "k": chosen["k"],
                "w_before": parent_w, "w_after": child_w,
                "d_upper": chosen["ledger"].full.upper,
                "improving_pool": len(search["improving"]),
                "exhausted": search["exhausted"],
                "dedup_exact": len(dup["exact"]), "dedup_wl": len(dup["wl"]),
            }
            chain.append(entry)
            if dup["exact"] or gated >= args.gate_cap:
                entry["gate_skipped"] = ("duplicate" if dup["exact"]
                                         else "gate cap")
                if dup["exact"]:
                    break
                # advance anyway without gating
                try:
                    state = apply_operation(state, chosen["operation"])
                    ledger = chosen["ledger"]
                    parent_w = child_w
                except Exception:
                    break
                continue

            try:
                sub = make_submission(
                    HX, HZ,
                    name=f"[[{chosen['n']},{chosen['k']},?]] greedy-weight",
                    construction=f"code-calculus PR #624 greedy weight-shed from {slug} step {step}",
                    authors=["mathysrennela"], family="code-calculus",
                    confidence="upper_bound", trials=args.trials, seed=0)
                d = sub["distance"]["d"]
                entry["d_witness"] = d  # gate-relevant upper bound from the witness
                sub["name"] = f"[[{chosen['n']},{chosen['k']},{d}]] greedy-weight"
                path = unique_path(os.path.join(
                    staging, f"{chosen['n']}-{chosen['k']}-{d}-weight.json"), sub)
                save_submission(sub, path, preflight=False, spec={
                    "constructor": "planner.bounded_sector_search",
                    "params": {"parent": slug, "step": step,
                               "objective": "weight",
                               "rebase": not args.no_rebase,
                               "budget": args.budget,
                               "min_child_upper": args.min_child_upper},
                })
                # Still staged above: the witness is never discarded even
                # when the child is below the campaign's distance floor.
                if d < args.min_d:
                    entry["gate_skipped"] = f"d={d} < {args.min_d}"
                    try:
                        state = apply_operation(state, chosen["operation"])
                        ledger = chosen["ledger"]
                        parent_w = child_w
                    except Exception:
                        break
                    continue
                verdict, _ = gate_and_record(path)
                gated += 1
                entry.update({
                    "gate_passed": verdict.get("passed"),
                    "board_advancing": (verdict.get("gates", {})
                                        .get("novelty", {})
                                        .get("board_advancing")),
                    "gate": verdict,
                    "path": path,
                })
                print(f"  [{pi}/{len(parents)}] {slug} s{step}: "
                      f"w {parent_w}->{child_w} n={chosen['n']} k={chosen['k']} "
                      f"d<={d} pass={verdict.get('passed')} "
                      f"adv={entry['board_advancing']}", flush=True)
            except Exception as exc:
                entry["gate_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
                print(f"  [{pi}/{len(parents)}] {slug} s{step}: "
                      f"GATE ERROR {entry['gate_error'][:100]}", flush=True)

            try:
                state = apply_operation(state, chosen["operation"])
                ledger = chosen["ledger"]
                parent_w = child_w
            except Exception:
                break
        records.append({"parent": slug, "parent_n": doc["n"],
                        "parent_k": doc["k"], "parent_d": target,
                        "parent_w": check_weight(doc), "chain": chain})

    total_steps = sum(len([c for c in r["chain"] if "improving" in c])
                      for r in records)
    passed = sum(1 for r in records for c in r["chain"] if c.get("gate_passed"))
    advancing = sum(1 for r in records for c in r["chain"]
                    if c.get("board_advancing"))
    summary = {"parents": len(parents), "gated": gated,
               "weight_improving_steps": total_steps,
               "gate_passed": passed, "board_advancing": advancing}
    with open(args.out, "w") as fh:
        json.dump({"summary": summary, "records": records}, fh, indent=2)
    print("SUMMARY", json.dumps(summary), flush=True)
    for r in records:
        for c in r["chain"]:
            if c.get("board_advancing"):
                print("FIND", r["parent"], c.get("n"), c.get("k"),
                      c.get("d_witness"), c.get("w_after"), c.get("path"),
                      flush=True)


if __name__ == "__main__":
    main()
