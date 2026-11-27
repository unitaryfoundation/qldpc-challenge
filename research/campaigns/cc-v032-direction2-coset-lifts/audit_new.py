#!/usr/bin/env python3
"""Decide whether a coset lift the certificate called new is permutation-equivalent to a regular lift.

The certificate of the full generated display (run.keys_of_full) separates
constructions, not codes: two generating sets of one code are different
graphs. So a class run.py reports as new is audited here against every
regular 1x2 lift of the same block count with the repository's permutation
audit (research/audits/permutation_audit.decide: basis-independent
invariants, a Tanner isomorphism search, then a light-vector enumeration),
which decides row-space equivalence up to a qubit permutation. A class the
audit cannot pair with any regular lift is new as a code; one it pairs is a
regular lift in a different presentation.

Run:  CODE_CALCULUS_PATH=<code-calculus at v0.3.2> uv run --extra research python \
      research/campaigns/cc-v032-direction2-coset-lifts/audit_new.py --new <out>/new_classes.json \
      --out <out>/audit.json [--budget 1000000] [--max 200]
"""

import argparse
import importlib.util
import itertools
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
CC = os.environ.get("CODE_CALCULUS_PATH", os.path.join(os.path.dirname(ROOT), "code-calculus"))
for _p in (
    CC,
    ROOT,
    os.path.join(ROOT, "verify"),
    os.path.join(ROOT, "research", "kit"),
    os.path.join(ROOT, "research", "audits"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np  # noqa: E402
import permutation_audit as PA  # noqa: E402

_spec = importlib.util.spec_from_file_location("coset_run", os.path.join(_HERE, "run.py"))
run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run)


def code_of(group_spec, A, B, subgroup, name):
    n, X, Z = run.full_lift_rows(group_spec, A, B, subgroup)
    sup = lambda masks: [[q for q in range(n) if (m >> q) & 1] for m in masks]  # noqa: E731
    HX = run.QV._matrix(sup(X), n)
    HZ = run.QV._matrix(sup(Z), n)
    doc = {
        "n": n,
        "k": int(n - np.linalg.matrix_rank(HX) - 0),
        "code_type": "CSS",
        "checks": {"X": sup(X), "Z": sup(Z)},
        "distance": {"d": 0},
    }
    return PA.code_from_matrices(name, HX, HZ), doc


def regular_index(order, shape, log):
    """Index every regular 1x2 lift of ``order`` blocks by (n, rank_X, rank_Z, intersection), the cheap invariants."""
    groups = {name: list(orders) for name, orders in run.ABELIAN.items() if int(np.prod(orders)) == order}
    for name in run.NONABELIAN_REGULAR:
        gens, degree = run.GROUPS[name]
        if len(run.closure(gens, degree)) == order:
            groups[name] = run.perm_group_spec(gens, degree)
    index = {}
    seen = set()
    for name, spec in groups.items():
        if isinstance(spec, list):
            elems = list(itertools.product(*[range(o) for o in spec]))
            identity = tuple(0 for _ in spec)
        else:
            elems = sorted(run.closure([tuple(g) for g in spec["generators"]], spec["degree"]))
            identity = tuple(range(spec["degree"]))
        first = run.entries(elems, identity, normalized=True)
        rest = run.entries(elems, identity, normalized=False)
        m, nn = shape
        cells = m * nn - 1
        count = 0
        for a1 in first:
            for ra in itertools.product(rest, repeat=cells):
                A = run._matrix(shape, a1, ra)
                for b1 in first:
                    for rb in itertools.product(rest, repeat=cells):
                        B = run._matrix(shape, b1, rb)
                        _, cert = run.keys_of_full(spec, A, B, None)
                        if cert in seen:
                            continue
                        seen.add(cert)
                        code, doc = code_of(spec, A, B, None, f"regular-{name}-{len(seen)}")
                        inv = PA.invariants(code)
                        key = (inv["n"], inv["rank_X"], inv["rank_Z"], inv["intersection"])
                        index.setdefault(key, []).append((name, A, B, code, doc, inv))
                        count += 1
        log(f"  regular lifts over {name}: {count} distinct constructions indexed")
    return index


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--new", required=True, help="new_classes.json from run.py")
    ap.add_argument("--out", required=True)
    ap.add_argument("--budget", type=int, default=10**6, help="light-vector budget per pair")
    ap.add_argument("--max", type=int, default=0, help="audit at most this many classes (0 = all)")
    ap.add_argument("--shape", default="1x2")
    args = ap.parse_args(argv)
    shape = tuple(int(x) for x in args.shape.split("x"))
    with open(args.new, encoding="utf-8") as f:
        new = json.load(f)
    new = {s: r for s, r in new.items() if tuple(r["shape"]) == shape}
    if args.max:
        new = dict(list(new.items())[: args.max])

    def log(msg):
        print(msg, flush=True)

    t0 = time.time()
    indexes = {}
    results = []
    for sig, rec in new.items():
        order = rec["index"]
        if order not in indexes:
            log(f"indexing the regular {shape[0]}x{shape[1]} lifts of {order} blocks ...")
            indexes[order] = regular_index(order, shape, log)
        spec = run.perm_group_spec([tuple(g) for g in rec["generators"]], rec["degree"])
        code, doc = code_of(spec, rec["A"], rec["B"], rec["subgroup"], f"coset-{rec['group']}-{sig}")
        inv = PA.invariants(code)
        key = (inv["n"], inv["rank_X"], inv["rank_Z"], inv["intersection"])
        candidates = [c for c in indexes[order].get(key, []) if PA.invariants_separate(inv, c[5]) is None]
        row = {
            "sig": sig,
            **{k: rec[k] for k in ("group", "subgroup_order", "index", "normal", "n", "k", "w")},
            "candidates_after_invariants": len(candidates),
            "verdict": "new (no regular lift shares its invariants)" if not candidates else None,
        }
        t1 = time.time()
        for name, A, B, rcode, rdoc, rinv in candidates:
            v = PA.decide(code, rcode, doc, rdoc, budget=args.budget)
            if v["verdict"] == "equivalent":
                row.update(
                    verdict="equivalent",
                    to=f"regular lift over {name}",
                    to_A=A,
                    to_B=B,
                    how=v.get("how") or v.get("reason"),
                )
                break
            row.setdefault("pair_verdicts", []).append(v["verdict"])
        if row["verdict"] is None:
            kinds = set(row.get("pair_verdicts", []))
            row["verdict"] = (
                "new (every candidate inequivalent)"
                if kinds == {"inequivalent"}
                else "undecided against some candidate"
            )
        row["seconds"] = round(time.time() - t1, 1)
        results.append(row)
        log(
            f"  {rec['group']}/{order} {'normal' if rec['normal'] else 'non-normal'} "
            f"[[{rec['n']},{rec['k']},?]] w={rec['w']}: "
            f"{len(candidates)} candidates -> {row['verdict']} [{row['seconds']}s]"
        )
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=1, default=str)
    from collections import Counter

    log(f"done in {time.time() - t0:.0f} s: {Counter(r['verdict'].split(' (')[0] for r in results)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
