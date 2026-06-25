"""Recipe 02 -- sweep a family, screen, and package the best find.

The autoresearch loop: generate many candidates from a family, screen each with
the cheap surrogate, rank by efficiency and Pareto frontier, then take the best
candidate, (optionally) confirm its distance, package it, and verify.

Run (pure numpy, no extra deps):
    uv run python research/recipes/02_search_a_family.py

To also confirm the winner's distance exactly, install scipy:
    uv run --with scipy python research/recipes/02_search_a_family.py
"""
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_RESEARCH = os.path.join(_HERE, "..")
_REPO = os.path.join(_RESEARCH, "..")
sys.path.insert(0, _RESEARCH)
sys.path.insert(0, os.path.join(_REPO, "verify"))

from bb import build_bb
from css import compute_k
from search import screen, pareto_frontier, sample_bb
from submit import make_submission, validate
import qldpc_verify

# 1. Generate + screen a sweep of random BB codes. distance_rand is an upper
#    bound, so this ranks CANDIDATES; we confirm the winner afterwards.
print("1. screening 400 random bivariate-bicycle candidates (k>=4, d>=4) ...")
records = screen(sample_bb(400, seed=7), min_k=4, min_d=4, trials=250)
print(f"   -> {len(records)} distinct codes survived")

# 2. Rank: the headline efficiency k*d^2/n, and the Pareto frontier over (n,k,d).
print("2. top 5 by efficiency k*d^2/n:")
for r in records[:5]:
    print(f"     [[{r['n']},{r['k']},{r['d']}]]  eff={r['efficiency']:.3f}")
front = pareto_frontier(records)
# Distinct codes can share (n,k,d) and all stay on the frontier (co-leaders);
# dedup by parameters for a readable one-line summary.
params = sorted({(r["n"], r["k"], r["d"]) for r in front})
print("   Pareto frontier: " + ", ".join(f"[[{n},{k},{d}]]" for n, k, d in params[:8]))

# 3. Take the best candidate and rebuild it from its (structured) spec -- no
#    string parsing needed, because the sampler recorded the build parameters.
best = records[0]
s = best["spec"]
print(f"3. best candidate: [[{best['n']},{best['k']},{best['d']}]]  {s}")
HX, HZ = build_bb(s["l"], s["m"], s["A"], s["B"])
assert compute_k(HX, HZ) == best["k"]

# 4. Package + verify the winner. (make_submission re-evaluates the witnesses at
#    higher trials, tightening the upper bound before we claim it. In a real
#    search you would also confirm exactly -- research/distance.py.)
doc = make_submission(
    HX, HZ,
    name=f"[[{best['n']},{best['k']},{best['d']}]] searched BB code",
    construction=f"Bivariate bicycle on Z_{s['l']} x Z_{s['m']}, "
                 f"A={s['A']}, B={s['B']} (found by random search over the BB family).",
    authors=["your-handle"],
    tracks=["bivariate bicycle (periodic)"],
    confidence="upper_bound",
    trials=4000,
)
report = qldpc_verify.verify(doc, refute=False)
print(f"4. packaged + verified: schema_valid={not validate(doc)}  "
      f"verifier_ok={report['ok']}  claims [[{doc['n']},{doc['k']},{doc['distance']['d']}]]")

out = os.path.join(tempfile.gettempdir(), "demo_searched_bb.json")
with open(out, "w") as f:
    import json
    json.dump(doc, f, indent=2)
print(f"   wrote demo submission to {out}")
print("   Next: confirm the distance (research/distance.py) before claiming it, "
      "then drop a real winner into codes/.")
