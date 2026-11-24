#!/usr/bin/env python3
"""code-calculus v0.3.1 stress campaign: lead-driven, staged, never submitted.

Runs on the v0.3.1 consumer (code-calculus-dev main @ 8aa97b9). Three arms,
each on a named lead from the 2026-11-22/23 fieldnotes:

  pairpartition: L-PAIR-PARTITION at p in {9, 11, 13} (the earlier grids
    stopped at p=7), block-mixing shift patterns.
  ppscale: PP-SCALE rung-3 SNF bundles with slope patterns outside the
    unit-slope CPM-PP grid (slopes 1 / P-1 via an order-2 root).
  greedy: pure weight-shedding over fresh board parents with the new
    v0.3.1 objective-aware search, recording the stop/budget/applicability
    reporting added in v0.3.1 (stop_reason, budget_declined, applicability).

Every connected derivation is packaged with make_submission (witness-backed
upper bound), staged with save_submission(..., spec=), and judged by the
unchanged trusted gate.  Nothing is submitted, committed, or opened as a PR.
Dedup covers the board, open PRs, and the previously staged (unsubmitted)
finds of the 2026-11-22 v0.3rc campaign, so a re-derivation of an already
staged code is refused locally rather than re-counted.
"""
import argparse
import glob
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
CC = os.environ.get(
    "CODE_CALCULUS_PATH",
    "/Users/mathysrennela/GitHub/code-calculus-dev",
)
for _p in (CC, ROOT, os.path.join(ROOT, "verify"), os.path.join(ROOT, "research", "kit")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from constructors import jsonable_params, pair_partition_specs, pp_scale_specs, resolve_spec  # noqa: E402
from machine.constructors import ADMITTED_CONSTRUCTORS, construct  # noqa: E402
from machine.planner import bounded_sector_search, infer_target_sector  # noqa: E402
from machine.priced_calculus import CodeState, DistanceLedger, apply_operation  # noqa: E402

PRIOR_CAMPAIGNS = (
    "research/campaigns/cc-v03-weight-shed-greedy-2026-11-23/campaign.json",
    "research/campaigns/cc-v03-weight-shed-greedy-2026-11-23/campaign_smalln.json",
    "research/campaigns/cc-v03rc-greedy-constructors-2026-11-23/result.json",
    "research/campaigns/cc-v03rc-greedy-constructors-2026-11-23/result-greedy.json",
)


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
        if not isinstance(doc.get("distance", {}).get("d"), int):
            continue
        out[os.path.splitext(os.path.basename(path))[0]] = doc
    return out


def prior_parents():
    used = set()
    for rel in PRIOR_CAMPAIGNS:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            continue
        with open(path) as fh:
            data = json.load(fh)
        for rec in (data.get("records") or data.get("greedy") or []):
            if rec.get("parent"):
                used.add(rec["parent"])
    return used


def prior_staged_paths():
    """Paths of this campaign's and the v0.3rc campaign's staged finds."""
    paths = []
    # This campaign's own staged records, so a rerun skips its earlier finds.
    for name in ("result.json", "result-run1.json"):
        here = os.path.join(_HERE, name)
        if os.path.exists(here):
            try:
                with open(here) as fh:
                    data = json.load(fh)
                for arm in ("pairpartition", "ppscale"):
                    for rec in (data.get(arm) or {}).get("records", []):
                        if rec.get("gate_passed") and rec.get("path"):
                            paths.append(rec["path"])
            except (OSError, ValueError):
                pass
    rel = "research/campaigns/cc-v03rc-greedy-constructors-2026-11-23/finds.json"
    path = os.path.join(ROOT, rel)
    if os.path.exists(path):
        with open(path) as fh:
            for find in json.load(fh).get("finds", []):
                if find.get("path"):
                    paths.append(find["path"])
    return paths


def select_parents(board, limit, n_lo, n_hi, order="n"):
    used = prior_parents()
    pool = [s for s, d in board.items()
            if n_lo <= d["n"] <= n_hi
            and d["distance"]["d"] >= 2 and check_weight(d) >= 5
            and s not in used]
    if order == "weight":
        pool.sort(key=lambda s: (-check_weight(board[s]), board[s]["n"], s))
    else:
        pool.sort(key=lambda s: (board[s]["n"], s))
    if limit > 0 and len(pool) > limit:
        step = len(pool) / limit
        pool = [pool[min(len(pool) - 1, int(i * step))] for i in range(limit)]
    return pool


def state_check_matrices(state):
    import numpy as np
    n = state.n()
    HX = np.zeros((len(state.sector_rows("X")), n), dtype=int)
    HZ = np.zeros((len(state.sector_rows("Z")), n), dtype=int)
    qidx = {q: i for i, q in enumerate(sorted(state.Q))}
    for i, row in enumerate(state.sector_rows("X")):
        for q in row.support:
            HX[i][qidx[q]] = 1
    for i, row in enumerate(state.sector_rows("Z")):
        for q in row.support:
            HZ[i][qidx[q]] = 1
    return HX, HZ


def child_weight(state):
    return max([len(r.support) for r in state.rows] + [0])


def choose(improving):
    def key(c):
        return (child_weight(c["state"]), -c["k"], c["n"],
                -(c["ledger"].full.upper or 0))
    return min(improving, key=key)


def stage_and_gate(state, label, constructor, params, index, args):
    """Package a child with witnesses, stage it with its recipe, gate it."""
    import dedup_oracle
    from coordination import gate_and_record, staging_dir, unique_path
    from submit import make_submission, save_submission

    entry = {"label": label, "constructor": constructor, "params": params,
             "n": state.n(), "k": state.k(), "w": child_weight(state)}
    from prescreen import block_structure
    HX, HZ = state_check_matrices(state)
    structure = block_structure(HX, HZ)
    entry["tanner_connected"] = structure["connected"]
    entry["block_structure"] = structure
    if not structure["connected"]:
        entry["gate_skipped"] = "direct sum / disconnected Tanner graph"
        return entry, None
    ident = dedup_oracle.identity_matrices(HX, HZ)
    dup = dedup_oracle.check(ident, index)
    entry["dedup_exact"] = len(dup["exact"])
    entry["dedup_wl"] = len(dup["wl"])
    if dup["exact"]:
        entry["gate_skipped"] = "exact duplicate"
        return entry, None
    index.append({"source": "this-run", "name": label,
                  "fingerprints": ident["fingerprints"],
                  "signatures": ident["signatures"]})
    try:
        doc = make_submission(
            HX, HZ,
            name=f"[[{state.n()},{state.k()},?]] {label}",
            construction=f"code-calculus v0.3.1 constructor run {label}; "
                         f"stress campaign",
            authors=["mathysrennela"], family="code-calculus",
            confidence="upper_bound", trials=args.trials, seed=0,
        )
        d = doc["distance"]["d"]
        doc["name"] = f"[[{state.n()},{state.k()},{d}]] {label}"
        entry["d_witness"] = d
        path = unique_path(os.path.join(
            staging_dir(), f"{state.n()}-{state.k()}-{d}-{label[:24]}.json"), doc)
        save_submission(doc, path, preflight=False, spec={
            "constructor": constructor, "params": params,
        })
        entry["path"] = path
        verdict, _ = gate_and_record(path)
        nov = verdict.get("gates", {}).get("novelty", {})
        entry.update({
            "gate_passed": verdict.get("passed"),
            "board_advancing": nov.get("board_advancing"),
            "dominated_by": nov.get("dominated_by"),
            "d_only_gain": nov.get("d_only_gain"),
            "cell": nov.get("cell"),
            "gate": verdict,
        })
        print(f"  GATE {label}: n={state.n()} k={state.k()} d<={d} w={entry['w']} "
              f"pass={verdict.get('passed')} adv={nov.get('board_advancing')}",
              flush=True)
        return entry, doc
    except Exception as exc:
        entry["gate_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        print(f"  REFUSE {label}: {entry['gate_error'][:140]}", flush=True)
        return entry, None


def derive_seed(label, spec):
    """Derive one constructor spec; return the seed record."""
    rec = {"label": label, "constructor": spec["constructor"],
           "params": jsonable_params(spec)}
    try:
        label, spec = resolve_spec(label, spec)
        res = construct(spec)
        st = res["state"]
        st.validate()
    except Exception as exc:
        rec["reason"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        return rec
    HX, HZ = state_check_matrices(st)
    from prescreen import block_structure
    gate_struct = block_structure(HX, HZ)
    rec.update({"connected": gate_struct["connected"],
                "blocks": gate_struct["blocks"],
                "block_sizes": gate_struct["block_sizes"],
                "n": st.n(), "k": st.k(), "w": child_weight(st)})
    rec["_state"] = st
    rec["_spec"] = spec
    return rec


def arm_constructors(args, index, specs):
    print("== arm: constructor seeds ==", flush=True)
    records = []
    gated = advancing = staged = 0
    derived = connected = 0
    for label, spec in specs:
        if args.label_contains and args.label_contains not in label:
            continue
        if args.cap and staged >= args.cap:
            break
        rec = derive_seed(label, spec)
        if "reason" in rec:
            records.append(rec)
            continue
        derived += 1
        if not rec.get("connected"):
            records.append({k: v for k, v in rec.items() if not k.startswith("_")})
            continue
        connected += 1
        if rec["w"] > args.max_w or rec["k"] < 2:
            records.append({k: v for k, v in rec.items() if not k.startswith("_")})
            continue
        staged += 1
        entry, _ = stage_and_gate(rec["_state"], rec["label"], rec["constructor"],
                                  rec["params"], index, args)
        rec = {k: v for k, v in rec.items() if not k.startswith("_")}
        rec.update(entry)
        if entry.get("gate_passed"):
            gated += 1
        if entry.get("board_advancing"):
            advancing += 1
        records.append(rec)
    print(f"constructor arm: derived={derived} connected={connected} "
          f"staged={staged} gate-passed={gated} board-advancing={advancing}",
          flush=True)
    return {"records": records, "derived": derived, "connected": connected,
            "staged": staged, "gate_passed": gated, "board_advancing": advancing}


def summarize_search(search):
    """Return the v0.3.1 stop/budget/applicability reporting, verbatim."""
    out = {
        "evaluated": search.get("evaluated"),
        "budget": search.get("budget"),
        "budget_used": search.get("budget_used"),
        "budget_declined": search.get("budget_declined"),
        "exhausted": search.get("exhausted"),
        "truncated": search.get("truncated"),
        "stop_reason": search.get("stop_reason"),
        "applicability": search.get("applicability"),
    }
    return out


def arm_greedy(args, index):
    print("== arm: objective-aware greedy (weight) ==", flush=True)
    board = load_board()
    parents = select_parents(board, args.limit, args.n_lo, args.n_hi, args.order)
    print(f"{len(parents)} fresh parents, steps={args.steps}, "
          f"budget={args.budget}", flush=True)
    records = []
    gated = advancing = 0
    for pi, slug in enumerate(parents, 1):
        if args.gate_cap and gated >= args.gate_cap:
            break
        doc = board[slug]
        state = CodeState.from_challenge(doc)
        ledger = DistanceLedger.from_challenge(state, doc)
        target = doc["distance"]["d"]
        parent_w = check_weight(doc)
        chain = []
        for step in range(args.steps):
            if args.gate_cap and gated >= args.gate_cap:
                break
            ts = infer_target_sector(ledger, target)
            try:
                search = bounded_sector_search(
                    state, ledger, ts, target=target, budget=args.budget,
                    objective="weight", sector_swap=False, rebase=True)
            except Exception as exc:
                chain.append({"step": step, "search_error": repr(exc)})
                break
            improving = search.get("improving", [])
            chain.append({"step": step, "improving": len(improving),
                          "search": summarize_search(search)})
            if not improving:
                break
            chosen = choose(improving)
            child_w = child_weight(chosen["state"])
            op = chosen.get("operation", {})
            from prescreen import block_structure
            _hx, _hz = state_check_matrices(chosen["state"])
            prof = block_structure(_hx, _hz)
            entry = {
                "operation": op.get("op") if isinstance(op, dict) else str(op),
                "n": chosen["n"], "k": chosen["k"],
                "w_before": parent_w, "w_after": child_w,
                "d_upper": chosen["ledger"].full.upper,
                "improving_pool": len(improving),
                "connected": prof["connected"],
            }
            chain[-1].update(entry)
            if not prof["connected"]:
                chain[-1]["gate_skipped"] = "disconnected"
            elif args.gate_cap and gated >= args.gate_cap:
                chain[-1]["gate_skipped"] = "gate cap"
            else:
                label = f"greedy-{slug}-s{step}"
                stage_entry, _ = stage_and_gate(
                    chosen["state"], label, "planner.bounded_sector_search",
                    {"parent": slug, "step": step, "objective": "weight",
                     "rebase": True, "budget": args.budget}, index, args)
                chain[-1].update(stage_entry)
                if stage_entry.get("gate_passed"):
                    gated += 1
                if stage_entry.get("board_advancing"):
                    advancing += 1
            try:
                op_name = op.get("op") if isinstance(op, dict) else None
                if op_name in ADMITTED_CONSTRUCTORS:
                    state = chosen["state"]
                else:
                    state = apply_operation(state, chosen["operation"])
                ledger = chosen["ledger"]
                parent_w = child_w
            except Exception as exc:
                chain.append({"step": step, "advance_error": repr(exc)})
                break
        records.append({"parent": slug, "parent_n": doc["n"],
                        "parent_k": doc["k"], "parent_d": target,
                        "parent_w": check_weight(doc), "chain": chain})
    print(f"greedy arm: {gated} gate-passed, {advancing} board-advancing",
          flush=True)
    return {"records": records, "gate_passed": gated,
            "board_advancing": advancing}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=("pairpartition", "ppscale", "greedy", "all"),
                    default="all")
    ap.add_argument("--limit", type=int, default=24)
    ap.add_argument("--n-lo", type=int, default=10)
    ap.add_argument("--n-hi", type=int, default=120)
    ap.add_argument("--order", choices=("n", "weight"), default="n")
    ap.add_argument("--steps", type=int, default=4)
    ap.add_argument("--budget", type=int, default=64)
    ap.add_argument("--trials", type=int, default=8000)
    ap.add_argument("--gate-cap", type=int, default=12)
    ap.add_argument("--cap", type=int, default=15,
                    help="max staged derivations per constructor arm (0 = all)")
    ap.add_argument("--max-w", type=int, default=10)
    ap.add_argument("--label-contains", default=None,
                    help="only run specs whose label contains this substring")
    ap.add_argument("--open-prs", action="store_true", default=True)
    ap.add_argument("--out", default=os.path.join(_HERE, "result.json"))
    args = ap.parse_args()

    import dedup_oracle
    index = dedup_oracle.combined_index(include_open_prs=args.open_prs,
                                        extra_paths=prior_staged_paths())
    print(f"dedup index: {len(index)} entries "
          f"(board + open PRs + {len(prior_staged_paths())} prior staged finds)",
          flush=True)

    result = {"cc": CC, "args": vars(args),
              "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if args.arm in ("pairpartition", "all"):
        result["pairpartition"] = arm_constructors(
            args, index, pair_partition_specs())
        with open(args.out, "w") as fh:
            json.dump(result, fh, indent=2, default=str)
    if args.arm in ("ppscale", "all"):
        result["ppscale"] = arm_constructors(
            args, index, pp_scale_specs())
        with open(args.out, "w") as fh:
            json.dump(result, fh, indent=2, default=str)
    if args.arm in ("greedy", "all"):
        result["greedy"] = arm_greedy(args, index)
    result["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(args.out, "w") as fh:
        json.dump(result, fh, indent=2, default=str)
    print("wrote", args.out, flush=True)


if __name__ == "__main__":
    main()
