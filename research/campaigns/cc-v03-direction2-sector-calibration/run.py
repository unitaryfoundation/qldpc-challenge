#!/usr/bin/env python3
"""Direction 2 of qldpc-challenge issue #7116: bounded sector search on the
v0.2 negative pilots (campaigns 3 and 4), with per-move-family refusal reasons.

This is a CALIBRATION run, not a submission campaign.  For each parent we
record two independent things:

  * what ``bounded_sector_search`` actually did (budget used, exhausted,
    sector-swap reason, which move families produced improving candidates);
  * a faithful replay of the ``plan`` single-step pipeline that records, per
    move family, *where each enumerated move was dropped*: apply_operation
    non-derivation, the bare-qubit structural screen, disconnection, ledger
    transport non-derivation, or survived-and-improved.

The second half is the input the next patch's applicability diagnostics need:
it separates "the move was inapplicable" from "the search did not reach it".

No candidate is gated or staged here.  Distances are the carried ledger's
upper bounds, never certified facts.
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
    "/Users/mathysrennela/GitHub/code-calculus",
)
for _p in (CC, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from machine.priced_calculus import (  # noqa: E402
    CodeState, DistanceLedger, NoDerivation, Malformed, apply_operation,
    tanner_components,
)
from machine.planner import (  # noqa: E402
    bounded_sector_search, infer_target_sector, candidate_moves,
    has_bare_qubit, reduce_display, sector_targeted_improvement,
)

FAMILIES = ("C-DELETE-CHECK", "E-PEEL", "E-PUNCTURE", "E-EXTEND",
            "E-GRAFT", "P-REBASE")
DROP_REASONS = ("enumerated", "apply_fail", "bare_qubit", "disconnected",
                "derive_fail", "survived", "improving_pre_budget")


def check_weight(doc):
    w = 0
    for side in ("X", "Z"):
        for check in doc.get("checks", {}).get(side, []):
            w = max(w, len(check))
    return w


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


def missing_n(board, lo=86, hi=400):
    present = {doc["n"] for doc in board.values()}
    return sorted(set(range(lo, hi + 1)) - present)


def deterministic_sample(items, limit, stride_seed=0):
    """Even spread over a sorted list, stable across runs."""
    items = sorted(items)
    if limit <= 0 or len(items) <= limit:
        return items
    step = len(items) / limit
    return [items[min(len(items) - 1, int(i * step))] for i in range(limit)]


def select_parents(board, campaign, limit, n_floor=0, n_cap=10**9):
    if campaign == 3:
        pool = [s for s, d in board.items()
                if d["distance"]["d"] >= 8 and check_weight(d) in (8, 9)]
    elif campaign == 4:
        pool = [s for s, d in board.items()
                if d["n"] >= 500 and d["distance"]["d"] >= 6]
    else:
        raise ValueError(campaign)
    pool = [s for s in pool if n_floor <= board[s]["n"] <= n_cap]
    # Prefer the smallest n within the pool: the single-step plan replay is
    # O(n^2) in the number of enumerated puncture/deletion moves, so this
    # keeps the calibration tractable while staying inside each campaign's
    # defining criteria (weight/d/n floors are unchanged).
    pool.sort(key=lambda s: (board[s]["n"], s))
    return deterministic_sample(pool, limit)


def diagnose(state, ledger, target, target_sector):
    """Replay the plan() single-step pipeline and record per-family drops."""
    per = {fam: collections.Counter() for fam in FAMILIES}
    working = reduce_display(state)
    for op in candidate_moves(working, structural=True, reduce_display=False,
                              rebase=False):
        fam = op.get("op")
        if fam not in per:
            per[fam] = collections.Counter()
        per[fam]["enumerated"] += 1
        try:
            child = apply_operation(working, op)
        except (NoDerivation, Malformed):
            per[fam]["apply_fail"] += 1
            continue
        if target is not None and target > 1 and has_bare_qubit(child):
            per[fam]["bare_qubit"] += 1
            continue
        if tanner_components(child) != 1:
            per[fam]["disconnected"] += 1
            continue
        try:
            child_ld = ledger.propagate(op, child, parent_state=working,
                                        observations=None, hypothesis=None)
        except (NoDerivation, Malformed):
            per[fam]["derive_fail"] += 1
            continue
        per[fam]["survived"] += 1
        improves, _, _, _ = sector_targeted_improvement(
            {"ledger": child_ld, "operation": op}, ledger, target_sector)
        if improves:
            per[fam]["improving_pre_budget"] += 1
    return {fam: {r: per[fam].get(r, 0) for r in DROP_REASONS}
            for fam in sorted(per)}


def compact_swap(swap):
    if not isinstance(swap, dict):
        return None
    return {
        "applied": swap.get("applied"),
        "reason": swap.get("reason"),
        "guard_name": swap.get("guard_name"),
        "refused_by": swap.get("refused_by"),
        "refusal_guard": swap.get("refusal_guard"),
        "unchanged": (swap.get("full_distance") or {}).get("unchanged"),
    }


def run_parent(slug, doc, budget, do_diagnose, missing_set):
    state = CodeState.from_challenge(doc)
    ledger = DistanceLedger.from_challenge(state, doc)
    target = doc["distance"]["d"]
    ts = infer_target_sector(ledger, target)
    started = time.time()
    search = bounded_sector_search(state, ledger, ts, target=target,
                                   budget=budget, sector_swap=True)
    elapsed = time.time() - started
    improving_ops = collections.Counter(
        c["operation"]["op"] for c in search.get("improving", []))
    child_n = {c["n"] for c in search.get("improving", [])}
    rec = {
        "slug": slug,
        "n": state.n(),
        "k": state.k(),
        "d": target,
        "w": check_weight(doc),
        "target_sector": ts,
        "budget": budget,
        "budget_used": search.get("budget_used"),
        "exhausted": search.get("exhausted"),
        "search_status": search.get("search_status"),
        "sector_swap": compact_swap(search.get("sector_swap")),
        "improving_count": len(search.get("improving", [])),
        "improving_by_family": dict(improving_ops),
        "improving_child_n": sorted(child_n),
        "improving_child_n_in_missing_set": sorted(child_n & missing_set),
        "heuristic_outcome": search.get("heuristic_outcome"),
        "seconds": round(elapsed, 3),
    }
    if do_diagnose:
        rec["diagnosis"] = diagnose(state, ledger, target, ts)
    return rec


def aggregate(records):
    agg = collections.Counter()
    by_family = {fam: collections.Counter() for fam in FAMILIES}
    for rec in records:
        agg["parents"] += 1
        agg["budget_used_total"] += rec["budget_used"] or 0
        agg["improving_total"] += rec["improving_count"]
        agg["exhausted"] += bool(rec["exhausted"])
        agg["swap_applied"] += bool((rec["sector_swap"] or {}).get("applied"))
        agg["missing_n_hits"] += len(rec["improving_child_n_in_missing_set"])
        agg["seconds_total"] += rec["seconds"]
        for fam, counts in (rec.get("diagnosis") or {}).items():
            for reason, value in counts.items():
                by_family[fam][reason] += value
    return {
        "totals": dict(agg),
        "by_family": {fam: dict(by_family[fam]) for fam in sorted(by_family)},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign", type=int, required=True, choices=(3, 4))
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--budget", type=int, default=128)
    ap.add_argument("--n-floor", type=int, default=0)
    ap.add_argument("--n-cap", type=int, default=10**9)
    ap.add_argument("--no-diagnose", action="store_true")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    board = load_board()
    mset = set(missing_n(board))
    parents = select_parents(board, args.campaign, args.limit,
                             args.n_floor, args.n_cap)
    print(f"campaign {args.campaign}: {len(parents)} parents "
          f"(budget {args.budget}, diagnose={not args.no_diagnose})", flush=True)

    records = []
    for i, slug in enumerate(parents, 1):
        rec = run_parent(slug, board[slug], args.budget,
                         not args.no_diagnose, mset)
        records.append(rec)
        print(f"  [{i}/{len(parents)}] {slug}: eval={rec['budget_used']} "
              f"exh={rec['exhausted']} impr={rec['improving_count']} "
              f"{rec['seconds']}s", flush=True)

    summary = aggregate(records)
    summary["campaign"] = args.campaign
    summary["budget"] = args.budget
    summary["limit"] = args.limit
    summary["missing_n_lo"] = 86
    summary["missing_n_hi"] = 400
    summary["n_missing_n"] = len(mset)
    summary["parents"] = [r["slug"] for r in records]

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump({"summary": summary, "records": records}, fh, indent=2)
    print(f"wrote {args.out}", flush=True)
    print(json.dumps(summary["totals"], indent=2), flush=True)


if __name__ == "__main__":
    main()
