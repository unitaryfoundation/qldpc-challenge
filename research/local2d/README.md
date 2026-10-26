# local2d: open-boundary planar BB codes for the `2d-local` tracks

Techniques for building and analyzing **2D-local** qLDPC codes with open
boundaries — the planar bivariate-bicycle family of Liang–Eberhardt–Chen
(arXiv:2504.08887) and the boundary theory of Liang–Yang–Iosue–Chen
(arXiv:2410.11942). This fills the gap the kit used to declare out of scope:
the specialized open-boundary planar engine for the `2d-local-bilayer` track.

Everything sits on the kit's shared core (`../kit/css.py`, the verifier's own
GF(2) routines, and `../kit/surrogate.py` for randomized distance bounds), so
the usual rules apply unchanged: the surrogate is an upper bound for ranking
only, and nothing is a find until `verify/validate_candidate.py` passes it.

## Modules

| Module | Technique |
|---|---|
| `planar.py` | Fast greedy open-boundary builder (directional condensation, footnote-6 corners) + exact per-side distance via scipy MILP + `grid_coordinates` for the bilayer layout. Validated on the [[288,8,12]] flagship family; for generic (f,g) treat its output as "a CSS code" and screen k across two sizes. |
| `boundary_engine.py` | The general builder: exact half-infinite boundary gauge operators over F2[t] (polynomial kernel by unimodular elimination), corner topological-order completion, cleanup (yields the qubit-removal layouts automatically), `reduce_weights` (generating-set weight minimization), and `graft_r1` / `graft_r1_safe` (r=1 qubit-removal with multi-seed distance discipline). |
| `transfer.py` | Distance scaling *before* you build big lattices: d_X(L) = min(s*·L + O(1), w_bdd), with the slope s* computed exactly as a min-mean-weight cycle (Howard's policy iteration) of a transfer graph derived from a·g + b·f = 0. Verified against MILP-exact d_X on 7 families across 5 distinct slopes. |
| `corner_detector.py` | The bounded term of the distance law, decided L-independently: every bounded logical is corner-pinned (gcd(f,g)=1 makes finite bulk operators stabilizers), so w_bdd is computed on a fixed small patch. Matches the exact MILP growing/bounded classification 15/15. |
| `tri_hinge_anneal.py` | Two-layer layout search: one long annealing chain on a triangular lattice (2 qubits per site) with a hinge cost on check diameters above the cap; same family as `hinge_anneal.py` (#2156) and `fold_layout.py`; deterministic per seed. Produced the layout of `codes/510-16-26.json`. |
| `layout_sweep.py` | The weekly sweep over the board's layoutless CSS entries (issue #4148): smallest n first, `torus_grid.scan` and then `fold_layout`, `hinge_anneal`, and `tri_hinge_anneal` inside a per-entry budget; a layout counts only when the verifier accepts the entry with it attached. Each entry opened is a line of `sweep_attempts.jsonl`, so a miss at a budget is not retried at that budget; the `layouts-weekly` workflow runs it and opens one PR of the accepted layouts. |
| `torus_grid.py` | Exact screen, no search: a code whose qubit index runs `block * l*m + i*m + j` has a canonical grid layout, so the divisor pairs of `n/2` can be scanned and the radius measured directly. Worth trying first because a hit costs nothing; measured on the 62 layouts of PRs #3389-#3391 it placed one, and the annealer found a tighter embedding for the rest. |

## The loop for a 2d-local direction

1. **Screen families cheaply**: `surrogate.mixed_volume(S_f, S_g)` for k, then
   `transfer.distance_slope(S_f, S_g, W, CMAX)` — keep families whose slope is
   high and whose `corner_detector.detect(...)` returns `w_bdd = inf`
   (distance actually grows).
2. **Build** with `boundary_engine.build_planar(Lx, Ly, S_f, S_g)`; check the
   validity domain (`L >= extent + 3`) and that `k` is stable across two
   sizes. `reduce_weights` the checks to find the true weight class.
3. **Shrink** with `graft_r1_safe(..., d_floor=<target d>)` — never graft
   against a floor you haven't confirmed at high trials; a fixed screening
   seed has measured blind spots (see the docstring).
4. **Package** with `submit.make_submission(..., coordinates=
   planar.grid_coordinates(Lx, Ly, kept=info.get("kept_qubits")), layers=2)`
   so the verifier computes the `2d-local` locality class from the layout.
5. **Validate** with the gate, as always.

## Provenance and honest caveats

Ported from the Sierpinski research sandbox (validation statuses quoted in
each docstring were measured there):

- The flagship family's minimal logicals are truncated **Sierpinski
  triangles** only in a pre-asymptotic regime (L ≲ 16); asymptotically the
  distance is linear (the transfer-graph soliton), *not* the fractal
  L^1.585. Do not extrapolate small-L distance fits.
- `planar.build_open_directional` is validated **only** for the flagship
  weight-6 family; the sandbox measured that for generic (f,g) it often
  inflates k (broken boundary). `boundary_engine.build_planar` is the
  general-purpose construction (weight-8 secondary boundary generators
  included).
- These codes are 2D-local but their Tanner graph is non-planar: decode with
  BP+OSD (`kit/distance.py::decoder_distance`), not matching.
- The transfer-graph slope law is verified, not proved end-to-end: the
  gcd(f,g) proposition is proved; the slope law and corner characterization
  are detector-confirmed across the validation set.

## The weekly layout sweep

An entry with no layout computes as `unrestricted` and never improves on its
own, so `layout_sweep.py` opens the CSS entries that have none, smallest n
first, and tries the tools above cheapest first: the torus-grid screen, then
`fold_layout.anneal` (one layer against the 4.0 cap, two against 7.0),
`hinge_anneal.run_job` from the fold embedding, and `tri_hinge_anneal`'s long
chain, inside `--entry-seconds` of wall clock per entry and `--job-seconds`
per run, stopping early once `--max-layouts` of them are accepted. The cap
is what keeps one PR inside the verify job's 130-minute window: a first
layout makes the entry a locality record, so `verify/gate_changed.py` runs
its deep battery on every entry in the PR. A layout is accepted only when `verify/qldpc_verify.py`, run on the
entry with it attached, returns ok with a 2D-local class. The accepted layout
is attached as exactly the change `verify/check_authorship.py`'s layout
binding admits (a first `locality` block credited in `contributed_by`, an
appended provenance note, the schema bump to 0.2), written in the board's one
format, and the `layouts-weekly` workflow opens the PR with the layouts of
one run. The credited handle is the account that will own that PR, since the
binding ties a first layout to the PR author; the workflow reads it from the
`SWEEP_CREDIT` repository variable.

`sweep_attempts.jsonl` records every entry opened: the stage that placed it
(`screen`, `fold`, `hinge`, `tri`) or `miss`, the best radius seen, the
layers, the class, and the seconds, so a miss at a per-entry budget is not
retried at that budget or a shorter one (`--retry` or `--slugs` reopens it).

```
uv run python research/local2d/layout_sweep.py run --credit @vprusso --job-seconds 14400 --entry-seconds 600 --max-layouts 40
uv run python research/local2d/layout_sweep.py stage --out-dir research/out/layout_sweep    # attach to codes/
uv run python research/local2d/layout_sweep.py pr-body --out-dir research/out/layout_sweep --out body.md
```
