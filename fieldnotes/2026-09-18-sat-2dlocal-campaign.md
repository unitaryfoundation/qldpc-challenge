---
title: "Locality-constrained SAT campaign on 2d-local CSS: [[50,6,3]] and [[36,6,4]] wins, UNSAT closures elsewhere, and the G-window rule"
date: 2026-09-18
author: "@mathysrennela"
model: "GLM 5.3 Flash (opencode CLI agent)"
topics: [sat-search, local-2d, css-codes, unsat-closure, geometric-efficiency, tooling, campaign-postmortem]
related:
  - fieldnotes/2026-09-18-hackathon-1155-frontier-map-and-playbook.md
  - fieldnotes/2026-09-18-sat-t2-weight6-2dlocal-records.md
  - fieldnotes/2026-08-29-g-parity-agenda.md
---

# Locality-constrained SAT campaign on 2d-local CSS codes

## Motivation (layout scan and the g-frontier)

A full scan of the board's 382 codes (119 with layouts), recomputing the site's
own geo score exactly, closed the "hidden g / suboptimal layout" hypothesis:
every top entry already sits at the r = √2 integer-lattice floor, and the site
recomputes r from coordinates regardless of stored claims. The recomputed
g-frontier is dominated by high-rate d = 3 plaquette tilings, not the mid-size
band: 656-114-3 at g = 1.564, 676-110-3 at 1.464, 676-36-5 at 1.331,
569-9-9 at 1.281. The concrete open target was therefore k/n > 0.174 at
d = 3, r = √2, or better distance at comparable rate — and SAT search is the
one tool that can prove a cell empty, which set the campaign's shape.

## Method (encodings, backends, budgets)

The enumerator (research/local_sat.py) builds a CNF over X/Z row-incidence
variables on an n_side × n_side grid: even-overlap commutation chains,
per-error detection clauses at depth t, a Sinz sequential-counter row-weight
bound, and anchor/radius clauses bounding interaction distance by construction.
Three encoding bugs cost the first sessions and define the grammar's semantics:
(1) CSS detection is a per-row XOR (X-rows detect via the Z-error part,
Z-rows via the X-part), not "some qubit with an odd pair"; (2) stabilizer-absorbed
errors legitimately have zero syndrome — requiring nonzero syndrome for every
weight-≤t error yields spurious UNSAT at t ≥ 2 (handled by post-hoc rejection);
(3) CPython id() reuse silently shared the weight counter across rows — the
computed-weight class in the gate caught it, which is exactly why the trust
split with verify/validate_candidate.py exists.

Error enumeration is the cost driver: generic per-(error, row) detection at
t = 3 gave ~198k errors and a 15M-clause / 6.4M-variable CNF at 6×6. Two fixes:
the CSS-split encoding (pure-X and pure-Z errors imply all mixed ones) cut the
error count 198k → 15.6k (~13×), solving 16 s → 0.3 s; the shared-aux t = 3
encoder (exact t ⟺ OR of per-row parities, ~25× aux-variable reduction,
7.25M → 368k clauses at 5×5) made 6×6 t = 3 enumerable where the plain encoder
hit a 13 GB memory wall.

Backends (a dedicated solver benchmark; the numbers are below): on the
6x6 t = 2 UNSAT
boundary, CaDiCaL/CryptoMiniSat prove UNSAT ~20× faster than Minisat22/Minicard
(18–21 s vs 455–483 s); CaDiCaL is the t = 3 champion (only backend with fast
yields on both t3 cells); CryptoMiniSat's conflict limits bite early on
enumeration; kissat is fastest on pure UNSAT (20.3 s) but its pysat wrapper
crashes the whole process at C level if add_clause is called after a solve, so
it cannot enumerate. Long runs must be launched with a setsid double-fork daemonizer (a
local2d utility; method: double-fork + setsid) -- nohup dies with the
terminal's process group. Budgets must be solver-level (conf_budget per solve), not
between-cell checks: one boundary probe ran ~7 h against a 1800 s job budget,
and SIGALRM cannot interrupt a C-level solve at all.

## Records merged

- PRs #709 ([[12,2,3]]), #710 ([[14,2,3]]), #712 ([[12,2,4]]) — the first
  unconstrained SAT wins, weight-4/6, witness-backed upper bounds.
- [[50,6,3]] (codes/50-6-3.json, g = 1.08) — the t = 2 punctured-RSC frontier:
  a sweep over boards 6×6 → 10×9 found no k ≥ 7 anywhere and g falls
  monotonically past n ≈ 55.
- PR #901 ([[16,4,4]], codes/16-4-4.json), PR #905 ([[25,5,4]],
  codes/25-5-4.json), PR #913 ([[36,6,4]], codes/36-6-4.json) — the t = 3
  weight-6 campaign's board points, with MILP-exact local distance
  certification. [[36,6,4]] came from the shared-aux encoder at 6×6 G = 15
  (97 + 80 raw yields, eight distinct gate-passed matrices; one submitted per
  the one-code-per-point rule) and was a new Pareto point: previous best k at
  d = 4 in the w6 cell was 5.
- [[676,51,4]] (codes/676-51-4.json) stands terminal: the [[676,52,4]]
  question is certified closed in-family by rank-gain-witness CEGIS — ladder
  H = 54 → 1 UNSAT at every hole count (~11 s per solve), plus certified
  "no clean configs at H ≥ 55". On the 26×26 grid the all-active config
  already has k = 51, so k = 52 needs a net rank gain from a hole, and none
  exists. The wall is the joint rank-gain + 3-sum-freeness event, not
  cleanliness (H = 1..5 configs are all clean, all rank-colliding).

## Closure map (per grid / weight / depth)

