#!/usr/bin/env python3
"""Prune code-calculus single-step moves by where their children must land (issue #4478, direction 6).

Direction 6 of issue #4478 asks whether a move can be skipped before any
distance search by computing the (n, k, d, w) region its child must land in
and checking that region against the board. This script answers it for the
three moves code-calculus v0.1 found productive. For every CSS board parent with
n <= N it enumerates C-DELETE-CHECK, E-PEEL, and E-PUNCTURE with the library's
own semantics (an independent displayed row; a qubit touching exactly one row of
the chosen sector, the opposite rows losing the qubit; a qubit and every row
touching it), applies the gate's structural refusals a child would meet (a
dependent display, a bare qubit, a disconnected Tanner graph, k = 0), computes
the child's exact (n', k', w') from ranks alone, and asks whether the optimistic
child (n', k', d_parent, w') is dominated on the current board in the strictest
cell it could land in (the parent's weight class recomputed from w', and
local-2d-single when the parent carries a layout). A dominated optimistic child
cannot be board-advancing at any real distance, since a child's distance never
exceeds its parent's under these moves, so the move can be skipped without a
witness search. The counts it prints are the pruning the filter buys.

Given the frontier record of a gated sweep (one JSON object per line with the
child's n, k, w, its parent slug, and the gate's board_advancing), it also
reports how the filter would have fared on children the gate actually judged:
a child pruned here and board-advancing there is a soundness failure unless the
board moved in between.

    uv run --frozen python research/audits/cc_reachability.py --n-cap 120 \
        --out research/audits/cc_reachability-<date>.json [--sweep <frontier.jsonl>] [--list]

The result of 2026-11-05 is research/audits/cc_reachability-2026-11-05.json and
its reading is in fieldnotes/2026-11-05-code-calculus-v0p1-directions-1-and-6.md.
"""

import argparse
import collections
import json
import os
import sys
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in ("verify", os.path.join("research", "kit")):
    _full = os.path.join(ROOT, _p)
    if _full not in sys.path:
        sys.path.insert(0, _full)
import gf2  # noqa: E402
import qldpc_verify as V  # noqa: E402
import validate_candidate as VC  # noqa: E402

W_ORDER = VC._WEIGHT_ORDER
L_ORDER = VC._LOCAL_ORDER


def weight_class(w):
    return "weight-4" if w <= 4 else "weight-6" if w <= 6 else "weight-8" if w <= 8 else "weight-9plus"


def rank(rows, n):
    if not rows:
        return 0
    M = np.zeros((len(rows), n), dtype=np.int8)
    for i, r in enumerate(rows):
        M[i, list(r)] = 1
    return gf2.rank(M)


def connected(rows, n):
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for row in rows:
        r = list(row)
        for q in r[1:]:
            ra, rb = find(r[0]), find(q)
            if ra != rb:
                parent[ra] = rb
    return len({find(q) for q in range(n)}) == 1


def dominated(point, cell, board):
    n, k, d, w = point
    wc, lc = cell
    for b in board:
        if b["code_type"] != "CSS" or b.get("w") is None:
            continue
        if W_ORDER.get(b["weight_class"], 9) > W_ORDER.get(wc, 9) or L_ORDER.get(b["locality_class"], 9) > L_ORDER.get(
            lc, 9
        ):
            continue
        if (
            b["n"] <= n
            and b["k"] >= k
            and b["d"] >= d
            and b["w"] <= w
            and (b["n"] < n or b["k"] > k or b["d"] > d or b["w"] < w)
        ):
            return True
    return False


def relabel(rows, q):
    """Drop qubit q from every row and shift the indices above it down."""
    out = []
    for r in rows:
        out.append(tuple(x - 1 if x > q else x for x in r if x != q))
    return out


