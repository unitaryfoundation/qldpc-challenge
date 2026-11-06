---
title: "tropidist backend: fast on moderate CSS and stabilizer codes, still times out on high-distance 2BGA"
date: 2026-11-06
author: "@MathysRennela"
topics: [certification, tropidist, benchmark, stabilizer]
status: active
---

## TL;DR

tropidist (arXiv:2611.08247, pinned at commit `b03ec2d` of github.com/Fanerst/tropidist)
closes moderate CSS and stabilizer entries in well under a second where the
challenge's MILP certifier takes tens of seconds, and it is the only exact
certifier available for stabilizer codes. It does **not** make high-distance
2BGA entries tractable at the sweep's 60–600 s budget: `[[544,18,76]]` reached
only lower bound 19 in 600 s.

## What ran

A small benchmark driver, one code at a time, comparing
`verify/certify.py` (scipy/HiGHS MILP) against the tropidist adapter
on the same entry with the same time limit:

| code | n | k | d | MILP | tropidist |
|---|---:|---:|---:|---|---|
| `[[7,1,3]]` Steane | 7 | 1 | 3 | exact, 0.01 s | exact, 0.91 s |
| `[[4,2,2]]` | 4 | 2 | 2 | exact, 0.01 s | exact, 0.90 s |
| `[[5,1,3]]` stabilizer | 5 | 1 | 3 | not supported | exact, 0.48 s |
| `[[72,12,6]]` | 72 | 12 | 6 | exact, 33.15 s | exact, 0.93 s |
| `[[144,12,12]]` | 144 | 12 | 12 | timed out at 60 s | exact, 0.3 s/side |
| `[[544,18,76]]` | 544 | 18 | 76 | n/a in budget | lower bound 19 in 600 s |

The 5-qubit stabilizer row is the important one: `verify/certify.py` returns
`d_exact = false` for stabilizer codes by design, so tropidist is the first
exact certifier available for that board.

## Interpretation

- **Where tropidist wins**: moderate-size CSS entries with k in the tens, and
  any stabilizer entry. `[[72,12,6]]` and `[[144,12,12]]` close in under a
  second per side where MILP needs tens of seconds or fails.
- **Where it does not help**: high-distance 2BGA entries at the sweep's budget.
  `[[544,18,76]]` proved only d >= 19 in 600 s, so it is not a drop-in
  replacement for the long SAT runs on those entries.
- **Cost**: tropidist is slower than MILP on tiny codes (0.9 s vs 0.01 s) and
  requires a C compiler and a pinned external checkout; it is solver-level only,
  with no DRAT proof.

## Recommendation

Use tropidist as a routed backend, not a replacement: stabilizer entries and
entries where MILP/SAT time out first, SAT/DRAT for proof-log certificates.
Record timeouts as interval certificates (PR #4721) rather than discarding them.
Keep the pinned commit (`b03ec2d`) and the smoke tests that ship
with PR #4719.