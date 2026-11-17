---
title: "Proxima-guided syndrome-extraction scheduling: 33 circuit-tier improvements"
date: 2026-11-17
author: "@mathysrennela"
model: "Beam 1.0"
topics: [circuits, scheduling, qldpc]
---

## Summary

Using the scheduling ideas from *Proxima* (arXiv:2611.19715) — optimizing
syndrome-extraction circuit (SEC) schedules via a DEM-level proximity
surrogate — I ran `research/kit/circuit_search.py` over every committed entry
whose circuit tier read `d_circ < d`. That is 36 CSS entries. The search staged
candidate schedules for 34 of them as individual circuit-tier PRs (replacing
`circuits/<slug>/` and the `circuit` block, with `circuit.contributed_by`
crediting `@mathysrennela`). Of those 34 PRs, **33 merged** into `main` and
1 (`#6145`, `64-20-8`) did not raise `d_circ` above the committed `5/5` tier.
The remaining entry `52-13-5` did not yield a claimable improvement.

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
3. Bound survivors with `verify/check_authorship.py` and submitted them as
   one PR per entry, gated by CI's `verify/circuit_verify.py` check.
4. For entries where CI's deeper DEM search found weight-4 or weight-5
   undetected fault sets below the initial `d_circ` estimate (`#5911`,
   `#5925`, `#5934`, `#5970`, `#6143`, `#6144`), the bounds were tightened
   before landing; `#6145` (`64-20-8`) remained at `5/5` and did not land.

## Results

33 circuit-tier improvements landed on `main`, e.g.

| Slug | Before (X/Z) | After (X/Z) |
|------|--------------|-------------|
| 102-6-13 | 7/7 | 13/13 |
| 80-8-12 | 5/5 | 12/12 |
| 90-4-9 | 8/8 | 9/9 |
| 88-4-13 | 7/6 | 13/13 |
| 182-32-9 | 6/6 | 9/9 |

Merged PRs (33): `#5891` (`90-4-9`), `#5900` (`80-6-12`), `#5901` (`98-26-7`),
`#5903` (`54-4-10`), `#5904` (`108-10-12`), `#5906` (`90-12-12`),
`#5907` (`104-6-14`), `#5909` (`108-16-12`), `#5911` (`64-21-7`),
`#5912` (`62-18-7-b`), `#5914` (`96-6-13`), `#5915` (`54-12-7-b`),
`#5916` (`108-8-12-b`), `#5918` (`90-10-11`), `#5919` (`53-13-6-b`),
`#5921` (`84-10-12`), `#5922` (`98-6-14-b`), `#5924` (`80-8-12`),
`#5925` (`62-21-6`), `#5927` (`108-8-13`), `#5928` (`98-6-14`),
`#5929` (`160-36-6`), `#5931` (`168-28-10`), `#5933` (`102-6-13`),
`#5934` (`63-21-7`), `#5964` (`180-36-10`), `#5968` (`60-18-6`),
`#5970` (`63-20-7`), `#5972` (`88-4-13`), `#5974` (`84-40-6`),
`#6143` (`42-16-6`), `#6144` (`62-20-6`), and `#6147` (`182-32-9`).
`#6145` (`64-20-8`) did not raise `d_circ` above `5/5`, and `52-13-5` stayed at
its committed bound across 3 deeper attempts.

## Tools

- `research/kit/circuit_search.py`, `verify/circuit_verify.py`,
  `verify/check_authorship.py`
- Model: Beam 1.0
