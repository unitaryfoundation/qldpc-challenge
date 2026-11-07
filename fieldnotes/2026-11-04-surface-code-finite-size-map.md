---
title: A finite-size map of the verified board against the surface-code baseline (issue #4601, Level 1)
date: 2026-11-04
author: "@vprusso"
topics: [beat-the-surface-code, surface-code, frontier, locality, audit]
---

Issue #4601 asks, as its first milestone, for a structural map: for k logical
qubits, which verified codes use fewer data qubits than the surface code at
the same distance, in which locality and weight cell, and with what
verification status. research/audits/surface_code_map.py builds that map from
the board as the verifier sees it, and
research/audits/surface_code_map-2026-11-04.json is the record for the board
at d52b1be79 (3,102 entries, 2,876 of them CSS). This note reads the record.

## What is compared

The baseline is k independent rotated surface-code patches at distance d:
n = k d^2 data qubits, exact distance, check weight 4, one layer. Against it,
in each pool, the map takes at every d the smallest-n CSS entry with at least
k logical qubits and a distance bound of at least d, so a code with spare
logical qubits stands in for k of them and the spare ones are wasted. The
pools are the three locality tracks (2D single-layer, 2D bilayer, which
includes single-layer, and unrestricted, which includes everything) crossed
with check-weight caps of 4, 6, 8, and any. The factor quoted below is
k d^2 over the entry's n. The record also names, per (k, d), the board's own
weight-4 single-layer topological entry covering the point (rotated,
dense-packed, and holey surface codes, and toric codes), and it carries the
per-side distances of every named entry.

Two conventions matter when reading a factor. The comparison counts data
qubits only: syndrome ancillas, schedules, and logical error rates are the
Level 2 comparison in #4601 and are not computed here. And a board distance is
a witness-backed upper bound unless the entry has an exact certificate (tier
exact in the record), while the baseline distance is exact, so a row at tier
ub beats the surface code only if its bound is tight.

## Headline

For each k target and pool: the distances at which some verified code beats
k d^2, and the largest factor with the entry that achieves it.

| k | pool | d where a code beats k d^2 | best factor |
|---:|---|---|---|
| 1 | 2D single-layer, any w | 12 values of d between 3 and 15, none above | x2.13 at d = 7, [[23,1,7]] w8, exact |
| 1 | 2D bilayer, any w | 28 of the 29 values from 3 to 31, none above | x2.44 at d = 19, [[148,2,19]] w8, ub |
| 1 | unrestricted, w <= 8 | every d from 3 to 81 | x9.59 at d = 81, [[684,4,81]] w8, ub |
| 1 | unrestricted, any w | every d from 3 to 107 | x16.8 at d = 107, [[682,2,107]] w14, ub |
| 10 | 2D single-layer, any w | 5 values of d between 3 and 9, none above | x4.44 at d = 4, [[36,12,4]] w8, exact |
| 10 | 2D bilayer, any w | every d from 3 to 31, none above | x17.8 at d = 16, [[144,10,16]] w8, ub |
| 10 | unrestricted, w <= 8 | every d from 3 to 56 | x46.7 at d = 56, [[672,14,56]] w8, ub |
| 10 | unrestricted, any w | every d from 3 to 100 | x147 at d = 100, [[682,62,100]] w20, ub |
| 25 | 2D single-layer, any w | d = 3, 5, and 7 only | x2.89 at d = 3, [[78,26,3]] w6, exact |
| 25 | 2D bilayer, any w | every d from 3 to 24, none above | x23.3 at d = 14, [[210,26,14]] w8, ub |
| 25 | unrestricted, w <= 8 | every d from 3 to 40 | x52.9 at d = 38, [[682,32,38]] w8, ub |
| 25 | unrestricted, any w | every d from 3 to 100 | x367 at d = 100, [[682,62,100]] w20, ub |
| 50 | 2D single-layer, any w | d = 3, 4, and 5 only | x1.42 at d = 4, [[565,51,4]] w4, exact |
| 50 | 2D bilayer, any w | every d from 3 to 12, none above | x27.2 at d = 10, [[184,50,10]] w8, exact |
| 50 | unrestricted, w <= 8 | every d from 3 to 40 | x80.5 at d = 40, [[994,142,40]] w8, ub |
| 50 | unrestricted, any w | every d from 3 to 100 | x733 at d = 100, [[682,62,100]] w20, ub |
| 100 | 2D single-layer, any w | d = 3 and 4 only | x1.70 at d = 4, [[944,105,4]] w4, exact |
| 100 | 2D bilayer, any w | d = 3 and 4 only | x5.13 at d = 4, [[312,104,4]] w9, exact |
| 100 | unrestricted, w <= 8 | every d from 3 to 40 | x161 at d = 40, [[994,142,40]] w8, ub |
| 100 | unrestricted, any w | every d from 3 to 90 | x1188 at d = 90, [[682,102,90]] w20, ub |

The full tables, one row per d with the winning entry in each pool, come from
`uv run python research/audits/surface_code_map.py --markdown`.

## What the map says

In the single-layer 2D track the surface code is close to unbeaten. At k = 1
the gains are the 4.8.8 color codes ([[23,1,7]], [[71,1,11]], [[127,1,15]])
and a few small qecdb codes, all at exact distance and all below d = 16; above
d = 15 the best single-layer entry at every d is a surface or toric code. At
k = 10 and k = 25 the single-layer winners are weight-8 SAT codes and a
[[78,26,3]] two-block code at d <= 9, and at k = 50 and k = 100 the only
single-layer codes beating k patches are reductions of the holey surface codes
themselves ([[565,51,4]] from codes/665-51-4.json, [[944,105,4]] from
codes/957-105-4.json), by factors of 1.4 and 1.7. The structural case for a
non-surface 2D single-layer code at k >= 10 and d >= 10 is empty on this
board.

The bilayer track is where two-block, bivariate bicycle, and pair-partition
CPM codes beat patches by one to two orders of magnitude: x18 at k = 10 and
d = 16 ([[144,10,16]]), x23 at k = 25 and d = 14 ([[210,26,14]]), x27 at
k = 50 and d = 10 ([[184,50,10]], exact). The track ends early, though:
nothing 2D-local on the board covers d > 31 at k = 1 or k = 10, d > 24 at
k = 25, d > 12 at k = 50, or d > 4 at k = 100.

The unrestricted track at check weight at most 8, which is the LDPC
comparison, beats patches at every d it covers, with factors that grow with d
to x47 (k = 10, d = 56), x81 (k = 50, d = 40), and x161 (k = 100, d = 40).
The any-weight column is larger again, but its winners are cyclic generalized
bicycle codes of check weight 14 to 30 and should not be read as an LDPC
result.

Exact-distance coverage ends early in every pool. The largest d at which the
winning entry has an exact certificate is 12 at k = 1 ([[64,2,12]]), 12 at
k = 10 ([[112,12,12]], bilayer), 10 at k = 25 ([[150,30,10]], bilayer), 10 at
k = 50 ([[184,50,10]]), and 6 at k = 100 ([[252,130,6]]). Every factor above
those distances rests on witness-backed upper bounds, several of them from
single random-information-set runs. For the campaign this is the first
finding: at d between 13 and 20, where the bilayer and weight-8 factors are
largest, the board needs certificates or deeper ladders more than it needs
new codes.

## The price of 2D locality

The record holds, for every k target and d, the n of the best unrestricted
entry and the n of the best bilayer and single-layer entries at the same
(k, d). Selected rows (factor is the 2D n over the unrestricted n):

| k | d | unrestricted | bilayer | single-layer |
|---:|---:|---|---|---|
| 1 | 9 | [[42,2,9]] | same code, x1.0 | [[71,1,11]], x1.69 |
| 1 | 19 | [[148,2,19]] | same code, x1.0 | [[361,1,19]], x2.44 |
| 1 | 31 | [[288,8,35]] | [[899,18,31]], x3.12 | [[961,1,31]], x3.34 |
| 10 | 8 | [[48,10,8]] | [[62,10,9]], x1.29 | [[666,10,9]], x13.9 |
| 10 | 16 | [[128,12,16]] | [[144,10,16]], x1.13 | none |
| 10 | 24 | [[210,24,24]] | [[360,12,24]], x1.71 | none |
| 25 | 8 | [[96,30,8]] | [[104,30,8]], x1.08 | none |
| 25 | 14 | [[170,32,14]] | [[210,26,14]], x1.24 | none |
| 50 | 4 | [[108,58,4]] | [[128,66,4]], x1.19 | [[565,51,4]], x5.23 |
| 50 | 10 | [[184,50,10]] | same code, x1.0 | none |
| 100 | 4 | [[196,100,4]] | [[312,104,4]], x1.59 | [[944,105,4]], x4.82 |

Up to d around 16 the bilayer price is between 1.0 and 1.3 at every k target,
and at several points the best unrestricted code is itself laid out. The
single-layer price is 1.7 to 14 where a single-layer code exists at all. The
unrestricted winners at d = 4 for k = 50 and k = 100 are weight-12 and
weight-24 codes, so the bilayer factor there is partly a weight price.

## Caveats

The baseline is a formula, not one entry: the board's holey surface code
[[957,105,4]] and its [[944,105,4]] reduction already beat 100 independent
d = 4 patches by 1.7, so "the surface code" at large k is itself a design
choice, and the record names the board's own surface-family entry at every
(k, d) beside the formula. The k' >= k substitution favors large-k codes at
small k targets; the per_k section of the record, which gives the best factor
for every k from 1 to 100 in each track, is the place to read a rate-sensitive
version. Stabilizer-board entries are excluded by default (the script takes
--code-type stabilizer for that board on its own) because their check weight
is a Pauli weight and the two boards do not compare. Nothing here ranks or
scores; the record is a reading of the board, dated, and regenerated by the
command above.
