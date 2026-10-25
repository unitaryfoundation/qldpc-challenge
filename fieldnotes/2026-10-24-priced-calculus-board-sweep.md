title: Priced construction calculus: board sweep over deletion, peel, puncture, graft
date: 2026-10-24
author: "@MathysRennela"
model: Beam 1.0
topics: [priced-construction-calculus, code-transformations, deletion, peel, puncture, graft, hadamard]
---

## Finding

A broad single-move sweep of the priced construction calculus over challenge
parents with n <= 12 produced 360 board-advancing candidates: 11 with
distance d >= 2 and 349 with d = 1. A follow-up 2-hour campaign over parents
with n <= 40, d >= 3 (deletion, peel, puncture, plus depth-2 peel->delete
chains) produced a further 332 board-advancing candidates, of which 35 are
distinct (n, k, d) triples: 19 with d >= 2 and 16 new d = 1 points. All
candidates were validated with the unchanged challenge verifier
(`passed: true`). Graft, Hadamard, rebase, and extend sweeps found no
board-advancing instances in the ranges tried.

## What was run

Campaign A (n <= 12, single moves):
- Parents: challenge entries with n <= 12 (including `codes/10-2-3-b.json`,
  `codes/12-2-4-b.json`, `codes/12-3-3.json`, `codes/12-4-2.json`).
- Moves: C-DELETE-CHECK, E-PEEL, E-PUNCTURE, E-GRAFT, E-LOCAL-HADAMARD.
- Each derived instance was filtered on Tanner connectivity, screened for
  X/Z logical witnesses up to weight 4, exported as a witness-backed
  upper-bound entry, and checked with `verify/validate_candidate.py`.
- Graft and Hadamard sweeps found no board-advancing instances in this range.

Campaign B (n <= 40, d >= 3, ~2 hours):
- Parents: all CSS entries with n <= 40, d >= 3 (177 parents).
- Moves: C-DELETE-CHECK, E-PEEL, E-PUNCTURE (single), plus depth-2
  peel->delete chains on d >= 4 parents.
- Witness search up to weight 6; 2,386 validated candidates, 332 board-advancing.
- Follow-up checks (E-EXTEND with new qubits, chained peels, non-identity
  P-REBASE over GL(m,2) for m <= 3, C-ADD-CHECK morphing of d = 1 codes)
  produced no additional board-advancing codes.

## Scorecard (board-advancing, d >= 2)

Campaign A:

| Move | Parent | Result | PRs |
| --- | --- | --- | --- |
| E-PUNCTURE | `codes/12-2-4-b.json` | `[[11,3,3]]` (x3) | #4059-#4061 |
| E-PEEL | `codes/12-3-3.json` | `[[11,3,3]]` (x2) | #4062-#4063 |
| C-DELETE-CHECK | `codes/12-4-2.json` | `[[12,5,2]]` (x6) | #4064-#4069 |

Campaign B (best per distinct (n, k, d)):

| (n,k,d) | cell | radius | PR |
| --- | --- | --- | --- |
| [[36,5,2]] | weight-4 / local-2d-single | 1.41 | #4108 |
| [[30,9,2]] | weight-6 / local-2d-single | 4.0 | #4109 |
| [[30,9,3]] | weight-6 / local-2d-single | 4.0 | #4110 |
| [[37,22,2]] | weight-9plus / local-2d-bilayer | 4.47 | #4111 |
| [[35,19,2]] | weight-9plus / local-2d-bilayer | 5.39 | #4112 |
| [[35,19,3]] | weight-9plus / local-2d-bilayer | 5.39 | #4113 |
| [[30,5,2]] | weight-4 / local-2d-single | 3.0 | #4114 |
| [[40,25,2]] | weight-9plus / local-2d-bilayer | 4.12 | #4115 |
| [[40,21,3]] | weight-9plus / unrestricted | inf | #4116 |
| [[34,5,2]] | weight-4 / local-2d-single | 1.41 | #4117 |
| [[30,10,2]] | weight-6 / unrestricted | inf | #4118 |
| [[30,10,3]] | weight-6 / unrestricted | inf | #4119 |
| [[34,17,3]] | weight-9plus / unrestricted | inf | #4120 |
| [[40,17,3]] | weight-9plus / unrestricted | inf | #4121 |
| [[38,11,2]] | weight-6 / local-2d-bilayer | 5.39 | #4122 |
| [[40,11,2]] | weight-6 / local-2d-bilayer | 5.39 | #4123 |
| [[32,19,2]] | weight-9plus / local-2d-bilayer | 3.61 | #4124 |
| [[27,12,2]] | weight-6 / local-2d-bilayer | 5.0 | #4125 |
| [[40,22,3]] | weight-9plus / unrestricted | inf | #4126 |

The d = 3 finds at n = 30-40 extend the d >= 2 frontier well beyond the
n <= 12 range of Campaign A.

## d = 1 codes

Campaign A produced 349 board-advancing d = 1 candidates across 27 distinct
(n, k) pairs, 44 distinct (n, k, cell) groups, and 41 distinct (n, k, w)
triples. The best variant of each (n, k, w) triple was submitted (41 PRs).

Campaign B added 16 new distinct (n, k, w) d = 1 points (n up to 40), all
submitted (#4127-#4142). They advance (n, k) or weight/locality axes but not distance. A
sampled C-ADD-CHECK morphing attempt did not turn any d = 1 code into d = 2;
d >= 2 codes came from d = 3/d = 4 parents via puncture/peel/deletion.

No candidate in either campaign was a d-only gain (no entry where distance is
the sole strict improvement), so no matched-depth `leader_audit.py pair` audits
were owed.

## Submission tally

- Campaign A d >= 2: 11 PRs (#4059-#4069)
- Campaign A d = 1 (best per (n, k, w)): 41 PRs
- Campaign B d >= 2 (best per (n, k, d)): 19 PRs (#4108-#4126)
- Campaign B d = 1 (new distinct (n, k, w)): 16 PRs (#4127-#4142)
- Fieldnote: PR #4070
- Consumer planner (code-calculus-dev): PR #103

Total code submissions: 87. Total PRs opened in this campaign (including
fieldnote): 88.

## Suggested next steps

1. Chain moves (peel then delete, delete then peel) at depth >= 3 on d >= 4 parents.
2. Exercise E-EXTEND with `new_qubits != ()` (patch growth).
3. Test non-identity P-REBASE over larger sectors of GL(m,2).
4. Deepen witness search beyond weight 6 on the surviving d = 1 codes.
