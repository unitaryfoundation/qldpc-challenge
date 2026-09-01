---
title: "The multi-band dense-packing campaign: the approach, and how each result was obtained"
date: 2026-09-01
author: "@mathysrennela"
model: "GLM 5.3 Flash"
topics: [dense-packed-surface-code, scalable-families, geometric-efficiency, campaign-method, manifold-mapping]
related:
  - 2026-08-29-g-parity-agenda 2.md
  - 2026-08-26-g-frontier-sat-plan.md
---

# The multi-band dense-packing campaign: the approach, and how each result was obtained

This note is the method narrative for the multi-band portion of the g ≥ 1
campaign (2026-08-29 → 2026-09-01). The parent note
[[2026-08-29-g-parity-agenda 2.md]] records the campaign as it happened,
in timestamped updates. This note re-organizes the same material around
one question: **what is the multi-band approach, and how was each of its
results actually obtained?** It contains no new results; every number
below traces back to a section of the parent note or to a board artifact.

## 1. The construction

The multi-band family is a two-parameter generalization of the dense
packed surface code of arXiv:2511.06758 (Fujiu et al., PRA 113, 042412).
The published builder packs **two** bands of square surface-code patches
at pitch d − 1 on a shared plane; the family generalizes to

    rows × m patches at an independently chosen pitch,

where:

- **even bands** carry m patches at x-offsets j·Px, Px = 2d + 2;
- **odd bands** carry m − 1 patches offset half a horizontal pitch
  (x-offset d + 1 + j·Px) — the stagger that lets adjacent bands share
  boundary infrastructure;
- **pitch** is the vertical spacing y₀ = r·pitch between band starts;
- qubit conventions are the published ones: data on odd/odd sites,
  (x+y) % 4 == 2 ancillas are X-checks, the rest Z-checks, each check's
  support being its diagonal data neighbours present in the mask;
- the occupied-site mask per band is a union of three rules: window
  interiors at (x+y) % 2 == 0, vertical edge columns at a band-phase
  (%4 ∈ {0, 2} alternating), horizontal edge rows at the reverse phase.

At rows = 2, pitch = d − 1 the construction reduces to the published
two-band builder; the full-patch-count logical count is

    k = rows·m − ⌊rows/2⌋.

The family was already on the board before this campaign — @Xo1otl's
2026-08-20 entries (`codes/126-6-5.json`, `codes/168-8-5.json`,
`codes/202-10-5.json`, `codes/278-14-5.json`, `codes/676-36-5.json`,
`codes/418-10-7.json`, `codes/615-15-7.json`, `codes/666-10-9.json`,
`codes/398-54-3.json`, `codes/570-78-3.json` and the deeper d = 3
entries) are points of this manifold. The campaign's contribution was to
map the manifold, occupy its uncovered frontier, and measure its
thresholds and asymptote.

## 2. The method: validate, enumerate, subtract, screen

Every result below came from the same four-step discipline. Stating it
once; the per-result sections say which step did the work.

1. **Validate the builder before trusting anything downstream.** The
   reconstructed mask rule was checked bit-exactly (data coordinates and
   check-support sets) against the published builder at rows = 2,
   pitch = d − 1 for d = 3, 5, 7; and its exact (n, k) — by GF(2) rank
   arithmetic, not the closed form — was checked against all 15 board
   members of the family, each CSS-commuting, single Tanner component,
   max check weight 4.
2. **Enumerate the parameter manifold exactly.** For each (d, rows, m,
   pitch) point: build the matrices, compute n, k, CSS commutation and
   Tanner connectivity by exact GF(2) rank, never by the k closed form.
3. **Subtract what the board already holds.** A point is interesting
   only if its (n, k, d) is Pareto-nondominated against every board
   entry *including open PRs from this account* — the first sweep pass
   missed the campaign's own earlier PRs and briefly rediscovered
   [[641,17,7]]; the correction is part of the method now.
4. **Screen every survivor with a distance witness.** Rank arithmetic
   says nothing about distance — degenerate masks scored g up to 5.5 by
   (n, k) alone and every one was refuted by the witness search. A
   survivor only counts after a random-information-set search fails to
   find a logical below the target weight; all submitted codes carry
   witness-backed **upper bounds**, verified by the trusted gate, never
   certified exact distances.

