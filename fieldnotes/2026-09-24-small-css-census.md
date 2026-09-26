---
title: "Exhaustive CSS census through n=6 finds no distance-three code"
date: 2026-09-24
author: "@MathysRennela"
model: "GPT-6 Luna (agent)"
topics: [css-codes, exhaustive-enumeration, exact-distance, small-blocklength]
---

## TL;DR

A complete census of CSS code classes with `1 <= n <= 6` and `k >= 1` found
no code with exact `d >= 3`. The enumeration covered 651 classes; the trusted
SAT certifier completed every distance check with no unresolved cases. Under
the equivalence used here, a CSS code with `k >= 1` and `d >= 3` therefore
requires at least seven physical qubits.

## Scope and method

Each code is represented by its pair of binary check row spaces `(U, V)` with
`U` orthogonal to `V`. The census identifies row-basis changes, simultaneous
permutations of physical qubits, and global X/Z exchange. It does not quotient
by arbitrary local-Clifford transformations. It enumerates all allowed row
spaces for each `n`, filters by `k = n - dim(U) - dim(V)`, and certifies the
minimum distance with the repository's trusted SAT certifier.

Distinct encoded-code classes enumerated by blocklength were:

| n | classes (`k >= 1`) |
|---:|---:|
| 1 | 1 |
| 2 | 3 |
| 3 | 11 |
| 4 | 37 |
| 5 | 126 |
| 6 | 473 |
| **Total** | **651** |

All 651 received exact distance certifications. The default query (`k >= 1`,
`d >= 3`) returned zero matches and zero unresolved cases.

## Reproduction

Run the default census:

```bash
uv run --extra research python research/kit/census_css.py
```

The script emits JSONL. Parameter ranges can be selected with `--n-min` /
`--n-max`, `--k-min` / `--k-max`, and `--d-min` / `--d-max`; for example:

```bash
uv run --extra research python research/kit/census_css.py \
  --n-min 4 --n-max 6 --k-min 1 --k-max 2 --d-min 3 --d-max 5 \
  --output census.jsonl
```

The implementation and enumeration tests are in `research/kit/census_css.py`
and `research/test_census_css.py`. The enumerator intentionally caps `n` at
6: its full permutation canonicalization is factorial in `n`.
