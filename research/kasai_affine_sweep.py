r"""Sweep the Kasai affine 2BGA family and stage the finalists.

The reason this sampler and not another: AUTORESEARCH section 3 measures every
sampler's reach and says the binding constraint is check weight, not n. Over
3000 draws each, the ceilings are

    sample_bb            max n  240   max check weight 6
    sample_dihedral      max n  320   max check weight 8
    sample_metacyclic    max n  320   max check weight 8
    sample_kasai_affine  max n  684   max check weight 8

and the board's 25 most efficient entries all sit at n between 630 and 682 with
check weight at least 12. So three of the four samplers cannot reach the band at
all, and `sample_kasai_affine` reaches it on n while needing `weight` raised from
4 to 6 (the docstring's own instruction: check weight is 2 * weight, so weight=6
is the first setting that clears 8). That is the whole premise of this sweep.

Nothing here is a find. `screen` estimates d with `surrogate.distance_rand`,
which is an upper bound, so every staged record carries confidence
"upper_bound" and only `coordination.gate_and_record` decides. Staging is cheap
and the witness is the expensive part, so it is persisted even when the gate
later rejects the candidate as a duplicate.

    # smoke test: is the plumbing right at all?
    python research/kasai_affine_sweep.py --num 40 --trials 60 --stage 2

    # the real sweep
    python research/kasai_affine_sweep.py --num 6000 --weight 6 --trials 400 \\
        --workers 8 --stage 6
"""

