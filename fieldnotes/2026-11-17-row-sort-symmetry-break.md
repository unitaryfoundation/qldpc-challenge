---
title: "Row-permutation symmetry break (row_sort) for local_sat"
date: 2026-11-17
author: "@mathysrennela"
model: "Beam 1.0"
topics: [sat, 2d-local, symmetry-breaking, scalability]
related:
  - research/local_sat.py
  - research/sat_rungs.py
---

# Row-permutation symmetry break for `local_sat`

## Why

`research/local_sat.py` already breaks the D4 (grid isometry) and X<->Z
symmetries via the static `lex` lex-leader, but it does **not** quotient by
permutations of the generator rows. A code's check set is unordered, so two
models that differ only by a row permutation are the same code; the solver
was spending enumeration rounds rediscovering them. On small complete
instances (`side=2, G=2, t=1`) this inflated the model count from 15 to 25
(40% duplicates).

## What was added

- `row_sort=False` parameter on `build_local_cnf` and
  `enumerate_local_sat_codes`, plus `add_row_sort_clauses(cnf, emit)` which
  enforces, for each side, that adjacent generator rows are lexicographically
  non-decreasing in their incidence vector. Cost is O(n) aux vars per
  adjacent row pair per side.
- `--row-sort` flag on `research/sat_rungs.py`.
- `row_sort_symmetry_selftest()` and a regression test in
  `research/test_local_sat.py`.

## Soundness fix

An initial version used the existing *superset* blocking scheme
(`[-v for v in incidence_vars if v in model]`), which blocks any model whose
incidence support contains a found model's. Combined with row_sort's changed
discovery order this dropped 3 valid orbits. Switching to *exact* incidence
blocking when `row_sort=True` (block only the exact incidence pattern)
restored completeness: 0 missing orbits, 17 distinct orbits vs 13 without
row_sort.

## What it achieved

A bounded search (`side=4, G=5, t=1, row_sort=True`) produced a connected,
non-duplicate, board-advancing code `[[16,6,2]]` (local-2d-single x
weight-4, `passed: true`, `board_advancing: true`), submitted as PR #5838.
The optimization is opt-in (`row_sort=False` default) and does not change
default behavior.
