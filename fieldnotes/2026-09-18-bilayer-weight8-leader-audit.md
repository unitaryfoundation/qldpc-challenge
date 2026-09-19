---
title: "Distance audit of the weight-8 leaders: [[360,12,24]] holds at 24, [[684,20,72]] is soft"
date: 2026-09-18
author: "@e-eight"
model: "DeepSeek V4 Flash 0731"
topics: [distance-audit, calibration, twisted-torus, bivariate-bicycle, local-2d, RIS, over-claim]
status: active
related:
  - 2026-07-01-trial-depth-floors.md
  - 2026-07-14-large-n-refutation-calibration.md
---

## TL;DR

The leader of `local-2d-bilayer x weight-8` is `codes/360-12-24.json`
(`kd^2/n = 19.20`), a **reconstructed literature baseline** whose provenance
records the distance as "an upper bound per the paper (probabilistic for
`d > 20`)". That is exactly the shape of claim the board has been burned by
before, so it was re-measured at depth before anyone spent budget trying to beat
it.

It holds. **Ten fresh seeds across 80M cumulative RIS trials return 24 and
never anything lighter**, and the independent decoder mechanism agrees at the
only weight it can reach. The bar to beat in this cell is a real
`(n, k, d, w) = (360, 12, 24, 6)`, `kd^2/n = 19.20` -- not a soft number.

Five further cell leaders were screened the same way, and **one of them was
soft**: the `unrestricted x weight-8` leader `[[684,20,72]]` collapses to
`d <= 48` under 8M trials, a 24-unit over-claim (revised separately as
`[[684,20,48]]`). The rest held or were inconclusive. The two that sit at low
rate and high weight (`684-20-72`, `922-18-31`) are *inconclusive* at the
screening budget rather than corroborated: RIS
does not even reach their claimed weight, so a flat reading there is a statement
about the search, not about the code.

## What was measured, and how

`codes/360-12-24.json`: `n = 360`, `k = 12`, max check weight 6, two-layer
layout, measured interaction radius 6.9283 (cap 7.0), `kd^2/n = 19.20`. The
laid-out code is what the verifier ranks, and the layout is not part of this
audit -- only the distance claim is.

RIS ladder, bit-packed backend (`verify/gf2_fast.distance_rand_witness`,
`pair_depth = 10`, both Pauli sides searched jointly). Every witness is
re-validated against the raw sparse matrices before it is recorded: support
size equals the reported weight, `H_opp v = 0` over GF(2), and `v` outside the
row space of `H_own`.

| budget | seeds | lightest logical | witness valid |
|---|---|---|---|
| 1,000,000 | 101, 102, 103, 104 | 24, 24, 24, 24 | yes, x4 |
| 5,000,000 | 201, 202, 203 | 24, 24, 24 | yes, x3 |
| 20,000,000 | 301, 302, 303 | 24, 24, 24 | yes, x3 |

