#!/usr/bin/env python3
"""Direction 6 of issue #7116 (was 7): systematic E-GLUE seam matching.

The v0.2 probe ran 0 successful glues because it had no seam enumerator.
code-calculus now exposes ``enumerate_seam_checks``; this campaign enumerates
seams over pairs of small CSS board parents, applies E-GLUE with each seam,
stages the child with a witness and a recipe, and gates it. Nothing is
submitted; board-advancing survivors are reported for human review.

Distances are witness-backed upper bounds. No soundness claim is made.
"""
import argparse
import collections
import glob
import itertools
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

from machine.priced_calculus import CodeState, apply_operation, Row  # noqa: E402
from machine.entrypoints import enumerate_seam_checks  # noqa: E402


def shifted(state, offset, reserved):
    """Disjoint-name copy of ``state`` for E-GLUE (canonical id remint)."""
    Q = tuple(q + offset for q in state.Q)
    rows = tuple(Row(r.id, r.sector, tuple(q + offset for q in r.support))
                 for r in state.rows)
    return CodeState(Q, rows, state.used).relabel_identifiers(used=reserved)


def state_check_matrices(state):
    import numpy as np
    n = state.n()
    xrows = list(state.sector_rows("X"))
    zrows = list(state.sector_rows("Z"))
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


def load_parents(n_lo, n_hi, limit):
    out = []
    for path in sorted(glob.glob(os.path.join(ROOT, "codes", "*.json"))):
        with open(path) as fh:
            doc = json.load(fh)
        if doc.get("code_type") != "CSS" or not (n_lo <= doc["n"] <= n_hi):
            continue
        d = doc.get("distance", {}).get("d")
        if not isinstance(d, int) or d < 1:
            continue
        try:
            out.append((os.path.splitext(os.path.basename(path))[0],
                        CodeState.from_challenge(doc)))
        except Exception:
            continue
        if len(out) >= limit:
            break
    return out


