---
title: "New code-calculus constructors: 75/75 derive, but the weight-4 yield is direct sums"
date: 2026-11-23
author: "@mathysrennela"
model: "Hy4 flash Free"
topics: [code-calculus, constructors, pair-partition, pp-scale, nonabelian, negative-result]
---

## Summary

Extension of issue #7116 direction 1 to the constructors added on
`code-calculus-dev` after public v0.3.0: `L-PAIR-PARTITION`, `PP-SCALE`, and
the nonabelian `L-GROUP-ALGEBRA` / `L-LIFTED` / `L-BALANCED` generalizations.
A deterministic grid of **75 parameter tuples derived 75/75** — applicability
is not the problem. But of the 58 derived codes with w ≤ 4 and k ≥ 2, **57 are
disconnected direct sums** that `make_submission` refuses before the gate; the
one connected code, `[[12,2,2]]` w=4 from `L-BALANCED` over S3, passes the gate
but is dominated by 13 existing board entries. **No board-advancing code was
found.** These constructors are currently generators of reducible codes under
the parameter families tested, not a source of frontier entries.

## What was run

- Snapshot: `code-calculus-dev` @ `4c989040a29fb4295abdee82dca9cc24c07012e4`
  in a detached worktree; `qldpc-challenge` `research/kit` verifier and gate.
- Grid: 40 `L-PAIR-PARTITION` (CPM/APM patterns, p ∈ {3,4,5,7,8,9,11,13},
  L ∈ {2,4,6}, unit slopes); 11 `PP-SCALE` (base P0=3, P ∈ {5,7,11,…,31},
  SNF bundle with root P−1); 20 `L-GROUP-ALGEBRA` (S3, D3, D4, D5, Q8;
  a={0,1}, b={0,i}); 3 `L-LIFTED` (S3, D4); 1 `L-BALANCED` (S3 regular
  left/right actions). All parameters and outcomes are in `yield.json`.
- Phase B: the 8 smallest connected w ≤ 4 candidates were to be staged with
  `submit.make_submission` (8,000 witness trials), `save_submission(..., spec=)`
  and gated via `coordination.gate_and_record`. Only 1 was connected, so 1 was
  gated. Distances are witness-backed `upper_bound`, never certified.

## Numbers

| Constructor | Tried | Derived | w ≤ 4, k ≥ 2 | Connected | Gate-passing | Board-advancing |
|---|---:|---:|---:|---:|---:|---:|
| L-PAIR-PARTITION | 40 | 40 | 24 | 0 | — | 0 |
| PP-SCALE | 11 | 11 | 11 | 0 | — | 0 |
| L-GROUP-ALGEBRA | 20 | 20 | 20 | 0 | — | 0 |
| L-LIFTED | 3 | 3 | 2 | 0 | — | 0 |
| L-BALANCED | 1 | 1 | 1 | **1** | 1 | 0 |
| **Total** | **75** | **75** | **58** | **1** | **1** | **0** |

Connectivity was measured with `research/kit/prescreen.block_structure`, the
same check `make_submission` applies: 57/58 had stabilizer-group blocks > 1
(e.g. CPM p=3,L=2 splits into three 4-qubit blocks; S3 two-block codes split
into two 6-qubit blocks), so they were refused with "not one code" before
reaching the gate.

The one connected code: `balanced-S3-regular`, `[[12,2,2]]` w=4, X/Z weight-2
witnesses found at 8,000 trials. Gate `passed: true`, `board_advancing: false`,
dominated by `[[10,2,3]]`, `[[4,2,2]]`, `[[12,4,2]]` and 10 others. No d-only
gain.

Size/weight ranges (all derived): `L-PAIR-PARTITION` n=12–156, k=6–130,
w∈{4,8,12}; `PP-SCALE` n=20–124, k=n/2, w=4; `L-GROUP-ALGEBRA` n=12–20,
k=4–8, w=4; `L-LIFTED` n=12–48, k=0–4, w∈{4,7}; `L-BALANCED` n=12, k=2, w=4.

## Why this is negative

Every weight-4 family tested produces a block-diagonal presentation: the pair
partition pairs columns identically, the SNF bundle scales a block structure,
and the nonabelian two-block / lifted products over these small supports split
the stabilizer group. The gate requires one connected code, so the entire
weight-4 yield is inadmissible before distance is even considered. The single
connected code is a rate-1/6, d=2 object in the most crowded part of the board.

This is **not** a claim that these constructors cannot make connected codes —
only that the natural small parameter families (and the specific pair
partitions / supports used here) do not. A pair partition that mixes blocks,
or a non-block-diagonal base for PP-SCALE, is the mechanism a rerun would need.

## Boundary

75 tuples, deterministic, on the dev snapshot above; no random search, no
parameter outside the stated ranges, and no attempt to connect the blocks.
`pullback`/`pushout` and `empty`/`free` were not re-run (see the v0.3.0
direction-1 fieldnote). No candidate was submitted; nothing here establishes
soundness or an exact distance.

## Reproduction

`research/campaigns/cc-v03-direction2b-new-constructors/run.py`, `yield.json`,
`gate.json`. From `qldpc-challenge`:

```
CODE_CALCULUS_PATH=<code-calculus-dev worktree> .venv/bin/python -u \
  research/campaigns/cc-v03-direction2b-new-constructors/run.py \
  --phase both --trials 8000 --cap 8
```

`run.py` records every parameter tuple, its derived/failure reason, and the
staged submission path with `spec=`.
