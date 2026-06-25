"""
Smoke test: the research/ starter kit must stay in sync with the verifier.

The kit shares the verifier's GF(2) core (verify/gf2.py) and targets the schema;
if either drifts in a way that breaks construction or packaging, this fails. It
builds a known code with the kit, packages it, and runs it through the REAL
verifier in-process -- the exact single-source-of-truth risk the design guards.

numpy-only (no scipy/ldpc), so it runs in the frozen CI env.

Run: uv run python research/test_smoke.py   (exit 0 = pass)
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)                                   # research/ modules
sys.path.insert(0, os.path.join(_HERE, "..", "verify"))    # the verifier

from bb import build_bb, KNOWN
from css import compute_k, verify_css
from surrogate import distance_rand, lightest_logical
from search import screen, pareto_frontier, sample_bb
from submit import make_submission, validate
import qldpc_verify

_fail = []


def check(name, cond):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}")
    if not cond:
        _fail.append(name)


def main():
    print("research/ starter-kit smoke test:")

    # 1. Construct a known code; parameters must match what the verifier computes.
    p = KNOWN["[[72,12,6]]"]
    HX, HZ = build_bb(p["l"], p["m"], p["A"], p["B"])
    check("verify_css holds", verify_css(HX, HZ))
    check("compute_k == 12", compute_k(HX, HZ) == 12)

    # 2. Surrogate recovers the (known) distance and a valid witness. d is an
    #    upper bound on the true distance 6, so it can only equal 6 by finding a
    #    weight-6 logical; fixed seed makes this deterministic.
    d = distance_rand(HX, HZ, trials=1000, seed=0)
    check("distance_rand == 6", d == 6)
    wx, xwit = lightest_logical(HX, HZ, trials=1000, seed=0)
    check("X witness has weight 6", wx == 6 and len(xwit) == 6)

    # 3. Package and run through the REAL verifier (the drift gate).
    doc = make_submission(HX, HZ, name="[[72,12,6]] smoke", construction="bb torus",
                          authors=["ci"], tracks=["bivariate bicycle (periodic)"],
                          confidence="upper_bound", trials=1000)
    check("packaged submission is schema-valid", not validate(doc))
    rep = qldpc_verify.verify(doc, refute=False)
    check("verifier accepts the packaged code", rep["ok"])
    check("earned_distance d == 6",
          rep.get("earned_distance", {}).get("d", {}).get("value") == 6)

    # 4. The search funnel runs and yields a (subset) frontier.
    recs = screen(sample_bb(40, seed=1), min_k=2, min_d=2, trials=120)
    check("search produced candidates", len(recs) > 0)
    check("pareto_frontier is a subset", len(pareto_frontier(recs)) <= len(recs))

    print("PASS" if not _fail else "FAIL: " + ", ".join(_fail))
    return 0 if not _fail else 1


if __name__ == "__main__":
    sys.exit(main())
