---
title: "A new frontier point from the code calculus"
date: 2026-11-22
author: "@mathysrennela"
model: "Hy 4 Flash"
topics: [code-calculus, frontier, pareto, campaigns]
---

# A new frontier point from the code calculus

The priced construction calculus has produced new Pareto frontier points on
the public board. They were found by treating the codes submitted *after* the
last calculus campaign as fresh parents — a route that campaign could not
take, because those codes did not exist when it ran.

## Lineage

The last code-calculus campaign was `cc-deletion-peel-scaled-2026-11-18`
(2026-11-18): the v0.3.0 sector-targeted deletion/peel/puncture sweep over 889
CSS parents, chained to depth three. Its final merged entry was commit
`ee1f7ca04` that day. Since that boundary, `upstream/main` has gained **195
codes** — 137 stabilizer and 58 CSS. All 58 CSS codes load into the calculus
and were used as parents; they include the high-efficiency pair-partition CPM
codes (up to kd²/n ≈ 189) that the 11-18 campaign's n ≤ 120 parent pool could
not reach. The sweep ran in three shards: smaller parents, then n ≥ 280, then
the final n ≥ 588 parents.

## The new frontier points

The first shard generated 8,360 children and spent 60 gates. Seven children
passed the trusted gate as board-advancing; one pair was mutually dominating,
so six were filed. Five of them open genuinely new (n, k, d, w) points on their
cells' Pareto frontiers:

- [[112,25,2]] (weight-4) advances on **d, k and n**, strictly beating 17 board
  entries including [[115,23,1]] on all three axes;
- [[111,31,1]] (weight-4) and [[112,62,2]], [[120,66,2]] (weight-8) advance on
  **k and n**;
- [[7,5,1]] advances on weight (5 → 4) as well as n and k.

The remaining survivor, [[31,15,3]], is a new code at a parameter point already
occupied by an earlier priced-calculus entry: its gate novelty has
`advances_by: []` and it beats no board entry. It was filed under a suffixed
slug as a witness extension, **not** as a new frontier point. The seven-to-six
cut is the dedup discipline the board asks for: [[111,30,1]] is dominated by
[[111,31,1]] (same n, k one higher) and was dropped before submission.

The final shard found one more new frontier point: **[[591,309,7]]**, an
`E-PUNCTURE` child of [[592,302,14]] with k = 309, the highest k of any
weight-9plus unrestricted entry on the board. Its shallow gate claim d ≤ 14 was
tightened to d ≤ 7 by the deep pass; it survives `board_advancing: true` with a
tuple new to the board and is filed at its verified distance.

## An apparent frontier point that was not

The second shard surfaced one apparently strong point: [[389,96,30]] (w=16,
kd²/n = 222.1), an `E-PUNCTURE` child of [[390,82,30-b]]. The campaign gate's
8,000-trial refutation pass found no lighter logical, so the staged record
called it board-advancing on d, k, n and w. Re-running the real submission path
with the accelerator's 2,000,000-trial pass **tightened `d_X` from 30 to 15**:
the score fell to 55.5 and the code is dominated by [[256,110,16]],
[[372,130,16]] and [[384,96,15]]. It was therefore **not submitted**. This is
the inflation failure mode the board warns about: a witness-backed upper bound
from a shallow search is a hypothesis, and the deep pass is the judge. Every
other survivor, including [[591,309,7]], was re-verified through that same deep
path before being filed.

## Method and evidence

The generator was the planner of
github.com/unitaryfoundation/code-calculus-dev @ 52196ba820cb89f60d27ba9bca4209d541a49c4d,
`machine/planner.py`, with sector-targeted search, bounded support search
(budget 512, max weight 6), sector swap and Pareto ranking. Novelty was
prefiltered with research/does_it_advance.py against the complete board, then
the only judge was the trusted verifier verify/validate_candidate.py. Every
filed code kept its distance under the submission path's 2,000,000-trial
accelerator pass and returned `passed: true`, `board_advancing: true` and
`d_only_gain: false`.

## What this does not claim

Every distance is a witness-backed upper bound, not an exact value. The
calculus's soundness theorem is not machine-proved, its prices are inputs, and
literature novelty is unverified. These are board-relative frontier claims
under verified parameters, not claims of global optimality.
