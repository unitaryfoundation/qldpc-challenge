---
title: The 13 undecided pairs of the permutation audit are 13 distinct codes
date: 2026-10-24
author: "@vprusso"
model: "Claude Fable 5.1 (Claude Code)"
topics: [dedup, permutation-equivalence, board-hygiene, low-weight-enumeration]
---

The permutation audit of 2026-10-17 (`research/audits/permutation_audit.py`,
record `research/audits/permutation_audit-2026-10-17.json`) left 13 pairs of
board entries `undecided`: same parameters, same ranks and intersection
dimension, Tanner graphs not isomorphic, and a row space too large to
enumerate, at ranks 27 to 336. Issue #4057 (@MicheldeMessieres) proposed
deciding them with Leon's method: enumerate only the low-weight row-space
vectors, completely, by the Brouwer-Zimmermann information-set argument, and
compare what is basis-independent about them. The issue's own computation,
with its own programs, found all 13 inequivalent. This note records the same
method implemented inside the audit, run with the board's tooling, and the
new record `research/audits/permutation_audit-2026-10-24.json`.

## What was added to the audit

Two cheap invariants and one stage, in the order the audit tries them:

1. Hull invariants. For each row space C the hull C ∩ C^⊥, its dimension and,
   when it has at most 2^20 vectors, its weight enumerator; and the weight
   enumerator of the intersection of the X and Z row spaces, whose dimension
   the audit already compared. Permutations preserve all of these, with the
   two hulls exchanged under an X/Z swap.
2. The light vectors. Every row-space vector of weight at most the larger
   check weight of the pair, from a Brouwer-Zimmermann enumeration over
   disjoint information sets: a vector missed by every set has at least
   t_i + 1 ones in each set, so the list is complete once the sum of the
   t_i + 1 exceeds the weight bound, at any rank. The per-weight counts are
   compared in both orientations, and when they agree, nauty compares the
   hypergraphs whose hyperedges are the light vectors. Those lists contain
   every check row, so they span, and an isomorphism of the hypergraphs is a
   permutation equivalence in both directions. For every one of the 13 pairs
   the light vectors are exactly the check rows, so this stage is the Tanner
   comparison the first audit already ran, now with the argument that makes
   it decisive.

The enumeration runs in numpy over bit-packed rows. The 13 pairs together
take about 21 s; the largest plan on the board, 468 million row sums per row
space at rank 325 (`872-222-18` / `872-222-20`), takes 53 s. The plan (sets,
subset sizes, row sums, column-order seed) is in each pair's record.
`run --enum-budget` caps the row sums per row space, and a pair over the
budget stays `undecided`.

One correction to the first audit came out of this: its swapped-orientation
comparison swapped both codes, so it compared the direct orientation twice.
No committed verdict depended on it, since all 44 refutations of 2026-10-17
were by the intersection dimension, which is symmetric; the new hull
dimensions would have been misread on `350-70-10` / `350-70-9` (hulls of
dimension 2 and 10 on opposite sides) without the fix.

## The 13 pairs

| pair | what separates them |
|---|---|
| `56-2-10` / `56-2-8` | light vectors (weight 6) are the 28 + 28 checks; Tanner graphs differ |
| `72-10-10` / `72-10-9` | weight enumerator of the X ∩ Z intersection (dimension 4) |
| `124-14-11` / `124-14-13` | light vectors (weight 8) are the 62 + 62 checks; Tanner graphs differ |
| `186-10-16` / `186-10-17` | light vectors (weight 7) are the 93 + 93 checks; Tanner graphs differ |
| `228-85-10` / `228-85-9` | light vectors (weight 12) are the 72 + 73 checks; Tanner graphs differ |
| `320-64-10` / `320-64-9` | weight enumerator of the X ∩ Z intersection (dimension 16) |
| `330-8-22` / `330-8-24` | light vectors (weight 6) are the 165 + 165 checks; Tanner graphs differ |
| `350-70-10` / `350-70-9` | light vectors (weight 8) are the 140 + 140 checks; Tanner graphs differ |
| `420-8-13` / `420-8-14` | light vectors (weight 5) are the 210 + 210 checks; Tanner graphs differ |
| `472-122-14` / `472-122-16` | light vectors (weight 8) are the 177 + 177 checks; Tanner graphs differ |
| `488-126-14` / `488-126-16` | light vectors (weight 8) are the 183 + 183 checks; Tanner graphs differ |
| `568-146-14` / `568-146-18` | light vectors (weight 8) are the 213 + 213 checks; Tanner graphs differ |
| `684-12-45` / `684-12-51` | hull dimensions (0, 0) against (0, 4) |

All 13 verdicts are `inequivalent` and agree with the issue's table. Where the
issue separated a pair by a count at a weight above the check weight
(`56-2-10` / `56-2-8` at weight 8, `124-14-11` / `124-14-13` at weight 12,
`350-70-10` / `350-70-9` at weight 10), the audit stops earlier, at the check
weight, where the light vectors are already the checks and the Tanner
comparison decides; the issue's hull enumerators for `72-10-10` / `72-10-9`
and `320-64-10` / `320-64-9` are the same subspaces the audit now enumerates.
The verdicts are about qubit permutations with an optional global X/Z swap,
the relation the audit tests, and say nothing about local Clifford
equivalence. The control pair `42-12-4` / `42-12-4-b` stays `equivalent`
through the Tanner graph, as before.

## The new record

`research/audits/permutation_audit-2026-10-24.json`, board at `80b42665b`,
137 s for the whole run. The board now has 84 WL-flagged pairs, 66 carried
over from the first record and 18 from entries added since, and none is
undecided:

| verdict | pairs | how |
|---|---|---|
| equivalent | 2 | Tanner isomorphism, verified, as before |
| inequivalent | 48 | intersection dimension |
| inequivalent | 8 | hull dimensions |
| inequivalent | 3 | weight enumerator of the intersection |
| inequivalent | 15 | light-vector hypergraphs (in every case the check rows) |
| gb_family_no | 8 | no unit map; the light-vector plan is over budget |

The 15 hypergraph verdicts are the ten pairs above, four pairs new since
2026-10-17 (`256-120-10` / `256-120-12`, `288-18-20` / `288-18-22`,
`684-346-8` / `684-346-8-b`, `872-222-18` / `872-222-20`), and
`570-2-40` / `570-2-51`, which the first record had as `gb_family_no` and
which is now a sound inequivalence (rank 284, 273 million row sums per row
space, 25 s); `682-140-76-b` / `682-140-82` moved from `gb_family_no` to
`inequivalent` the same way, by hull dimensions. The 8 pairs still at
`gb_family_no` are generalized bicycle codes with check weights 14 to 32,
where the plans run from 7 x 10^12 to 9 x 10^27 row sums, so the family
verdict stands for them and `undecided` is what any other family would get at
those weights. The literature half is unchanged: 38 of 42 rows re-derived and
equivalent, the four Wang-Pryadko rows not re-derived.
`research/provenance/board_screen.json` is regenerated against the new
record: its 38 WL review matches now carry 1 `equivalent` and 37
`inequivalent`, with none unaudited.
