# Autosearch strategy for weaker models

The qLDPC challenge has so far been driven by frontier models (every `codes/*.json`
submission carries `"model": "Claude Fable 5"`). This note describes an autosearch
strategy tuned for *weaker* models — ones that cannot invent constructions or
"guess" good exponent sets. The guiding principle, already baked into the repo
(`research/AUTORESEARCH.md`): **the trusted gate decides, not the model.** So we
move all the intelligence out of the model's reasoning and into the *search loop*.

> **Read this first — what NOT to do.** Do not optimize metrics, do not write your
> own distance/quality check, do not invent constructions, and do not edit anything
> under `verify/`. The verifier's gate (`verify/validate_candidate.py`) is the only
> thing that decides whether a code is "find." Your only job is: run a sampler →
> screen → validate → stage. The analytical notes (`METRICS_REPORT.md`,
> `WHY_KG_IS_FAIR.md`) are context for humans, not instructions for you.

## Three principles

The loop should be minimal and goal-directed. Three rules:

1. **One relevant code, in a *sparse* cell.** The board is a grid of
   `(locality_class × weight_class)` cells, each a Pareto frontier over
   `(n, k, d, w)` — *not* a single `k·d²/n` leaderboard (see `TRACKS.md`). The
   win condition is *one board-clearing code in some cell*, and the easiest way
   to get there is to **target a sparse (ideally empty) cell**, not the weight
   class with the most scalar headroom. An empty cell is trivially cleared — no
   need to beat the best `k·d²/n` in a crowded class.

   **Caveat (faithful ≠ frontier-advancing).** A code in an empty cell is a
   legitimate *record* per the rules, but an empty cell can be empty for a reason
   (hard to construct, or scientifically uninteresting). A mediocre code in an
   empty cell clears the bar without advancing the research frontier. For the
   weak-model win condition (one board-clearing code) this is still the right
   call — it is strictly easier than beating a crowded cell — but flag such finds
   honestly as "record in a thin cell," not "frontier advance."

   **Sampler → cell map (constrains the reachable space).** The real samplers in
   `research/kit/search.py` are `sample_bb`, `sample_dihedral`, `sample_metacyclic`,
   `sample_kasai_affine`, plus `sample_hypergraph_product` / `sample_lifted_product`
   / `sample_balanced_product` in `research/kit/products.py`. Their cells:
   - `sample_bb` → `unrestricted × weight-6` (the easy clears)
   - `sample_dihedral` / `sample_metacyclic` / `sample_kasai_affine` →
     `unrestricted × weight-8`
   - `sample_hypergraph_product` → can reach `weight-4` / `weight-6` (random small
     base codes); `products.classical_library()` is a curated list of SPC /
     repetition / Hamming base codes you can feed through `hypergraph_product`
     directly for more control — this is the route to the emptiest `weight-4` cell
   - **Unreachable by current samplers:** `local-2d-single` (radius ≤ 4.0). The
     `unrestricted × weight-8` cell is crowded and brutal (the `[[168,20,14]]` at
     `k·d²/n ≈ 23.3` sets a high bar there), so prefer the `weight-6` cells
     (`sample_bb`) or the `weight-4` cell (`sample_hypergraph_product`) for an easy
     clear.

2. **Fail fast.** Never build a matrix that cannot clear the bar. Pre-filter with
   `surrogate.mixed_volume` so only exponent sets whose k-upper-bound beats the
   target are materialized. Gate only candidates whose *screened* efficiency clears
   the live bar — `search.screen` already refuses `k < min_k` / `d < min_d`. Stop at
   the first verified find: run the loop once, take the top screen result, validate
   it, and stop. Do **not** raise `trials` to convergence "just in case" — see the
   warning below.

   **CRITICAL — the screen is permissive, not conservative.** `distance_rand`
   returns an **upper bound** on $d$ (it found *a* logical of that weight, so
   $d \le$ that). A looser (higher) $d$ inflates efficiency, so
   `eff_screen >= eff_true`: the screen **over-reports**, it does *not* guarantee
   safety. Low trials → loose bound → you may screen a code that later fails exact
   distance. The fix is not more trials in the screen — it is the **gate**: always
   run `verify/validate_candidate.py` on the finalist. The screen only ranks
   candidates; the gate is the only truth.

3. **Less is more.** One sampler, one weight class. `sample_bb` already draws
   random exponent sets from the `bb.KNOWN` neighborhood, so just run it and let
   `screen` rank the results — there is no flag to pick a single seed. Avoid
   exhaustive enumeration unless the grid is tiny. Minimal call: `screen(
   sample_bb(num, ...), min_k=, min_d=, trials=, keep=1)`.

## Token budget

The three principles above are also a *token* budget. The expensive work (searching
the exponent space, building matrices, screening) runs as model-free Python in
`research/kit/`; the model only orchestrates one command and reviews one result.
Keep it that way:

- **One shot, then stop.** Run the loop once. If it finds a code, report it and
  stop — do not re-prompt to "improve" it.
- **No silent iteration.** If the first run finds nothing (empty neighborhood for
  the chosen cell), report the failure and the cell you tried. Do **not** loop
  internally tweaking flags — each retry is a fresh orchestration+review cycle that
  multiplies cost. Pick a sparser cell or a different sampler, then take one more
  shot and stop.
- **Trim the log.** `screen(..., verbose=False)` (the default) keeps the review
  cheap; turn on `verbose=True` only if you need to see candidate counts.

For a weak/cheap model this double-counts: few tokens × low cost per token.

## Recommended loop (minimal, real API)

```python
# research/kit  (add research/kit and verify/ to sys.path first)
from search import screen, sample_bb
from products import sample_hypergraph_product
from submit import make_submission, save_submission
import sys; sys.path.insert(0, "verify")
from validate_candidate import validate_candidate

# Easy clear: weight-6 cell via bivariate-bicycle random sampling.
recs = screen(sample_bb(200, l_range=(6, 10), m_range=(6, 10), weight=3, seed=0),
              min_k=8, min_d=6, trials=1500, keep=1)
# Or the emptiest cell: weight-4 via hypergraph product of small base codes.
# recs = screen(sample_hypergraph_product(200, n_range=(4, 8), m_range=(3, 6), seed=0),
#               min_k=4, min_d=4, trials=1500, keep=1)

for r in recs:
    spec = r["spec"]                       # JSON-serializable construction params
    # rebuild (HX, HZ) from spec, then:
    doc = make_submission(HX, HZ, name=..., construction=..., authors=[...],
                          family="bivariate-bicycle", trials=8000, seed=0)
    save_submission(doc, f"research/candidates/{doc['n']}-{doc['k']}-{doc['distance']['d']}.json")
    assert validate_candidate(doc)["passed"] is True   # the only truth
```

`screen` consumes any iterable of `(spec, HX, HZ)` triples (so you can point it at
your own generator), requires `k >= min_k`, estimates `d` with `distance_rand`
(upper bound; requires `d >= min_d`), scores by `k*d²/n`, deduplicates by
fingerprint, and returns records sorted best-first, truncated to `keep`. The
`spec` dict lets you rebuild the winner without re-parsing a string.

## Why this beats "just prompt a weaker model"

The weaker the model, the less it should do. Pick one weight class, sample from the
`bb.KNOWN` neighborhood (or `classical_library` for weight-4), screen, gate, stop at
the first pass. `mixed_volume` pre-filter + random sampling are model-free; the
model only orchestrates and reviews. We make the loop as small as possible so the
model's role — and its chances of error — are minimized.