- Weight-4, d ≥ 4: provably empty at n = 9 and n = 10 (UNSAT ~16 s each);
  n = 12 CaDiCaL finished in 844 s with no k ≥ 2 solution. [[16,2,4]] is
  exceptional, not the first of a family.
- t = 1: trivial (< 0.1 s) but g ≪ 1. t = 2: satisfiable fast below the
  boundary; boundary instances are the hard ones.
- t = 3 punctured-RSC grammar: UNSAT everywhere — with the 13× cheaper
  CSS-split encoding, zero SAT across ~35 configurations up to 9×8
  (~90 qubit sites). The grammar's boundary truncation that buys d = 3 with
  k = 6 creates weight-3 logicals at d ≥ 4; it cannot express d ≥ 4 with
  k > 1.
- 6×6 t = 3 weight-6: mined at G = 15 (the win), then G = 18 and G = 21
  negative — 80 raw at G = 18 yielded only [[36,4,4]] co-entries dominated by
  [[36,6,4]]; 30 raw at G = 21, zero passing the k ≥ 4 / d ≥ 4 screen.
- 8×8 t = 3 (n = 64), G = 16/12: ~9 h total at 500k and 5M conflict budgets,
  zero models — BUDGET-EXHAUSTED, not UNSAT. Next rung ≈ 50M conflicts ≈
  2 days/solve; do not re-attack below that.
- t = 4 at 5×5/6×6: builds fine with the shared-aux encoder (6×6 build 290 s),
  enumeration empty within the 500k budget — empty, not certified UNSAT.
- 4×4 G = 7/8 t = 3 ([[16,5,4]] watch): 120 raw models in 38 s, zero passed
  the screen — k-increment window closed at budget. 5×5 G = 10 re-found only
  [[25,5,4]] co-entries (same-point filter correctly skipped them).
- Bilayer (layers = 2): dead by metric — the r⁴ charge gives best bilayer
  g ≈ 0.08 vs 1.56 single-layer, and stacked/paired variants work out to
  (2n, 2k, d) exactly, cancelling in kd²/n. Bridged multiband extensions:
  288 + 54 hand-designed long-range-bridge configs all fail CSS commutation
  (the base family's parity relies on short-offset ancilla pairs).
- Weight-8 2d-local: structurally sparse — the board cell holds only
  [[16,6,4]] (Reed–Muller type) plus 2 entries with best kd²/n = 6.00; the
  published exact w8 bar is kd²/n ≈ 12.7 ([[512,18,19]]). The corrected cell
  counts after the board-parse fix: w6 has 6 entries (best kd²/n = 3.56,
  [[18,4,4]]), w8 has 2 (6.00). Earlier session-log claims were inflated by a
  radius-parsing bug (binary rows read as index lists).

## Tooling lessons

- Orbit symmetry breaking (D4 + X/Z interchange, canonical-representative
  enumeration) was a measured negative: 22× slower per enumeration than
  blocking clauses; static in-CNF lex-leader clauses remain the untested variant.
- Diversity fix worth keeping: block solutions on check-incidence variables
  only (not anchors/counters) — 1 → 30–40 codes per solve.
- pysat traps: CryptoMiniSat needs both time and conflict limits or solve()
  errors; minisat/cadical expose no time-budget method; the enumerator's
  round count was the unbounded axis (each round budgeted, the count not).
- pysat holds the GIL during solve — a silent log is not a hang; check RSS/CPU
  with ps or sample. A second concurrent uv run can wedge in a thread join.
- Board-reading filters must match the merged schema: filtering on a
  locality key the schema does not store silently returns an empty board, so
  same-point duplicates look like fresh finds — one [[25,5,4]] co-entry was
  staged as "advancing" before the driver rebuilt the board inline.
- Persist tooling and witnesses: campaign tooling named in a note must exist
  in the tree or the note must say how to rebuild it; stage candidates via the
  kit path so a found witness is never print-only.

## Boundary

The reusable selection rule from the whole campaign: the enumerator emits G
rows per side with rank ≈ G and k = n − rank(H_X) − rank(H_Z), so a k-target
has a narrow rank-pressure window G ≈ (n − k_target)/2 — calibrated by the
incumbents ([[16,4,4]] = 12 = 6+6, i.e. G = 6; [[25,5,4]] G = 10;
[[36,6,4]] G = 15); hunt k+1 at incumbent G + 1..3. Above the window every
model needs mass rank deficiency; below it t = 3 detection goes UNSAT. G
sweeps that ignored this were ~2 h of empty-by-construction enumeration.

Open, in expected-value order: t = 4 with CryptoMiniSat on detection-heavy
CNFs (queued and killed, never ran) for a d ≥ 5 Pareto point; 8×8 t = 3 only
at ~50M conflicts or with static in-CNF symmetry breaking; weight-8
single-layer at the rank-derived G window (the night-campaign runner
pattern: incremental checkpointing, per-stage budgets, staging through the
kit path); and the frontier's real question, k/n > 0.174 at
d = 3, r = √2, which needs a parametric description of the high-rate tiling
family or SAT at n ≈ 656 (cube-and-conquer territory, untried).

## Consolidation record

Absorbs (not committed; content merged here): the 2026-08-25 sat-code-discovery
note, the 2026-08-26 local-sat-g note, the 2026-08-26 t2-sweep-pivot note, the
2026-08-26 t3-unsat-closed note, the 2026-08-26 t3-css-split-unsat note, the
2026-08-26 layout-scan-frontier-reframe note, the 2026-09-02 weight68
sat-campaign-postmortem note, the 2026-09-04 sat-solver-and-encoding-gaps
note, the 2026-09-08 campaign-closure note, and the 2026-09-08 w6-single-layer
closed pivot-weight8 note.
