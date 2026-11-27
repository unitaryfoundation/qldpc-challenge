---
title: "code-calculus v0.3.2 direction 2: coset lifted products over small nonabelian groups reach new codes, all at distance 2"
date: 2026-11-27
author: "@vprusso"
model: "Claude Fable 5.1"
topics: [code-calculus, lifted-product, coset, campaign, negative-result]
---

## Summary

Direction 2 of issue #7377 asks whether `L-LIFTED` with a nontrivial subgroup
`H <= G` (code-calculus v0.3.2, `lifted_product(..., subgroup=)`) reaches
codes the regular lifts over groups of the same block count do not. Over ten
nonabelian groups of order 6 to 24, every subgroup class of index 2 to 8, and
one-row group-algebra protographs as the base matrices, it does: 23 one-row
classes with H non-normal have rank and row-space-intersection invariants
that no regular 1x2 lift over any group of that order shares, and 210 more
appear at 1x3 against a sampled comparator. A normal H gives the regular lift
over the quotient group, row for row, and nothing else. Every class found has
distance 2, and two-row bases reach distance 4 at best, so none of it is a
frontier point by distance; the gate labels five d = 2 classes
board-advancing in the weight-8 unrestricted cell, and they are staged, not
filed. The campaign record is `research/campaigns/cc-v032-direction2-coset-lifts/REPORT.md`,
with `manifest.json`, the runner `run.py`, the code-level audit
`audit_new.py`, and four result files beside it.

## What ran

- `run.py` against code-calculus v0.3.2 (github.com/unitaryfoundation/code-calculus
  @ 474104a257f79019a61bb3e8d9c7ae25e43047a6) and this repository's verifier.
  Groups S3, D4, Q8, D5, A4, D6, Dic3, S4, D7, D8; 47 (group, subgroup class)
  pairs, 27 with H normal. Base shapes 1x2 (3.59 M pairs, exhaustive for 22
  subgroups, 100,000 sampled otherwise) and 1x3 (2,000 pairs per subgroup);
  2x2 (1,500 per subgroup) in an earlier pass. Comparators: 518,397 regular
  lifts over the abelian groups of order 2 to 8 and over S3, D4, Q8.
- Classes keyed on the nauty certificate of the typed Tanner graph of the
  full generated row set. Two earlier keys were wrong in opposite directions
  and are recorded as dead ends: the WL signature of the library's retained
  display (which depends on which dependent rows were dropped) called the
  quotient lifts of normal subgroups new 3,380 times, and the WL hash of the
  full rows merged distinct codes (16 classes where nauty separates 107).
- The 295 new classes were packaged with `research/kit/submit.make_submission`
  and gated with `research/kit/coordination.gate_and_record` (the trusted
  `verify/validate_candidate.py`, RIS at 20,000 trials per side): 295 passed,
  0 refuted, all at d = 2, 8,282 s in all.
- `audit_new.py` compared each 1x2 class with every regular 1x2 lift of the
  same block count (262 constructions over the groups of order 4, 6, and 8),
  by (n, rank_X, rank_Z, intersection) first and `permutation_audit.decide`
  on a match: no match, so all 23 are new as codes.

## Findings

1. Non-normal subgroups do produce codes outside the regular-lift family at
   matched block count and base shape. The 23 one-row witnesses come from
   D4, A4, D6, S4 (two subgroup classes), and D8, at n = 20, 30, and 40.
2. Normal subgroups produce nothing new: the coset lift equals the quotient
   lift. Exhaustive at 1x2 in every group (0 new classes), and the 62 "new"
   normal-H classes at 1x3 measure the sampled comparator's coverage, not
   novelty.
3. Distance is the wall. One-row bases over sums of at most two group
   elements give d = 2 on every class tried (checks of weight 5 to 8); 2x2
   bases give 219 classes at d = 2, 15 at d = 3, and 6 at d = 4 (n = 32 and
   64), none board-advancing.
4. Five d = 2 classes are board-advancing by the gate's rule: [[40,24,2]] w=8
   (two classes, D4) and [[80,46,2]] w=8 (three classes, D8), in the weight-8
   unrestricted cell. They are staged under the gitignored candidates
   directory; filing a d = 2 record is a decision for a maintainer.

## What the next searcher should know

- The direction's text proposes board codes as the outer and inner factors;
  this campaign used one-row and two-row algebra protographs, so it answers
  the fingerprint question at the protograph level only. Board factors are
  the next run.
- Entries of three or more group elements, or index above 8 (S4 has
  subgroups of index 12 and 24 the cap excluded), are where d >= 3 might
  appear at one-row bases.
- For code-calculus itself: a consumer comparing lifts across quotients must
  not key on the WL signature of `lifted_product`'s retained display.
  `machine.ingestion.ingest` gives a canonical display, and the fingerprint
  (a row-space invariant) is safe; the display's WL signature is not.

## Spent

About 8.7 CPU-hours on one laptop core: 3,014 s for the committed phase A,
7,981 s for the three superseded passes, 8,282 s gating the committed classes,
and 12,160 s gating the superseded ones.
