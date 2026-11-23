---
title: "Greedy weight shedding with objective-aware search: 15 board-advancing codes"
date: 2026-11-23
author: "@mathysrennela"
model: "Hy4 flash Free"
topics: [code-calculus, greedy, weight-shedding, board-advancing, gate-passing]
---

## Summary

Used the objective-aware search from code-calculus-dev
[PR #624](https://github.com/unitaryfoundation/code-calculus-dev/pull/624)
(`objective="weight"`, `rebase=True`) to run a greedy weight-shedding campaign
over 140 CSS board parents. Of 157 single-step attempts, 23 produced a
weight-improving child; all 23 were staged with witnesses and gated, **all 23
passed**, and **15 were board-advancing** (gate `gates.novelty.board_advancing:
true`). Dedup against the board and open PRs found 0 exact/WL duplicates, and
the 15 finds are mutually non-duplicate. Every find is a d=1, weight-reduced
variant in the `weight-9plus`/unrestricted cell; none is a d-only gain. These
are staged for human review only — no PR was opened.

## What was run

- Tool: `code-calculus-dev` PR #624 worktree @ `6b02aba` (branch
  `codex/issue-7116-consumer-diagnostics`, base `origin/main` `dae82da`).
- Two waves: (1) 60 parents, n ∈ [10,120], weighted toward high check weight;
  (2) 80 parents, n ∈ [10,80], ordered by n (the productive pilot regime).
  Both: CSS, d ≥ 2, parent w ≥ 5, 3 greedy steps, sector budget 64.
- Each step called `bounded_sector_search(..., objective="weight",
  sector_swap=False, rebase=True)`; the best child was chosen by
  (lower max check weight, larger k, smaller n, higher carried upper bound).
- Every chosen child was packaged with `submit.make_submission` (8,000 witness
  trials), staged via `save_submission(..., spec=)` with the parent/step/
  objective recorded, and gated via `coordination.gate_and_record`. Dedup used
  `dedup_oracle.combined_index(include_open_prs=True)` (3,695 entries).
- Sector swaps were excluded by construction: they change no weight and PR
  #624 reports them separately as presentation-only.

## Numbers

| | Wave 1 | Wave 2 | Total |
|---|---:|---:|---:|
| Parents | 60 | 80 | 140 |
| Single-step attempts | 64 | 93 | 157 |
| Steps with a weight-improving child | 5 | 18 | **23** |
| Candidates gated | 5 | 18 | 23 |
| Gate `passed: true` | 5 | 18 | **23** |
| `board_advancing: true` | 2 | 13 | **15** |
| Duplicates (board + open PRs) | 0 | 0 | 0 |
| d-only gains | 0 | 0 | 0 |

Hit rate: 23/157 = 14.6% of steps produced a gateable child; 15/23 = 65% of
gated children advanced the board. A large majority of steps (134/157) found
no weight-improving child at this budget — consistent with the v0.2 finding
that single-step weight reduction is rare, but now measured on the correct
axis instead of the distance interval.

## The 15 finds

All are `[[n,k,d]] = [[n,k,1]]` with d witnessed at 8,000 trials; `w` is the
max check weight after the greedy chain, and the parent is the chain origin.

| Parent | n | k | w | Parent | n | k | w |
|---|---:|---:|---:|---|---:|---:|---:|
| 62-42-2 | 60 | 45 | 30 | 35-17-3 | 34 | 27 | 18 |
| 62-42-2 | 59 | 45 | 29 | 35-17-3 | 33 | 27 | 17 |
| 29-23-2 | 28 | 23 | 15 | 35-17-3 | 32 | 27 | 16 |
| 36-19-3 | 34 | 27 | 17 | 38-32-2 | 37 | 32 | 21 |
| 36-19-3 | 33 | 28 | 16 | 38-32-2 | 36 | 32 | 20 |
| 46-30-2 | 43 | 33 | 21 | 38-32-2 | 35 | 32 | 19 |
| 63-48-3 | 62 | 53 | 31 | 63-48-3 | 61 | 53 | 30 |
| 63-48-3 | 60 | 53 | 29 | | | | |

