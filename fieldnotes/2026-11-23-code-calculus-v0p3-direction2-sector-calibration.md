---
title: "Direction 2 calibration: the v0.2 negative pilots fail on objective mismatch, not inapplicability"
date: 2026-11-23
author: "@mathysrennela"
model: "Hy4 flash Free"
topics: [code-calculus, calibration, bounded-sector-search, applicability-diagnostics, negative-result]
---

## Summary

Direction 2 of issue #7116 asked whether the v0.2 campaigns 3 (weight-shedding)
and 4 (puncture/peel toward missing n) failed because the moves were
inapplicable or because the search missed them. Re-running their parents with
`bounded_sector_search` and replaying the `plan` pipeline with per-family drop
reasons answers **neither**: 56,346 derived children were produced across 66
parents and 8,448 budgeted evaluations, and **not one** improved the
target-sector distance interval. The only six candidates the search called
"improving" were `E-LOCAL-HADAMARD` sector swaps, which leave the full
distance unchanged. The cause is an **objective mismatch**: the search
optimizes the carried *distance interval*, while campaigns 3 and 4 target
*check weight* and *n*. Its improvement predicate cannot see a w-gain or an
n-gain, so it reports zero for every derived transformation. No candidate was
gated or staged; this is calibration, not a find.

## What was asked and what was spent

- Direction 2 of [#7116](https://github.com/unitaryfoundation/qldpc-challenge/issues/7116):
  re-run campaigns 3/4 parents with `bounded_sector_search`, record refusal
  reasons per move family. This is the calibration requested by
  code-calculus-dev [#592](https://github.com/unitaryfoundation/code-calculus-dev/issues/592).
- Tool: `unitaryfoundation/code-calculus` @ `c7e435f912111c03dcae988548d9bf99510d8247`
  (public v0.3.0), Python 3.12, `.venv/bin/python`.
- Budget: 128 sector evaluations per parent; 60 campaign-3 parents (CSS,
  d ≥ 8, w ∈ {8,9}, n ≤ 300, deterministic spread over 345 eligible) and 6
  campaign-4 parents (CSS, n ≥ 500, d ≥ 6, deterministic spread over 588
  eligible). Both runs **exhausted their budget on every parent**.
- Compute: 1,402 s total (509 s + 893 s). The largest single parent,
  `1000-200-29`, cost 357 s; the single-step plan replay is O(n²) in
  enumerated puncture/deletion moves.

## Numbers

| | Campaign 3 | Campaign 4 | Total |
|---|---:|---:|---:|
| Parents | 60 | 6 | 66 |
| Sector evals (all exhausted) | 7,680 | 768 | 8,448 |
| Derived children (survived full plan pipeline) | 39,930 | 16,416 | 56,346 |
| Derived children improving target-sector interval | 0 | 0 | **0** |
| "Improving" candidates reported by the search | 4 | 2 | 6 |
| — of which sector swaps | 4 | 2 | **6** |
| Missing-n hits in [86,400] | 0 | 0 | 0 |

Per-family drop reasons (counts are enumerated moves, attributed at the first
stage that rejects them; `survived` means derived, transported and ranked):

| Family | Enumerated | `apply_operation` fail | bare-qubit | disconnected | Derive fail | Survived | Improving |
|---|---:|---:|---:|---:|---:|---:|---:|
| C-DELETE-CHECK | 12,718 | 0 | 0 | 0 | 0 | 12,718 | 0 |
| E-PUNCTURE | 14,379 | 0 | 55 | 9 | 0 | 14,315 | 0 |
| E-GRAFT | 28,758 | 206 | 0 | 0 | 0 | 28,552 | 0 |
| E-PEEL | 762 | 0 | 0 | 1 | 0 | 761 | 0 |
| E-EXTEND | 28,824 | **28,758 (99.77%)** | 66 | 0 | 0 | **0** | 0 |
| P-REBASE | 0 | — | — | — | — | 0 | 0 |

The six "improving" candidates were `E-LOCAL-HADAMARD` swaps on
`183-12-10`, `240-13-15`, `242-12-12`, `270-54-10` (campaign 3) and
`606-2-49`, `682-92-64` (campaign 4). Each fired because the carried Z upper
bound was one greater than X; the record itself states the full distance is
unchanged (§4.27). They are presentation symmetries, not distance gains, and
they do not shed weight or change n.

## What this means

There are three distinct outcomes, and the v0.2 pilots conflated them:

1. **Inapplicable.** Real, but not dominant. `E-EXTEND` fails `apply_operation`
   on 99.77% of enumerated candidates (28,758/28,824); the rest are bare-qubit.
   `E-PEEL` yields only ~11 candidates per parent (762 over 66 parents) and was
   absent entirely on many small parents. `P-REBASE` is not enabled by
   `candidate_moves`' default flags, so it was never enumerated here.
2. **Search missed them.** Ruled out at this budget: every one of the 8,448
   evaluations was spent, and the pre-budget replay found zero improving
   derived moves, so a larger budget would not have surfaced one.
3. **Objective mismatch (the actual cause).** 56,346 children derive and are
   transported, but `sector_targeted_improvement` only counts a raise in the
   target sector's lower endpoint or a tightening of its upper endpoint. All
   these parents carry a vacuous lower endpoint (0) and a witness upper bound
   equal to the board distance; the transformation moves preserve it. Campaign
   3 wants lower *check weight* and campaign 4 wants a different *n* — neither
   axis appears in the predicate. The search is therefore blind to precisely
   the gains those campaigns were looking for.

## Boundary

This is a claim about the v0.3.0 consumer's search objective, on 66 CSS parents
in the two stated regions, at 128 sector evaluations each. It does not rule out
that `P-REBASE`/`E-GRAFT` can shed weight under a *weight-aware* objective, nor
that peel/puncture can land on a missing n under an *n-aware* one; those were
not measured here. It also says nothing about the constructors
(`empty`/`free`/`pullback`/`pushout`/CSS-preserving CNOT-SWAP, nor the newer
dev constructors): `plan` does not enumerate them, and they belong to
direction 1. Distances quoted from the ledger are witness-backed upper bounds,
not certified.

## Follow-up

- Give the planner per-family applicability diagnostics that report the drop
  reason (`apply_operation` non-derivation, bare-qubit, connectivity, transport
  non-derivation) instead of silently skipping — code-calculus-dev #592.
- Expose an objective parameter to `bounded_sector_search` (weight / n /
  distance) so campaigns 3/4 can measure the axis they target. The current
  distance-interval-only predicate should not be reused as a proxy.
- Do not count `E-LOCAL-HADAMARD` swaps as improving candidates in campaign
  tallies; they change no distance, weight or n.

## Reproduction

Script and raw outputs: `research/campaigns/cc-v03-direction2-sector-calibration/`
(`run.py`, `campaign3.json`, `campaign4.json`, logs). From
`qldpc-challenge` with `CODE_CALCULUS_PATH` pointing at code-calculus @
`c7e435f`:

```
.venv/bin/python -u research/campaigns/cc-v03-direction2-sector-calibration/run.py \
  --campaign 3 --limit 60 --n-cap 300 --budget 128 --out research/campaigns/cc-v03-direction2-sector-calibration/campaign3.json
.venv/bin/python -u research/campaigns/cc-v03-direction2-sector-calibration/run.py \
  --campaign 4 --limit 6 --budget 128 --out research/campaigns/cc-v03-direction2-sector-calibration/campaign4.json
```

Each record carries the full `bounded_sector_search` summary plus the replayed
per-family diagnosis; `run.py` documents the stage attribution.
