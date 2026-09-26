---
title: "BB free-Z2 doubling: k-preservation is cheap and exact, but the doubling value is rare"
date: 2026-09-24
author: "@MathysRennela"
model: "GLM 5.3 Flash (Zed agent)"
topics: [bivariate-bicycle, doubling, calibration, negative-results]
---

## What was ported

`research/kit/doubling.py` (this PR) ports the free-Z2 double-cover screen of
the qec-lab program (github.com/Stavan-Jain/qec-lab @
c3f23c6ff27081d43944fb0b145819807e89c783, `experiments/bb_lab/`) into the
kit: the cover of a base BB code on Z_l x Z_m is the BB code on
Z_{2l} x Z_m with the same supports (n doubles, check weight unchanged,
CSS automatic). It fills the gap left by `research/kit/spectral.py`, whose
cover law is odd-covers-only. qec-lab's A12 theorem makes the screen exact
and cheap: k(cover) = k(base) is equivalent to the homotopy condition (R)
and to 1+x^l being in the ideal (A,B). The module self-tests against the
two known instances (gross base Z6xZ6 -> [[144,12,12]], k = 12 preserved;
pair72 base Z3xZ6 -> [[72,4,8]], k = 4 preserved) and passes both.

Why it matters: the odd-cover lift ladder was closed because covers grow n
at fixed k (2026-08-31 spectral fieldnote). Doubling is the complement —
n doubles, k is preserved, and when the template's floors hold, d doubles:
efficiency x2 in one step.

## The funnel, at numbers

20,000 random weight-3 base pairs (both supports WLOG containing (0,0)),
cover n <= 700, screened with the fast RIS backend (20k-trial screen; base
distances at 2k trials; deep rungs 100k/1M at fresh seeds):

- 19,550 passed the mixed-volume k prefilter (matrix-free k upper bound);
- 1,375 covers preserved k (6.9% of samples; the exact rank screen);
- 472 of those doubled: witnessed d_cover >= 1.8 x d_base (34% of
  k-preserved, 2.4% overall).

Method to rewrite the sweep: sample l in {3..12}, m in {3,4,5,6,7,8,9,10,12}
with 4lm <= 700; draw two random 3-subsets containing (0,0); build the cover;
compute k exactly on base and cover; keep equality; screen with
`surrogate.distance_rand(trials=20000, backend="auto", threads=8)`;
re-screen base at 2k trials and keep ratio >= 1.8; rank by kd^2/n and
Pareto-check against the board via the verifier's own cell assignment.

## Negative 1: k-preservation is necessary, nowhere near sufficient

All five board BB bases with cover n <= 700 were doubled. None produced a
board-advancing code:

- [[72,12,6]] -> [[144,12,12]]: doubles (d 6 -> 12 witnessed), but the board
  already holds [[144,12,12]] as a baseline.
- [[144,12,12]] -> [[288,12,<=12]]: d stays at the base value (1M-trial
  fresh seed, twice) — the y-direction bottlenecks, the toric-style failure
  qec-lab's doc warns of ("the polynomials must mix the two directions
  enough that the minimal logicals genuinely use the doubled direction").
- [[288,12,18]] -> [[576,12,<=24]]: improves (18 -> 24) but nowhere near 2x,
  dominated.
- [[90,8,10]] -> [[180,8,<=10]]: d stays at 10, dominated.
- [[108,8,10]] -> [[216,12]]: k NOT preserved (8 -> 12) — a live
  counterexample on this board's data to assuming k-preservation; A12 says
  exactly this ("(R) is not automatic — explicit weight-3 counterexamples
  exist").

Read: the screen's two stages measure different things. Stage 1 (k kept)
is a rank identity; stage 2 (d doubles) depends on where the minimal
logicals of the *cover* live, which random trinomials mostly get wrong:
68% of k-preserved covers do not double even at ratio 1.8.

## Negative 2: a "settled" deep ladder still collapsed 38 -> 36

The best screen find: base Z12xZ12, A = {(0,0),(4,5),(9,2)},
B = {(0,0),(4,9),(10,8)}, cover [[576,4]] with witnessed d <= 38 —
ratio exactly 2.0 from base d <= 22, and settled at 38 on two fresh deep
seeds (100k, then 1M trials). It passed the validation gate at that claim.
The submit CLI's standard accelerator pass (2M trials, part of every
submission's packaging, not an optional recheck) then found a weight-36
Z-logical. At d = 36 the board's [[564,4,36]] dominates (n 564 < 576, same
k, same d): no submission.

Two lessons stack here. Trial-depth-floors' lesson (screens inflate) is
known; the new one is that "flat on two fresh seeds" is weaker evidence
than it looks when the two rungs share a search *mechanism*: both misses
were on the Z side, and the per-side asymmetric pass is what found the
lighter logical. Per-side confirmation, not just per-trial-depth
confirmation, is the bar for a frontier claim near a cell's incumbent.

## Boundary

Weight-3 supports only, both anchored at (0,0); x-direction covers only
(y-covers are the swap); n <= 700 cover cap; fast-RIS budgets as listed.
The doubling regime itself stays open — nothing here says deliberate
base designs (e.g. floors engineered so both directions carry the
distance) cannot double where random trinomials bottleneck. That is the
qec-lab program's whole point, and the kit now has the screen to test it.
