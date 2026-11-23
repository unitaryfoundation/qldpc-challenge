"""Produce heuristic distance certificates -> certs/heuristic/<slug>.json.

A manual deep-check for a single code's distance claim (the board no longer
shows a separate corroborated tier -- every merged code faces the deeper
per-PR refutation gate, so `d<=` already carries this meaning).
Runs the RIS upper-bound search (verify/heuristic_distance) and, when ldpc is
importable, the independent syndrome-decoder cross-check (decode/distance), then
records both methods, an agreement flag, and a combined verdict. Analogous to
certify.py, which produces certs/<slug>.json for the exact tier.

Combined verdict:
  refuted       any method found a logical lighter than the claimed distance
  corroborated  every method that ran found exactly the claimed weight, none lighter
  inconclusive  otherwise (e.g. budget too small, or methods disagree)

Usage: python verify/heuristic_certify.py codes/foo.json [--trials N] [--seed S] [--write]
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import heuristic_distance as ris

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _syndrome(doc, trials, seed):
    """Run the BP+OSD cross-check if available; return its result or None."""
    try:
        sys.path.insert(0, os.path.join(ROOT, "decode"))
        import distance as sd  # decode/distance.py (needs ldpc)

        return sd.estimate(doc, trials=trials, seed=seed)
    except Exception:
        return None


def certify(doc, trials=200000, seed=0):
    claimed = int(doc["distance"]["d"])
    methods = {}
    r = ris.estimate(doc, trials=trials, seed=seed)
    methods["ris"] = {"d": r["d_heuristic"], "verdict": r["verdict"], "trials": r["trials"], "sides": r["sides"]}
    s = _syndrome(doc, trials, seed)
    if s is not None:
        methods["syndrome_decoder"] = {
            "d": s["d_heuristic"],
            "verdict": s["verdict"],
            "trials": s["trials"],
            "sides": s["sides"],
        }

    found = [m["d"] for m in methods.values() if m["d"] is not None]
    d_heur = min(found) if found else None
    agree = len(set(found)) <= 1

    if d_heur is not None and d_heur < claimed:
        verdict = "refuted"
    elif d_heur == claimed and all(m["verdict"] == "corroborated" for m in methods.values()):
        verdict = "corroborated"
    else:
        verdict = "inconclusive"

    return {
        "name": doc.get("name", ""),
        "claimed_d": claimed,
        "d_heuristic": d_heur,
        "verdict": verdict,
        "agree": agree,
        "methods": methods,
        "seed": seed,
    }


def main(path, trials, seed, write):
    doc = json.load(open(path))
    res = certify(doc, trials=trials, seed=seed)
    if write:
        outdir = os.path.join(ROOT, "certs", "heuristic")
        os.makedirs(outdir, exist_ok=True)
        slug = os.path.basename(path)
        json.dump(res, open(os.path.join(outdir, slug), "w"), indent=2)
        print(
            f"wrote certs/heuristic/{slug}  verdict={res['verdict']} "
            f"d_heuristic={res['d_heuristic']} methods={list(res['methods'])}"
        )
    else:
        print(json.dumps(res, indent=2))
    return 2 if res["verdict"] == "refuted" else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--trials", type=int, default=200000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    sys.exit(main(a.path, a.trials, a.seed, a.write))
