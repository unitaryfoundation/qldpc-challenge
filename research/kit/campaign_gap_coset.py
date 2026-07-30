"""Phase 2 campaign: GAP-enhanced coset code enumeration (orders 60-200).

Uses GAP's subgroup lattice to systematically enumerate (G, H) pairs with
large |N_G(H)/H|, then builds coset codes and screens them.

Usage:
    uv run python research/kit/campaign_gap_coset.py [--orders 60-200] [--trials 400]
"""
import argparse
import json
import os
import sys
import time

import numpy as np

_KIT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _KIT)
sys.path.insert(0, os.path.join(_KIT, "..", "..", "verify"))
sys.path.insert(0, os.path.join(_KIT, ".."))

from gap_bridge import (all_groups_of_order, gap_available,  # noqa: E402
                         gap_coset_candidates)
from group_algebra import build_2bga  # noqa: E402
from coset import build_coset  # noqa: E402
from css import compute_k, verify_css  # noqa: E402
from surrogate import distance_rand  # noqa: E402
from search import (screen, pareto_frontier, efficiency,  # noqa: E402
                    load_skip_fingerprints, update_leaderboard)
from submit import make_submission, save_submission  # noqa: E402


def parse_order_range(s):
    if "-" in s:
        lo, hi = s.split("-", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(x) for x in s.split(",")]


# Simple/almost-simple group order thresholds to skip (groups where
# coset construction plateaus at d=2 per fieldnote record)
_SKIP_ORDERS_SIMPLE = set()  # populated dynamically from GAP metadata


def _is_simple_or_almost_simple(g_info):
    """Heuristic: skip groups with trivial center and high derived length
    (likely simple or almost-simple)."""
    if g_info.get("center_size", 1) <= 1 and g_info.get("derived_length", 0) >= 3:
        return True
    return False


def _generate_coset_candidates(orders, min_nrm_q, support_weights,
                                num_random, seed):
    """Generate coset-code candidates from GAP subgroup lattices."""
    groups = all_groups_of_order(*orders)
    if not groups:
        return

    rng = np.random.default_rng(seed)
    total_candidates = 0

    for g_info in groups:
        order = g_info["order"]
        desc = g_info["description"]

        # Skip abelian groups (already covered by existing BB samplers)
        if g_info.get("abelian", False):
            continue

        # Skip simple/almost-simple groups per fieldnote
        if _is_simple_or_almost_simple(g_info):
            continue

        # Get subgroup lattice from GAP
        subs = gap_coset_candidates(None, min_nrm_q, order=order, index=g_info["index"])
        if not subs:
            continue

        cayley = np.array(g_info["cayley_table"], dtype=np.int64)

        for sub_info in subs:
            H = sub_info["H_elements"]
            N_G_H = sub_info["N_elements"]
            nrm_q = sub_info["nrm_quotient"]
            m_cosets = order // sub_info["size_H"]
            n = 2 * m_cosets

            valid_weights = [w for w in support_weights if w < m_cosets and w < order]
            if not valid_weights:
                continue

            for w in valid_weights:
                for _ in range(num_random):
                    a = sorted(int(x) for x in rng.choice(order, size=w, replace=False))
                    b_cap = min(w, len(N_G_H))
                    if b_cap < 2:
                        continue
                    b = sorted(int(x) for x in rng.choice(N_G_H, size=b_cap, replace=False))
                    try:
                        HX, HZ = build_coset(cayley, H, a, b, check_normalizer=False)
                    except Exception:
                        continue
                    if HX.shape[1] == 0 or HX.shape[0] == 0:
                        continue

                    spec = {
                        "family": "2bga-coset-gap",
                        "group_order": order,
                        "group_description": desc,
                        "subgroup_size": sub_info["size_H"],
                        "coset_index": m_cosets,
                        "nrm_quotient": nrm_q,
                        "weight": w,
                        "a": a, "b": b,
                    }
                    yield (spec, HX, HZ)
                    total_candidates += 1


