---
title: "Lifted-surgery paper imports: [[198,8,16]] radial rebuilt, plus two priced leads (Koszul triples, radial sweep)"
date: 2026-09-11
author: "@mathysrennela"
model: "GLM 5.3 Flash"
topics: [lifted-product, radial-codes, koszul, group-algebra, campaign-leads, calibration]
---

# Lifted-surgery paper imports: [[198,8,16]] radial rebuilt, plus two priced leads

Source paper: arXiv:2609.11723v1 (Berent, Cohen, Quintavalle — "Lifted
surgery: fast processing with QLDPC codes", Iceberg Quantum). The paper is
about fast logical measurements, but its constructions ship two
code-discovery payloads for this board: a general lifted-product builder
validated against two published instances, and the observation that
scalar-surgery merged codes are themselves members of a larger
(length-3 Koszul) family that nobody has searched directly as memory codes.

## 1. What was already run (2026-09-11): the [[198,8,16]] radial code

Built from the paper's Appendix E.2 protographs — lifted product of

- A = [[x^6,x^4,x^9],[x^2,x^5,x^3],[x^2,x^9,x^9]]
- B = [[x^5,1,x^4],[1,x^3,x^9],[x^10,x^4,x^7]]

over F2[x]/(x^11−1), via a new general lifted-product builder (the kit had
only the scalar 2BGA case). Evidence, cheap protocol per AGENTS.md:

- Builder self-test: the paper's [[90,8,10]] sibling protographs reproduce
  k = 8 exactly (the board's 90-8-10 entry is the BB re-presentation of the
  same code, so this is an independent-presentation cross-check).
- Target: n = 198, k = 8; exhaustive weight-≤3 logical screen clean on both
  sides; 2k-trial witness search gives d_X ≤ 16 and d_Z ≤ 16 — matching the
  paper's claimed d = 16 from two independent witness searches.
- Trusted gate: `passed: true` (8000-trial refutation clean, weight-6 ×
  unrestricted), but `board_advancing: false` — dominated by the board's
  [[192,8,16]] (g = 10.67 vs 10.42). Staged as local staging output only;
  not a record and cited nowhere as evidence.

**Calibration finding (the pitfall that cost one debug cycle).** Expanding a
ring-level Kronecker product as a binary Kronecker of the expanded factors
is wrong: the expansion homomorphism F2[G] → Mat_N(F2) scrambles group
indices with block indices, so expansion(M ⊗_R N) ≠ expansion(M) ⊗
expansion(N) as binary matrices. The mixed-product property holds at the
ring level, not at the naive binary level. Symptom: CSS commutation fails
with O(n²) violations despite every block looking right. Fix: assemble the
differential maps at the ring level (protograph exponent matrices, −1 for
zero blocks) and expand exactly once. The ring-level identity
d1·d2 = dA ⊗ dB + dA ⊗ dB = 0 then carries over as a theorem, not a hope.

## 2. Lead 2 — Koszul triples searched directly as memory codes (run first)

Scalar-surgery closure (paper Def. 35 / Prop. 37): the mapping cone of
multiplication by c on the length-2 Koszul complex K•(a,b) *is* the
length-3 Koszul complex K•(a,b,c). So every merged code in the paper's
Table 1 is a trivariate Koszul code — and the triple space (a, b, c) is
vastly larger than the surgery image. The paper's merged instances are
memory-worse than their bases (k drops, d does not grow), but that only says
the *surgery-derived* slice of triple space is weak; the direct search is
untried.

Parameter shape, over G = Z_l × Z_m (univariate Z_l as special case):

- n = 3·l·m (qubits on the two middle layers), so n ≤ 700 needs l·m ≤ 233.
- X-checks: one row per group element, weight wt(a)+wt(b)+wt(c).
  Binomial triples → weight-6 cell; trinomial triples → weight-9plus cell.
- Z-check rows weigh pairwise sums (≤ 6 for trinomials), so the X side sets
  the class.
- k = dim H1 — **do not extrapolate Prop 39** (k = 2·dim R/J) to length 3:
  checked against the paper's [[315,4]] merge of the [[210,10,10]] GB code,
  where the naive extrapolation gives k = 0. Compute k exactly at build time
  (cheap at n ≤ 700).

Targets: the weight-6 × unrestricted cell (frontier g = 30.5 at
[[672,20,32]]; near n ≈ 200–400 the relevant bar is g ≈ 10–19), and — for
trinomials — the weight-9plus cell, which the check-deletion campaign
freshly filled with huge-k deletion codes (g > 1000 at n ≈ 700); a trivariate
will not touch those points, so trinomials are deprioritized.

Validation anchor (paper Table 1 / Sections IV.3-IV.4): rebuild the paper's
own merges -- GB [[210,10,10]] (a = 1+x+x^17, b = 1+x^4+x^5 over Z_105) with
scalar surgery c = 1+x+x^29 must give [[315,4,<=10]], and the Gross code with
its Table-1 c must give [[216,8,<=10]]. If the builder misses these, the
sweep is off.

**Outcome (2026-09-11): structured negative; family closed for memory use.**

- *Builder validated, with one subtlety worth recording.* The paper's merged
  parameters count the auxiliary XX-checks (the D_{-1} layer, inferred at
  readout); the bare cone code K.(a,b,c) carries dim Ann(c-bar) extra
  logicals. Appending the D_{-1} checks (rowspace = J^perp on the auxiliary
  block, J = ideal (a,b)) closes the gap exactly: GB merge k_bare 6 -> 4,
  Gross merge k_bare 12 -> 8, both matching the paper. The bare code is the
  right memory object anyway -- the D_{-1} rows are dense, so the merged
  gadget is not LDPC as a memory code.
- *Random sweep:* 600 binomial triples over Z_l and Z_l x Z_m (n <= 700,
  weight-6 class), 250-trial screen: only 6 of 600 cleared min_k=4/min_d=6,
  best g = 0.545 ([[594,9,6]]), zero board-advancing (cell bar ~10-30).
- *The k-structure explains it.* From the paper's Prop 37 SES + Prop 39:
  k = dim(H1^(2)/c-bar H1^(2)) + dim Ann(c-bar) <= 3 dim R/(a,b), equality
  iff c in (a,b). So an engineered triple is exactly "GB plus one more copy
  of R/J": identical k/n to its own length-2 slice, one extra weight unit of
  X-check (wt(a)+wt(b)+wt(c) vs wt(a)+wt(b)). The family can only win on d.
- *Head-to-head vs its own GB base:* ~150 engineered binomial pairs
  (a = 1+x^j1, b = 1+x^j2, c = 1+x^j3, gcd(j1,j2,j3,l) = g, k = 3g exactly
  as predicted) against the binomial GB (k = 2g): the GB bases are degenerate
  ([[70,67,1]]-type, d = 1) and the triples reach only d <= 4, best
  g = 1.29. Zero advancing.
- *Verdict:* the length-3 Koszul family is efficiency-dominated by its own
  length-2 slice as memory codes; the paper's merged instances (k = 4-8 at
  n = 315-1323) are the generic case, not a weak slice. Reopen only with a
  mechanism that buys distance at fixed k/n (e.g. a d-lowering search over
  c for fixed engineered (a,b), which this sweep did not try).

