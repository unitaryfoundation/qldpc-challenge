"""Run the smoke campaign end to end: definition -> loop -> summary.

Proves a campaign definition actually drives the existing loop rather than
sitting beside it. One experiment, one known [[72,12,6]] bivariate bicycle
code, screened with the kit, packaged with the kit, and put through the real
gate. Nothing here is a find until the gate says so, and nothing is submitted:
the survivor is staged and summarised, exactly as an unattended run must.

    uv run --frozen python research/campaigns/smoke-bb-72/run.py
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
for _p in (os.path.join(_ROOT, "research", "kit"), os.path.join(_ROOT, "verify")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bb import build_bb  # noqa: E402
from campaign import Ledger, load_campaign, write_summary  # noqa: E402
from submit import make_submission  # noqa: E402
from surrogate import distance_rand  # noqa: E402
from validate_candidate import validate_candidate  # noqa: E402


def main(out=None, refute=False):
    camp = load_campaign(os.path.join(_HERE, "campaign.json"))
    led = Ledger(camp)
    print(f"campaign {camp.id}: {camp.name}")

    led.start_experiment("bivariate-bicycle", seed=0,
                         note="the known Z_6 x Z_6 trinomial pair")
    HX, HZ = build_bb(6, 6, [(3, 0), (0, 1), (0, 2)], [(0, 3), (1, 0), (2, 0)])
    n, w = HX.shape[1], int(max(HX.sum(axis=1).max(), HZ.sum(axis=1).max()))
    trials = camp.c["methods"]["screening"]["trials_per_candidate"]
    d = distance_rand(HX, HZ, trials=trials, seed=0, backend="numpy")
    led.spend(candidates_screened=1)
    print(f"  screened [[{n},?,{d}]] w={w} at {trials} trials")

    if not camp.in_scope(n=n, d=d, w=w):
        led.record_negative("out of scope",
                            f"[[{n},.,{d}]] w={w} is outside the campaign's "
                            "search space")
        led.end_experiment()
    else:
        doc = make_submission(
            HX, HZ, name=f"[[{n},12,{d}]] smoke campaign BB code",
            construction="Bivariate bicycle on Z_6 x Z_6, the known "
                         "trinomial pair; built by the smoke campaign.",
            authors=["@your-handle"], family="bivariate-bicycle",
            confidence="upper_bound")
        verdict = validate_candidate(doc, seed=11, refute=refute)
        if verdict["passed"]:
            row = led.record_candidate(doc, verdict)
            print(f"  gate accepted [[{row['n']},{row['k']},{row['d']}]]"
                  f" -> {row['cell']}")
        else:
            led.record_negative("gate rejected",
                                "; ".join(verdict.get("labels") or []))
            print("  gate rejected it; recorded as a negative result")
        led.end_experiment()

    best = camp.score(n=n, k=12, d=d)
    fired = led.stop_reason(best_score=best)
    print(f"  stopped by: {fired[0]} ({fired[1]})" if fired
          else "  no stopping condition fired")
    summary = led.summary(best_score=best,
                          report="research/campaigns/smoke-bb-72/REPORT.md")
    out = out or os.path.join(_HERE, "summary.json")
    write_summary(summary, out)
    print(f"  summary -> {os.path.relpath(out, _ROOT)}")
    return summary


if __name__ == "__main__":
    s = main(refute=True)
    print(json.dumps(s["stopped_by"], indent=2))
