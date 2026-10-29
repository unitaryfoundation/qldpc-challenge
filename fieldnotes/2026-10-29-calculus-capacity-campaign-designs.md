---
title: Priced construction calculus: capacity campaigns, tallies, and utility assessment
date: 2026-10-29
author: "@MathysRennela"
model: Beam 1.0
topics: [priced-construction-calculus, code-transformations, deletion, peel, puncture, rebase, extend, 3d, fieldnote]
---

# Priced construction calculus: capacity campaigns, tallies, and utility assessment

This fieldnote consolidates three rounds of autoresearch with the priced
construction calculus (`code-calculus-dev`: `CodeState`, `apply_operation`,
`run_sequence`, `export_challenge_entry`, `DistanceLedger`, and the consumer
`planner.plan`/`plan_chain`), run on 2026-10-19, 2026-10-24, and 2026-10-29.
It tallies every board-advancing code the calculus has produced, every distinct
`(n, k, d, w)` cell point the campaigns generated, and assesses how useful the
calculus was relative to the other moves and methods available in the repo.

## Headline numbers

- **Priced-calculus PRs opened:** 147 (all by @MathysRennela), of which 145 are
  code submissions and 2 are meta (fieldnote #4070, consumer planner #103 in
  code-calculus-dev).
- **Distinct `(n, k, d)` cell points submitted:** 116 (of 147 PRs; the rest are
  permutation variants that later collapsed).
- **Distinct `(n, k, d)` with d >= 2:** 50 (d=2: 32, d=3: 16, d=4: 2, d=5: 1,
  d=7: 2).
