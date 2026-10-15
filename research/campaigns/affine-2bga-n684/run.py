"""Campaign record: the affine-2BGA sweeps that produced [[684,4,124]].

Two sweeps of the same sampler at two check weights, and they came out
opposite ways. Recording both is the point: the refuted one is the more
instructive result and would otherwise leave nothing behind.

    w=12 sweep   sample_kasai_affine(num=30, weight=6, seed=7), screen at 50
                 trials, top 6 refined at 2000 trials.
                 -> [[684,4,124]] PASSED the gate (refuted=false, no WL match)

    w=8  sweep   sample_kasai_affine(num=6000, weight=4, seed=7), screen at
                 400 trials, top 25 refined at 20000 trials.
                 -> [[684,14,96]] REFUTED by the gate: a weight-40 logical was
                    found under a claimed 96, AND the code is WL-equivalent to
                    the existing board entry [[684,14,54]].

The refutation is worth the ledger on its own. The refine screen read 96 at
20000 trials and `research/does_it_advance.py` reported it beating 13 entries
on n, k and d -- all built on an inflated bound over a code that was already on
the board. The gate's `d_only_peers` named [[684,14,54]] first, which is
exactly the entry the WL signature then matched. A cheap pre-filter that says
"advances the board" is a triage hint; it is not evidence.

    uv run --extra research python research/campaigns/affine-2bga-n684/run.py
"""

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
for _p in (os.path.join(_ROOT, "research", "kit"), os.path.join(_ROOT, "verify")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from campaign import Ledger, load_campaign, scaffold_campaign, write_campaign, write_summary  # noqa: E402

CAMPAIGN_ID = "affine-2bga-n684"
CAND = os.path.join(_ROOT, "research", "candidates")


def _load(rel):
    with open(os.path.join(CAND, rel)) as fh:
        return json.load(fh)


def _gate(rel):
    """Load the gate's own persisted verdict.

    Re-running validate_candidate here would re-roll the refutation seed, and
    that is not a stable thing to key a ledger row on: against the 124 claim it
    passed 13 times in 14 and found a weight-123 logical once, so a fresh run
    can legitimately disagree with the run whose output is the evidence. The
    verdict file written by coordination.gate_and_record is the record.
    """
    return _load(rel.replace(".json", ".verdict.json") if not rel.endswith(".verdict.json") else rel)


def ensure_definition():
    path = os.path.join(_HERE, "campaign.json")
    if os.path.exists(path):
        return load_campaign(path)
    spec = scaffold_campaign(
        CAMPAIGN_ID,
        "Affine 2BGA (Kasai) sweeps at n <= 684, check weights 8 and 12",
        budget={"cpu_hours": 4, "candidates_screened": 20_000},
        families=["generalized-bicycle"],
        status="completed",
        stopping=[{"type": "no_progress", "experiments": 2}],
        constraints={"n": [200, 684], "min_distance": 4, "max_check_weight": 12},
        methods={
            "generators": ["research/kasai_affine_sweep.py"],
            "screening": {"seeds": [7], "trials_per_candidate": 400},
        },
        notes=(
            "sample_kasai_affine is the only kit sampler whose n reaches the band the "
            "board's most efficient entries sit in (630..682); see the reach table in "
            "research/AUTORESEARCH.md. weight=6 -> check weight 12, weight=4 -> check "
            "weight 8, since check weight is 2*weight. Both sweeps rank candidates on a "
            "refined reading, because the coarse distance reading inflates d and efficiency "
            "goes as d^2. The gate decides every find."
        ),
    )
    write_campaign(spec, path)
    return load_campaign(path)


def main():
    camp = ensure_definition()
    led = Ledger(camp)
    print(f"campaign {camp.id}: {camp.name}")

    # --- w=12 sweep, the one that produced the find -----------------------
    led.start_experiment(
        "generalized-bicycle",
        seed=7,
        mode="novel_generation",
        params={
            "sampler": "sample_kasai_affine",
            "num": 30,
            "weight": 6,
            "check_weight": 12,
            "screen_trials": 50,
            "refine_trials": 2000,
        },
        note="w=12; coarse 50-trial screen, top 6 refined at 2000 trials",
    )
    led.spend(cpu_hours=0.9, candidates_screened=30)
    led.record_screen(trials=2000, d=125, backend="fast", n=684, k=4)
    doc = _load("20261015-151931-nipogi-4011940/684-4-124.json")
    v = _gate("20261015-151931-nipogi-4011940/684-4-124.json")
    led.record_candidate(doc, v)
    print(f"  [[684,4,124]] passed={v['passed']} labels={v['labels'][:1]}")
    led.record_verdict("passed" if v["passed"] else "not_run")
    led.record_negative(
        "the 124 claim was superseded before submission",
        "the gate passed it at seed 1889774572, but 14 independent re-runs gave 13 "
        "passes and one weight-123 logical, and a deeper probe read 118, then 117 "
        "twice, at 20k, 50k and 150k trials. qldpc submit's own witness search "
        "found a weight-111 logical, so the entry was filed as codes/684-4-111.json "
        "at the lighter reading rather than at this record's 124.",
    )
    led.record_negative(
        "coarse reading inflated",
        "50 trials read 131 and 2000 read 125; two of the six refined finalists "
        "collapsed from 101 to 16, so the refine stage is load-bearing",
    )
    led.end_experiment()

    # --- w=8 sweep, the one the gate refuted -----------------------------
    led.start_experiment(
        "generalized-bicycle",
        seed=7,
        mode="novel_generation",
        params={
            "sampler": "sample_kasai_affine",
            "num": 6000,
            "weight": 4,
            "check_weight": 8,
            "screen_trials": 400,
            "refine_trials": 20000,
        },
        note="w=8; 6000 candidates, top 25 refined at 20000 trials",
    )
    led.spend(cpu_hours=1.5, candidates_screened=6000)
    led.record_screen(trials=20000, d=96, backend="fast", n=684, k=14)
    v2 = _gate("20261015-152430-nipogi-3946435/684-14-96.json")
    print(
        f"  [[684,14,96]] passed={v2['passed']} refuted={v2['gates']['refute']['refuted']} "
        f"wl={v2['gates']['dedup'].get('wl_equivalent_of')}"
    )
    led.record_negative(
        "gate refuted [[684,14,96]]: over-claimed distance and a WL match",
        "claimed 96 after a 20000-trial refine; the refutation found a weight-40 "
        f"logical, and dedup reported WL equivalence to the existing board entry "
        f"{v2['gates']['dedup'].get('wl_equivalent_of')}. does_it_advance.py had "
        "called it a 13-entry advance on n, k and d -- every axis of that was an "
        "inflated bound over a code already on the board. The gate's d_only_peers "
        "named 684-14-54.json first, which is the entry the WL signature then "
        "matched, so the caution was aimed at exactly the right code. Recorded as "
        "a non-frontier result, not submitted.",
    )
    led.record_verdict("refuted")
    led.end_experiment()

    if not led.stop_reason():
        print("note: no stopping condition fired")
    write_summary(led.summary(), os.path.join(_HERE, "summary.json"))
    print(f"wrote {os.path.join(_HERE, 'summary.json')}")


if __name__ == "__main__":
    main()