The most productive parents were chains of 3 steps (`62-42-2`,
`35-17-3`, `38-32-2`, `63-48-3`), each shedding one unit of n and w per step
while preserving k. The single largest one-step shed was `29-23-2` →
`[[28,23,1]]`, w 21 → 15.

Each staged candidate carries its gate verdict and reproduction spec beside it
in gitignored working output; none of those paths is cited here as a board entry.

## Extended arm: forcing distance ≥ 2

A follow-up run targeted the question left open by the first campaign — all 15
finds were d=1 — by adding two floors to the same objective search:
`min_child_upper=3` (transport-level) and `min_d=2` (only children whose
witnessed distance is ≥ 2 are gated; lower-d children are still staged so no
witness is discarded). Parents were CSS, d ≥ 3, n ∈ [80,160] (120 parents,
3 steps, budget 64). Rebase was disabled after measuring that its O(m²)
enumeration costs >2 min per parent without producing hits the punctures did
not already find.

| | Extended arm |
|---|---:|
| Parents / steps | 120 / 125 |
| Weight-improving children | 5 |
| Staged with witness d = 1 (skipped by floor) | 4 |
| Staged with witness d = 3 (gated) | 1 |
| Gate passed | 1 |
| Board-advancing | **0** |

The single d≥2 candidate, `103-30-7` → `[[102,36,3]]` w=8 (parent w=14), passed
the gate but was dominated by 6 board entries. The 4 d=1 children came from
`141-44-4`, `158-52-3` and `80-16-4`, where the carried upper bound stayed at 3
or 4 but the witness search found a weight-1 logical — a direct illustration
that a transported upper bound is not a witnessed distance.

**Conclusion:** across 157 + 125 = 282 greedy steps, this objective produced
**0 gate-passing, board-advancing codes with d ≥ 2**. Weight shedding preserves
or lowers the ledger's upper endpoint but frequently drops the *witnessed*
distance to 1; the few children that keep d ≥ 2 are dominated. Reaching the
thin high-distance cells needs a different move family (one that provably
preserves distance), not a larger budget on these moves.

Raw data: `extended.json` in the campaign directory.

## Negative results and boundaries

- `rebase=True` did not change the hit rate (2/30 vs 2/30 on a fixed parent
  slice): P-REBASE was enumerated but did not produce weight-improving
  children within the budget. This does not rule out a different row-mix
  schedule.
- The missing-n objective (`{"axis":"n","targets":...}`) found 0 children on
  small parents — their peel/puncture children land at n < 86, outside the
  missing-n set. It needs n ≥ 500 parents and was not run here.
- All finds are d=1. The thinnest high-distance cell (`w4·d≥16`, 65 board
  entries) was **not** reached: weight shedding preserved d and reduced w by
  1 per step from w ≥ 9, so w ≤ 4 would need many more steps. No claim is made
  about reaching that cell.
- One wave-2 run crashed on a child with an empty check sector (the verifier
  requires an explicit 0×n matrix); the helper was fixed and the wave rerun in
  full. No witness was lost: the crash happened before staging that child.

## Reproduction

`research/campaigns/cc-v03-weight-shed-greedy-2026-11-23/run.py`, with
`results.json`, `campaign_smalln.json`, and logs beside it. From
`qldpc-challenge` with `CODE_CALCULUS_PATH` pointing at the PR #624 worktree:

```
.venv/bin/python -u research/campaigns/cc-v03-weight-shed-greedy-2026-11-23/run.py \
  --limit 60 --budget 64 --gate-cap 40 --open-prs --out research/campaigns/cc-v03-weight-shed-greedy-2026-11-23/results.json
.venv/bin/python -u research/campaigns/cc-v03-weight-shed-greedy-2026-11-23/run.py \
  --limit 80 --n-hi 80 --order n --budget 64 --gate-cap 25 --open-prs \
  --out research/campaigns/cc-v03-weight-shed-greedy-2026-11-23/campaign_smalln.json
```

No PR was opened for any find; promotion remains a human decision.
