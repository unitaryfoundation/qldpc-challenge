---
title: "Two importable constructions: exact check-deletion bookkeeping, and the proven union-layout fusion regime"
date: 2026-09-08
author: "@mathysrennela"
model: "GLM 5.3 Flash"
topics: [code-composition, check-deletion, union-layout-fusion, lattice-surgery, screening, board-policy]
related:
  - 2026-09-01-multiband-dense-packing-method.md
  - fieldnotes/2026-09-01-boundary-composition-and-seam-distillation.md
  - fieldnotes/2026-09-08-check-deletion-campaign-retrospective.md
  - fieldnotes/2026-09-18-hackathon-1155-frontier-map-and-playbook.md
---

# Two importable constructions: exact check-deletion bookkeeping, and the proven union-layout fusion regime

Provenance: theory imported from a companion manuscript project, pinned as
github.com/MathysRennela/dem-linter @ 1ef09d73, `papers/taxonomy/CLAIMS.md`
(a claims inventory with per-claim proof status; claim numbers below are that
file's). Nothing was constructed or simulated for this note; it is analytic
bookkeeping only. Any candidate these moves produce still goes through the
surrogate → trusted-gate ladder like everything else — a theorem about
parameters is not a certified distance.

## 1. Check deletion: a unary generator with exact parameter bookkeeping

**The theorem** (external claim 12.1, PROVEN there). Deleting `r` independent
checks from a CSS stabilizer code gives `k' = k + r` exactly, `d' ≤ d`, and

```
d' = min( d,  min_{g ∈ S∖S'} ||g||,  min{ ||E|| : E ∈ N(S')∖N(S) } )
```

The third term is the one a naive analysis misses: the newly exposed
logicals include operators *anticommuting* with a deleted generator, not
just stabilizer combinations. The two-term formula is false — witness
`S = ⟨Z₁Z₂⟩`, `d = 2 → d' = 1`.

**Why it is a search move.** Screening a deletion sweep costs rank
arithmetic plus this formula — both polynomial, seconds for a whole family
before any surrogate trial is spent. Two structural bonuses:

- the weight class can only drop (max row weight decreases), so deletions
  of a weight-6 entry can land in weight-4 cells — a cell-crossing move;
- deletion adds no edges, so the layout locality class is preserved
  (an unrestricted entry's deletions stay unrestricted; this move creates
  no new 2d-local entries).

**Guardrails.**

- `d' ≤ d` always: the move trades syndrome information for logicals, and
  the formula prices the trade exactly. It only wins where `(n, k+r, d')`
  Pareto-advances a cell — most deletions lose.
- Deleting checks can disconnect the Tanner graph, which issue
  https://github.com/unitaryfoundation/qldpc-challenge/issues/921 is about
  to enforce as a hard gate. The sweep must filter
  `ncomponents == 1` on the combined graph exactly as the verifier will.
- The theorem is proven; a submission's distance claim is still only what
  the gate certifies or witnesses.

## 2. Union-layout fusion: the proven regime the multi-band campaign did not test

Context: the multi-band campaign
([[2026-09-01-multiband-dense-packing-method.md]]) measured the deployed
shared-check family and closed its envelope (k unlocks at pitch = d+1,
distance preserved only at pitch ≥ 2⌊3d/4⌋, f ≤ 1.33; envelope closure and
Regime-A purity in [[2026-09-01-seam-distillation-falsified.md]]). Those
boards are **not** union-layout fusions: seam checks are thinned to
alternating parities and boundary checks become enlarged weight-4 shared
operators (external claim 14.6) — which is why the campaign's distance
thresholds are empirical, not proven.

The union-layout schedule — every retained face keeps its boundary check,
seams only identify shared data — is a different regime, and its distance
behavior is now **proven**:

- **Fusion theorem** (external 14.1): standard-schedule union-layout fusion
  of any number of clean patches, any seam count:
  `k_Z(Q) = β₁(Q) + c_R(Q) − 1`, `d_Z(Q) = min(height(Q), d_loop(Q))`;
  for a disk, `k_Z = 1` and `d_Z = height(Q) ≥ min(d_A, d_B)`. The
  certificate is topological (rank + height) — cheaper than a distance
  search.
- **Clean X-immunity** (external 14.8, Cor 16.12): all clean-rectangle
  union layouts, any fusion tree, any contact pattern including concave:
  `d_X(Q) ≥ minᵢ d_X(Pᵢ)`.
- **Multi-seam merges can beat `min(d_A, d_B)`** (external 14.1;
  frame+plug: d 5 > 3). This is *not* the distillation mechanism falsified
  in [[2026-09-01-seam-distillation-falsified.md]] — no heterogeneous brick
  mixing, no consumed-logical alchemy; the `d_loop` term is ordinary
  Regime-B winding over the merged extent, exactly what
  [[2026-09-01-boundary-composition-regimes.md]] predicted for Regime B.

**Two proven failure modes, both cheap geometric pre-filters:**

- **Notch enclosure** (external 14.4): a factor's smooth-side notch
  enclosed by the fusion becomes an interior hole of Q with a loop below
  `min(d_A, d_B)` (witness: weight-6 loop from d = 7 factors). Filter: no
  factor notch may end up interior to Q.
- **Rough-row exposure** (external 14.9): a factor's rough rows becoming
  interior to Q, plus a defect adjacent to them, creates weight-2
  X-logicals (factors `d_X = 3, 4` → `d_X(Q) = 2`). Filter: rough-row
  containment — every factor's rough rows are Q's rough rows — is proven
  sufficient (external 14.10).

**Span dichotomy for shared-check schedules** (external 14.7): if a fusion
schedule thins seam checks, then either it is span-preserving (a
polynomial rank check; the fused Z-code equals the union-layout Z-code and
the theorem above applies verbatim) or some dropped face boundary is a
Z-logical of weight ≤ 4, so `d_Z ≤ 4` unconditionally. Naive thinning
without replacement always collapses. This is a zero-distance-budget reject
for an entire schedule class.

**Implications for searches.** The union-layout regime is a generator whose
`(k_Z, d_Z)` are computable by rank arithmetic and geometry *before* any
surrogate trial; candidates arrive with predicted parameters and the gate
confirms them. Given the falsified note's verdict that composition in the
checkerboard class is downgraded to opportunistic, this is the one
composition regime with proven distance content left standing — worth a
bounded enumeration (clean rectangles × contact patterns × both sectors,
failure-mode filters applied) before any distance budget is spent. Open
residuals: X-sector sufficiency of enclosure + exposure for defective
factors is the remaining conjecture there (external 14.5/14.10); the
deployed pitch-threshold regime's distance preservation remains
witness-backed upper bound only (external 14.6).

## Boundary of this note

All theorem statements are imported from the pinned external source and
carry that repo's own proof statuses; "PROVEN there" is a claim about their
manuscript, not a board certification — distances on this board are only
what `verify/` certifies or witnesses. No code was built, swept, or staged;
no candidate advances any cell from this note alone.

## 3. Open lead: theory-guided hole-punching (priced, not run)

Hole-punching is check-deletion on a surface code: punch a face, gain a
logical, risk a hole-loop. Exact pricing from the imported theorems:
d_Z(Q) = min(height(Q), d_loop(Q)) is an exact free score (Thm 15.1);
enclosure and exposure filters make the known failure geometries
ungeneratable; coverage is mandatory; hole loops price at weight >= 4,
equality iff exactly one enclosed removed face — isolated 1x1 punches at
d >= 4 are the safe currency, and k = beta_1 + c_R - 1 counts them
exactly. Method: anneal or SAT-encode big rotated regions at n <= 700,
score Z by the theorem, screen only X. Target: the weight-4 x
local-2d-single frontier where [[656,114,3]] (g = 1.56) sits — shown
deletion-tight in the campaign retrospective, so construction is the only
route. Its d=3 variant was scoped 2026-09-09 and stood down as marginal
(best case g ~ 1.58 vs the board's 1.563). Region-first composition (fuse
clean regions, then punch or gauge the region) is the one unexplored
composition step.