def children(doc, rep):
    """Yield (move, n', k', w', note) for every derivable single-step child."""
    n = doc["n"]
    X = [tuple(sorted(r)) for r in doc["checks"]["X"]]
    Z = [tuple(sorted(r)) for r in doc["checks"]["Z"]]
    rx, rz = rank(X, n), rank(Z, n)
    k = n - rx - rz
    assert k == doc["k"], (doc["n"], k, doc["k"])
    indep = {"X": rx == len(X), "Z": rz == len(Z)}
    # C-DELETE-CHECK: an independent displayed row
    for sector, rows, other in (("X", X, Z), ("Z", Z, X)):
        for i, r in enumerate(rows):
            rest = rows[:i] + rows[i + 1 :]
            if not indep[sector] and rank(rest, n) == rank(rows, n):
                yield ("C-DELETE-CHECK", None, "dependent row")
                continue
            allrows = rest + other
            w = max((len(x) for x in allrows), default=0)
            touched = set()
            for x in allrows:
                touched.update(x)
            if len(touched) < n:
                yield ("C-DELETE-CHECK", None, "bare qubit")
                continue
            if not connected(allrows, n):
                yield ("C-DELETE-CHECK", None, "disconnected")
                continue
            yield ("C-DELETE-CHECK", (n, k + 1, w), "")
    # E-PEEL: q with exactly one row in the sector; that row goes, opposite rows lose q
    for sector, rows, other in (("X", X, Z), ("Z", Z, X)):
        for q in range(n):
            touching = [i for i, r in enumerate(rows) if q in r]
            if len(touching) != 1:
                continue
            if any(r == (q,) for r in other):
                yield ("E-PEEL", None, "zero-check guard")
                continue
            rest = rows[: touching[0]] + rows[touching[0] + 1 :]
            new_rows = relabel(rest, q)
            new_other = relabel(other, q)
            n2 = n - 1
            r1, r2 = rank(new_rows, n2), rank(new_other, n2)
            if r1 < len(new_rows) or r2 < len(new_other):
                yield ("E-PEEL", None, "dependent display")
                continue
            allrows = new_rows + new_other
            touched = set()
            for x in allrows:
                touched.update(x)
            if len(touched) < n2:
                yield ("E-PEEL", None, "bare qubit")
                continue
            if not connected(allrows, n2):
                yield ("E-PEEL", None, "disconnected")
                continue
            k2 = n2 - r1 - r2
            w = max((len(x) for x in allrows), default=0)
            yield ("E-PEEL", (n2, k2, w), "")
    # E-PUNCTURE: remove q and every row touching it
    for q in range(n):
        keepX = relabel([r for r in X if q not in r], q)
        keepZ = relabel([r for r in Z if q not in r], q)
        n2 = n - 1
        allrows = keepX + keepZ
        if not allrows:
            yield ("E-PUNCTURE", None, "no rows left")
            continue
        r1, r2 = rank(keepX, n2), rank(keepZ, n2)
        if r1 < len(keepX) or r2 < len(keepZ):
            yield ("E-PUNCTURE", None, "dependent display")
            continue
        touched = set()
        for x in allrows:
            touched.update(x)
        if len(touched) < n2:
            yield ("E-PUNCTURE", None, "bare qubit")
            continue
        if not connected(allrows, n2):
            yield ("E-PUNCTURE", None, "disconnected")
            continue
        k2 = n2 - r1 - r2
        if k2 < 1:
            yield ("E-PUNCTURE", None, "k = 0")
            continue
        w = max((len(x) for x in allrows), default=0)
        yield ("E-PUNCTURE", (n2, k2, w), "")


