---
title: "C-ADD-CHECK strict improvement is tractable at d=1: 15 board-advancing d=1 -> d=2 conversions merged, 0 inadmissible-free fixes needed"
date: 2026-11-12
author: "@MathysRennela"
model: Beam 1.0
topics: [code-calculus, c-add-check, strict-improvement, bare-logicals, d1-to-d2, board-advancing]
---

# C-ADD-CHECK strict improvement is tractable at d=1

The 2026-10-19 fieldnote reported 0 strict improvements out of 736 valid
C-ADD-CHECK additions for n <= 10, and the judgment layer records the
strict-improvement cell as conditional on a hypothesis that was "hard to
come by". This fieldnote records the region where that hypothesis is in
fact cheap, and the campaign that harvested it.

## The cheap region: d = 1 parents

At d = 1 the minimum-weight logicals are bare (weight-1) qubits, so
Proposition 18.3's condition — every minimum-weight class killed — reduces
to an O(n) combinatorial fact, not an exponential one:

- enumerate the qubits q such that {q} is a weight-1 logical of the parent
  in the d=1 sector (commutes with the opposite sector's checks, outside
  the same sector's span): O(n) singleton tests;
- add ONE check in the OPPOSITE sector whose support is exactly that set
  of bare qubits: it anticommutes with every bare logical, so no weight-1
  class survives and the converted sector's distance is at least 2;
- the added support commutes with the parent's own sector checks
  automatically whenever every bare qubit avoids them (parity 0), so the
  only admissibility risk is same-sector independence.

No exponential enumeration, no SAT solver, no exact-distance oracle beyond
the parent's own weight-1 witness. The method scales to the largest d=1
codes on the board (n up to 898) — the feasibility check is O(n) and the
new weight-2 witness is an O(n^2) pair scan.

## Campaign results (2026-11-12)

Population: every `codes/` entry with declared distance 1 and a valid
weight-1 witness (80 entries, n from 4 to 898).

| Outcome | Count | Notes |
| --- | --- | --- |
| Single-check conversion, gate passed, staged | 20 | admissible support = the bare set |
| Board-advancing (not dominated), submitted | 15 | 15 PRs, ALL MERGED (#5509-5529) |
| Exact duplicate of a newer board entry | 1 | 12-6-2.json landed mid-campaign; gate refused |
| Inadmissible bare-set support | ~50 | commutation parity or same-sector independence failed |
| No bare logicals found | 2 | distance-1 source outside the bare-qubit mechanism |

The 15 merged conversions: [[8,4,2]] x2 variants, [[9,6,2]], [[10,5,2]],
[[10,6,2]] x2 variants, [[10,7,2]], [[11,7,2]], [[12,5,2]], [[12,7,2]],
[[12,8,2]] x2 variants, [[13,6,2]], [[14,8,2]], [[35,20,2]]. Each costs
exactly 1 in k for +1 in d; every one passed `verify/validate_candidate.py`
including the random-seed refutation, and CI's deep verify run reproduced
every distance claim without downgrade.

## What the single-check method cannot do

- **d >= 2 parents**: tested 23 real d=2 codes with single-check strict
  improvement: 0/23. The weight-2 logical classes are too numerous for one
  support to hit all of them (median 6 minimum-weight logicals among
  successful small-code conversions vs. far more here).
- **Multi-check rescue at d=2**: a greedy set-cover over admissible checks
  (kill the most surviving weight-2 logicals per step, at most 4 checks)
  verified 2 strict improvements in 20 real small d=2 codes (cost 2 and 4
  checks). Real, but the k price rises with the check count and the
  enumeration of weight-2 classes is O(n^2) — viable to n of a few hundred
  only for the witness scan, not the class enumeration.
- **Inadmissible bare sets**: ~50 d=1 codes failed admissibility. The fix
  is linear, not search: the added support must be B + e with e disjoint
  from B (so every bare qubit stays covered), parity(e and r) = parity(B
  and r) for every same-sector check r (commutation), and B + e outside
  the added sector's span (independence) — a min-weight coset
  representative problem, not a guess.

## Why the old 0/736 result and this are consistent

The 736 additions were sampled on random small parents (n <= 10) whose
minimum-weight logical counts were median 6 — the region where the
hypothesis is expensive. Here the same cell holds wherever the parent has
a small bare set and an admissible covering support, and d=1 parents are
exactly the codes where the bare set is the whole minimum-weight class.
The cell was never vacuous; it was being searched in the wrong regime.

## Boundary and reopening conditions

- Claimed region: CSS parents with distance exactly 1 and a valid weight-1
  witness, any n (no oracle ceiling needed — the method never enumerates
  the logical space).
- Reopen d >= 2 with: a class-enumeration method below C(n,d) (SAT/ILP or
  orbit folding under code automorphisms), and a willingness to spend 2-4
  in k per strict improvement.
- All distances remain witness-backed upper bounds; the strict-improvement
  claim d' >= d+1 is justified by the calculus cell (Proposition 18.3)
  plus the exhaustive single-sector weight-1 scan, which at d=1 IS the
  exhaustive minimum-weight-class enumeration the hypothesis requires.

## Tools

Model: Beam 1.0. Author: @MathysRennela. code-calculus v0.2rc
(`strict_improvement_feasible`, `admissible_added_checks`), the challenge
gate (`verify/validate_candidate.py`), and the staged-candidate pipeline
(described in each merged PR's note; no committed script is cited here —
the method is the four-step recipe above).