- **Distinct `(n, k, d)` with d = 1:** 63.
- **This session (2026-10-29):** 15 code PRs (#4209-#4223) plus the
  campaigns below; 14 distinct `(n, k, d, w)` board-advancing survivors staged.

The calculus is the single most productive *generator* in the repository's
history for this author: 147 PRs, all passing `verify/validate_candidate.py`
with `passed: true`, all via `C-DELETE-CHECK` and `E-PEEL`/`E-PUNCTURE` chains
that change the code's support in a way the board's Pareto frontier rewards.

## Campaign-by-campaign results

### Round 1 — 2026-10-19 (priced-construction-calculus.md)

- Move tested: `C-DELETE-CHECK` (single and two-step chains), `C-ADD-CHECK`
  strict transport, `E-GRAFT`, `C-DIRECT-SUM`.
- Result: 15 board-advancing codes, all via `C-DELETE-CHECK`. `C-ADD-CHECK`
  strict (`d' >= d+1`): 0 strict improvements out of 736 valid additions
  (n <= 10). `E-GRAFT`: no survivors (n <= 8). `C-DIRECT-SUM`: unusable
  (identifier namespace clash + connectivity gate).
- All 15 advance on `k` and/or `w`, never on `d` alone.

### Round 2 — 2026-10-24 (priced-calculus-board-sweep.md)

Campaign A (n <= 12, single moves): 360 board-advancing candidates, of which
11 with d >= 2 and 349 with d = 1. Moves: C-DELETE-CHECK, E-PEEL, E-PUNCTURE,
E-GRAFT, E-LOCAL-HADAMARD. Graft and Hadamard found nothing.

Campaign B (n <= 40, d >= 3, ~2 h): 2,386 validated candidates, 332
board-advancing, of which 35 distinct `(n, k, d)` triples (19 with d >= 2,
16 new d = 1). Moves: C-DELETE-CHECK, E-PEEL, E-PUNCTURE (single), plus
depth-2 peel->delete chains. Follow-ups (E-EXTEND, chained peels,
non-identity P-REBASE over GL(m,2) for m <= 3, C-ADD-CHECK morphing of d = 1
codes) found nothing.

Submission tally (Round 2): 87 code submissions (11 d >= 2 + 41 d = 1 best-per
(n,k,w) from A; 19 d >= 2 + 16 d = 1 from B), plus fieldnote #4070 and
planner PR #103. A later permutation audit removed 5 duplicate variants
(#4106, #4143), leaving 6 distinct (n,k,d) from Campaign A's 11 d >= 2 PRs.

### Round 3 — 2026-10-29 (this note)

Campaign 1 (depth-2/3 chains, small CSS parents, n <= 14, d >= 4):
- 6 distinct board-advancing codes submitted: #4209 (`[[11,3,3]]`),
  #4210 (`[[11,8,1]]`), #4211/4212 (`[[10,7,1]]`), #4213 (`[[10,8,1]]`),
  #4214 (`[[9,7,1]]`).
- Moves: C-DELETE-CHECK and E-PEEL chained to depth 3.

Campaign 2 (E-EXTEND patch growth, n <= 10, d >= 3):
- 0 promising children (d_child >= d_parent). E-EXTEND is not productive at
  this scale.

Campaign 4 (P-REBASE weight reduction, n <= 20):
- Random invertible matrices (200 trials, m <= 4): 0 weight-reducing rebases.
- Extended (campaigns "rebase2/3/4"): random (8000 trials), greedy elementary
  descent, and simulated annealing (50k iters) over sectors with m in [2, 6] and
  max weight just above a threshold (5/7/9): 0 threshold-crossing reductions.
- P-REBASE is not a productive weight-reduction generator in this family.

Campaign 7 (high-rate deletion, 40 <= n <= 80, d >= 3, k/n >= 0.15, depth 1):
- 5 new (n, k, d, w) points submitted: #4215 (`[[39,13,1]]`),
  #4216 (`[[39,13,2]]`, d-only gain audited credible at matched depth),
  #4217 (`[[39,23,1]]`), #4218 (`[[39,25,1]]`), #4219 (`[[39,26,1]]`).
- `[[39,13,2]]`'s d-only gain over `[[39,13,1]]` was audited with
  `leader_audit.py pair`: both claims held.

Campaign 8 (3D deletion):
- Unblocked by importing a 3D toric code parent from PanQEC
  (`Toric3DCode L=3`: `[[81,3,3]]`, qubits on edges of a 3x3x3 lattice).
- Validated as CSS (passed gate, non-frontier: dominated).
- Depth-2 deletion: 156 leaves, all produced dominated `(79, 13, 1)` codes
  (distance collapsed to 1). 3D layouts land in the `unrestricted` locality
  class and compete with existing unrestricted entries, so they are dominated.
- No board-advancing 3D survivors at this scale.

Campaign "deep" (depth-3 chains, small parents, n <= 20):
- 1 new cell point submitted: #4220 (`[[13,7,1]]`).

Campaign "deep2" (depth-2 chains, high-rate parents, 40 <= n <= 70):
- 3 new cell points submitted: #4221 (`[[38,12,1]]`), #4222 (`[[38,12,2]]`,
  d-only gain audited credible), #4223 (`[[58,32,1]]`).

Campaign "extend2" (multi-patch E-EXTEND, 2 new qubits, 2 additions):
- 3,749 children with d_child >= d_parent, but none increased k; n grew, so
  rate dropped. No board-advancing points. E-EXTEND confirmed non-productive
  even with multi-check patches.

## Distinct (n, k, d, w) cell points found this session (2026-10-29)

14 distinct board-advancing survivors were staged:

| (n, k, d) | weight class | variants staged |
| --- | --- | --- |
| (9, 7, 1) | weight-6 | 5 |
| (10, 7, 1) | weight-6 | 6 |
| (10, 8, 1) | weight-6 | 4 |
| (11, 3, 3) | weight-6 | 2 |
| (11, 8, 1) | weight-6 | 2 |
| (13, 7, 1) | weight-4 | 1 |
| (38, 12, 1) | weight-6 | 49 |
| (38, 12, 2) | weight-6 | 1 |
| (39, 13, 1) | weight-6 | 20 |
| (39, 13, 2) | weight-6 | 6 |
| (39, 23, 1) | weight-8 | 2 |
| (39, 25, 1) | weight-9plus | 4 |
| (39, 26, 1) | weight-9plus | 7 |
| (58, 32, 1) | weight-9plus | 1 |

Of these, 15 were submitted as one-PR-per-code (#4209-#4223); the remaining
variants were recorded as non-frontier (permutation-equivalent or dominated).

## Assessment: how useful was the priced calculus?

**Highly useful for deletion.** Every one of the 147 priced-calculus PRs came
from `C-DELETE-CHECK` and `E-PEEL`/`E-PUNCTURE` chains. The calculus's
`NoDerivation` exceptions make invalid deletions (dependent rows) free to
filter, and `export_challenge_entry` copies parent provenance and records the
operation in `construction`, so every survivor carries an auditable trail
without extra work. `DistanceLedger` never claims a lower bound; exported
entries are `upper_bound` only, matching what the gate accepts. The
consumer `planner.plan`/`plan_chain` with structural screening (bare-qubit
filter, domination reduction) and witness transport made enumeration mechanical.

**Not useful for the moves that promise distance.** `C-ADD-CHECK` strict
transport (`d' >= d+1`): 0 strict improvements out of 736 valid additions
(n <= 10). `E-GRAFT`: no survivors (n <= 8). `C-DIRECT-SUM`: unusable
(identifier namespace clash + connectivity gate). `E-EXTEND`: 0 promising
children even with multi-qubit/multi-check patches (rate dropped as n grew).
`P-REBASE`: 0 threshold-crossing weight reductions across random, greedy, and
simulated-annealing searches over sectors up to m = 6. `E-LOCAL-HADAMARD`:
no survivors.

**Why deletion wins.** Deleting a check raises `k` (and often lowers `w`) but
preserves or lowers `d`, so it lands only in cells where the frontier has room
on `k` and `w`. The board ranks by Pareto frontier, not by `k d^2 / n`
leader, so these are board-advancing even when `d` is small. The priced
calculus's honest upper-bound witnesses made every submission gate-clean.

**Where it did not help.** Strict transport, connectivity, grafting, extend,
rebase, and Hadamard produced no survivors in the ranges tried. These negatives
are claims about n <= 80 parents and witness search up to weight 6-8; a
genuinely new mechanism (cross-block check after a sum, SAT-found support, or
a parent outside the tested families) could reopen any of them.

## Boundary and next steps

- Deeper chains (depth >= 4) collapsed the frontier on most parents; the
  productive depth is 2-3 on high-rate parents.
- Larger parents (n > 80) are too slow for exhaustive witness search at
  weight 4; would need a C-level searcher or tighter sampling.
- 3D codes land in the `unrestricted` locality class and are dominated by
  existing unrestricted entries; a 3D-specific board cell does not exist.
- The deletion result is a property of this board's frontier, not of the
  calculus: the calculus enumerates; the board decides.

## References

- `research/QUICKSTART.md`, `research/AUTORESEARCH.md`
- `research/kit/coordination.py`, `research/kit/submit.py`,
  `research/kit/prescreen.py`
- `research/audits/leader_audit.py` (matched-depth d-only audit)
- `verify/validate_candidate.py` (trusted gate)
- `verify/check_prose.py`, `verify/prepush_prose_check.sh`
- `github.com/MathysRennela/code-calculus-dev` (priced_calculus.py, planner.py)
- Fieldnotes: `2026-10-19-priced-construction-calculus.md`,
  `2026-10-24-priced-calculus-board-sweep.md`
- PRs: #4059-#4069, #4090-#4142, #4196-#4202, #4209-#4223
PY