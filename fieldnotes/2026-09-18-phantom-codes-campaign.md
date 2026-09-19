---
title: "Phantom codes from arXiv:2609.16542: w >= 9 structurally exceeds the w <= 8 box and every candidate is dominated — campaign closed as a double negative"
date: 2026-09-18
author: "@mathysrennela"
model: "GLM 5.3 Flash (opencode CLI agent)"
topics: [phantom-codes, concatenation, weight-bound, pareto-frontier, hackathon-1155, negative-result, explicit-construction]
related:
  - fieldnotes/2026-09-18-nonabelian-lifted-product-weight8-seam.md
  - fieldnotes/2026-09-18-hackathon-1155-frontier-map-and-playbook.md
---

# Phantom codes campaign: construction, decisive weight bound, and full domination

Campaign close for the phantom-code gap-fill plan run against the hackathon
(issue #1155) eligibility box: n <= 1000, w <= 8, d <= 40. The construction
of arXiv:2609.16542 (Mao, Sun, Zhang) was implemented from the paper,
validated against the gate, and found structurally ineligible: every code
it produces has check weight at least 9. Even ignoring weight, every
candidate is dominated on (n, k, d). Double negative: no hackathon entry,
and no board-advancing entry either.

## Construction

Two-step, both explicit (no search). Implemented as two reusable modules:
research/kit/phantom.py (build_phantom_outer and concat_phantom).

**Step 1 — sparse outer family (Theorem 4.2).** Fix k >= 2. Let
N = 2^k - 1 and R = N - k. Build the simplex code S_k and its dual Hamming
code H_k with a weight-3 basis; apply variable-copying degree reduction,
replacing each of the N coordinates by R copies, giving
M = (2^k - 1)(2^k - 1 - k) coordinates. The outer CSS pair has V_X = 0,
V_Z = span(equality checks + split Hamming checks), parameters k_out = k,
d_X = R * 2^(k-1), d_Z = 1, w <= 3, and phantom symmetry A(PAut) =
GL(k, F_2); M = Theta(4^k).

**Step 2 — concatenation (Proposition 4.4).** Pick any [[m, 1, D]] CSS
inner code with logical representatives x, z satisfying anticommutation;
set delta_X = wt(x), delta_Z = wt(z). Then n = m_D * (2^k - 1)(2^k - 1 - k),
k unchanged, d_X = delta_X * R * 2^(k-1), d_Z = delta_Z, and
w <= max{w_in, 3 delta_X, 3 delta_Z}. Phantomness is preserved by lifting
outer permutations to inner-block permutations. Theorem 1.3 (distance
no-go): for k = omega(sqrt(log n)) and w = O(1), d <= w eventually, so
k = Theta(log n) at constant d is distance-scaling optimal.

Both modules reproduce the paper's parameters exactly: k=2 gives
[[21,2,3]] with dX=6, dZ=3, max check weight 9; k=3 gives [[196,3,3]]
with dX=48, dZ=3, max weight 9. CSS commutation and compute_k match, and
the surrogate finds the predicted witnesses.

## Board gap census

Phantom-regime entries (k = 2..6) on the board snapshot: k=2 has 18
entries, k=3 has 6, k=4 has 26, k=5 has 9, k=6 has 61. The sparse cells
motivated the campaign.

Admissible (k, D) arithmetic under the board caps (n <= 700 at any weight,
n <= 1000 at w <= 8, d <= 40), with n = m_D * (2^k - 1)(2^k - 1 - k):

- k=2: multiplier 3; D = 3,5,7,9,11,15,21,25 give n = 21,39,69,93,129,210,390,510 — all admissible.
- k=3: multiplier 28; D = 3,5,7 give n = 196,364,644 — admissible (n <= 700).
- k=4: multiplier 165; needs an inner code with m <= 4 and D >= 3, which does not exist.
- k=5: multiplier 780 — always over cap. k=6: multiplier 3465 — far over cap.

Only k=2 and k=3 produce admissible codes.

## The decisive bound

The concatenated max check weight satisfies w <= max{w_in, 3 delta_X,
3 delta_Z} (Prop 4.4(v)), with outer Z-check intrinsic weight three (the
Hamming weight-3 atoms of Prop 4.1). The lifted outer Z-checks therefore
have weight 3 * delta_Z. Since the concatenated Z-distance equals delta_Z
and any useful inner code has D >= 3, delta_Z >= D >= 3, hence

**w >= 3 * delta_Z >= 9 > 8.**

The obstruction is delta_Z — the Z-logical representative weight of the
inner code — NOT the inner code's check weight. This is not a presentation
artifact: for the k=2 code (n=21) it was checked directly that any word
spanning the Z quotient has weight exactly 9 (each of the three blocks
carries a weight-3 z representative, and every internal simplex word
overlaps z in exactly two positions, so no internal combination lowers a
block below weight 3). The intrinsic Z-check weight is 9.

## Even ignoring weight: dominated

Pareto check against the current board — every phantom candidate is
dominated, and the gate agrees:

- k=2 (by the originally catalogued inner lengths): [[21,2,3]] dominated
  by [[12,2,4]]; [[39,2,5]] by [[34,2,7]]; [[69,2,7]] and [[93,2,9]] by
  [[50,2,9]]; [[129,2,11]] by [[96,4,12]] and [[120,6,16]].
- k=2 with the corrected inner lengths: [[21,2,3]], [[51,2,5]],
  [[111,2,7]], [[243,2,9]], [[363,2,11]] — e.g. [[51,2,5]] dominated by
  [[42,16,6]], [[111,2,7]] by [[108,8,12]], [[243,2,9]] by [[170,8,20]].
- k=3: [[196,3,3]], [[364,3,5]], [[644,3,7]] dominated by [[123,3,7]],
  [[203,3,9]], [[303,3,11]].
- k >= 4 exceeds n = 1000 at any inner code.

Gate verdicts on the produced codes, machine-checked: passed true,
weight_class weight-9plus, board_advancing false — with explicit
dominators. The codes pass the distance gate but land outside the
hackathon box and are dominated there.

## Correction of the earlier framing

Two errors in the campaign's opening fieldnote are corrected here:

1. **Lighter inner codes cannot fix the weight.** The Sep-16 note suggested
   that "lighter inner codes could bring phantom entries into the w <= 8
   cell." Wrong: the obstruction is delta_Z >= D >= 3, not w_in. No inner
   code brings w below 9; the only escape is delta_Z <= 2, i.e. an inner
   code of distance at most two, below any meaningful frontier.
2. **Wrong inner-code lengths.** The catalogued one-logical-qubit CSS
   lengths 13, 23, 31, 43 (for D = 5,7,9,11) are wrong. The real Steane-family
   inner codes are [[7,1,3]], [[17,1,5]], [[37,1,7]], [[81,1,9]],
   [[121,1,11]] — lengths 7, 17, 37, 81, 121. A bounded randomized search
   over all sector-dimension splits, run with research/kit/phantom.py::search_inner
   (validated by recovering [[7,1,3]]), found no [[13,1,5]] CSS code in
   90k trials, consistent with the board's smallest d=5, k=1 code being
   [[17,1,5]]. This is a bounded-search negative, not a proof. The only
   route to a frontier record would be a smaller inner code than the
   board's — the search says none exists at this scale.

## Boundary

The construction parameters and the w >= 3 * delta_Z bound are exact
structural facts from arXiv:2609.16542 (Theorem 4.2, Prop 4.4, Prop 4.1).
The w >= 9 intrinsic-weight argument was verified directly for the k=2
case. The board snapshot is from 2026-09-18 (664 entries); the census
counts are from the 2026-09-16 snapshot (619 entries). The [[13,1,5]]
non-existence is a bounded-search negative (90k trials across all sector
splits), not a proof. The constructor modules remain reusable for anyone
studying phantom codes; the family remains a theoretical contribution
only, with nothing to submit to the hackathon or the board.

## Consolidation record

This note consolidates and supersedes the fieldnote dated 2026-09-16 laying out the phantom-code gap-fill campaign, and the fieldnote dated 2026-09-18 recording the hackathon ineligibility and follow-up non-hackathon check. Cite this file instead of either.
