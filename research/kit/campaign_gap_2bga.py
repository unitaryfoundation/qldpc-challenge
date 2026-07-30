"""Phase 1 campaign: GAP-enhanced 2BGA enumeration (orders 60-120).

Systematically enumerates non-abelian groups of order 60-120 via GAP,
builds 2BGA codes with both random and conjugacy-class-invariant supports,
screens them with the surrogate, and stages winners for validation.

Usage:
    uv run python research/kit/campaign_gap_2bga.py [--orders 60-120] [--trials 400]
"""
import argparse
import json
import os
import sys
import time

import numpy as np

# Add kit and verify to path
_KIT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _KIT)
sys.path.insert(0, os.path.join(_KIT, "..", "..", "verify"))
sys.path.insert(0, os.path.join(_KIT, ".."))

from gap_bridge import all_groups_of_order, gap_available, conjugacy_class_supports  # noqa: E402
from group_algebra import build_2bga  # noqa: E402
from css import compute_k, verify_css  # noqa: E402
from surrogate import distance_rand  # noqa: E402
from search import (screen, pareto_frontier, fingerprint, efficiency,  # noqa: E402
                    load_skip_fingerprints, update_leaderboard)
from submit import make_submission, save_submission  # noqa: E402


def parse_order_range(s):
    """Parse '60-120' or '60,80,100' into a list of ints."""
    if "-" in s:
        lo, hi = s.split("-", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(x) for x in s.split(",")]


def _generate_candidates(orders, support_weights, num_random, num_conj, seed):
    """Generate 2BGA candidates from GAP-enumerated groups."""
    groups = all_groups_of_order(*orders)
    if not groups:
        print("No groups found (GAP may not be available).")
        return

    rng = np.random.default_rng(seed)
    n_generated = 0

    for g_info in groups:
        order = g_info["order"]
        cayley = np.array(g_info["cayley_table"], dtype=np.int64)
        desc = g_info["description"]
        abelian = g_info["abelian"]

        for w in support_weights:
            if w >= order:
                continue

            # Random supports
            for _ in range(num_random):
                a = sorted(int(x) for x in rng.choice(order, size=w, replace=False))
                b = sorted(int(x) for x in rng.choice(order, size=w, replace=False))
                try:
                    HX, HZ = build_2bga(cayley, a, b)
                except Exception:
                    continue
                spec = {
                    "family": "2bga-gap",
                    "group_order": order,
                    "group_description": desc,
                    "support_type": "random",
                    "weight": w,
                    "a": a, "b": b,
                }
                yield (spec, HX, HZ)
                n_generated += 1

            # Conjugacy-class-invariant supports (non-abelian only)
            if not abelian and num_conj > 0:
                for support_a, classes_a in conjugacy_class_supports(cayley, w, rng):
                    for support_b, classes_b in conjugacy_class_supports(cayley, w, rng):
                        try:
                            HX, HZ = build_2bga(cayley, support_a, support_b)
                        except Exception:
                            continue
                        spec = {
                            "family": "2bga-gap",
                            "group_order": order,
                            "group_description": desc,
                            "support_type": "conj-class",
                            "weight": w,
                            "a": support_a, "b": support_b,
                            "classes_a": classes_a, "classes_b": classes_b,
                        }
                        yield (spec, HX, HZ)
                        n_generated += 1
                        if n_generated >= (num_random + num_conj) * len(orders):
                            return


