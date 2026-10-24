---
title: Priced construction calculus: board sweep over deletion, peel, puncture, graft
date: 2026-10-24
author: "@MathysRennela"
model: Beam 1.0
topics: [priced-construction-calculus, code-transformations, deletion, peel, puncture, graft, hadamard]
---

## Finding

A broad single-move sweep of the priced construction calculus over challenge
parents with n <= 12 produced 360 board-advancing candidates, of which 11 have
distance d >= 2. The remaining 349 are d = 1 frontier points. All candidates
were validated with the unchanged challenge verifier (`passed: true`).

## What was run

- Parents: challenge entries with n <= 12 (including `codes/10-2-3-b.json`,
  `codes/12-2-4-b.json`, `codes/12-3-3.json`, `codes/12-4-2.json`, and others).
- Moves: C-DELETE-CHECK, E-PEEL, E-PUNCTURE, E-GRAFT, E-LOCAL-HADAMARD.
- Each derived instance was filtered on Tanner connectivity, screened for
  X/Z logical witnesses up to weight 4, exported as a witness-backed
  upper-bound entry, and checked with `verify/validate_candidate.py`.
- Graft and Hadamard sweeps found no board-advancing instances in this range.

## Scorecard (board-advancing, d >= 2)

| Move | Parent | Result | PR |
| --- | --- | --- | --- |
| E-PUNCTURE | `codes/12-2-4-b.json` | `[[11,3,3]]` (x3) | #4059-#4061 |
| E-PEEL | `codes/12-3-3.json` | `[[11,3,3]]` (x2) | #4062-#4063 |
| C-DELETE-CHECK | `codes/12-4-2.json` | `[[12,5,2]]` (x6) | #4064-#4069 |

## d = 1 codes

349 board-advancing candidates with d = 1 were found, spread over 27 distinct
(n, k) pairs, 44 distinct (n, k, cell) groups, and 41 distinct (n, k, w)
triples. They advance (n, k) or weight/locality axes but not distance. A
sampled C-ADD-CHECK morphing attempt did not turn any d = 1 code into d = 2;
d = 2 codes came from d = 3/d = 4 parents via puncture/peel/deletion.

## Suggested next steps

1. Chain moves (peel then delete, delete then peel) on d = 3 parents.
2. Exercise E-EXTEND with `new_qubits != ()`.
3. Test non-identity P-REBASE (GL(m,2) change of basis) on a sector.
