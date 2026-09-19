---
title: "Boundary composition has two regimes; distance distillation is falsified in the checkerboard seam class; the multi-band family is envelope-closed"
date: 2026-09-01
author: "@mathysrennela"
model: "GLM 5.3 Flash (opencode CLI agent)"
topics: [code-composition, lattice-surgery, tile-codes, falsification, frontier-theory, board-policy]
related:
  - fieldnotes/2026-09-18-hackathon-1155-frontier-map-and-playbook.md
---

# Boundary composition and seam distillation: consolidated

Framing worked out while analyzing issue #748 (direct sums) and the
multi-band dense-packed wave (#822-#851, generalizing the patch-fusion
construction of arXiv:2511.06758). All claims below are now backed by an
exhaustive small-scale test and a measured family envelope. No candidate
from this work advances any board cell.

## Two regimes

Compose small 2D patches by boundary fusion: neighbors share boundary
qubits, seam checks are deformed to joint stabilizers. The composition
splits by what the seam does to logicals.

**Regime A — logical-preserving.** Seam stabilizers preserve every patch's
logical. Then k = sum of k_i (additive), d = min(d_i) (a logical inside the
smallest patch never touches a seam), and n = sum of n_i minus s, the
shared-boundary savings. The convexity argument that killed direct sums in
#748 does not extend here: for equal-distance patches,
f(fused) = (k1+k2) d^2 / (n1+n2-s) > max(k_i d^2 / n_i) strictly for any
s > 0, so fusion is metric-advancing, not merely Pareto-advancing. This is
why grafted tile records are legitimate and not flood artifacts.

Micro-example: two d=3 rotated patches (n=13, k=1 each, f = 9/13 = 0.692),
logical-preserving seam sharing 4 qubits gives [[22,2,3]] with
f = 18/22 = 0.818 — same d, better efficiency, impossible for a direct sum.
(Mixing distances is wasteful in this regime: since d = min(d_i), replacing
a larger-d patch by extra small-d patches at the same n strictly raises f,
assuming comparable seam savings.)

**Regime B — logical-consuming.** Seam measurements project out joint
logicals. k drops below the sum, and d can grow: surviving logicals wind
through the merged extent, so d scales with the array, not the tile. This
is the constructive composition behind the tile/grafted board entries, and
it is where non-identical patches become a design degree of freedom.

Cheap mechanical test between regimes: compare k_fused to the patch-sum by
rank arithmetic. Equal means Regime A; the deficit counts consumed logicals.
Both regimes produce connected Tanner graphs, so connectivity sorts nothing.

## Distillation falsified

The sharpest open question was whether, in Regime B with heterogeneous
patches, seams could consume exactly the small-distance logicals so the
fused d exceeds min(d_i) of the preserved logicals — a distance-raising
composition over cheap bricks at weight 4, r = sqrt(2).

**Closed in the checkerboard seam class.** The multi-band mask rule was
generalized to heterogeneous patches: a d=3 rotated patch (n=9) and a d=5
rotated patch (n=25) on one lattice over a grid of offsets and both
phases — 24 fused variants plus 4 baselines, every CSS-connected variant
certified distance-exact by the trusted stack's MILP certifier. Results:

- Every k=2 variant has d=3 exactly (e.g. [[31,2,3]], [[34,2,3]]); f = 0.53-0.60.
- One variant, [[34,2,4X/3Z]], shows one-sided deformation: dX rose 3 to 4
  at fixed k=2, but the Z side stayed pinned at 3 and s = 0.
- Every k=3 variant has d=2: the extra logical from merged seam checks is
  always light. Homogeneous d3+d3 deep overlap gives [[17,2,3]] (f = 1.059,
  the convexity escape confirmed) but the board's [[12,2,3]] and [[14,2,3]]
  dominate it — Regime-A fusion is real and worthless here.
- No variant achieved k=1 with d >= 5, k=2 with d > 3, or any d >= 8.
  13 of 24 placements were not even CSS (truncated edge ancillas overlap on
  an odd number of qubits, verified by an explicit violating pair).

**Rank argument closing the loopholes.** Product-stabilizer surgery cannot
pin d above min-width: adding Z1·Z2 as a Z-check consumes the anticommuting
X-logicals but the surviving Z-coset retains its weight-3 representative;
killing both light logicals requires both products and drives k to 0.
Min-width pinning: a preserved logical's distance is set by the minimal
width of its supporting region; gluing a d=3 brick to anything keeps a
width-3 cut, and the consumed brick's qubits remain as dead weight in n.
Both sides rising never occurred; the min side pins the code's d.

## Multi-band envelope

The multi-band family (all 15 board members plus a pitch sweep at rows=4,
m=3) was measured against its own published construction. Rank arithmetic
exact; sweep distances are surrogate upper bounds.

1. **Pure Regime A.** k equals the true patch count exactly for every
   member, d = brick d, deficit zero. Nothing is consumed or distilled.
2. **Value is data-site sharing only.** s equals doubly-claimed data sites
   exactly; ancilla sharing reduces n by zero. Sharing fractions: ~16% of
   the data sum at d=3 (7.3-7.4 qubits per logical vs 9 standalone), 24.9%
   at the deepest d=5 member, [[676,36,5]] (18.78 vs 25). Independently,
   [[621,85,3]] at 7.3 qubits per logical implies ~44% sharing against
   standalone d=3 patches — consistent with aggressive Regime-A fusion.
3. **Sharp pitch threshold at d+1.** At pitch = d+1 the family achieves
   full k with maximal sharing. Below threshold k collapses to about half:
   d=5 pitch 4 gives [[169,5,5]] (upper bound, f = 0.74); pitch 2 gives
   [[127,5,4]] (upper bound, f = 0.98), with consumed logicals gaining no
   distance. Above threshold sharing decays linearly to zero at pitch =
   2d+2. The envelope is closed: max f = 1.33 ([[676,36,5]]), and no pitch
   beats it. Efficiency multiplier across members is f = 1.17-1.33.
4. **Domination.** [[398,54,3]] dominates [[625,50,3]]; [[570,78,3]]
   dominates four entries: [[625,50,3]], [[696,76,3]], [[700,75,3]],
   [[700,57,3]]. Conversely [[615,15,7]] is itself dominated by
   [[567,15,7]]. The cell's actual frontier is hole-punching (best f:
   1.564 at d=3, [[656,114,3]]), which beats the family by ~15-30% at high
   k density.

Verdict: the family is closed as a research direction — pure Regime A,
envelope-capped, slots filled, mechanism beaten by hole-punching. The r =
sqrt(2), weight-4 cell remains the property of direct search and
hole-punching, not of composition.

## Boundary

One seam class (checkerboard mask fusion), one offset grid, binary phases,
one heterogeneous pair (d=3, d=5). Distances exact via the trusted MILP
certifier; k by rank arithmetic; pitch-sweep distances are surrogate upper
bounds; domination computed against the current board with locality class
filtered per entry. The regime split and the Regime-A wastefulness argument
carry exact-distance evidence; the min-width argument is
construction-independent for 2D-local layouts but was not extended to other
seam algebras. No candidate advanced any board cell.

## Consolidation record

This note consolidates and supersedes two earlier fieldnotes dated 2026-09-01: the note on the two boundary-composition regimes of fused patches, and the note falsifying distance distillation by heterogeneous seam fusion in the checkerboard seam class. Cite this file instead of either.
