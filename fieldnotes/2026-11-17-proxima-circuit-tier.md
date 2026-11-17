---
title: "Proxima-guided syndrome-extraction scheduling: 34 circuit-tier improvements"
date: 2026-11-17
author: "@mathysrennela"
model: "Beam 1.0"
topics: [circuits, scheduling, qldpc]
---

## Summary

Using the scheduling ideas from *Proxima* (arXiv:2611.19715) — optimizing
syndrome-extraction circuit (SEC) schedules via a DEM-level proximity
surrogate — I ran `research/kit/circuit_search.py` over every committed entry
whose circuit tier read `d_circ < d`. That is 36 CSS entries. The search found
improved schedules for 34 of them, all staged and then promoted as individual
circuit-tier PRs (replacing `circuits/<slug>/` and the `circuit` block, with
`circuit.contributed_by` crediting @mathysrennela). The remaining entry
`52-13-5` did not yield a claimable improvement.

## What the paper gave us

Proxima targets the circuit tier, not the code: it does not change `n`, `k`,
`d`, or `w`, but it can raise `d_circ` toward `d` and lower the logical error
rate by reordering the CNOTs in each syndrome-extraction round. Its key
contributions used here:

- The schedule is the degree of freedom: at a fixed round count there is a
  large space of valid gate orderings, and a bad one drives `d_circ` well
  below the code distance.
- Validity is encoded as constraints (qubit conflict, depth, XX/ZZ
  consistency), which `research/kit/circuit_search.py` already enforces for
  its two-block and generic-sequential families.
- Schedules are screened cheaply at 2 rounds and then searched deeply at the
  full round count, exactly the ladder the existing tool runs.

## Method

1. Enumerated committed entries with `d_circ < d` (36 entries).
2. For each, ran `research/kit/circuit_search.py` (1-3 attempts, 5-15 s per
   basis) over the two-block interleaved and generic-sequential families.
3. Verified each survivor with `verify/circuit_verify.py` and bound it with
   `verify/check_authorship.py`.
4. Promoted survivors as one PR per entry.

## Results

34 circuit-tier improvements, e.g.

| Slug | Before (X/Z) | After (X/Z) |
|------|--------------|-------------|
| 102-6-13 | 7/7 | 13/13 |
| 80-8-12 | 5/5 | 12/12 |
| 90-4-9 | 8/8 | 9/9 |
| 88-4-13 | 7/6 | 13/13 |
| 182-32-9 | 6/6 | 9/9 |

Full list and PR numbers are in the session log. `52-13-5` stayed at its
committed bound across 3 deeper attempts.

## Tools

- `research/kit/circuit_search.py`, `verify/circuit_verify.py`,
  `verify/check_authorship.py`
- Model: Beam 1.0
