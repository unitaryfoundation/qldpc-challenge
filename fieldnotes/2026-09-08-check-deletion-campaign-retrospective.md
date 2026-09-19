---
title: "Check-deletion as a code-discovery engine: what worked, what closed, and the open leads"
date: 2026-09-08
author: "@mathysrennela"
model: "Omen Alpha 1.0"
topics: [check-deletion, census, negative-results, grafting, geo-efficiency, pareto-filler]
related:
  - 2026-09-08-check-deletion-and-union-fusion-imports.md
  - 2026-09-18-hackathon-1155-frontier-map-and-playbook.md
---

The 2026-09-08 check-deletion campaign (waves 1–4), follow-up censuses,
and the 2026-09-16 reframe. Theory: dem-linter taxonomy, claim 12.1
PROVEN (pinned at 1ef09d73). Distances are upper bounds; CI deep-refutes.

## 1. How check-deletion found new codes

Delete r independent checks: k' = k + r, d' = min(d, min deleted-check
weight, min exposed-logical weight); terms 1–2 are guaranteed witnesses.

Wave 1: 529 sources, 39,818 moves; prune ladder (term-2 free bound ->
board-potential -> Tanner connectivity per #921 -> exact rank -> qubit
coverage) -> 600 screened in ~90 s; 348 nondominated at 31 points,
all weight-9plus x unrestricted, from 228-82-12, 276-98-14, 574-252-18,
576-294-12, 602-264-20, 672-336-12, 700-206-28 -- heavy checks (w 12–28)
with d-slack, nothing for weight-4/6.

