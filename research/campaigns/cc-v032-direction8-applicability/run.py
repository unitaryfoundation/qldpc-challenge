#!/usr/bin/env python3
r"""Direction 8 of issue #7377: move applicability diagnostics over the board's CSS entries.

For every parent, code-calculus v0.3.2's ``machine.planner.move_applicability_report``
tries the whole candidate domain of each move family (``C-DELETE-CHECK``,
``E-PEEL``, ``E-PUNCTURE``, ``E-GRAFT``, ``P-REBASE``, ``E-EXTEND``) and says,
per family, how many candidates there are, how many derive, how many
children pass the screens (no bare qubit or weight-1 logical, connected, at
or under the weight cap), and which premise or screen accounts for the rest.
This is search control: it reads no ledger and says nothing about distance.

The weight cap is the parent's own displayed check weight, so "usable" means
a child no heavier than its parent. ``P-REBASE`` tries every elementary row
mix, which is quadratic in the row count (37,812 mixes at n = 288, nine
minutes), so it is asked for only up to ``--rebase-n-max`` qubits; above that
the family is recorded as not asked for.

Pools (the v0.2 campaigns of issue #6198 the direction names, by their
parent definitions, over the current board) are labels on each record, not
separate runs: C2 (delete-check chains into k-heavy cells: d >= 8, w <= 8),
C3 (weight shedding: d >= 8, w >= 8), C4 (puncture and peel chains toward
missing n: n >= 500, d >= 6), C6 (sector-swap rebalance: d_X != d_Z). Every
CSS entry is run, so the board-wide table is the same file.

    CODE_CALCULUS_PATH=<checkout> uv run python research/campaigns/cc-v032-direction8-applicability/run.py \\
        --out research/candidates/<run>/ --workers 8 --rebase-n-max 100

Output: ``<out>/reports.jsonl``, one record per parent (slug, pools, parent
stats, per-family domain/derived/usable/blocking/best_child_w, seconds), and
``<out>/run.log``. A rerun skips the slugs already in the file.
"""

import argparse
import glob
import json
import multiprocessing as mp
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
CC = os.environ.get("CODE_CALCULUS_PATH", os.path.join(os.path.dirname(ROOT), "code-calculus"))
for _p in (CC, ROOT, os.path.join(ROOT, "verify")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

FAMILIES = ("C-DELETE-CHECK", "E-PEEL", "E-PUNCTURE", "E-GRAFT", "P-REBASE", "E-EXTEND")


def pools_of(doc, w):
    d = doc["distance"]["d"]
    dx = (doc["distance"].get("X") or {}).get("value")
    dz = (doc["distance"].get("Z") or {}).get("value")
    out = []
    if d >= 8 and w <= 8:
        out.append("C2")
    if d >= 8 and w >= 8:
        out.append("C3")
    if doc["n"] >= 500 and d >= 6:
        out.append("C4")
    if dx is not None and dz is not None and dx != dz:
        out.append("C6")
    return out


def parents(codes_dir, n_max=None, slugs=None, n_min=None):
    out = []
    for path in sorted(glob.glob(os.path.join(codes_dir, "*.json"))):
        slug = os.path.basename(path)[:-5]
        if slugs is not None and slug not in slugs:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError):
            continue
        if doc.get("code_type", "CSS") != "CSS" or "X" not in (doc.get("checks") or {}):
            continue
        if n_max is not None and doc["n"] > n_max:
            continue
        if n_min is not None and doc["n"] < n_min:
            continue
        out.append((slug, path))
    return out


def one(args):
    """Run the report for one parent; return its record (errors are records too)."""
    slug, path, rebase_n_max = args
    from machine.planner import move_applicability_report
    from machine.priced_calculus import CodeState

    t0 = time.time()
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    rec = {"slug": slug, "n": doc["n"], "k": doc["k"], "d": doc["distance"]["d"], "family_tag": doc.get("family")}
    try:
        state = CodeState.from_challenge(doc)
        w = state.w()
        rec["w"] = w
        rec["pools"] = pools_of(doc, w)
        rebase = doc["n"] <= rebase_n_max
        rep = move_applicability_report(state, weight_cap=w, rebase=rebase)
        rec["parent"] = {k: v for k, v in rep["parent"].items() if k != "weight_one_logicals"}
        rec["parent"]["weight_one_logicals"] = {
            s: len(v) for s, v in rep["parent"].get("weight_one_logicals", {}).items()
        }
        fams = {}
        for fam, e in rep["families"].items():
            if not e.get("enabled", True):
                fams[fam] = {"enabled": False}
                continue
            reasons = dict(e.get("refusals") or {})
            reasons.update(e.get("screens") or {})
            fams[fam] = {
                "enabled": True,
                "domain": e["domain"],
                "derived": e["derived"],
                "usable": e["usable"],
                "blocking": e.get("blocking"),
                "best_child_w": e.get("best_child_w"),
                "refusals": e.get("refusals") or {},
                "screens": e.get("screens") or {},
            }
        rec["families"] = fams
        rec["rebase_asked"] = rebase
    except Exception as exc:  # noqa: BLE001 - one bad parent must not end the run
        rec["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    rec["seconds"] = round(time.time() - t0, 1)
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True, help="durable output directory (under research/candidates/)")
    ap.add_argument("--codes", default=os.path.join(ROOT, "codes"))
    ap.add_argument("--n-max", type=int, default=None, help="skip parents above this n")
    ap.add_argument("--n-min", type=int, default=None, help="skip parents below this n")
    ap.add_argument("--rebase-n-max", type=int, default=100, help="ask for P-REBASE only up to this n")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    ap.add_argument("--slugs", nargs="*", default=None, help="only these parents")
    ap.add_argument("--largest-first", action="store_true", help="schedule the largest parents first")
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    out_path = os.path.join(args.out, "reports.jsonl")
    log_path = os.path.join(args.out, "run.log")

    def log(msg):
        print(msg, flush=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(msg + "\n")

    done = set()
    if os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line)["slug"])
                except (ValueError, KeyError):
                    continue
    todo = [
        (s, p)
        for s, p in parents(args.codes, args.n_max, set(args.slugs) if args.slugs else None, args.n_min)
        if s not in done
    ]
    if args.largest_first:
        todo.sort(key=lambda sp: -json.load(open(sp[1]))["n"])
    log(
        f"direction 8: {len(todo)} parents to run ({len(done)} already in {out_path}), workers={args.workers}, "
        f"rebase up to n={args.rebase_n_max}, code-calculus at {CC}"
    )
    t0 = time.time()
    n_done = 0
    with mp.get_context("spawn").Pool(args.workers) as pool, open(out_path, "a", encoding="utf-8") as out:
        for rec in pool.imap_unordered(one, [(s, p, args.rebase_n_max) for s, p in todo], chunksize=1):
            out.write(json.dumps(rec, sort_keys=True) + "\n")
            out.flush()
            n_done += 1
            if "error" in rec:
                log(f"  {rec['slug']}: ERROR {rec['error']} [{rec['seconds']}s]")
            elif n_done % 25 == 0 or rec["seconds"] > 120:
                usable = {f: e.get("usable") for f, e in rec["families"].items() if e.get("enabled")}
                log(
                    f"  {n_done}/{len(todo)} {rec['slug']} n={rec['n']} [{rec['seconds']}s] "
                    f"usable={usable}  elapsed {time.time() - t0:.0f}s"
                )
    log(f"direction 8 done: {n_done} parents in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