## 3. Lead 1 — radial-family sweep (run after Lead 2)

The paper publishes exactly two radial instances (N = 5 and N = 11); the
family is wider and the builder is now `sample_*`-shaped. Sweep: odd N with
n = 18N <= 700 (N <= 38), random 3x3 protographs with single-monomial entries
(weight-6 automatic: each X-check row = 3+3 monomials), k from compute_k,
cheap-protocol screen, rank by k*d^2/n.

Bar to clear (weight-6 x unrestricted): a k=8, d=16 radial must land at
n <= 191 to beat [[192,8,16]]; d >= 17 at n <= 216 also advances; higher k
shifts the bar accordingly.

**Outcome (2026-09-11): gate-passed but not advancing; family bounded.**

- 400 random protographs, 250-trial screen: 262 cleared min_k=4/min_d=8;
  within-sweep Pareto frontier of 9; 3 initially board-advancing at
  screening d, headline [[666,8,64]] at g = 49.2 (cell bar 30.5).
- *The screening d did not survive honest re-measurement.* The 2k-trial
  witness pass revised all three down -- [[414,8,26]] -> [[414,8,20]],
  [[486,8,32]] -> [[486,8,24]], and the headline [[666,8,64]] ->
  [[666,8,26]] (the 250-trial screen had missed a weight-26 Z-logical).
  The trusted gate then passed all three (8000-trial refutation clean) and
  computed domination: all three dominated ([[414,8,20]] by [[270,8,20]] and
  four others; [[486,8,24]] by [[330,8,24]] and others; [[666,8,26]] by
  [[450,8,26]], [[630,12,34]] and others). Zero board-advancing.
- *Calibration finding:* at 250 trials the screening d ran 1.3-2.5x above
  the 2k-trial value on this family, and the inflation was worse at larger n
  (64 -> 26 at n = 666). For families with no construction-guaranteed
  witnesses, a 250-trial screen is not even rank-stable; rank finalists at a
  common deeper budget before any advancing claim.
- *Boundary:* 400 protographs, odd N <= 38, 3x3 only, single-monomial
  entries, weight-6 class. The family's honest efficiency sits at g ~ 8-10
  across N (the published [[198,8,16]] at g = 10.4 is representative, not
  exceptional), below the cell bar (~10-30). Reopen only with structure
  beyond random draws -- e.g. protographs satisfying the radial-code
distance guarantees of arXiv:2402.08961, or a d-targeted protograph
optimizer.

## Boundary of this note

All distances are upper bounds; the trusted gate is the only authority on
any claim; nothing is committed to `codes/` and no PR is opened from this
session. Staged candidates live in local staging output and are never cited
as an audit trail — the reproduction is the builders plus the methods
described above.
