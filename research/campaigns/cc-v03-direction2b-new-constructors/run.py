#!/usr/bin/env python3
"""Direction-2 extension: enumerate the NEW code-calculus constructors.

Issue #7116 direction 1 asks which constructors fire and whether any child
advances the board. The v0.3.0 fieldnote covered only empty/free/CNOT-SWAP;
this script exercises the constructors added on code-calculus-dev after
v0.3.0: L-PAIR-PARTITION, PP-SCALE, and the nonabelian L-GROUP-ALGEBRA /
L-LIFTED / L-BALANCED generalizations.

Phase A (yield): enumerate a deterministic parameter grid, record for every
parameter tuple whether the constructor derives and the resulting (n, k, w).

Phase B (gate): for derived codes with w <= 4 and k >= 2, build a submission
via research/kit/submit.make_submission (which runs the witness search),
stage it with spec= and pass it through the trusted gate. No candidate is
submitted to the board; passing candidates are only reported.

Distances are witness-backed upper bounds. Nothing here is certified.
"""
import argparse
import collections
import itertools
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
CC = os.environ.get(
    "CODE_CALCULUS_PATH",
    "/Users/mathysrennela/GitHub/code-calculus-dev-7116-ext",
)
for _p in (CC, ROOT, os.path.join(ROOT, "verify"),
           os.path.join(ROOT, "research", "kit")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from machine.constructors import construct, pair_partition_code  # noqa: E402
from machine.priced_calculus import NoDerivation, Malformed  # noqa: E402


# --------------------------------------------------------------------------
# parameter grid
# --------------------------------------------------------------------------
S3 = {"generators": [[1, 2, 0], [1, 0, 2]]}


def dihedral_table(m):
    n = 2 * m
    table = [[0] * n for _ in range(n)]
    for a in range(n):
        ra, sa = a % m, a // m
        for b in range(n):
            rb, sb = b % m, b // m
            r = (ra + rb) % m if sa == 0 else (ra - rb) % m
            table[a][b] = (sa ^ sb) * m + r
    return table


D3 = {"table": dihedral_table(3)}
D4 = {"table": dihedral_table(4)}
D5 = {"table": dihedral_table(5)}
Q8 = {"table": [[0, 1, 2, 3, 4, 5, 6, 7],
                [1, 0, 3, 2, 5, 4, 7, 6],
                [2, 3, 0, 1, 6, 7, 4, 5],
                [3, 2, 1, 0, 7, 6, 5, 4],
                [4, 5, 6, 7, 0, 1, 2, 3],
                [5, 4, 7, 6, 1, 0, 3, 2],
                [6, 7, 4, 5, 2, 3, 0, 1],
                [7, 6, 5, 4, 3, 2, 1, 0]]}


def pair_partition_cases():
    cases = []
    # CPM pattern, J=1 and J=2.
    for p in (3, 4, 5, 7, 8, 9, 11, 13):
        for L in (2, 4, 6):
            bx = [[0] * L + [1] * L]
            bz = [[0] * L + [1] * L]
            cases.append((f"cpm-p{p}-L{L}",
                          {"constructor": "L-PAIR-PARTITION", "p": p,
                           "blocks_x": bx, "blocks_z": bz}))
    # APM pattern with unit slopes and an explicit pair partition.
    for p in (5, 7, 11, 13):
        for a, b in ((2, 2), (2, 3), (3, 2), (3, 3)):
            if __import__("math").gcd(a, p) != 1 or __import__("math").gcd(b, p) != 1:
                continue
            bx = [[(a, 1), (a, 1), (a, 0), (a, 0)]]
            bz = [[(b, 1), (b, 1), (b, 0), (b, 0)]]
            cases.append((f"apm-p{p}-a{a}-b{b}",
                          {"constructor": "L-PAIR-PARTITION", "p": p,
                           "blocks_x": bx, "blocks_z": bz,
                           "pair_partition": [(0, 1), (2, 3)]}))
    return cases


def pp_scale_cases():
    cases = []
    base_bx = [[(2, 2), (2, 2), (2, 0), (2, 0)]]
    base_bz = [[(2, 2), (2, 2), (2, 0), (2, 0)]]
    try:
        c0, _ = pair_partition_code(3, base_bx, base_bz)
    except Exception:
        return cases
    for P in (5, 7, 11, 13, 16, 17, 19, 23, 25, 29, 31):
        root = P - 1  # (P-1)^2 = 1 mod P for every P >= 2
        bundle = {
            "P0": 3, "orders_e": [2], "roots_r0": [2], "roots_r": [root],
            "shape_x": (1, 4), "shape_z": (1, 4),
            "Q_x": [[1], [1], [1], [1]], "Q_z": [[1], [1], [1], [1]],
            "G_x": [[1], [1], [0], [0]], "G_z": [[1], [1], [0], [0]],
            "theta_x": [2], "theta_z": [2],
            "blocks_x0": base_bx, "blocks_z0": base_bz,
            "pair_partition": [(0, 1), (2, 3)],
        }
        cases.append((f"pp-P{P}", {"constructor": "PP-SCALE", "state": c0,
                                   "P": P, "bundle": bundle}))
    return cases


def group_algebra_cases():
    cases = []
    for gname, group in (("S3", S3), ("D3", D3), ("D4", D4), ("D5", D5), ("Q8", Q8)):
        # small subsets {identity, element} for a and b; try element indices 1,2
        for ai in (1, 2):
            for bi in (1, 2):
                cases.append((f"lga-{gname}-a{ai}-b{bi}",
                              {"constructor": "L-GROUP-ALGEBRA", "group": group,
                               "a": [0, ai], "b": [0, bi]}))
    return cases


def lifted_cases():
    cases = []
    for gname, group in (("S3", S3), ("D4", D4)):
        cases.append((f"lift-{gname}-1x1",
                      {"constructor": "L-LIFTED", "group": group,
                       "A": [[[0, 1]]], "B": [[[0, 1]]]}))
        if gname == "D4":
            cases.append(("lift-D4-2x2",
                          {"constructor": "L-LIFTED", "group": D4,
                           "A": [[[0, 1], [4]], [[2], [0, 5]]],
                           "B": [[[0, 4], [1, 6]]]}))
    return cases


def balanced_cases():
    from machine.constructors import balanced_product  # noqa: F401
    cases = []
    ell = 6
    # S3 regular actions, mirroring the test vector.
    table = [[S3["generators"][0][S3["generators"][0].index(0)]]]  # placeholder
    # Build the Cayley table from generator permutations.
    import machine.constructors as cc
    info = cc._group_spec(S3)
    gt = info["table"]
    from machine.constructors import _left_lift_rows, _right_lift_rows
    la = _left_lift_rows(frozenset({0, 1}), info)
    rb = _right_lift_rows(frozenset({0, 3}), info)
    H1 = [[(la[r] >> c) & 1 for c in range(ell)] for r in range(ell)]
    H2 = [[(rb[r] >> c) & 1 for c in range(ell)] for r in range(ell)]
    right = [[gt[x][g] for x in range(ell)] for g in range(ell)]
    left = [[gt[g][y] for y in range(ell)] for g in range(ell)]
    cases.append(("balanced-S3-regular",
                  {"constructor": "L-BALANCED", "group": S3, "H1": H1,
                   "action1": {"rows": right, "cols": right}, "H2": H2,
                   "action2": {"rows": left, "cols": left}}))
    return cases


def enumerate_cases():
    out = []
    out.extend(pair_partition_cases())
    out.extend(pp_scale_cases())
    out.extend(group_algebra_cases())
    out.extend(lifted_cases())
    out.extend(balanced_cases())
    return out


# --------------------------------------------------------------------------
# phases
# --------------------------------------------------------------------------
def describe(res):
    st = res["state"]
    w = max([len(r.support) for r in st.rows] + [0])
    return {"n": res["n"], "k": res["k"], "w": w,
            "dropped_rows": res["dropped_rows"]}


def phase_a(out_path):
    records = []
    for label, spec in enumerate_cases():
        params = {}
        for k, v in spec.items():
            if k == "constructor":
                continue
            if hasattr(v, "Q") and hasattr(v, "rows"):  # CodeState factor
                params[k] = {"n": len(v.Q), "k": getattr(v, "k", lambda: None)()}
            else:
                params[k] = v
        rec = {"label": label, "constructor": spec["constructor"],
               "params": params}
        started = time.time()
        try:
            res = construct(spec)
            res["state"].validate()
            rec.update(describe(res))
            rec["derived"] = True
            rec["state"] = res["state"]
        except (NoDerivation, Malformed, Exception) as exc:
            rec["derived"] = False
            rec["reason"] = "%s: %s" % (type(exc).__name__, str(exc)[:160])
        rec["seconds"] = round(time.time() - started, 4)
        records.append(rec)
        print(f"  {label}: {rec.get('n')} {rec.get('k')} {rec.get('w')} "
              f"derived={rec['derived']} {rec.get('reason','')[:60]}", flush=True)

    summary = collections.Counter()
    for r in records:
        summary[(r["constructor"], "tried")] += 1
        summary[(r["constructor"], "derived")] += bool(r["derived"])
        if r["derived"] and r["w"] <= 4 and r["k"] >= 2:
            summary[(r["constructor"], "w4_k2")] += 1
    with open(out_path, "w") as fh:
        json.dump({
            "summary": {f"{c}|{k}": v for (c, k), v in sorted(summary.items())},
            "records": [{k: v for k, v in r.items() if k != "state"}
                        for r in records],
        }, fh, indent=2)
    # Keep derived states in memory for phase B when invoked in the same run.
    return records


def state_check_matrices(state):
    n = state.n()
    HX = [[0] * n for _ in state.sector_rows("X")]
    HZ = [[0] * n for _ in state.sector_rows("Z")]
    qidx = {q: i for i, q in enumerate(sorted(state.Q))}
    for i, row in enumerate(state.sector_rows("X")):
        for q in row.support:
            HX[i][qidx[q]] = 1
    for i, row in enumerate(state.sector_rows("Z")):
        for q in row.support:
            HZ[i][qidx[q]] = 1
    return HX, HZ


def phase_b(records, out_path, trials=8000, cap=8):
    from submit import make_submission, save_submission
    from coordination import unique_path, gate_and_record, staging_dir

    staging = staging_dir()
    os.makedirs(staging, exist_ok=True)
    from prescreen import block_structure
    candidates = []
    for r in records:
        if not (r["derived"] and r["w"] <= 4 and r["k"] >= 2):
            continue
        HX, HZ = state_check_matrices(r["state"])
        structure = block_structure(HX, HZ)
        r["connected"] = structure["connected"]
        r["structure"] = structure
        if not structure["connected"]:
            continue
        candidates.append(r)
    # Prefer small n, then lower w, then higher k.
    candidates.sort(key=lambda r: (r["n"], r["w"], -r["k"]))
    candidates = candidates[:cap]
    out = []
    for rec in candidates:
        entry = {"label": rec["label"], "constructor": rec["constructor"],
                 "n": rec["n"], "k": rec["k"], "w": rec["w"]}
        try:
            HX, HZ = state_check_matrices(rec["state"])
            params = {k: v for k, v in rec["params"].items()
                      if k not in ("state",)}
            doc = make_submission(
                HX, HZ,
                name=f"[[{rec['n']},{rec['k']},?]] {rec['constructor']}",
                construction=f"code-calculus dev constructor {rec['constructor']} "
                             f"({rec['label']})",
                authors=["mathysrennela"], family="code-calculus",
                confidence="upper_bound", trials=trials, seed=0,
            )
            path = unique_path(os.path.join(
                staging, f"{rec['n']}-{rec['k']}-{rec['constructor']}.json"), doc)
            save_submission(doc, path, preflight=False, spec={
                "constructor": rec["constructor"], "params": params,
            })
            verdict, _ = gate_and_record(path)
            entry.update({
                "distance": doc.get("distance"),
                "gate_passed": verdict.get("passed"),
                "board_advancing": (verdict.get("gates", {})
                                    .get("novelty", {}).get("board_advancing")),
                "gate": verdict,
                "path": path,
            })
            print(f"  GATE {rec['label']}: passed={verdict.get('passed')} "
                  f"advancing={(verdict.get('gates',{}).get('novelty',{}).get('board_advancing'))}",
                  flush=True)
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            print(f"  REFUSE {rec['label']}: {entry['error'][:120]}", flush=True)
        out.append(entry)
    with open(out_path, "w") as fh:
        json.dump(out, fh, indent=2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=("a", "b", "both"), default="both")
    ap.add_argument("--out-a", default=os.path.join(_HERE, "yield.json"))
    ap.add_argument("--out-b", default=os.path.join(_HERE, "gate.json"))
    ap.add_argument("--trials", type=int, default=8000)
    ap.add_argument("--cap", type=int, default=8)
    args = ap.parse_args()

    records = None
    if args.phase in ("a", "both"):
        records = phase_a(args.out_a)
    if args.phase in ("b", "both"):
        if records is None:
            raise SystemExit("phase b needs phase a in the same invocation")
        phase_b(records, args.out_b, args.trials, args.cap)


if __name__ == "__main__":
    main()
