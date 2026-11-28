---
title: "Direction 8: applicability diagnostics on the v0.2/v0.3.0 negative pilots (code-calculus v0.3.2)"
date: 2026-11-28
author: "@MathysRennela"
topics: [code-calculus, applicability-diagnostics, negative-result, calibration]
---

## Summary

Direction 8 of issue #7377: re-run the v0.3.0 negative-pilot parents with
`machine.planner.move_applicability_report` and record, per move family, domain,
derived, usable counts and the dominant refusal/screen. Campaign 3 (60
weight-shedding parents, n <= 300) and campaign 4 (6 missing-n parents,
n up to 1000) were run. No code is submitted; this is calibration.

## What was run

- Tool: `unitaryfoundation/code-calculus` @ v0.3.2, `move_applicability_report`,
  `weight_cap = parent w`, rebase enabled for campaign 3.
- Parents: `research/campaigns/cc-v03-direction2-sector-calibration/campaign3.json`
  (60 slugs) and `campaign4.json` (6 slugs).
- Driver and results:
  `research/campaigns/cc-v032-direction8-applicability/run.py`,
  `research/campaigns/cc-v032-direction8-applicability/result-campaign3.json`, `research/campaigns/cc-v032-direction8-applicability/result-campaign4.json`,
  `research/campaigns/cc-v032-direction8-applicability/REPORT.md`.
- Campaign 4 parents are large, so P-REBASE (O(n^2) domain) was disabled
  (`--no-rebase`) for that run; the other five families completed in ~20 min.

## Numbers

Campaign 3 (60 parents):

| Family | Domain | Derived | Usable |
|---|---:|---:|---:|
| C-DELETE-CHECK | 9258 | 9258 | 8730 |
| E-PEEL | 20194 | 614 | 613 |
| E-PUNCTURE | 10097 | 10097 | 7692 |
| E-GRAFT | 20194 | 20022 | 650 |
| P-REBASE | 851194 | 851194 | 10492 |
| E-EXTEND | 20254 | 60 | 0 |

Campaign 4 (6 parents, rebase disabled):

| Family | Domain | Derived | Usable |
|---|---:|---:|---:|
| C-DELETE-CHECK | 3460 | 3460 | 3329 |
| E-PEEL | 8564 | 148 | 148 |
| E-PUNCTURE | 4282 | 4282 | 3686 |
| E-GRAFT | 8564 | 8530 | 141 |
| E-EXTEND | 8570 | 6 | 0 |

## Findings

- Deletion and puncture derive every candidate and lose only children that would
  have distance 1 (validated weight-1 logical) or a bare qubit.
- E-PEEL is dominated by the unique-touch premise (~97% of its domain): it
  needs a qubit in exactly one displayed row per sector.
- E-GRAFT derives almost everything but 96% of children are screened by
  `over_weight_cap`; only ~1% are usable.
- P-REBASE has the largest domain (851194 over 60 parents) and 99% are
  screened by `over_weight_cap`; it is the runtime bottleneck and was disabled
  on the large campaign-4 parents.
- E-EXTEND is refused on 99.77% of candidates by the opposite-sector
  commutation premise and yields zero usable children, confirming the v0.3.0
  calibration.

## Limits

- Campaign 4 omits P-REBASE for runtime reasons.
- The report is search control: it moves no ledger endpoint and says nothing
  about distance beyond validated weight-1 witnesses.
PY