Wave 2: [[700,206,28]] -> [[700,216,28]]; champion -> [[700,222,28]] (10
steps, +1 k each); [[85,40,5]] (+3). Wave 3: 300k screens; the 276
family's claim 12 fell to a witnessed 10. Wave 4: (276,100,10) dominated by (276,101,10). Nine submissions (#960, #961, #967–#973); with merges
(#934, #938–#941), sixteen codes on the board.

Promotion: one champion per frontier point; 300k re-screen before
submitting with explicit term-2 witnesses injected (the deep search's best find was
weight 77 vs weight-28 term-2 by construction). Provenance:
derived-from + deleted indices + schedule-does-not-transfer. Protocol:
exhaustive weight-<=3 + ~2k RIS; 300k for standouts.

## 2. What didn't work -- the three honest negatives

**Check-addition (dual move): 0/122.** All 122 weight-4 2d-local
targets have lightest logicals weighing > 4 -- nothing gaugeable inside
the weight class.

**Union-layout fusion: validated builder, board-empty.** Cellulation =
edge complex (qubits = edges, Z = faces, X = vertex stars;
no half-faces). Builder validated; 17,000 rectangle/hole + 842
concave-union shapes, zero board-advancing. k >= 2 needs holes; holes
carry weight-2 X-logicals below d >= 3; notches dominated ([[175,2,6]]
by [[112,2,10]]); board-empty at n <= 700.

**Graft r=1 pilot.** [[112,6,7]] -7, [[120,5,8]] -6, [[128,8,6]] -12
qubits at held d-floor; the tool did not report which qubits it removed,
so layouts could not transfer without fabricating a locality class.
13 codes, ~113 s/code (~ 7.5 h sweep, ~1 h parallelized).

Scars: dense-row witnesses (`v[row]=1` sets qubits {0,1}, silently
accepted by fancy indexing, failing downstream as "no witness found") --
hand-verify one; long gf2_fast RIS screens are a memory hazard (#966);
submit from isolated worktrees (parallel sessions race a shared
checkout).

## 3. Census closures across all boundaries
**9plus->8 closed, structurally.** Entering weight-8 deletes every row
heavier than 8 on both sides. Of 127 heavy sources, 126 have a uniformly
heavy side -- crossing empties it, leaving weight-1 logicals on the
opposite Pauli type (d = 1). Exception [[80,16,4]] (w=12, 8 heavy + 24
light per side) dies on 2 unchecked qubits, its 78-qubit remainder screens
at d <= 1, all 37 sampled moves died likewise.

**All boundaries: 2,525 moves over all 529 sources, zero cross-cell
survivors.** w->6/4 from weight-6/8 sources (41 alive at t=4, 13 at t=6):
every move dies -- 1,169 connectivity deaths (heavy checks are the Tanner
bridges), 1,121 free-bound kills, 106 board-dominated, 129 screened
records all d <= 2. bilayer->single: non-regen deletions expose d <= 2. unrestricted->bilayer:
empty pool (240 layouted codes -- 187 single, 53 bilayer, none above
radius 7.0).

**Two machinery bugs, fixed.** The term-2 free bound over-pruned
dependent deletions (a dependent row is a redundant stabilizer; removal
preserves the code space exactly; the corrected
independent-deleted-rows bound resurrected one survivor class, headlines
unchanged), and salted hash() RNG seeds (fixed with zlib.crc32).

**Regen family: nine bilayer entries truly single-locality.** Their
long-range checks (diameter 4.12, mostly corner stabilizers) are
rowspace-redundant; removal preserves the code space exactly; derived
matrices measure radius <= 4.0: [[72,6,<=6]], [[112,6,<=7]], [[128,6,<=8]],
[[160,6,<=9]], [[180,6,<=10]], [[198,12,<=7]], [[240,6,<=11]], [[264,6,<=12]],
[[336,6,<=14]] -- local-2d-single x weight-6, same (n, k, d) as the board. Eight are
dominated there ([[70,6,8]], [[154,6,11]] w=5, [[182,6,12]] w=5);
[[336,6,<=14]] is a genuine frontier point, but the gate returned duplicate
(identical to the board entry) -- the dedup rule refuses same-code
re-packaging, so it is unreachable under current rules (maintainer policy
question).

## 4. Operator pricing and lead results

Operators, priced before search: check deletion (k + r; d' = min(d,
deleted wts, exposed) -- exact, claim 12.1); check addition (k - r; d' >= d,
old logicals mostly survive gauging); qubit removal/graft (validated
local2d tools); union-layout fusion (k_Z = beta1 + c_R - 1, per-sector
min(height, d_loop), claims 14.1–16.14). Price-first made deletion
profitable. Leads: L1 check-addition 0/122 (above); L2 hole-punching is a priced
design in the imports note (Thm 15.1 scoring); L3/L4 graft (Section 7);
L5 closed by wave 4. Region-first composition (fuse clean regions, then
punch or gauge the region) is the one unexplored step.

**Filter landmine:** the board-dominance helper `board_single_layer_w6()`
filtered on `locality.interaction_radius`, which the merged schema does
not store -- it silently returned empty, dominance passed everything, and
same-point duplicates looked like fresh finds (the [[25,5,4]] co-entry
incident, 2026-09-08). Audit every board-dominance check the same way.

## 5. Geo-efficiency refutation

g = 4kd^2/(nρ^2r⁴); deletion's lever is k-up at fixed n, ρ, r. Of 240
layouted codes (152 at the r = √2 floor), the g leaders are the chamfer
family -- [[656,114,3]] g ~ 1.564, [[676,110,3]] 1.465, [[676,36,5]] 1.331,
[[641,17,7]] 1.300 -- all weight-4, rank exactly n-k, ultra-sparse.

Random-subset sampling failed informatively (top 400 of 7,800 deletions,
r <= 2.0, all screened d <= 2): leaders have degree-1 qubits. In
[[656,114,3]] X-degrees are 270 qubits at 1, 386 at 2 -- 251 of 271
X-checks touch a degree-1 qubit, so deleting one unchecks it (weight-1
logical, d = 1). Clean peeling (all qubits degree >= 2: 20 X + 26 Z in
656-114-3) over the top-40 g sources: 33 of 40 have no viable peel.
Exact linear algebra: deleting the cleanest X-check (check 14, qubits
{33,34,59,60}, none unchecked afterwards) creates 3 genuine weight-2
Z-logicals -- pairs (9,34), (7,33), (8,34) -- commuting with every kept
X-check, not in rowspace(H_Z); the source has zero weight-2 logicals.
The 7 peelable sources collapse in d ([[641,17,7]] d 7->3, g 1.300->0.267;
[[691,11,9]] d 9->4, 1.289->0.370), dominated by real d=3 codes. Verdict:
deletion-tight.

## 6. Pareto-filler reframe (2026-09-16, retracts an earlier conclusion)

Retracted: "the operator set has no constructor value" was wrong. The
board ranks by Pareto nondomination over (n, k, d, w) within a cell, not
a single kd^2/n rank -- raising k at fixed n, d-tier, weight class is
board-advancing; the record proves it ([[700,212,28]] #934,
[[700,216,28]] #940, [[700,222,28]] #941, [[85,40,5]] #938, [[192,43,12]]
#939 each strictly dominate their sources). Cross-cell closed (no
boundary crossed); in-cell open (chains still gaining +1 k/step at the
depth cap; ~30 same-cell census points staged, never promoted). Rule:
the operator set fills frontier points inside a cell; it does not move
codes between cells or set efficiency records.

Ancilla-split probe on [[60,12,6]]: one weight-9 Z-check hand-split
(shared ancilla, odd-overlap X-fixup), verified exact at n = 61 --
commutation holds, k preserved at 12, max X weight rose 9->10; the other
23 Z-checks stayed weight 9. Single-row splitting cannot reach w <= 8:
claim 12.1 prices why -- a weight-9 source check bounds the reachable
distance tier by its own weight (same reason 9plus->8 closed).

Weight-8 x unrestricted: 459 entries / 293 nondominated; holds the kd^2/n
ceiling ([[684,20,72]]), the high-rate band ([[584,150,18]],
[[632,162,18]], [[664,170,18]]), and the largest untouched in-cell
k-slack pool.

Remaining leads: (1) deletion chains at uncapped depth on the five census
sources plus the 700-family; (2) re-screen the unpromoted census tail at
300k; (3) graft sweep after the provenance fix (~1 h parallelized); (4)
weight-8 in-cell census; (5) 9plus->8 via Hastings weight reduction
(copying/gauging/coning -- keeps k, usually d, pays constant-factor n).

## 7. Lead B -- graft identity transfer (CLOSED 2026-09-09)

The fix landed: `boundary_engine.graft_r1_safe` takes `return_orig=True`,
returning the surviving ORIGINAL qubit identities -- layout transfer is
exact.

Sweep 1 (board-wide): r=1 grafts over every laid-out board code (d_floor
= the source's claimed d, gated): 23 gate-passed, 7 advancing
(single-source -2 removals), one per PR: #974 [[34,4,3]],
#975 [[48,6,3]], #976 [[198,8,9]], #977 [[181,12,10]], #978 [[240,12,12]],
#979 [[214,15,11]], #980 [[261,16,12]]. Distances remain upper bounds;
CI re-verifies.

Sweep 2 (parked deep grafts, honest negative): [[112,6,7]] -> [[105,6,7]]
(-7), [[120,5,8]] -> [[114,5,8]] (-6), [[128,8,6]] -> [[114,8,6]] (-14) --
all gate-passed, none board-advancing. Pilot gains reproduced exactly;
depth beyond -2 does not beat the frontier -- the advancing currency is
the light -2 removal.

## Boundary and consolidation record

Every positive claim has a PR number and a gate verdict; every negative
is a measured zero with its sample size. Lead B closed in #974-#980.

Absorbs (not committed; merged here): the 2026-09-08 census-status,
deformation-operator-leads, geo-efficiency, cross8- and cellmoves-census
notes, and the 2026-09-16 pareto-filler reframe note.
