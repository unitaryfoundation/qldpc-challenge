---
title: "code-calculus v0.1 on this board: reachability pruning buys five percent, and stabilizer parents are outside the state model (issue #4478, directions 6 and 1)"
date: 2026-11-05
author: "@vprusso"
topics: [code-calculus, priced-calculus, stabilizer, reachability, negative-results, audit]
---

Issue #4478 opens code-calculus v0.1 to other hands and lists six directions
nobody has run. This note runs two of them against the board as it stood on
2026-11-05 and reports the numbers, including the ones that close a route.
Direction 6 (compute where a move's children must land and run only the moves
that could reach the frontier) is measured over every CSS parent with n <= 120
by research/audits/cc_reachability.py, record
research/audits/cc_reachability-2026-11-05.json. Direction 1 (stabilizer codes
as parents) turns out to be outside the library's state model on this board, so
it is run as a campaign of symplectic analogs of the three productive moves,
research/campaigns/cc-stabilizer-parents-2026-11-05/, whose summary.json,
manifest.json, and report.json are the record. Every distance below is a
witness-backed upper bound from a 1,000-trial Pauli-weight or RIS screen;
nothing here is a certificate, and nothing was filed.

## Direction 1: stabilizer parents

The direction as written is to convert stabilizer codes to CSS by a local
Clifford and run the calculus on the image. On this board no entry can take
that path: none of the 226 stabilizer entries is CSS up to a local Clifford,
because the verifier refuses such a submission as a CSS code in disguise and
sends it to the CSS board, so every stabilizer entry is genuinely non-CSS by
construction. code-calculus v0.1's CodeState holds X-type and Z-type row
spaces only (github.com/unitaryfoundation/code-calculus @ b8a7465,
`spec/REPRESENTATION.md`), so it cannot load any of them. A stabilizer parent
needs a symplectic calculus, which v0.1 does not have.

The campaign runs the symplectic analogs instead, once from each of the 54
stabilizer entries with n <= 40: delete an independent generator
(C-DELETE-CHECK), remove a qubit and every generator touching it (E-PUNCTURE),
and remove a qubit together with one generator touching it while the others
lose the qubit, kept only when the result is still isotropic (E-PEEL; the CSS
peel is the special case where the surviving rows never touched the qubit in
the chosen sector). Children are deduplicated by the canonical form of the
symplectic matrix, refused on the gate's structural grounds, pruned when the
optimistic point (n', k', d_parent, w') is dominated on the stabilizer board,
screened at 1,000 Pauli-weight RIS trials, and the nondominated survivors with
screened d >= 3 go through verify/validate_candidate.py unchanged. Children at
d <= 2 are counted and not gated: on a board of 226 stabilizer entries they are
nondominated on paper and worthless, which is the lesson of the issue's own
campaign A (349 of its 360 board-advancing children at d = 1).

| move | enumerated | refused before any search | distinct derivable children | pruned at the parent's d | screened | nondominated at d <= 2, not gated | gated at d >= 3 | passed | board-advancing |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| C-DELETE-CHECK | 1,259 | 982 | 108 | 0 | 108 | 70 | 8 | 0 | 0 |
| E-PUNCTURE | 1,324 | 575 | 723 | 0 | 723 | 459 | 236 | 236 | 172 |
| E-PEEL | 8,647 | 8,578 | 69 | 0 | 69 | 45 | 4 | 4 | 4 |

248 children with screened d >= 3 were put through the gate; the cap of 400 was not reached. 240 passed and 8 were refused as exact duplicates of board entries. Of the 240, 176 are board-advancing on the stabilizer board and 64 are dominated. The 176 advancing children are 8 distinct (n, k, d, w) points from 8 parents (puncturing a cyclic parent at each of its qubits gives one point many times over, since the probe deduplicates exact displays and not permutations), 172 of them punctures and 4 peels, and the largest screened distance is 4. 574 further children were nondominated at the screen but read d <= 2 and were not gated.

The best 8 points by kd^2/n:

| child (upper bound at 1,000 trials) | w | copies | move | parent | kd^2/n |
|---|---:|---:|---|---|---:|
| [[26,7,4]] | 8 | 26 | E-PUNCTURE | 27-3-7 | 4.31 |
| [[27,7,4]] | 8 | 27 | E-PUNCTURE | 28-4-6 | 4.15 |
| [[11,5,3]] | 8 | 4 | E-PUNCTURE | 12-4-4 | 4.09 |
| [[15,4,3]] | 5 | 4 | E-PEEL | 16-4-4-s | 2.40 |
| [[19,5,3]] | 6 | 19 | E-PUNCTURE | 20-3-5 | 2.37 |
| [[32,6,3]] | 7 | 32 | E-PUNCTURE | 33-2-8 | 1.69 |
| [[26,4,3]] | 5 | 26 | E-PUNCTURE | 27-2-6 | 1.38 |
| [[38,4,3]] | 5 | 38 | E-PUNCTURE | 39-2-7 | 0.95 |

What this says about the direction. The moves transfer to symplectic form
without difficulty, though E-PEEL almost never derives on a non-CSS parent
(the surviving generators that touched the qubit stop commuting), and
C-DELETE-CHECK is refused on most parents because their displays carry
dependent generators. The optimistic domination test pruned nothing here: on
a board of 226 stabilizer entries there is almost never a dominator at the
parent's distance, which is the sparse-board version of the direction 6
result below. The stabilizer board is sparse enough that a puncture of a
small parent (k <= 4 here) lands nondominated at almost every n it has not seen. That
is a fact about the stabilizer board's occupancy, not about the moves: the CSS
board holds better codes at every one of these (n, k) and the two boards are
ranked apart by rule. The children are staged under the run's staging
directory with their witnesses and verdicts (gitignored working output, not
cited here); none is filed, and a filing would need the ladder and, for any
d-only gain, the matched-depth pair audit of research/AUTORESEARCH.md section
5b. The structural finding is the durable one: direction 1 needs a symplectic
extension of the calculus before any of the library's machinery (the planner,
the ledger, the exporter) can touch a stabilizer parent, and the campaign's
negative results record the moves that produced nothing at d >= 3.

