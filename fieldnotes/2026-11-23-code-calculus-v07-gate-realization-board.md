---
title: "Gate-realization judgments on real board codes: the rows decide, and one branch stays not-yet-defined"
date: 2026-11-23
author: "@mathysrennela"
model: "Hy4 flash Free"
topics: [code-calculus, gate-realization, preserves-U, weight-floor, calibration]
---

## Summary

Direction 3 of issue #7116 applies the two gate-realization judgment rows of
github.com/unitaryfoundation/code-calculus-dev @ 4c98904, `spec/JUDGMENT_LAYER.md` §2h to real CSS board entries, not synthetic small
displays. On 23 board codes with n ∈ [4,10], d ≥ 2: 115 gate-preservation
checks produced 37 preserving and 78 non-preserving gates, and **0 disagreements**
with the state-vector oracle at θ = π/4. Of 222 addable-row survival checks,
most carried at π/4, 10 did not carry, and 119 stayed `not_yet_defined` at a
non-π/4 angle with an anticommuting generator — exactly the branch the judgment
leaves open. The equal-syndrome weight row held on all 16 sampled families on
12 codes: `w_max ≥ ⌈d/2⌉` was satisfied, never violated, and never tight in this
sample. A wider n ≤ 14 run was attempted but stopped: the harness's
`random_addable_row` enumerates all 2^n masks with a basis reduction per mask,
so the run stalled after 10 of 64 entries (~5 min) without completing a single
additional verdict. The completed n ≤ 10 slice below is the reported result.

## What was run

- Tool: code-calculus PR #624 worktree, github.com/unitaryfoundation/code-calculus-dev @ 4c98904, `machine/experiments/gate_realization_rows.py`
  (`Display.from_code_state`, `preserves_pi4`, `addition_survival_verdict`,
  `oracle_preserves`, `random_equal_syndrome_family`, `weight_floor`, `w_max`).
- Board entries: 23 CSS codes, n ∈ [4,10], d ≥ 2, seed 7116. Each code got 5
  seeded commuting Hermitian gate families and up to 6 addable check rows.
- The survival row was evaluated at θ = π/4 and at θ = 0.3 for the same added
  row, so the `not_yet_defined` branch is counted explicitly.
- The weight row needs a family of commuting Paulis with one **common nonzero
  syndrome**. A CSS stabilizer logical commutes with every check, so it has
  zero syndrome and cannot seed the row; families were therefore sampled from
  physical Paulis on each real display with the harness's own generator.

## Numbers (n ≤ 10 slice)

| Metric | Value |
|---|---:|
| Board codes | 23 |
| Preservation checks (oracle: π/4) | 115 |
| — preserving | 37 |
| — not preserving | 78 |
| Oracle disagreements | **0** |
| Codes with a preserving gate | 19 |
| Survival checks | 222 |
| Verdicts at π/4 | carries 212, does_not_carry 10 |
| Verdicts at θ = 0.3 | carries 103, not_yet_defined 119 |
| Codes with an addressable logical family | 12 |
| Weight-row families checked | 16 |
| — satisfied, above floor | 16 |
| — violated / tight | 0 / 0 |

The three-branch verdict behaves as stated: when every generator commutes with
the added row, the row carries at every angle; when a generator anticommutes
and the angle is π/4, the stabilizer-membership test decides; when the angle is
not π/4 and a generator anticommutes, the judgment is `not_yet_defined`. No
case was observed where the derived criterion disagreed with the oracle.

## Boundary

- The weight row was sampled, not exhaustively enumerated: 16 equal-syndrome
  families on 12 codes. It was never tight and never violated, so this sample
  cannot distinguish "the row is loose on these codes" from "the sampler did
  not hit the minimum-weight family". The board's witnessed d was used as the
  comparison distance; no exact-distance certificate was assumed.
- The `not_yet_defined` count is about the judgment's domain, not a failed
  prediction: those cases are deliberately outside the two derived rows.
- This is evidence that the transcription matches the oracle on real displays,
  not a proof of soundness (AGENTS.md).

## Reproduction

`research/campaigns/cc-v07-gate-realization-board/run.py` and `campaign.json`.
From `qldpc-challenge` with `CODE_CALCULUS_PATH` at PR #624:

```
.venv/bin/python -u research/campaigns/cc-v07-gate-realization-board/run.py \
  --limit 80 --n-hi 10 --gates 5 --additions 6 --out research/campaigns/cc-v07-gate-realization-board/campaign.json
```
