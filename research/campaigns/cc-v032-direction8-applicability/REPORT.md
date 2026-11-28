# Direction 8: applicability diagnostics on the v0.2/v0.3.0 negative pilots

Issue #7377, direction 8. Tool: `machine.planner.move_applicability_report`
(code-calculus @ v0.3.2). Parents: the 60 weight-shedding parents of
`research/campaigns/cc-v03-direction2-sector-calibration/campaign3.json` and the
6 missing-n parents of `campaign4.json`. Report with `weight_cap = parent w`
(non-increasing check weight) and rebase enabled for campaign 3; campaign 4
parents are large (n up to 1000) and were run with `--no-rebase` because the
P-REBASE enumeration is O(n^2) and dominates wall time.

## Aggregates (campaign 3, 60 parents)

| Family | Domain | Derived | Usable | Dominant refusal / screen |
|---|---:|---:|---:|---|
| C-DELETE-CHECK | 9258 | 9258 | 8730 | 528 x weight_one_logical |
| E-PEEL | 20194 | 614 | 613 | 9748/9832 x unique-touch (X/Z) |
| E-PUNCTURE | 10097 | 10097 | 7692 | 2345 x weight_one_logical |
| E-GRAFT | 20194 | 20022 | 650 | 19372 x over_weight_cap |
| P-REBASE | 851194 | 851194 | 10492 | 840702 x over_weight_cap |
| E-EXTEND | 20254 | 60 | 0 | 20194 x opposite-sector commutation |

## Aggregates (campaign 4, 6 parents, rebase disabled)

| Family | Domain | Derived | Usable | Dominant refusal / screen |
|---|---:|---:|---:|---|
| C-DELETE-CHECK | 3460 | 3460 | 3329 | 131 x weight_one_logical |
| E-PEEL | 8564 | 148 | 148 | 4208/4208 x unique-touch (X/Z) |
| E-PUNCTURE | 4282 | 4282 | 3686 | 592 x weight_one_logical |
| E-GRAFT | 8564 | 8530 | 141 | 8389 x over_weight_cap |
| E-EXTEND | 8570 | 6 | 0 | 8564 x opposite-sector commutation |

## Reading

- Deletion and puncture are the workhorses: every enumerated candidate derives,
  and 75-94% survive the screens. Their only screen is a validated weight-1
  logical (i.e. the child would have distance 1).
- E-PEEL is gated by column weight: a peel needs a qubit in exactly one
  displayed row of each sector, so on these parents ~97% of the domain fails
  `apply_operation` on the unique-touch premise. Only 614 of 20194 derive.
- E-GRAFT derives almost everything (20022/20194) but 96% of derived children
  are screened out by `over_weight_cap`: the graft raises the displayed check
  weight. Only 650 usable children across 60 parents.
- P-REBASE has the largest domain (851194 across 60 parents) and derives
  everything, but 99% are screened by `over_weight_cap`. It is the only family
  whose domain is large enough to dominate runtime; it was disabled for the
  campaign-4 parents.
- E-EXTEND is refused on 99.8% of candidates by the opposite-sector
  commutation premise; the 60 that derive all produce bare qubits, so zero
  usable children. This matches the v0.3.0 calibration (20194/20254 refusals).

## Files

- `run.py` -- driver (supports `--campaign`, `--out`, `--no-rebase`,
  `--include-disconnected`).
- `result-campaign3.json`, `result-campaign4.json` -- per-parent reports and
  aggregates.
PY