def spread(items, count):
    if count <= 0 or len(items) <= count:
        return list(items)
    step = len(items) / count
    return [items[min(len(items) - 1, int(i * step))] for i in range(count)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-lo", type=int, default=8)
    ap.add_argument("--n-hi", type=int, default=12)
    ap.add_argument("--parents", type=int, default=20)
    ap.add_argument("--pairs", type=int, default=40)
    ap.add_argument("--seams-per-pair", type=int, default=3)
    ap.add_argument("--max-size", type=int, default=4,
                    help="max seam support size (3 never yields cross-factor seams)")
    ap.add_argument("--gate-cap", type=int, default=25)
    ap.add_argument("--trials", type=int, default=8000)
    ap.add_argument("--open-prs", action="store_true")
    ap.add_argument("--out", default=os.path.join(_HERE, "campaign.json"))
    args = ap.parse_args()

    from submit import make_submission, save_submission
    from coordination import unique_path, gate_and_record, staging_dir
    import dedup_oracle

    board = load_parents(args.n_lo, args.n_hi, args.parents)
    pairs = spread(list(itertools.combinations(board, 2)), args.pairs)
    index = dedup_oracle.combined_index(include_open_prs=args.open_prs)
    print(f"{len(board)} parents, {len(pairs)} pairs, "
          f"dedup index {len(index)} (open_prs={args.open_prs})", flush=True)
    staging = staging_dir()
    os.makedirs(staging, exist_ok=True)

    cert = {"move_words": ["U", "U"],
            "evidence": "systematic seam enumeration (issue #7116 direction 6)"}
    records = []
    gated = 0
    started = time.time()
    for pi, ((na, la), (nb, lb)) in enumerate(pairs, 1):
        rb = shifted(lb, max(la.Q) + 1, la.used)
        seams = enumerate_seam_checks(la, rb, max_size=args.max_size)
        left_labels, right_labels = set(la.Q), set(rb.Q)
        cross = [s for s in seams
                 if any(q in left_labels for q in s[1])
                 and any(q in right_labels for q in s[1])]
        rec = {"left": na, "right": nb, "n_left": la.n(), "n_right": rb.n(),
               "seams_total": len(seams), "cross_seams": len(cross),
               "children": []}
        # A within-factor seam cannot join the two stabilizer blocks, so the
        # gate refuses the child. Prioritise seams spanning both factors.
        for seam in spread(cross or seams, args.seams_per_pair):
            entry = {"seam": [seam[0], list(seam[1])]}
            try:
                child = apply_operation(la, {
                    "op": "E-GLUE", "right_state": rb,
                    "seam_checks": [seam], "seam_certificate": cert})
                child.validate()
            except Exception as exc:
                entry["derive_error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
                rec["children"].append(entry)
                continue
            entry.update({"child_n": child.n(), "child_k": child.k()})
            HX, HZ = state_check_matrices(child)
            entry["max_w"] = max([len(r.support) for r in child.rows] + [0])
            dup = dedup_oracle.check(dedup_oracle.identity_matrices(HX, HZ),
                                     index)
            entry["dedup_exact"] = len(dup["exact"])
            entry["dedup_wl"] = len(dup["wl"])
            if dup["exact"]:
                entry["gate_skipped"] = "duplicate"
                rec["children"].append(entry)
                continue
            if gated >= args.gate_cap:
                entry["gate_skipped"] = "gate cap"
                rec["children"].append(entry)
                continue
            try:
                sub = make_submission(
                    HX, HZ,
                    name=f"[[{child.n()},{child.k()},?]] eglue",
                    construction=f"E-GLUE seam {na}+{nb} (systematic enumeration)",
                    authors=["mathysrennela"], family="code-calculus",
                    confidence="upper_bound", trials=args.trials, seed=0)
                d = sub["distance"]["d"]
                entry["d_witness"] = d
                sub["name"] = f"[[{child.n()},{child.k()},{d}]] eglue"
                path = unique_path(os.path.join(
                    staging, f"{child.n()}-{child.k()}-{d}-eglue.json"), sub)
                save_submission(sub, path, preflight=False, spec={
                    "constructor": "E-GLUE",
                    "params": {"left": na, "right": nb, "seam": entry["seam"],
                               "max_size": args.max_size},
                })
                verdict, _ = gate_and_record(path)
                gated += 1
                entry.update({
                    "gate_passed": verdict.get("passed"),
                    "board_advancing": (verdict.get("gates", {})
                                        .get("novelty", {})
                                        .get("board_advancing")),
                    "gate": verdict, "path": path})
                print(f"  [{pi}/{len(pairs)}] {na}+{nb}: n={child.n()} "
                      f"k={child.k()} d={d} pass={verdict.get('passed')} "
                      f"adv={entry['board_advancing']}", flush=True)
            except Exception as exc:
                entry["gate_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
                print(f"  [{pi}/{len(pairs)}] {na}+{nb}: GATE ERROR "
                      f"{entry['gate_error'][:90]}", flush=True)
            rec["children"].append(entry)
        records.append(rec)

    stats = collections.Counter()
    for rec in records:
        stats["pairs"] += 1
        stats["seams_total"] += rec["seams_total"]
        stats["cross_seams_total"] += rec["cross_seams"]
        for c in rec["children"]:
            stats["children_tried"] += 1
            if "derive_error" in c:
                stats["derive_fail"] += 1
            if c.get("dedup_exact"):
                stats["duplicate"] += 1
            if "gate_passed" in c:
                stats["gated"] += 1
                stats["passed"] += bool(c["gate_passed"])
                stats["advancing"] += bool(c["board_advancing"])
    summary = dict(stats)
    summary["seconds"] = round(time.time() - started, 1)
    summary["open_prs"] = args.open_prs
    with open(args.out, "w") as fh:
        json.dump({"summary": summary, "records": records}, fh, indent=2)
    print("SUMMARY", json.dumps(summary), flush=True)
    for rec in records:
        for c in rec["children"]:
            if c.get("board_advancing"):
                print("FIND", rec["left"], rec["right"], c["child_n"],
                      c["child_k"], c["d_witness"], c["max_w"], c["path"],
                      flush=True)


if __name__ == "__main__":
    main()
