---
title: "Multiband surface-code fills and campaign scalability"
date: 2026-11-17
author: "@mathysrennela"
model: "Beam 1.0"
topics: [multiband, surface-code, scalability, reachability, gf2_fast, pre-filter]
---

## Summary

Two parallel efforts: (1) a multiband dense-packed surface-code construction
that fills missing n's with weight-4, 2D-local codes, and (2) scalability
improvements to the reachability campaign (gf2_fast pre-filter, parallel saves,
screening-depth reduction). The multiband sweep found 73 fillable missing n's;
56 codes were built and staged. The campaign is running with the faster code.

## Multiband fills

the multiband module implements the (rows, m, pitch) packing from
arXiv:2511.06758 (Fujiu et al.). Enumerating d in {3,5,7,9,11}, rows in
{2..5}, m in {2..15}, pitch in {d-1, 2*(3d//4), d+1} found 73 missing n's
fillable with weight-4, connected, 2D-local codes (d=3 to 13). 56 were built
and staged (trials=500, surrogate screening). These satisfy the weight cap
(<=32 standard, <=8 for n>700) that blocked the earlier parity-check fills.

### Why multiband works where parity-check failed

Parity-check codes have weight = n (all-ones check), exceeding 32 for n>32.
Multiband surface codes have weight 4 (each check touches 4 data qubits),
satisfying the cap for all n. The trade-off: k is smaller (n-k = 2*rank,
where rank depends on rows and m).

## Campaign scalability

The reachability campaign's bottleneck was the single-threaded save phase
(make_submission running surrogate at 8000-20000 trials per child). Three
changes (all in the reachability campaign script, Tier 0):

1. Screening depth 2000 (TRIALS default, was 20000): ~10x faster saves.
   Survivors deep-confirmed at 20000+ before promotion.
2. SKIP_DOMINATED on by default: skips parents already dominated by the
   board (heuristic).
3. Parallel save phase: make_submission + save_submission run in a worker
   pool, not single-threaded. Dedup stays centralized.
4. gf2_fast pre-filter: each child is screened with
   gf2_fast.distance_rand_witness before saving. Over-claimed children
   (lighter logical found) are skipped. This is a cheap upstream filter
   (2-5s per child in workers) that reduces downstream gating waste.

Result: campaign rate improved from ~8.4 to ~13.7 parents/min (+63%).

### gf2_fast as pre-filter, not gate

Making gf2_fast the gate itself would be a Tier 1 change (verify/ is
hash-pinned). The pre-filter approach gets most of the speed benefit without
touching the trust anchor. The gate remains numpy-based and authoritative.

## Re-gating lesson

58 of 95 "ready" candidates were reclassified as dominated after the board
grew (2 revisions). Always re-gate before promoting; stale verdicts
overstate board-advancing status. The pre-filter (dominated + gf2_fast)
should be run on all staged candidates before gating.

## Tools

- The multiband module (build, params, connected).
- gf2_fast (distance_rand_witness).
- The submit and coordination kits.
- Model: Beam 1.0.

## Reproduction

Multiband: enumerate (d, rows, m, pitch) via multiband params(),
filter by missing n / css / connected / k>=1, build, stage with
make_submission (trials=500) + save_submission.

Campaign: uv run --extra research python -u reachability_campaign.py --resume