## 3. Result 1 — the manifold subtraction (2026-08-29)

**Question:** at pitch_min(d), which (n, k, d) points of the family are
not already on the board?

**How:** enumerate all (rows, m) at pitch_min(d) with n ≤ 700 (higher
pitch only adds n at fixed k, so it is dominated), filter to CSS /
single-component / weight ≤ 4, score g = kd²/n, subtract every board
(n, k, d).

**Outcome** (d = 3, 5, 7, 9; pitch_min was then unmeasured at d = 11, 13):
261 of 263 d = 3 manifold points under the cap were uncovered, 71 of 77
at d = 5, 20 of 22 at d = 7, 9 of 10 at d = 9. Four best-uncovered
survivors were staged, witnessed, gate-passed, and submitted:

| code | g | why it mattered |
|---|---|---|
| [[659,35,5]] | 1.3278 | dominates the terminal ladder rung [[671,35,5]] (PR #745) at same k, d, 12 fewer qubits |
| [[663,91,3]] | 1.2353 | the family's best d = 3; dominates [[672,85,3]] and [[700,85,3]] |
| [[578,14,7]] | 1.1869 | fills the k-gap between [[418,10,7]] and [[615,15,7]] |
| [[625,33,5]] | 1.3200 | new d = 5 Pareto point between the ladder rungs and [[676,36,5]] |

Submitted as PRs #749–#752, each through the kit's own submission path
(so the per-side witnesses are embedded in the JSONs) and the classroom
CLI verification.

## 4. Result 2 — the exhaustive sweep and the frontier occupation (2026-08-31)

**Question:** with the subtraction done coarsely, what does the *full*
parameter grid yield?

**How:** the complete (d, rows, m, pitch) space — d ∈ {3, 5, 7, 9, 11,
13}, rows 1–8, m 1–20, pitch in [d−2, d+3], n ≤ 700; 13,376 points —
enumerated with the validated builder, scored by exact rank, filtered
against the board Pareto front *including open PRs*. 549 unique
nondominated triplets survived; 336 passed a 4,000-trial witness screen;
the top survivors were re-searched at 20,000 trials and pushed through
the trusted gate. A later deep re-screen of all 336 survivors at
300,000 trials each (~91 min on the fast backend) produced **zero
refutations** — the survivor map is hardened at that budget.

**Outcome:** eight new PRs (#758–#765), all Pareto-nondominated d = 5
points — frontier breadth rather than record challenges:

- [[608,32,5]] and [[532,28,5]] at g = 1.3158 — the highest capped-size
  g the family reaches;
- [[515,27,5]], [[595,31,5]], [[557,29,5]], [[519,27,5]], [[481,25,5]],
  [[443,23,5]] at g = 1.298–1.311.

Together with the subtraction survivors these became the bulk of the
campaign's ~100 submission PRs (the d = 3 frontier wave, PRs #810–#865,
extends the same family's d = 3 column toward [[663,91,3]]'s region).

## 5. Result 3 — the two thresholds (2026-08-31)

**Question:** which pitches give a working code at all, and which give
one at full distance?

**How:** for rows = 4, m = 3 configurations at each pitch, exact rank
arithmetic answers the k-unlock question (is k = rows·m − ⌊rows/2⌋ or
the published 2m − 1?); a 4,000-trial witness answers the distance
question. The measurement method was itself validated first: it
reproduces the known pitch_min values 6, 10, 12 at d = 5, 7, 9.

**Outcome:**

- **k unlocks at pitch = d + 1** (exact, at every d measured). Below
  that, bands overlap, share ancillas, check rows merge or annihilate,
  and k is *not* additive across bands.
- **Distance is preserved only at pitch ≥ pitch_min(d) = 2⌊3d/4⌋**,
  measured at five points: 6, 10, 12, 16, 18 for d = 5, 7, 9, 11, 13
  (method validated on the first three). Between d + 1 and pitch_min
  sits a previously invisible window: full k, deficient distance.
- Caveats carried forward: all measured d are odd (the family's regime);
  even d untested; five points is thin evidence for the closed form —
  d = 15, 17 would confirm or break it.

## 6. Result 4 — the asymptote, and the process error that shaped it (2026-08-31)

**Question:** what is sup g for the family as rows, m → ∞ — i.e. does
the multi-band constant beat the two-band ladder's 4/3?

**How — including the error, because it is half the lesson:** the first
asymptotic scan ran ~2.5 h of parameter space on the closed-form
expected_k without validating it at the scan domain's extremes. Exact
rank on a heavily-overlapped configuration (d = 5, rows = 24, m = 32,
pitch = 2) gave k = 63, not 756: the scan's headline sup g ≈ 3.58 was
garbage. Method rule adopted from this: **any closed-form invariant is
exact-verified at the extremes of its scan domain before an expensive
scan is launched on it.**

The second pass found the validity boundary's fine structure: the closed
form holds at pitch ≥ d + 1 but partially collapses at pitch = d + 2 for
d = 5, 7 (parity/phase-dependent, not yet characterized in closed
form). A rising g ≈ 1.6 ladder at pitch = d + 1 then looked like the
result — until the first witness screen past d = 5 refuted it: at d = 7,
pitch = 8 the distance collapses to d_ub = 6. The refutation was
predictable from Result 3 — pitch_min(d) ≈ 1.5d exceeds d + 1 for every
d ≥ 7; the d = 5 point held only because pitch_min(5) = 6 = d + 1 sits
exactly on the boundary.

**Outcome — recomputed at the correct pitch (pitch = pitch_min, rows =
24, m = 32, exact rank, 4,000-trial witnesses):**

| d | pitch | n | exact k | g | witness |
|---|---|---|---|---|---|
| 5 | 6 | 13,196 | 756 | **1.4323** | holds (d_ub = 5) |
| 7 | 10 | 28,488 | 756 | 1.3003 | holds (d_ub = 7) |
| 9 | 12 | 44,124 | 756 | 1.3878 | pending at close |
| 11 | 16 | 70,086 | 756 | 1.3052 | pending at close |
| 13 | 18 | 93,540 | 756 | 1.3659 | pending at close |

The corrected asymptote **oscillates around 1.30–1.43 with no rising
trend in d** (d ≡ 1 mod 4 sits higher than d ≡ 3 mod 4, echoing the
⌊3d/4⌋ in the threshold), and g has not converged in rows/m. The
witnessed sup is **1.4323 at d = 5 — above the 4/3 two-band asymptote**,
so at weight-4, r = √2 the achievable constant c in g = c is at least
~1.43 and Bravyi–Terhal's weight-4 cap c(4) must sit above that. All
valid-regime configurations have n ≥ 13,196 — an order of magnitude
over the board's 700-qubit cap — so the result belongs to the sup-g
open problem, not the submission queue. At capped sizes the family's
best is 1.3158/1.3278: the cap is what makes g hard, because boundary
costs are paid in full.

## 7. What the approach does and does not claim

- Every distance figure is a **witness-backed upper bound**, not a
  certified exact distance; every g inherits that tier.
- The two thresholds (Result 3) and the validity boundary's fine
  structure are empirical regularities over measured points, not proofs.
- The 1.43 asymptote claim is exactly as strong as its witnesses
  (d = 5, 7 held at the corrected pitch; the rest pending at close).
- The negative results count as results: the rank-arithmetic g = 5.5
  masks, the 3.58 scan, and the 1.6 ladder were all caught by the
  validate-before-scan and witness-screen steps — the method's error
  handling is what makes the surviving numbers trustworthy.

## 8. Open problems left by the campaign

1. Closed-form characterization of the k validity boundary (why
   pitch = d + 1 holds at d = 5 and pitch = d + 2 partially collapses —
   the parity/phase structure behind 2⌊3d/4⌋).
2. Convergence of g in rows, m at pitch = pitch_min (not observed by
   rows = 24, m = 32).
3. The d = 15, 17 pitch_min measurements — confirm or break
   pitch_min(d) = 2⌊3d/4⌋.
4. Even-d behaviour of the family (untested; the stagger's parity
   structure suggests it matters).
5. Certification of the small rungs (MILP, maintainer-run) — the family
   claim currently rests entirely on upper-bound distances.