def run(n_cap, sweep=None, keep_list=False):
    """Return the pruning record for parents with n <= n_cap."""
    t0 = time.time()
    board = VC._board_entries()
    reports = {e["slug"]: e for e in V.board_reports(os.path.join(ROOT, "codes"))}
    parents = []
    for slug, e in reports.items():
        doc, rep = e["doc"], e["report"]
        if not doc or not rep or not rep.get("ok") or doc.get("code_type", "CSS") != "CSS":
            continue
        if doc["n"] > n_cap:
            continue
        parents.append((slug, doc, rep))
    print(
        f"{len(parents)} CSS parents with n <= {n_cap}; board rows {len(board)}; loaded in {time.time() - t0:.1f}s",
        file=sys.stderr,
        flush=True,
    )
    counts = collections.defaultdict(collections.Counter)
    refused = collections.defaultdict(collections.Counter)
    remaining = []
    per_parent = []
    done = 0
    for slug, doc, rep in parents:
        comp = rep["computed"]
        d = doc["distance"]["d"]
        laid = comp.get("locality_class", "unrestricted") != "unrestricted"
        strict_loc = "local-2d-single" if laid else "unrestricted"
        left = collections.Counter()
        counts_here = collections.Counter()
        for move, child, note in children(doc, rep):
            if child is None:
                refused[move][note] += 1
                counts[move]["refused"] += 1
                continue
            n2, k2, w2 = child
            counts[move]["derived"] += 1
            counts_here[move] += 1
            cell = (weight_class(w2), strict_loc)
            if dominated((n2, k2, d, w2), cell, board):
                counts[move]["pruned"] += 1
            else:
                counts[move]["remaining"] += 1
                left[move] += 1
                remaining.append(
                    {"parent": slug, "move": move, "n": n2, "k": k2, "d_max": d, "w": w2, "cell": list(cell)}
                )
        per_parent.append(
            {"parent": slug, "n": doc["n"], "remaining": dict(left), "derived": sum(counts_here.values())}
        )
        done += 1
        if done % 200 == 0:
            print(f"  {done}/{len(parents)} parents, {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
    # soundness against the gated sweep children
    sound = {
        "checked": 0,
        "pruned_and_advancing": 0,
        "pruned_and_not_advancing": 0,
        "kept_and_advancing": 0,
        "kept_and_not_advancing": 0,
        "parent_missing": 0,
        "examples": [],
    }
    if sweep and os.path.exists(sweep):
        for line in open(sweep, encoding="utf-8"):
            r = json.loads(line)
            if r.get("board_advancing") is None:
                continue
            pe = reports.get(r["parent"])
            if not pe or not pe["doc"]:
                sound["parent_missing"] += 1
                continue
            pdoc, prep = pe["doc"], pe["report"]
            laid = prep["computed"].get("locality_class", "unrestricted") != "unrestricted"
            cell = (weight_class(r["w"]), "local-2d-single" if laid else "unrestricted")
            pruned = dominated((r["n"], r["k"], pdoc["distance"]["d"], r["w"]), cell, board)
            sound["checked"] += 1
            key = (
                ("pruned" if pruned else "kept") + "_and_" + ("advancing" if r["board_advancing"] else "not_advancing")
            )
            sound[key] += 1
            if pruned and r["board_advancing"] and len(sound["examples"]) < 10:
                sound["examples"].append(
                    {
                        "file": os.path.basename(r["file"]),
                        "parent": r["parent"],
                        "point": [r["n"], r["k"], r["d"], r["w"]],
                        "cell": r["cell"],
                    }
                )
    by_cell = collections.Counter((r["move"], r["cell"][0], r["cell"][1]) for r in remaining)
    by_parent_d = collections.Counter(r["d_max"] for r in remaining)
    derived_parents = sum(1 for p in per_parent if p["derived"])
    out = {
        "date": time.strftime("%Y-%m-%d"),
        "n_cap": n_cap,
        "parents": len(parents),
        "parents_with_a_derivable_child": derived_parents,
        "parents_with_nothing_remaining": sum(1 for p in per_parent if not p["remaining"]),
        "parents_pruned_to_nothing": sum(1 for p in per_parent if p["derived"] and not p["remaining"]),
        "seconds": round(time.time() - t0, 1),
        "counts": {m: dict(c) for m, c in counts.items()},
        "refused": {m: dict(c) for m, c in refused.items()},
        "remaining_total": len(remaining),
        "remaining_by_move_and_cell": {f"{m} {wc} {lc}": c for (m, wc, lc), c in by_cell.most_common()},
        "remaining_by_parent_d": {str(d): c for d, c in sorted(by_parent_d.items())},
        "soundness_vs_sweep": sound if sweep else None,
    }
    if keep_list:
        out["remaining"] = remaining
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--n-cap", type=int, default=120, help="largest parent blocklength (default 120)")
    ap.add_argument("--out", default=None, help="write the record here as JSON")
    ap.add_argument(
        "--sweep",
        default=None,
        help="frontier record of a gated sweep (JSON lines with n, k, w, parent, board_advancing)",
    )
    ap.add_argument("--list", action="store_true", help="keep every remaining child in the record")
    args = ap.parse_args(argv)
    out = run(args.n_cap, sweep=args.sweep, keep_list=args.list)
    text = json.dumps({k: v for k, v in out.items() if k != "remaining"}, indent=1)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1)
            f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
