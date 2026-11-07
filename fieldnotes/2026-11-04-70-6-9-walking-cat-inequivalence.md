---
title: The [[70,6,9]] 2BGA entry is permutation-inequivalent to the two Walking Cat bivariate bicycle codes with the same parameters
date: 2026-11-04
author: "@vprusso"
topics: [generalized-bicycle, bivariate-bicycle, code-equivalence, literature-match, nauty, sat]
---

[70-6-9](../codes/70-6-9.json) is a literature reproduction: line 1 of
diswtabelian_wt7wtL3_order35_k6.txt in Lin and Pryadko's public database of
two-block group-algebra codes (github.com/QEC-pages/2BGA-codes @
403d194c3f98f0cadc236aecbc4a8b6139ccf23c, abelian.zip, July 2023), the
abelian group SmallGroup(35,1) with nonidentity supports a = [3, 14] and
b = [3, 13, 20] in 1-based GAP positions. Its novelty label is
known_parameters and its references are arXiv:2306.16400, the database
paper, and arXiv:2604.19481, which lists two codes with the same parameters
that are not this one.

## The two Walking Cat codes

Table XXX of arXiv:2604.19481 lists two weight-7 [[70,6,9]] bivariate
bicycle codes with l = 7 and m = 5. Write S_l for the l by l cyclic shift,
x = S_l (x) I_m, and y = I_l (x) S_m, so that x and y commute and generate the
group algebra of Z_7 x Z_5, which is SmallGroup(35,1). Each code is
H_X = [A | B] and H_Z = [B^T | A^T] with

```
Q70:         A = y^2 + x^2 + x^3 + x^4      B = y + x + x^3
second row:  A = y^3 + x y + x^2 y^2 + x^5  B = x y^3 + x^5 + x^6 y^2
```

Both are connected [[70,6]] codes with 35 checks per side and maximum check
weight 7, so they sit in the board entry's cell with the board entry's
parameters, over the same group.

## Inequivalence

A Tanner-graph isomorphism test proves inequivalence only when both graphs
are built on canonical generating sets, since a permutation equivalence need
not carry the given rows of one code to the given rows of the other. For each
of the three codes and each side, a SAT instance over the 35 row
coefficients, with the weight of the combination capped at 7 and the zero
combination and the 35 single rows excluded, is unsatisfiable. Each code
therefore has exactly 35 stabilizers of weight 7 per side, namely the given
rows, and on each side the set of minimum-weight stabilizers is a canonical
generating set.

On those sets, with research/provenance/iso_common.py, nauty's canonical
forms of the typed Tanner graphs (nauty_certificate) differ between the board
entry and each Walking Cat code, with and without the X/Z swap, and VF2
(tanner_isomorphic) independently finds no isomorphism. Neither Walking Cat
code is a permutation image of the board entry. Inequivalence under local
Clifford transformations beyond the global X/Z swap was not tested.

## What the gate would say

The verifier's Weisfeiler-Leman signature (verify/qldpc_verify.py,
signature) is equal for all three codes, with and without the swap, while
the exact fingerprint differs. A submission of either Walking Cat code would
surface as a review pair against 70-6-9 rather than as a duplicate, which is
why the nauty check was needed before the reference was recorded.

Reported by Nicolas Delfosse (IonQ) in review of the QEC Challenge paper.
FarLab reproduced the Q70 half of the check in review of PR #4460.
