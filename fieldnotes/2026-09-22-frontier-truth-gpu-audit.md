---
title: "Frontier truth at 300M GPU trials: 681 entries re-measured, twelve corrections, three of them exact"
date: 2026-09-22
author: "@vprusso"
model: Claude Fable 5.1
topics: [distance-audit, calibration, generalized-bicycle, RIS, over-claim, refutation-gate]
status: active
related:
  - 2026-09-18-bilayer-weight8-leader-audit.md
  - 2026-07-01-trial-depth-floors.md
---

## What was re-measured

Campaign 0 of issue #1851 asks for deep fresh-seed re-measurement of the
board's leaders before compute is spent trying to beat them. Two sets went
through `verify/ris_gpu.py` in recover mode on one A40, 300,000,000 trials
per side per entry, one fresh seed per set. The wrapper derives the
opposite-side logical basis with `verify/gf2.py`, hands the packed matrices to
the `verify/ris_gpu.cu` binary, and re-verifies every recovered operator on the
CPU (in the kernel of the opposite checks, anticommuting with a logical, weight
recounted); only CPU-verified operators are reported.

- The 90 newly verified entries (seed 2027, about 14 hours): 84 receipts in
  this set, four more ([[288,12,24]], [[216,6,23]], [[288,18,20]],
  [[216,12,18]]) fall in the frontier set below, and `codes/682-20-22.json` and
  `codes/336-20-20.json` have no receipt.
- The 599 upper-bound entries of the frontier, ordered by descending kd^2/n
  (seed 2031, about 23 hours): 597 receipts; [[998,54,5]] and [[964,52,5]]
  produced none.

Each receipt records, per side, the claimed weight, the lightest CPU-verified
logical found, the trial count, and the seed. The receipts are not in this
tree; every change they drove is a correction PR whose note carries the
witness and its budget, so the evidence trail is the PR set below.

## Outcome

| entry as filed | claimed d | found | correction | mechanism |
|---|---:|---:|---|---|
| [[682,182,76]], now `codes/682-182-66.json` | 76 | 66 | #1760 | exact, norm-word lift (RIS at 300M read 74) |
| [[682,182,75]], now `codes/682-182-66-b.json` | 75 | 66 | #1771 | exact, same lift (same code up to permutation, issue #1651) |
| [[682,172,76]] weight 32, now `codes/682-172-72.json` | 76 | 72 | #1809 | exact, single-block constituent word |
| [[682,140,86]], now `codes/682-140-82.json` | 86 | 82 | #1762 | sampled |
| [[682,142,85]], now `codes/682-142-82.json` | 85 | 82 | #1763 | sampled |
| [[640,16,88]], now `codes/640-16-52.json` | 88 | 52 | #1742 | sampled |
| [[400,12,50]], now `codes/400-12-40.json` | 50 | 40 | #1744 | sampled |
| [[396,10,37]], now `codes/396-10-33.json` | 37 | 33 | #1743 | sampled |
| [[600,8,96]], now `codes/600-8-92.json` | 96 | 92 | #1779 | sampled |
| [[360,8,48]], now `codes/360-8-45.json` | 48 | 45 | #1778 | sampled |
| [[968,18,33]], `codes/968-18-33.json` | 33 | 32 | #1852 (open) | sampled, later run at the same budget, seed 2051 |
| [[390,82,32]], now `codes/390-82-31-b.json` | 32 | 31 | #1761 | exact, duplicate of [[390,82,31]] (issue #1651); RIS read 32 |

The GPU also read 19 against 20 on [[562,18,20]]; PR #1731 had already
refiled it as `codes/562-18-19.json` from an independent CPU run.

## What held

New-entry set: 4 of 84 refuted, 70 read exactly the claim, 10 read above it.
Frontier set: 5 of 597 refuted, 579 read exactly the claim, 13 read above it.
A reading above the claim is inconclusive, not corroboration: the search did
not reach the claim, so it says nothing either way (the convention of
`fieldnotes/2026-09-18-bilayer-weight8-leader-audit.md`).

The five frontier refutations sit at ranks 1, 2, 3, 19, and 42 by kd^2/n. The
top three are the n = 682 generalized-bicycle leaders; the other two are k = 8
low-rate entries. Ranks 4 through 18 (the 674 family, both [[666,150,76]]
entries, [[662,180,60]], [[502,102,50]], and the rest) and everything from
rank 43 down held or read above the claim. Below the top three, the frontier
held at 300M trials on a fresh seed.