def main():
    parser = argparse.ArgumentParser(description="Phase 1: GAP 2BGA enumeration")
    parser.add_argument("--orders", default="60-120",
                        help="Group order range (e.g. '60-120' or '60,80,100')")
    parser.add_argument("--weights", default="4,5,6",
                        help="Support weights (comma-separated)")
    parser.add_argument("--random-per-group", type=int, default=20,
                        help="Random supports per group per weight")
    parser.add_argument("--conj-per-group", type=int, default=10,
                        help="Conjugacy-class supports per group per weight")
    parser.add_argument("--trials", type=int, default=400,
                        help="Surrogate trials per candidate")
    parser.add_argument("--seed", type=int, default=42,
                        help="RNG seed")
    parser.add_argument("--min-k", type=int, default=4,
                        help="Minimum k to keep")
    parser.add_argument("--min-d", type=int, default=4,
                        help="Minimum d to keep")
    parser.add_argument("--output", default=None,
                        help="Output JSON path for leaderboard")
    parser.add_argument("--validate-top", type=int, default=0,
                        help="Validate top N candidates with the gate")
    parser.add_argument("--skip-fingerprint-file", default=None,
                        help="JSON/text file of fingerprints to skip")
    parser.add_argument("--checkpoint-file", default=None,
                        help="JSON file used to checkpoint processed fingerprints")
    args = parser.parse_args()

    orders = parse_order_range(args.orders)
    weights = [int(w) for w in args.weights.split(",")]

    print(f"=== Phase 1: GAP 2BGA enumeration ===")
    print(f"Orders: {orders[0]}-{orders[-1]} ({len(orders)} orders)")
    print(f"Weights: {weights}")
    print(f"Random supports/group/weight: {args.random_per_group}")
    print(f"Conj-class supports/group/weight: {args.conj_per_group}")
    print(f"Surrogate trials: {args.trials}")
    print(f"GAP available: {gap_available()}")
    print()

    t0 = time.time()

    # Generate and screen candidates
    candidates = _generate_candidates(
        orders, weights,
        args.random_per_group, args.conj_per_group,
        args.seed
    )

    records = screen(
        candidates,
        min_k=args.min_k,
        min_d=args.min_d,
        trials=args.trials,
        seed=args.seed,
        verbose=True,
        skip_fingerprints=load_skip_fingerprints(args.skip_fingerprint_file),
        checkpoint_path=args.checkpoint_file,
    )

    elapsed = time.time() - t0
    print(f"\n=== Screening complete: {len(records)} codes with k>={args.min_k}, d>={args.min_d} ===")
    print(f"Time: {elapsed:.1f}s")

    if records:
        print(f"\nTop 10 by efficiency:")
        for r in records[:10]:
            print(f"  [[{r['n']},{r['k']},{r['d']}]]  eff={r['efficiency']:.3f}  "
                  f"{r['spec'].get('group_description', '')}  "
                  f"w={r['spec'].get('weight', '?')}  "
                  f"{r['spec'].get('support_type', '')}")

        front = pareto_frontier(records)
        params = sorted({(r["n"], r["k"], r["d"]) for r in front})
        print(f"\nPareto frontier ({len(params)} distinct params):")
        for n, k, d in params[:15]:
            print(f"  [[{n},{k},{d}]]  eff={efficiency(n,k,d):.3f}")

    # Save leaderboard
    output = args.output or os.path.join(
        _KIT, "..", "candidates", f"gap_2bga_orders_{orders[0]}-{orders[-1]}.json"
    )
    os.makedirs(os.path.dirname(output), exist_ok=True)
    merged = update_leaderboard(output, records) if os.path.exists(output) else records
    with open(output, "w") as f:
        json.dump(merged, f, indent=2)
    print(f"\nLeaderboard saved to {output} ({len(merged)} records)")

    # Validate top candidates
    if args.validate_top > 0 and records:
        print(f"\n=== Validating top {args.validate_top} candidates ===")
        validated = 0
        for r in records[:args.validate_top]:
            spec = r["spec"]
            cayley = np.array(
                all_groups_of_order(spec["group_order"])[0]["cayley_table"],
                dtype=np.int64
            ) if all_groups_of_order(spec["group_order"]) else None
            if cayley is None:
                continue
            try:
                HX, HZ = build_2bga(cayley, spec["a"], spec["b"])
            except Exception:
                continue

            doc = make_submission(
                HX, HZ,
                name=f"[[{r['n']},{r['k']},{r['d']}]] GAP 2BGA {spec['group_description']}",
                construction=f"2BGA on {spec['group_description']}, "
                             f"weight-{spec['weight']} {spec['support_type']} supports",
                authors=["autoresearch-gap"],
                family="generalized-bicycle",
                confidence="upper_bound",
                trials=8000,
            )
            vpath = os.path.join(_KIT, "..", "candidates",
                                 f"{r['n']}-{r['k']}-{r['d']}_gap.json")
            errs = save_submission(doc, vpath)
            if not errs:
                # Run the gate
                import subprocess
                gate = os.path.join(_KIT, "..", "..", "verify", "validate_candidate.py")
                result = subprocess.run(
                    [sys.executable, gate, vpath],
                    capture_output=True, text=True
                )
                if "passed: true" in result.stdout:
                    print(f"  PASSED: [[{r['n']},{r['k']},{r['d']}]]")
                    validated += 1
                else:
                    print(f"  FAILED: [[{r['n']},{r['k']},{r['d']}]]")
            else:
                print(f"  SCHEMA ERRORS: {errs}")

        print(f"\n{validated}/{args.validate_top} passed validation")


if __name__ == "__main__":
    main()
