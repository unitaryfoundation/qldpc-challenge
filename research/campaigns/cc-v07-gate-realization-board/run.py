#!/usr/bin/env python3
"""Direction 3 of issue #7116: gate-realization judgments on real board codes.

Applies the two rows of spec/JUDGMENT_LAYER.md §2h to CSS board entries:

* the C-ADD-CHECK survival row: at pi/4 the judgment is decided by one
  stabilizer-membership test, and at any other angle with an anticommuting
  generator it stays ``not_yet_defined``;
* the equal-syndrome weight row: w_max(gens) >= ceil(d/2), checked against
  the board entry's own witness-backed distance.

Also runs the state-vector oracle on the same real displays at pi/4 and reports
disagreements. No candidate is staged or submitted: this is calibration.
"""

import argparse
import collections
import glob
import json
import math
import os
import random
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
CC = os.environ.get(
    "CODE_CALCULUS_PATH",
    "/Users/mathysrennela/GitHub/code-calculus-dev-7116-pr",
)
for _p in (CC, os.path.join(CC, "machine", "experiments"), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from gate_realization_rows import (  # noqa: E402
    Display,
    Pauli,
    addition_survival_verdict,
    equal_syndrome,
    nontrivial,
    oracle_preserves,
    popcount,
    preserves_pi4,
    random_addable_row,
    random_equal_syndrome_family,
    random_stabilizer,
    w_max,
    weight_floor,
)
from machine.priced_calculus import CodeState  # noqa: E402

QUARTER = math.pi / 4


def load_codes(n_lo, n_hi, limit):
    out = []
    for path in sorted(glob.glob(os.path.join(ROOT, "codes", "*.json"))):
        with open(path) as fh:
            doc = json.load(fh)
        d = doc.get("distance", {}).get("d")
        if doc.get("code_type") != "CSS" or not (n_lo <= doc["n"] <= n_hi):
            continue
        if not isinstance(d, int) or d < 2:
            continue
        try:
            state = CodeState.from_challenge(doc)
        except Exception:
            continue
        out.append((os.path.splitext(os.path.basename(path))[0], doc, state))
        if len(out) >= limit:
            break
    return out


def syndrome_families(display, rng, trials=8):
    """Equal-syndrome commuting Pauli families on a real board display.

    A stabilizer logical commutes with every check, so it has zero syndrome
    and cannot seed the weight row (which needs one common *nonzero*
    syndrome). These families are sampled from physical Paulis on the real
    display by the harness's own generator, then filtered to the row's
    premises.
    """
    families = []
    for _ in range(trials):
        gens = random_equal_syndrome_family(rng, display)
        if gens is None or len(gens) < 2:
            continue
        if not equal_syndrome(display, gens) or not nontrivial(display, gens):
            continue
        families.append({"gens": gens})
    return families


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-lo", type=int, default=4)
    ap.add_argument("--n-hi", type=int, default=10)
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--gates", type=int, default=4)
    ap.add_argument("--additions", type=int, default=6)
    ap.add_argument("--seed", type=int, default=7116)
    ap.add_argument("--out", default=os.path.join(_HERE, "results.json"))
    args = ap.parse_args()

    codes = load_codes(args.n_lo, args.n_hi, args.limit)
    print(f"{len(codes)} CSS board entries n in [{args.n_lo},{args.n_hi}]", flush=True)
    records = []
    stats = collections.Counter()
    started = time.time()

    for ci, (slug, doc, state) in enumerate(codes, 1):
        display = Display.from_code_state(state)
        d = doc["distance"]["d"]
        rec = {"slug": slug, "n": state.n(), "k": state.k(), "d": d, "gates": [], "weight": []}
        rng = random.Random(args.seed + ci)

        # --- survival row on gates that preserve the real codespace ---
        preserving = 0
        for _ in range(args.gates):
            # Build a commuting Hermitian gate family; bias toward preserving.
            gens = []
            for _try in range(12):
                cand = None
                if gens and rng.randrange(2):
                    cand = gens[0] * random_stabilizer(rng, display)
                else:
                    x = rng.randrange(1 << display.n)
                    z = rng.randrange(1 << display.n)
                    cand = Pauli(x, z, popcount(x & z) + 2 * rng.randrange(2))
                if cand.is_hermitian() and all(not cand.anticommutes(g) for g in gens):
                    gens.append(cand)
                if len(gens) >= 2:
                    break
            if not gens:
                continue
            eps = [rng.choice((1, -1)) for _ in gens]
            quarter = [QUARTER] * len(gens)
            try:
                pred = preserves_pi4(display, gens, eps)
                obs = oracle_preserves(display, gens, eps, quarter)
            except Exception as exc:
                rec["gates"].append({"error": repr(exc)})
                continue
            stats["preservation_checked"] += 1
            stats["preserving" if obs else "not_preserving"] += 1
            if pred != obs:
                stats["disagreement_preservation"] += 1
            if not obs:
                continue
            preserving += 1
            # Try addable rows: record the three-branch verdict at pi/4 and
            # at a non-pi/4 angle with an anticommuting generator.
            for _a in range(args.additions):
                choice = random_addable_row(rng, display)
                if choice is None:
                    break
                sector, row = choice
                try:
                    v_quarter = addition_survival_verdict(display, gens, eps, sector, row, [QUARTER] * len(gens))
                    v_other = addition_survival_verdict(display, gens, eps, sector, row, [0.3] * len(gens))
                except Exception as exc:
                    rec["gates"].append({"add_error": repr(exc)})
                    continue
                stats["survival_checked"] += 1
                stats[f"verdict_{v_quarter}"] += 1
                stats[f"verdict_{v_other}"] += 1
                if v_quarter == "not_yet_defined":
                    stats["unexpected_quarter_undefined"] += 1
                rec["gates"].append(
                    {"sector": sector, "row_weight": popcount(row), "verdict_pi4": v_quarter, "verdict_other": v_other}
                )

        # --- weight row on the board's own witness-derived logicals ---
        for fam in syndrome_families(display, rng):
            gens = fam["gens"]
            floor = weight_floor(d)
            observed = w_max(gens)
            ok = observed >= floor
            stats["weight_checked"] += 1
            stats["weight_tight" if observed == floor else "weight_above" if ok else "weight_violation"] += 1
            rec["weight"].append({"w_max": observed, "floor": floor, "d": d, "satisfied": ok})
        rec["preserving_gates"] = preserving
        if preserving:
            stats["codes_with_preserving_gate"] += 1
        if rec["weight"]:
            stats["codes_with_addressable_logical"] += 1
        records.append(rec)
        if ci % 10 == 0:
            print(
                f"  [{ci}/{len(codes)}] {slug}: preserving={preserving} weight_families={len(rec['weight'])}",
                flush=True,
            )

    summary = dict(stats)
    summary.update({"codes": len(codes), "seconds": round(time.time() - started, 1), "seed": args.seed})
    with open(args.out, "w") as fh:
        json.dump({"summary": summary, "records": records}, fh, indent=2)
    print("SUMMARY", json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