def main():
    parser = argparse.ArgumentParser(description="Phase 2: GAP coset code enumeration")
    parser.add_argument("--orders", default="60-200",
                        help="Group order range")
    parser.add_argument("--weights", default="3,4,5",
                        help="Support weights")
    parser.add_argument("--min-nrm-q", type=int, default=6,
                        help="Minimum |N_G(H)/H| threshold")
    parser.add_argument("--random-per-pair", type=int, default=20,
                        help="Random supports per (G,H) pair per weight")
    parser.add_argument("--trials", type=int, default=400,
                        help="Surrogate trials per candidate")
    parser.add_argument("--seed", type=int, default=42,
                        help="RNG seed")
    parser.add_argument("--min-k", type=int, default=4,
                        help="Minimum k to keep")
    parser.add_argument("--min-d", type=int, default=4,
                        help="Minimum d to keep")
    parser.add_argument("--output", default=None,
                        help="Output JSON path")
    parser.add_argument("--validate-top", type=int, default=0,
                        help="Validate top N candidates")
    parser.add_argument("--skip-fingerprint-file", default=None,
                        help="JSON/text file of fingerprints to skip")
    parser.add_argument("--checkpoint-file", default=None,
                        help="JSON file used to checkpoint processed fingerprints")
    args = parser.parse_args()

    orders = parse_order_range(args.orders)
    weights = [int(w) for w in args.weights.split(",")]

    print(f"=== Phase 2: GAP coset code enumeration ===")
    print(f"Orders: {orders[0]}-{orders[-1]} ({len(orders)} orders)")
    print(f"Weights: {weights}")
    print(f"Min |N_G(H)/H|: {args.min_nrm_q}")
    print(f"Random supports/(G,H)/weight: {args.random_per_pair}")
    print(f"Surrogate trials: {args.trials}")
    print(f"GAP available: {gap_available()}")
    print()

    t0 = time.time()

    candidates = _generate_coset_candidates(
        orders, args.min_nrm_q, weights,
        args.random_per_pair, args.seed
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
    print(f"\n=== Screening complete: {len(records)} codes ===")
    print(f"Time: {elapsed:.1f}s")

    if records:
        print(f"\nTop 10 by efficiency:")
        for r in records[:10]:
            print(f"  [[{r['n']},{r['k']},{r['d']}]]  eff={r['efficiency']:.3f}  "
                  f"{r['spec'].get('group_description', '')}  "
                  f"|H|={r['spec'].get('subgroup_size', '?')}  "
                  f"[G:H]={r['spec'].get('coset_index', '?')}  "
                  f"|N/H|={r['spec'].get('nrm_quotient', '?')}")

        front = pareto_frontier(records)
        params = sorted({(r["n"], r["k"], r["d"]) for r in front})
        print(f"\nPareto frontier ({len(params)} distinct params):")
        for n, k, d in params[:15]:
            print(f"  [[{n},{k},{d}]]  eff={efficiency(n,k,d):.3f}")

    output = args.output or os.path.join(
        _KIT, "..", "candidates",
        f"gap_coset_orders_{orders[0]}-{orders[-1]}.json"
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
            try:
                cayley_list = all_groups_of_order(spec["group_order"])
                if not cayley_list:
                    continue
                cayley = np.array(cayley_list[0]["cayley_table"], dtype=np.int64)

                # Reconstruct H from the subgroup info
                subs = gap_coset_candidates(None, 1,
                                            order=spec["group_order"],
                                            index=cayley_list[0]["index"])
                # Find matching subgroup
                H = None
                for s in subs:
                    if (s["size_H"] == spec["subgroup_size"] and
                            s["nrm_quotient"] == spec["nrm_quotient"]):
                        H = s["H_elements"]
                        break
                if H is None:
                    continue

                HX, HZ = build_coset(cayley, H, spec["a"], spec["b"],
                                      check_normalizer=False)
            except Exception:
                continue

            doc = make_submission(
                HX, HZ,
                name=f"[[{r['n']},{r['k']},{r['d']}]] GAP coset {spec['group_description']}",
                construction=f"Coset 2BGA on {spec['group_description']}, "
                             f"|H|={spec['subgroup_size']}, [G:H]={spec['coset_index']}, "
                             f"|N/H|={spec['nrm_quotient']}",
                authors=["autoresearch-gap"],
                family="2bga-coset",
                confidence="upper_bound",
                trials=8000,
            )
            vpath = os.path.join(_KIT, "..", "candidates",
                                 f"{r['n']}-{r['k']}-{r['d']}_gap_coset.json")
            errs = save_submission(doc, vpath)
            if not errs:
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
