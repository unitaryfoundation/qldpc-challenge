---
title: "code-calculus v0.3.2 direction 8: move applicability over the CSS board, by family, with the v0.2 pilots as pools"
date: 2026-11-27
author: "@vprusso"
model: "Claude Fable 5.1"
topics: [code-calculus, applicability, calibration, campaign]
---

## Summary

Direction 8 of issue #7377 asks for code-calculus v0.3.2's
`move_applicability_report` over the parents of the v0.2 negative pilots, as
a board-wide table of what each move family can and cannot do before any
search is paid for. It was run over every CSS entry on the board, 3,529
parents, with the pilots' parent definitions as labels. Deletion and
puncture apply almost everywhere (84 and 70 percent of candidates usable,
usable on 3,009 and 2,822 parents); peels apply exactly where a sector has a
column-weight-1 qubit (2,064 parents); grafts and rebases derive but almost
never stay within the parent's weight (8 and 4 percent usable); extension is
closed except on 32 d = 1 placeholders. For the pilots: delete chains
(campaign 2) and puncture chains (campaign 4) did not fail on applicability,
weight shedding by rebase and graft (campaign 3) did, and the deletions that
follow a sector swap (campaign 6) apply to 81 percent of the asymmetric
parents. The record is
`research/campaigns/cc-v032-direction8-applicability/REPORT.md`, with the
runner, the two analysis scripts, and four result files beside it.

## What ran

- `run.py` on code-calculus v0.3.2 (github.com/unitaryfoundation/code-calculus
  @ 474104a257f79019a61bb3e8d9c7ae25e43047a6): for each CSS entry of `codes/`
  at fdccaecfc, `CodeState.from_challenge` and
  `move_applicability_report(state, weight_cap=state.w(), rebase=n <= 100)`.
  A usable child is one that derives and passes the consumer's screens (no
  bare qubit, no weight-1 logical, connected, no heavier than the parent).
  `P-REBASE` is quadratic in the row count (37,812 mixes and nine minutes at
  n = 288) and was asked for only up to n = 100, 1,133 parents.
- Pools, as labels: C2 (d >= 8, w <= 8), C3 (d >= 8, w >= 8), C4 (n >= 500,
  d >= 6), C6 (d_X != d_Z), the parent definitions of issue #6198's campaigns
  2, 3, 4, and 6.
- `aggregate.py` gives, per pool and family, the parents asked, the candidate
  domain, derived and usable counts, the parents with a usable child, and
  the dominant blocker with its share of the blocked candidates;
  `analyze.py` the dead parents, the peel precondition, the usable share by
  n band, and which families ever leave a lighter display.

## Findings

1. Deletion: 850,421 candidates, all derive, 718,019 usable; the only
   blocker is a child with a weight-1 logical. Puncture: 1,002,327 candidates,
   697,322 usable, the same blocker for 83 percent of the rest. Both usable
   shares grow with n (deletions 42 percent at n <= 50, 88 percent at 201 to
   500).
2. Peel: 8 percent of 2,004,654 candidates derive (the unique-touch premise
   refuses the rest, evenly across sectors) and the precondition is exact:
   2,432 parents have a column-weight-1 qubit, 2,064 have a usable peel, none
   without one.
3. Graft and rebase do not shed weight in one step. Grafts derive 94 percent
   of the time and are usable 8 percent of the time (93 percent of the blocked
   are over the cap); rebases below n = 100 are usable for 3.9 percent of
   918,892 mixes, and only 11 of 1,121 parents have a rebased child lighter
   than the parent, by one unit. Punctures leave a lighter display on 142
   parents, deletions on 48.
4. Extension is closed: 4,779 of 2,008,183 bounded additions derive, 35 are
   usable, all on d = 1 placeholders; the refusal is opposite-sector
   commutation. This matches v0.1's 0 of 736 strict additions.
5. 242 parents have no usable child in any family, 160 of them at n <= 50 and
   2 above n = 500.
6. Pilots: C2 deletion usable on all 1,154 parents (94 percent of candidates);
   C3 rebase usable on 8 of 98 parents asked and graft on 328 of 1,158, with
   every blocked candidate over the cap; C4 puncture usable on all 613 parents,
   peel on 289; C6 follow-up deletion usable on 503 of 622.

## What the next searcher should know

- The report is single-step and caps the child at the parent's weight; the
  C3 question wants the cap at the next weight class and the families after
  an `E-LOCAL-HADAMARD`, which the report does not cover. Depth-2 chains on C2
  and C4 are the applicability number those campaigns needed.
- The 242 dead parents are a planner stop-list (`result-readings.json`).
- For the library: about 0.35 s per qubit without `P-REBASE` (343 s at
  n = 996); a `families=` argument on the report would let a consumer pay for
  one family.

## Spent

64.9 CPU-hours (median 16 s per parent, 584 s at most) and about 5.9 hours
of wall time on one laptop with up to fourteen workers; no parent failed.