Of the four leaders the issue names for its first step: [[682,182,76]] is
refuted to 66 exactly; [[684,14,72]] read 83, [[684,10,101]] read 108, and
[[922,18,31]] read 33, all above the claim, so their own ladders remain the
deepest evidence about them. [[682,172,76]] with check weight 28
(`codes/682-172-76.json`, kd^2/n 1456.7) was in neither set; its constituent
cap below is exactly 76, so the exact checks give it no slack.

## Two exact bounds

Both apply to cyclic generalized-bicycle codes: H_X = [A | B] and
H_Z = [B^T | A^T] with A and B the m x m circulants of polynomials a and b in
GF(2)[x]/(x^m - 1), so n = 2m.

Norm-word lift. Let m = q r with q a proper divisor. Reducing a and b modulo
x^q - 1 gives the quotient code on Z_q, whose dimension is 2 deg gcd(a, b,
x^q - 1). Let N_r = (x^m - 1)/(x^q - 1) = 1 + x^q + ... + x^{q(r-1)} be the
norm word, of weight r. If u is a logical of the quotient code of weight w,
then N_r u is a logical of the full code of weight r w: it lies in the kernel
of the Z checks because N_r (x^q - 1) = x^m - 1 = 0, and it is not a stabilizer
because N_r = 1 modulo x^q - 1, so a stabilizer lift would reduce to a
stabilizer of the quotient. Hence d <= (m/q) d_q, with d_q the quotient
distance. For both k = 182 entries m = 341, q = 31, r = 11; the degree-91 gcd
contains x - 1 and two of the six degree-5 factors of x^31 - 1, the quotient
is a [[62,22]] code with a weight-6 logical, and d <= 11 x 6 = 66. The same
lift gives 88 for [[682,172]] and 99 for [[682,142]], neither binding, and
nothing for [[682,140]], whose quotient has k = 0.

Constituent cyclic code. Let g = gcd(b, x^m - 1) and h = (x^m - 1)/g. The
annihilator of b is the ideal generated by h, which as a set of vectors is the
[m, deg g] cyclic code C_g with nonzeros at the roots of g. For any u in C_g
the single-block operator (u | 0) commutes with every Z check, since u b = 0.
It is an X stabilizer only if u lies in a times the annihilator of b, the
ideal generated by h gcd(a, g), a proper subideal of C_g whenever gcd(a, g) is
not 1 and the zero ideal when g divides a. Every word of C_g outside that
subideal is therefore an X logical, and d is at most the weight of the
lightest such word, which transports to the Z side by the block-swap and
reversal symmetry. C_g has dimension deg g, so information-set search on it
is close to exact at a few hundred thousand trials. For the weight-32
[[682,172]] entry deg g = 96 and C_g has a weight-72 word that validates on
the committed matrices, so d <= 72. The weight-28 [[682,172,76]] entry sits at
its cap of 76 (both gcds of degree 86); [[682,140,82]] and [[682,142,82]] sit
6 below their caps of 88.

## Consequence for Campaign 0 and for the gate

Campaign 0 has run. The n = 682 top of the board reprices from 1541.4 to
1456.7, held by the weight-28 [[682,172,76]] entry at its own exact cap; the
remaining targets in `fieldnotes/2026-09-18-hackathon-1155-frontier-map-and-playbook.md`
should be re-read against the corrected leaders above. One seed at 300M is a
floor, not a ceiling: all eight sampled corrections had passed the gate at
merge time, and the [[640,16,88]] to 52 collapse is 36 units below a claim
that had survived it.

The CI refuter (`verify/gate_changed.py`, `_fast_refute`) runs at most
8,000,000 trials at `pair_depth=8`, and the weekly sweep
(`verify/refute_board.py`) drives the same candidate set. It misses
two things this audit found. First, the sampled corrections: the gate's
budget is 37 times smaller than the one that found the eight above, and even
300M trials find 74, not 66, on [[682,182,76]]. Second, the exact bounds, which no sampling budget
reaches because the witness sits in a low-dimensional subspace (the norm lift
lives inside one coset of the quotient, the single-block word inside one
circulant block). Closing the gap needs a standing GPU check, a
`verify/ris_gpu.py` campaign over the frontier at 300M trials per side with a
fresh seed each run, plus two exact checks for entries where
`verify/gf2_fast` `circulant_gb_witness` reports a nonzero block size: the
quotient check (for each proper divisor q of m, form the quotient code,
search it, and lift by N_r) and the single-block check (search C_{gcd(a)} and
C_{gcd(b)} and validate (u | 0) and (0 | u) on the committed matrices). Both
exact checks run on codes of dimension deg g and cost seconds; the detector
that identifies the family already exists (issue #942), and only the two
searches behind it are missing.
