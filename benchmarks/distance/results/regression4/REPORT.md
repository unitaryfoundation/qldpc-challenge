# CPU distance-search pilot

This is an exploratory implementation comparison, not an exact-distance or cap-raising certificate.

Platform: macOS-26.6.2-arm64-arm-64bit; arm64. Workers: 4. Budget: 10 seconds per code, split equally between X and Z. Imports/JIT and shared basis preparation are outside this search budget.

Seeds per method/case: 1. Method order is shuffled within each case/seed. A single-seed pilot does not establish repeated-run reliability. Core affinity: unavailable/not fixed.

## Target recovery

A hit means at least one validated nontrivial logical reached the code's target within its side's deadline. The validated-reference column uses only witnesses available before the run. The all-target column also includes analytic toric and initially unverified paper targets. Not-applicable structural searches are excluded, so their denominator differs.

| Method | Validated targets reached | All targets reached | Actual claim refutations | Not applicable |
|---|---:|---:|---:|---:|
| cpp | 0/1 | 0/1 | 0 | 0 |
| cpp-circulant | 0/1 | 0/1 | 1 | 0 |
| cpp-no-pairs | 0/1 | 0/1 | 0 | 0 |
| m4ri | 0/1 | 0/1 | 0 | 0 |
| numpy | 0/1 | 0/1 | 0 | 0 |
| qdistevol | 0/1 | 0/1 | 0 | 0 |

## Refutation witnesses

These observations tighten existing upper bounds. Each supporting vector is retained in results.jsonl and was checked with the repository's GF(2) routines. No leaderboard entries were changed.

| Input | Method | Seed | Existing claim | Found weight |
|---|---|---:|---:|---:|
| regression-690-182 | cpp-circulant | 11 | 77 | 48 |

## Per-code best weights

Each cell is the minimum weight observed within budget over both sides and all listed seeds. Where no timely result is available, an asterisk marks the best late result; it receives no timely-success credit. With multiple seeds, these minima are descriptive and do not replace success rates. The complete per-seed/per-side events and timing are in results.jsonl.

| Input | n | k | cpp | cpp-no-pairs | m4ri | qdistevol | numpy | cpp-circulant |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| regression-690-182 | 690 | 182 | 86 | 87 | 86* | 90 | 94 | 48 |

## Limits and follow-up

* Native and NumPy RIS use short observation batches with cached bases. The trial kernels are unchanged, but batch-specific random streams differ from one long public-API call.
* QDistEvol runs independent populations of 100 candidates, with ten offspring per retained parent. Repeated-seed and longer-budget measurements are needed before judging evolutionary guidance.
* dist-m4ri exports its witness file at exit. An export observed after the deadline is retained as best_returned but conservatively receives no in-budget credit. This especially affects full-budget runs without an early-stop target. No late result is silently discarded.
* This pilot scores search-stage latency. The raw records separate common preparation, dispatch/search, validation and saving; they do not assert an end-to-end production gate speedup.
* Fresh cases have no preselected witness targets. Use an independent reference phase to freeze those targets before held-out seed comparisons. Do not tune and evaluate on the same seeds.
* Repeat on the intended CI CPU with fixed physical-core affinity before selecting a production default.
