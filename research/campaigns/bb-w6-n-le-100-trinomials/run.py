"""Run the trinomial BB campaign: 120 random trinomial pairs at n <= 100 against the cell's seeded bar.

The first campaign filed with a direction card (issue #4028). Each sampled
pair is one experiment: built with the kit, screened at 400 numpy RIS trials,
and sent to the real gate only when its screened kd^2/n clears the bar in
the card (90-8-10, 8.889). Nothing here is a find until the gate says so, and
nothing is submitted; the summary and its negative results are the output
whatever the count of survivors.

    uv run --extra research python research/campaigns/bb-w6-n-le-100-trinomials/run.py
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
for _p in (os.path.join(_ROOT, "research", "kit"), os.path.join(_ROOT, "verify")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from campaign import Ledger, load_campaign, write_summary  # noqa: E402
from css import compute_k  # noqa: E402
from search import sample_bb  # noqa: E402
from submit import make_submission  # noqa: E402
from surrogate import distance_rand  # noqa: E402
from validate_candidate import validate_candidate  # noqa: E402


def main(out=None, refute=True):
    camp = load_campaign(os.path.join(_HERE, "campaign.json"))
    card = camp.direction
    bar = camp.c["objective"]["target"]
    trials = camp.c["methods"]["screening"]["trials_per_candidate"]
    budget = camp.c["budget"]["candidates_screened"]
    led = Ledger(camp)
    print(f"campaign {camp.id}: {camp.name}")
    print(f"  bar {card['bar']['slug']} at kd^2/n {bar}; {budget} candidates at {trials} trials")

    best = None
    # A random trinomial pair encodes nothing most of the time (k = 0), and a
    # code with no logical qubits has no distance to screen. Those draws are
    # counted and reported, not charged to the budget, so the 120 candidates
    # the budget buys are 120 codes with k >= 1. sample_bb counts its own
    # rejected draws toward num, so it is asked for more than enough.
    sampled = sample_bb(10 ** 9, l_range=(3, 10), m_range=(3, 10), weight=3, seed=0,
                        n_range=(40, 100), max_weight=6)
    trivial = 0
    screened = 0
    for i, (spec, HX, HZ) in enumerate(sampled):
        if screened >= budget:
            break
        n = HX.shape[1]
        k = compute_k(HX, HZ)
        if k == 0:
            trivial += 1
            continue
        screened += 1
        params = {"l": spec["l"], "m": spec["m"], "A": str(spec["A"]), "B": str(spec["B"]), "k": k}
        led.start_experiment("bivariate-bicycle", seed=i, mode="novel_generation", params=params)
        d = distance_rand(HX, HZ, trials=trials, seed=0, backend="numpy")
        led.spend(candidates_screened=1)
        led.record_screen(trials=trials, d=d, backend="numpy", n=n, k=k)
        eff = round(k * d * d / n, 3) if d else 0.0
        if best is None or eff > best[0]:
            best = (eff, n, k, d, params)
        if d is None or eff <= bar:
            led.record_verdict("not_run")
            led.end_experiment()
            continue
        doc = make_submission(
            HX, HZ, name=f"[[{n},{k},{d}]] trinomial bivariate bicycle",
            construction=f"Bivariate bicycle on Z_{spec['l']} x Z_{spec['m']}, A = {spec['A']}, "
                         f"B = {spec['B']}; sampled by the bb-w6-n-le-100-trinomials campaign.",
            authors=["@vprusso"], family="bivariate-bicycle", confidence="upper_bound")
        verdict = validate_candidate(doc, seed=11, refute=refute)
        if verdict["passed"]:
            led.record_verdict("passed")
            row = led.record_candidate(doc, verdict)
            print(f"  gate accepted [[{row['n']},{row['k']},{row['d']}]] -> {row['cell']}")
        else:
            labels = "; ".join(verdict.get("labels") or [])
            led.record_negative("gate rejected", f"[[{n},{k},{d}]] screened at {eff}: {labels}")
            led.record_verdict("duplicate" if "duplicate" in labels.lower() else "refuted")
        led.end_experiment()

    eff, n, k, d, params = best
    led.record_negative(
        "bar not reached" if eff <= bar else "bar reached only on screen",
        f"{screened} trinomial pairs with k >= 1 at n in [40, 100], {trials} numpy RIS trials each "
        f"({trivial} further draws had k = 0 and were not charged): the best screened kd^2/n was "
        f"{eff} at [[{n},{k},{d}]] (l={params['l']}, m={params['m']}) against the bar {bar} "
        f"({card['bar']['slug']}); " + card["what_a_negative_would_teach"])
    fired = led.stop_reason()
    print(f"  stopped by: {fired[0]} ({fired[1]})" if fired else "  no stopping condition fired")
    summary = led.summary(report="research/campaigns/bb-w6-n-le-100-trinomials/REPORT.md")
    out = out or os.path.join(_HERE, "summary.json")
    write_summary(summary, out)
    print(f"  best screened kd^2/n {eff} at [[{n},{k},{d}]]; {trivial} draws had k = 0; "
          f"survivors {len(summary['survivors'])}")
    print(f"  summary -> {os.path.relpath(out, _ROOT)}")
    return summary


if __name__ == "__main__":
    s = main()
    print(json.dumps(s["stopped_by"], indent=2))
