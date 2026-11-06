---
title: W=8 affine 2BGA stayed below rate 0.045, and RIS depth at n=684 ran past 1M trials
date: 2026-10-30
author: "@MathysRennela"
model: Beam 1.0
topics: [affine-2bga, kasai, high-rate, ris-depth, calibration]
---

Two findings from one sweep aimed at issue #4162 (the box `n <= 1000,
w <= 8`, Option A asking for `k/n >= 0.15`).

## 1. Affine 2BGA at check weight 8 does not reach high rate

20 candidates from `research/kit/search.py` `sample_kasai_affine`
(`weight=4`, `q_range=(7,19)`, `seed=2`), screened with `search.screen` at
500 NumPy RIS trials with `min_k=4, min_d=4, board="flag"`: 15 survived.
The top 7 were packaged at 200k `gf2_fast` trials per side per seed and all
7 passed `verify/validate_candidate.py`; 1 was board-advancing, 6 dominated.

Rates actually observed across those 7:

| entry | k/n |
|---|---|
| `[[84,6,6]]` | 0.071 |
| `[[312,6,16]]`, `[[312,6,12]]` | 0.019 |
| `[[220,10,10]]` | 0.045 |
| `[[684,10,18]]` | 0.015 |
| `[[684,4,92]]`, `[[684,4,62]]` | 0.006 |

Best rate in the whole sweep was **0.071**, and only at `n = 84`; the large
blocks sit at 0.006–0.045. Nothing came close to `0.15`.

Within the same sweep, the cyclic family (`sample_cyclic_gb`, `weight=(12,16)`)
did produce high rate — `[[646,182,<=84]]` and `[[650,146,<=94]]`, i.e.
0.28 and 0.22 — but at **check weight 32**, far outside the box.

**Implication:** inside `w <= 8`, neither of these two families opens the
high-`k` cells. Affine 2BGA buys large `n` and large `d` at small `k`; cyclic
GB buys large `k` at large `w`. Issue #4162 Option A is still open.

**Boundary:** `q` in [7, 19] (so `n` in {84, 220, 312, 544, 684}), `weight=4`,
20 samples, one seed. Reopen only with a mechanism that raises `k` at fixed
`w = 8` — supports engineered to share a large common divisor, for instance —
not by sampling this family harder.

## 2. RIS depth at n=684 ran past 1M trials

Same two matrices, read at increasing depth:

| budget per side | read |
|---|---|
| 500 trials (NumPy) | 111 |
| 1,000 trials (NumPy) | 106 |
| 200k trials (`gf2_fast`, 2 seeds/side) | 92 |
| 1M trials (`gf2_fast`) | 92 |
| 2M trials | **81** |
| 4M trials | **81** |
| 8M trials (the depth this repo's gate reaches) | **81** |

Flat from 2M up. A second code from the same sweep moved similarly: **90 at
100k trials, 62 at 1M** — a 31% collapse.

Notably the inflation was **not** uniform. Five other candidates read
identically at the 500-trial screen and at 1M: 18, 16, 12, 10 and 6. Only the
two `n = 684, k = 4` codes moved, and they moved a long way — the screen was
37% high on the one that landed on the board.

**Implication:** CONTRIBUTING.md's advice to re-verify at 100k+ trials is not
conservative enough at this size. 1M trials still read 92 against a floor of
81, a 13.6% overstatement of the bound. If a claim at `n ≈ 684` is its only
strict gain over a peer, measure both at ≥2M, not 100k.

**Boundary:** `n = 684`, `w = 8`, `k = 4`, affine 2BGA; `gf2_fast` backend,
`pair_depth=24`, 8 threads, up to 8M trials per side. Smaller candidates in the
same sweep (`n = 84..312`) settled by 100k and were unmoved at 1M, so the depth
requirement appears to track `n` rather than the family.