## Direction 6: compute where a move's children must land, and skip the rest

The proposal is to compute the (n, k, d, w) region a parent's children must
land in and run only the moves that could reach the frontier. The calculus
makes the first half cheap. Under C-DELETE-CHECK a child has n' = n and
k' = k + 1; under E-PEEL n' = n - 1 and, on every child the 2026-11-02 sweep
gated, k' = k; under E-PUNCTURE n' = n - 1 and k' = k - 1 + (rows removed),
which ran from k + 1 to k + 29 on those children. In every case w' <= w and
d' <= d, and (n', k', w') is exact from ranks alone, so the only unknown is how
far d falls. research/audits/cc_reachability.py enumerates the three moves over
every CSS parent with n <= 120 with the library's own semantics, applies the
gate's structural refusals, and asks whether the optimistic child
(n', k', d_parent, w') is dominated in the strictest cell it could land in. If
it is, no distance search on that child can pay.
research/audits/cc_reachability-2026-11-05.json is the record.

| move | enumerated | refused before any search | derivable children | pruned by the optimistic test | left for a witness search |
|---|---:|---:|---:|---:|---:|
| C-DELETE-CHECK | 51,335 | 33,603 (33,476 dependent rows) | 17,732 | 1,185 (6.7%) | 16,547 |
| E-PEEL | 8,515 | 965 | 7,550 | 1,130 (15.0%) | 6,420 |
| E-PUNCTURE | 61,086 | 33,876 (27,314 dependent displays, 6,047 bare qubits) | 27,210 | 538 (2.0%) | 26,672 |

The filter is sound but weak. Across 1,009 parents it removes 2,853 of 52,492
derivable children, 5.4 percent, and empties only 14 parents; 411 parents have
nothing left, but 397 of those had no derivable child in the first place. The
reason is the board's frontier rule. A child is compared on all four axes
(n, k, d, w) within its cell, and on the board today about seven entries in
ten are nondominated in their cell, so a child read at its parent's distance is
nondominated almost everywhere. What kills a child is the distance it loses
under the move, and that is exactly what a reachability computation cannot
know without a witness search. Direction 6 as stated therefore saves little
here; the bottleneck it was meant to remove is the distance search, and it
cannot remove it.

Two things the enumeration does say. First, the structural refusals are the
real filter: 67,479 of 120,936 enumerated moves never produce a derivable
child, almost all because the parent displays redundant generators (a deletion
of a dependent row changes nothing, and a puncture that leaves a dependent
display has no derivation under v0.1's validate), so a planner that reads the
display's rank first skips more than half the work before any state is built.
Second, against the 664 children the 2026-11-02 sweep put through the gate,
the filter would have skipped 60, of which 2 were board-advancing at the time:
both are the [[53,12,6]] w = 8 peels of 54-12-6-b, dominated now by the
53-12-6-c that landed from the same sweep as PR #4600. That is board drift, not
a false prune. Of the 604 children it would have kept, 232 advanced the board
and 372 did not, which is the filter's precision: it cannot see the distance
drop.

What would make the direction pay is a distance bound that moves with the
move. The library's DistanceLedger carries [lower, upper] intervals, and its
lower endpoints come only from input lower bounds and the licensed addition
rules; for deletion, peel, and puncture the transported lower bound is 0, so
``decide`` never certifies a child above its target without a search. A move
that came with a proven lower bound on d' (a peel that provably keeps d, say,
when the peeled qubit lies on no minimum-weight logical) would turn the
optimistic test into a decision. That is direction 2 of the issue, and the
measurement here is why it matters more than direction 6.

## What to try next

- Direction 2 before direction 6. A transported lower bound on d' is what
  would let the reachability test decide instead of guess; without one the
  test prunes five percent and the distance search stays the cost.
- Read the display's rank first. More than half of the enumerated moves at
  n <= 120 have no derivation because the parent displays redundant generators;
  a planner that reduces the display once per parent skips them for free, and
  the 27,314 punctures refused as dependent displays are a property of v0.1's
  validate that a planner could pre-empt by the same reduction.
- A symplectic CodeState, if direction 1 is to be pursued: the three moves here
  are twenty lines each in symplectic form, and the board's 226 stabilizer
  entries are the parents.

## Reproduction

```
uv run --frozen python research/audits/cc_reachability.py --n-cap 120 \
    --out research/audits/cc_reachability-2026-11-05.json
QLDPC_RUN_ID=cc-stabilizer-parents uv run --extra research \
    python research/campaigns/cc-stabilizer-parents-2026-11-05/run.py --n-cap 40 --gate-cap 400
```

The first takes about six minutes on a cold checkout (the board's structural
pass) and under two on a warm one; the second about twenty minutes, most of it
the gate. The soundness block of the reachability record was computed against
the frontier record of the 2026-11-02 single-step sweep, which is local staging
output and is described in fieldnotes/2026-11-02-code-calculus-v0p1-campaigns.md's
companion submissions (PRs #4588 to #4600 and #4605 to #4626); rerunning
without it leaves that block null.