import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (os.path.join(_ROOT, "research", "kit"), os.path.join(_ROOT, "verify")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from coordination import staging_dir, unique_path  # noqa: E402
from group_algebra import build_2bga, metacyclic  # noqa: E402
from search import (  # noqa: E402
    _primitive_root,
    pareto_frontier,
    sample_kasai_affine,
    screen,
)
from submit import make_submission, save_submission  # noqa: E402
from surrogate import distance_rand  # noqa: E402


def rebuild(spec):
    """Rebuild (HX, HZ) from the spec `screen` kept. The spec IS the record."""
    if spec.get("family") != "2bga-affine":
        raise ValueError(f"unexpected family {spec.get('family')}")
    q = int(spec["q"])
    mul, _elems = metacyclic(q, q - 1, _primitive_root(q))
    return build_2bga(mul, spec["a"], spec["b"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--num", type=int, default=6000, help="candidates to draw")
    ap.add_argument("--weight", type=int, default=6, help="monomials per side; check weight = 2*weight")
    ap.add_argument("--q-max", type=int, default=19, help="q<=19 gives n<=684")
    ap.add_argument("--trials", type=int, default=400, help="RIS trials per candidate")
    ap.add_argument("--min-k", type=int, default=4)
    ap.add_argument("--min-d", type=int, default=4)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--stage", type=int, default=6, help="how many finalists to stage")
    ap.add_argument("--refine", type=int, default=0, help="re-screen this many finalists at --refine-trials")
    ap.add_argument("--refine-trials", type=int, default=20_000)
    ap.add_argument("--witness-trials", type=int, default=3000,
                    help="budget make_submission spends finding the witness it writes")
    ap.add_argument("--dry-run", action="store_true", help="screen only, stage nothing")
    args = ap.parse_args()

    if args.weight == 4:
        print(
            "WARNING: weight=4 caps the check weight at 8, and every one of the\n"
            "         board's 25 most efficient entries is at least 12. Raise --weight.",
            flush=True,
        )

    t0 = time.time()
    cands = sample_kasai_affine(args.num, q_range=(7, args.q_max), weight=args.weight, seed=args.seed)
    print(
        f"screening {args.num} x 2bga-affine weight={args.weight} "
        f"(check weight {2 * args.weight}) at {args.trials} trials, "
        f"{args.workers} workers...",
        flush=True,
    )

    recs = screen(
        cands,
        min_k=args.min_k,
        min_d=args.min_d,
        trials=args.trials,
        seed=args.seed,
        backend="auto",
        workers=args.workers,
    )
    elapsed = time.time() - t0
    print(f"  -> {len(recs)} distinct codes survived k>={args.min_k}, d>={args.min_d} in {elapsed:.0f}s", flush=True)

    if not recs:
        print("nothing survived; nothing staged")
        return

    print("\ntop 12 by k*d^2/n:", flush=True)
    for r in recs[:12]:
        print(f"  [[{r['n']},{r['k']},{r['d']}]]  eff={r['efficiency']:8.3f}  w={2 * args.weight}", flush=True)

    front = pareto_frontier(recs)
    params = sorted({(r["n"], r["k"], r["d"]) for r in front})
    # pareto_frontier returns nondominated records in an order that is NOT by
    # efficiency, so front[0] is not the best -- take the max explicitly.
    best_front = max(r["efficiency"] for r in front)
    print(f"\nPareto frontier over the sweep: {len(params)} distinct parameter sets, best eff {best_front}", flush=True)

    # --- refine ------------------------------------------------------------
    # distance_rand returns an upper bound on d: it reports the LIGHTEST logical
    # it happened to find. Fewer trials means it finds lighter ones less often,
    # so a cheap screen systematically INFLATES d -- and efficiency goes as d^2,
    # so the inflation is squared. A candidate at 50 trials and eff 187 means
    # nothing until it has been re-run deep on its own. Re-rank the finalists on
    # the deep reading, and never on the coarse one.
    if args.refine and len(recs):
        k_take = min(args.refine, len(recs))
        print(f"\nrefining top {k_take} at {args.refine_trials} trials...", flush=True)
        refined = []
        for r in recs[:k_take]:
            try:
                HX, HZ = rebuild(r["spec"])
            except Exception as exc:
                print(f"  rebuild failed: {exc}")
                continue
            d2 = distance_rand(HX, HZ, trials=args.refine_trials, seed=args.seed, backend="auto")
            if d2 is None:
                # the estimator could not resolve it; the coarse reading stands
                # but is never promoted, so keep it where it was
                refined.append(r)
                continue
            # d is an upper bound, so more trials can only LOWER it. If it came
            # back higher the two runs disagreed, and the smaller is the safer
            # bound -- never promote a bound on the strength of a disagreement.
            d2 = int(min(d2, r["d"]))
            refined.append({**r, "d": d2, "efficiency": round(r["k"] * d2 * d2 / r["n"], 4), "coarse_d": r["d"]})
            print(
                f"  [[{r['n']},{r['k']},{d2}]]  d_coarse={r['d']}  "
                f"eff={refined[-1]['efficiency']:8.3f}" + ("   <-- fell below min_d" if d2 < args.min_d else ""),
                flush=True,
            )
        refined.sort(key=lambda r: (-r["efficiency"], r["fingerprint"]))
        recs = refined
        print(f"\nafter {args.refine_trials}-trial refine, top {min(12, len(recs))}:", flush=True)
        for r in recs[:12]:
            print(
                f"  [[{r['n']},{r['k']},{r['d']}]]  eff={r['efficiency']:8.3f}  "
                f"(coarse d was {r.get('coarse_d', r['d'])})",
                flush=True,
            )

    if args.dry_run:
        print("\n--dry-run: staging nothing")
        return

    print(f"\nstaging top {min(args.stage, len(recs))}:", flush=True)
    staged = []
    for r in recs[: args.stage]:
        try:
            HX, HZ = rebuild(r["spec"])
        except Exception as exc:
            print(f"  rebuild failed for {r['spec']['family']} q={r['spec'].get('q')}: {exc}")
            continue
        n = HX.shape[1]
        d = int(r["d"])
        doc = make_submission(
            HX,
            HZ,
            name=f"[[{n},{r['k']},{d}]] affine 2BGA q={r['spec']['q']} w={2 * args.weight}",
            construction=(
                f"Generalized bicycle on the metacyclic realisation of Aff(F_{r['spec']['q']}) "
                f"(Z_{r['spec']['q']} x| Z_{r['spec']['q'] - 1}, primitive root), "
                f"block size n = 2*q*(q-1) = {n}, monomials a = {r['spec']['a']} and "
                f"b = {r['spec']['b']} of weight {len(r['spec']['a'])} "
                f"(check weight {2 * args.weight}). Drawn by research/kasai_affine_sweep.py "
                f"seed {args.seed}; d is a surrogate reading of {args.trials} RIS trials."
            ),
            authors=["@MathysRennela"],
            family="generalized-bicycle",
            confidence="upper_bound",
            trials=args.witness_trials,
            seed=args.seed,
            found_by="research/kasai_affine_sweep.py",
        )
        path = unique_path(f"{staging_dir()}/{n}-{r['k']}-{d}.json", doc)
        save_submission(doc, path)
        staged.append(path)
        print(f"  staged {path}   eff={r['efficiency']:.3f}", flush=True)

    print("\n--- gate with ---")
    for p in staged:
        print(f"  uv run --extra research python research/kit/coordination.py gate {p}")
    with open(os.path.join(_HERE, "kasai_sweep_last.json"), "w") as fh:
        json.dump(
            {
                "staged": staged,
                "seconds": elapsed,
                "screened": len(recs),
                "weight": args.weight,
                "trials": args.trials,
                "seed": args.seed,
            },
            fh,
            indent=1,
        )


if __name__ == "__main__":
    main()
