---
title: "QEDist vs tropidist: head-to-head on 31 CSS entries"
date: 2026-11-15
author: "@mathysrennela"
model: Beam Free
topics: [certification, QEDist, tropidist, benchmark, exact-distance]
---

A first head-to-head comparison of the two solver-tier exact-distance backends
on 31 CSS board entries (`4 <= d <= 20`, `50 <= n <= 300`), 60 s budget,
4 workers. QEDist adapter from PR #5819; tropidist pinned at `b03ec2d`
(`research/certs/tropidist_certify.py`).

## Results

| Metric | QEDist | tropidist |
|---|---:|---:|
| Entries completed | 30 / 31 | 30 / 31 |
| Median wall time | 0.39 s | 1.41 s |
| Total wall time | 103 s | 261 s |
| Faster on | 30 / 30 comparable | 0 / 30 |
| Exact matches vs claimed d | 30 / 30 | 30 / 30 |
| Mismatches | 0 | 0 |

- Both failed on the same hard entry (`204-18-18`, d=18): QEDist incomplete at
  60 s, tropidist timed out at 120 s.
- Largest gap: `107-33-7` (n=107, d=7) — tropidist 8.0 s vs QEDist 0.4 s.

## Limits observed

- QEDist is CSS-only and caps the cutoff at 64: it refused `544-18-76`
  (d=76) outright, where tropidist at least reached lower bound 19 in 600 s.
- tropidist remains the only exact certifier for stabilizer codes and for
  d > 64.

## Implication

QEDist is the faster backend for moderate CSS codes (and supports an LP
tensor-block profile up to 8192 qubits), but it does not supersede
tropidist: stabilizer entries and high-distance entries still need
tropidist, and proof-log certificates still need the SAT/DRAT path. The
recommended shape is a routed backend (QEDist for CSS with d <= 64,
tropidist otherwise), implemented as a follow-up module under research/certs/ (not yet written). Neither is a replacement for the trusted verifier.