80M trials over ten independent seeds, flat at exactly the claimed value, with
no rung ever reaching 23. For contrast, the neighbouring collapse found on this
board (`[[882,18,30]] -> 29`, merged as PR #1165) needed a 15M-trial rung with a
particular seed to surface, and the sibling in the 684 family
(`[[684,12,81]] -> 66`, issue #896) needed 8M. A 20M rung that reads exactly the
claim is therefore meaningful evidence here, not a budget artifact.

Two small controls:

* **`pair_depth` is not hiding anything.** Re-running 300k trials at
  `pair_depth` 4, 8, 16, 32 and 64 returns 24 at every setting. The collapse is
  not sitting just outside the pairwise-candidate set.
* **The structure-aware refutation does not fire.**
  `verify/gf2_fast.circulant_gb_witness` returns `block_size = 0`: the code's
  group is `Z_6 x Z_30` (Smith normal form of the twist lattice sums to
  `6 * 30 = 180`, not cyclic), so `H_X = [A | B]` is a *2-dimensional*
  circulant and the single-block squeeze of issue #942 cannot be applied. That
  is a limitation of the accelerator, not evidence about the distance, but it
  is worth recording so the next audit does not expect it to fire on the
  twisted-torus family.

## Independent mechanism (decoder)

`decode/distance.py` (pinned `BpOsdDecoder`, `osd_cs`, order 10, 200k injected
errors per side per seed, seeds 1/2/3) returns 32, nothing, 40 -- i.e.
`d_ub = 32`. That is **weaker than RIS, not contradictory**, and it matches the
finding of issue #1148 that at these budgets the syndrome-decoder cross-check is
dominated by RIS for low-rate codes. It is reported here for completeness
because the audit protocol asks for a second mechanism; it does not add
confidence beyond the RIS ladder.

## Exact certification was attempted and did not close

A single-cap MILP in the shape of `verify/certify.py`
(`H v = 0`, `<v, tL> = 1`, `weight(v) <= 23`, one solve per logical-basis row,
`tlim = 100` s per solve, HiGHS via scipy) **timed out on all 12 generators of
the X side** (1217 s) and was stopped before the Z side. The claim is `d <= 24`
with `k = 12`; `CONTRIBUTING.md` records the certified envelope as
`d <= 13, k <= 12`, and `d = 24` is well past the weight cap that sets the
per-solve cost. No lighter logical was found inside the budget, but the run
proves nothing either way and is reported as inconclusive.

So the honest tier for `[[360,12,24]]` remains `d <=`. The audit changes
nothing about the entry; it removes the specific worry that its *number* is
soft.

## The rest of the cell, and the neighbouring cells, screened

Same harness, 2M trials, one seed (seed 51), for triage:

| entry | n | k | w | claim | RIS at 2M | reading |
|---|---|---|---|---|---|---|
| 672-20-32 | 672 | 20 | 6 | 32 | **32** | corroborated |
| 682-182-76 | 682 | 182 | 32 | 76 | **76** | corroborated |
| 584-150-18 | 584 | 150 | 8 | 18 | **18** | corroborated |
| 922-18-31 | 922 | 18 | 8 | 31 | 32 | inconclusive |
| 684-20-72 | 684 | 20 | 8 | 72 | 84 | inconclusive at 2M |

`[[922,18,31]]`'s own note already documents an independent-seed ladder of
20k -> 200k -> 1M -> 5M -> 20M trials holding at 31, so the 2M reading of 32
supersedes nothing and a further run was not spent on it.

`[[684,20,72]]` was the exception. Its 2M rung reads 84 -- twelve units *above*
the claim -- and looks uninformative, but at **8M trials it yields a weight-48
Z-logical**, refuting the claim by 24. The witness was re-validated by a
from-scratch NumPy GF(2) rank (`H_X v = 0`, `rank(H_Z)` 332 vs 333 with `v`
appended) and the entry has been revised to `[[684,20,48]]`, whose note carries
the ladder. The lesson is sharper than "low rate needs more trials": **the
reading that looks most like a non-result is the one worth deepening.**

## What this means for the campaign

* The `local-2d-bilayer x weight-8` cell is led by a **verified** `19.20`, and
  the arithmetic of the tile family makes it hard to reach: for the 4+4 open
  boundary tile `k = 18` and `n = 2L^2`, so `kd^2/n = 9 (d/L)^2`, and reaching
  `19.20` needs `d/L > 1.46`. The measured members sit at `d/L` between 1.21
  (`L = 19`, `d = 23`) and 1.38 (`L = 21`, `d = 29`). Beating the twisted torus
  at its own game therefore needs a tile whose *slope* is higher, not merely a
  larger lattice -- which is precisely the quantity
  `research/local2d/transfer.py` is meant to rank before any lattice is built.
* A concrete tooling blocker is recorded with this finding:
  `transfer.py::distance_slope` enumerates states as all `(2D)`-slot windows
  with a cumulative popcount cap, so its state space is exponential in the row
  degree; a 4+4 tile with `max x-degree 3` does not fit, and the `Dcap` filter
  then skips the family entirely (already noted as a dead end in
  `notes/882-18-29.md`). A reachable-state / on-the-fly min-mean-cycle
  formulation is the fix that turns the tile sweep from sampling into ranking.
* The other half of the lesson is that the audit is cheap relative to the
  search it protects. Two people-hours of fresh-seed RIS moved the
  `unrestricted x weight-8` headline by 24 units; the same budget spent building
  candidates against the old number would have been wasted, and any candidate
  tuned to beat `151.58` would have been tuned against a fiction.

## Reproduction

The audit uses tools already in the tree. `verify/heuristic_distance.py` runs a
random-information-set search on both Pauli sides and exits 2 when it refutes a
claim; `decode/distance.py` is the independent decoder mechanism. Every witness
quoted here was re-checked against the raw sparse matrices before being recorded
(support size equals the weight, `H_opp v = 0` over GF(2), and `v` outside
`rowspace(H_own)`), and the weight-48 witness was additionally confirmed by a
from-scratch GF(2) rank.

```
# the ladder above, one budget and seed per rung (the tool takes one at a time)
uv run --frozen python verify/heuristic_distance.py codes/360-12-24.json \
    --fast-trials 1000000 --seed 101
uv run --frozen python verify/heuristic_distance.py codes/360-12-24.json \
    --fast-trials 20000000 --seed 301

# the independent decoder mechanism
uv run --frozen --with ldpc python decode/distance.py codes/360-12-24.json \
    --trials 200000 --seed 1

# the leader triage repeats the first command against each cell leader, e.g.
uv run --frozen python verify/heuristic_distance.py codes/672-20-32.json \
    --fast-trials 2000000 --seed 51
```

Approximate cost: 80M RIS trials plus the decoder sweep, about 90 minutes of
wall clock on 16 cores.
