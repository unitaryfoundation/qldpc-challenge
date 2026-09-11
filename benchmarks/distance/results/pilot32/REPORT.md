# CPU distance-search pilot

This is an exploratory implementation comparison, not an exact-distance or cap-raising certificate.

Platform: macOS-26.6.2-arm64-arm-64bit; arm64. Workers: 4. Budget: 10 seconds per code, split equally between X and Z. Imports/JIT and shared basis preparation are outside this search budget.

Seeds per method/case: 1. Method order is shuffled within each case/seed. A single-seed pilot does not establish repeated-run reliability. Core affinity: unavailable/not fixed.

## Target recovery

A hit means at least one validated nontrivial logical reached the code's target within its side's deadline. The validated-reference column uses only witnesses available before the run. The all-target column also includes analytic toric and initially unverified paper targets. Not-applicable structural searches are excluded, so their denominator differs.

| Method | Validated targets reached | All targets reached | Actual claim refutations | Not applicable |
|---|---:|---:|---:|---:|
| cpp | 11/14 | 18/26 | 0 | 0 |
| cpp-circulant | 1/4 | 1/4 | 1 | 28 |
| cpp-no-pairs | 11/14 | 18/26 | 0 | 0 |
| m4ri | 10/14 | 19/26 | 0 | 0 |
| numpy | 5/14 | 7/26 | 0 | 0 |
| qdistevol | 9/14 | 15/26 | 0 | 0 |

## Refutation witnesses

These observations tighten existing upper bounds. Each supporting vector is retained in results.jsonl and was checked with the repository's GF(2) routines. No leaderboard entries were changed.

| Input | Method | Seed | Existing claim | Found weight |
|---|---|---:|---:|---:|
| board-682-172-79 | cpp-circulant | 11 | 76 | 72 |

## Per-code best weights

Each cell is the minimum weight observed within budget over both sides and all listed seeds. Where no timely result is available, an asterisk marks the best late result; it receives no timely-success credit. With multiple seeds, these minima are descriptive and do not replace success rates. The complete per-seed/per-side events and timing are in results.jsonl.

| Input | n | k | cpp | cpp-no-pairs | m4ri | qdistevol | numpy | cpp-circulant |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| board-72-12-6 | 72 | 12 | 6 | 6 | 6 | 6 | 6 | N/A |
| board-144-12-12 | 144 | 12 | 12 | 12 | 12 | 12 | 12 | N/A |
| board-300-4-27 | 300 | 4 | 27 | 27 | 27 | 27 | 29 | N/A |
| board-450-8-16 | 450 | 8 | 16 | 16 | 16 | 16 | 16 | N/A |
| board-550-110-18 | 550 | 110 | 18 | 18 | 18 | 18 | 18 | N/A |
| board-700-6-32 | 700 | 6 | 32 | 32 | 34 | 32 | 38 | 200 |
| board-700-140-22 | 700 | 140 | 22 | 22 | 22 | 26 | 24 | N/A |
| board-700-222-28 | 700 | 222 | 77 | 77 | 75* | 84 | 81 | N/A |
| board-674-128-80 | 674 | 128 | 92 | 92 | 95* | 96 | 98 | 97 |
| board-682-172-79 | 682 | 172 | 86 | 86 | 86* | 90 | 97 | 72 |
| board-576-294-12 | 576 | 294 | 12 | 12 | 12 | 22 | 30 | N/A |
| board-300-60-14 | 300 | 60 | 14 | 14 | 14 | 14 | 14 | N/A |
| board-630-126-20 | 630 | 126 | 20 | 20 | 20 | 20 | 22 | N/A |
| board-682-20-22 | 682 | 20 | 22 | 22 | 22 | 22 | 30 | 160 |
| tanner-144_2_13 | 144 | 2 | 13 | 13 | 13 | 13 | 13 | N/A |
| tanner-432_8_33 | 432 | 8 | 34 | 36 | 33 | 32 | 38 | N/A |
| tanner-684_2_29 | 684 | 2 | 31 | 31 | 35* | 31 | 42 | N/A |
| mitten-780-156 | 780 | 156 | 22 | 22 | 22 | 26 | 44 | N/A |
| mitten-975-195 | 975 | 195 | 26 | 26 | 24 | 60 | 117 | N/A |
| zsz-775-155 | 775 | 155 | 22 | 22 | 22 | 30 | 35 | N/A |
| zsz-840-168 | 840 | 168 | 24 | 24 | 24 | 26 | 48 | N/A |
| bb-756-16 | 756 | 16 | 36 | 36 | 36* | 34 | 64 | N/A |
| bb-864-4 | 864 | 4 | 50 | 50 | 50* | 60 | 102 | N/A |
| toric-720 | 720 | 2 | 18 | 18 | 18 | 18 | 20 | N/A |
| toric-840 | 840 | 2 | 20 | 20 | 20 | 20 | 20 | N/A |
| toric-1000 | 1000 | 2 | 20 | 20 | 20 | 20 | 24 | N/A |
| fresh-bb-768 | 768 | 2 | 98 | 98 | 108* | 108 | 136 | N/A |
| fresh-bb-864 | 864 | 4 | 133 | 133 | 136* | 142 | 155 | N/A |
| fresh-bb-960 | 960 | 6 | 152 | 152 | 160* | 162 | 184 | N/A |
| fresh-hgp-720 | 720 | 144 | 2 | 2 | 2* | 2 | 2 | N/A |
| fresh-hgp-845 | 845 | 169 | 2 | 2 | 2* | 2 | 2 | N/A |
| fresh-hgp-980 | 980 | 196 | 2 | 2 | 2* | 2 | 2 | N/A |

## Limits and follow-up

* Native and NumPy RIS use short observation batches with cached bases. The trial kernels are unchanged, but batch-specific random streams differ from one long public-API call.
* QDistEvol runs independent populations of 100 candidates, with ten offspring per retained parent. Repeated-seed and longer-budget measurements are needed before judging evolutionary guidance.
* dist-m4ri exports its witness file at exit. An export observed after the deadline is retained as best_returned but conservatively receives no in-budget credit. This especially affects full-budget runs without an early-stop target. No late result is silently discarded.
* This pilot scores search-stage latency. The raw records separate common preparation, dispatch/search, validation and saving; they do not assert an end-to-end production gate speedup.
* Fresh cases have no preselected witness targets. Use an independent reference phase to freeze those targets before held-out seed comparisons. Do not tune and evaluate on the same seeds.
* Repeat on the intended CI CPU with fixed physical-core affinity before selecting a production default.
