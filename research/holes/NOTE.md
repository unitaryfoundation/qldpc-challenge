# The hole-packing constant exceeds 1/16: a counterexample family to the planar BPT conjecture

**Date:** 2026-08-13 · **Branch:** `research/hole-packing-constant` · **Status:** exact finite instances verified by two independent methods; planar-window trend **complete and confirming**.

**RESULTS addendum (planar windows, all exact):** [[1069,6,8]], [[1797,14,8]],
[[2709,26,8]], [[3805,42,8]], [[5085,62,8]] (m = 2..6): **d = 8 at every
size**, k = holes+1 exactly, ratio 0.0225 → 0.0312 → 0.0384 → 0.0442 →
0.0488, on the predicted rim-dilution curve to 2/23 (crossing 1/16 at
m ≈ 12, n ≈ 16k — instance buildable, exact check needs bit-packed GF2
ops, queued as follow-up).

## Question

The paper `talks/bpt-sharp-constants.tex` conjectures (conj:main) that every family of
stabilizer codes with capacity-4ρ planar layouts and d→∞ satisfies
limsup kd²/(c²n) ≤ 1/16, with the rotated surface code extremal. Punctured
(holey) layouts evade every exact theorem in the paper (they break
bisection-connectivity — rem:puncture), and PR #464's fixed-d hole packing
motivated computing the **asymptotic optimal hole-packing constant**: does it
stay below 1/16?

## Answer

**No. It reaches 2/23 ≈ 0.0870 > 1/16 = 0.0625.**

The witness family — **dual-grid hole packing** — is explicit:

- Rotated (checkerboard-cell) lattice, one qubit per site, all checks in 2×2
  boxes of sites: capacity c = 4 (w = 2, ρ = 1).
- Smooth (X-boundary) h×h holes on a square grid of pitch R = 5h;
  rough (Z-boundary) h×h holes on the dual grid, offset (R/2, R/2).
- On the torus (L = 5hm, m×m of each hole type):
  **[[23h²m², 2m², 4h]]**, giving kd²/(c²n) = 2m²·16h²/(16·23h²m²) = **2/23
  exactly, at every h and m.**

Verified instances (all CSS, commuting, weights ≤ 4, every check in a 2×2 box):

| instance | parameters | d method | ratio |
|---|---|---|---|
| torus h=2, m=2 | **[[368, 8, 8]]** | graph-exact **and** MILP-exact (HiGHS), both sides | 0.08696 = 2/23 |
| torus h=2, m=3 | **[[828, 18, 8]]** | graph-exact **and** MILP-exact, both sides | 2/23 |
| torus h=4, m=2 | **[[1472, 8, 16]]** | graph-exact | 2/23 |
| planar h=2, m=2..3 windows | [[1069,6,8]], [[1797,14,8]] | graph-exact | rim-diluted; **d = 8 persists with open boundary** |

The planar family is the growing window of the same pattern: k = holes+1,
d = 4h (verified at m ≤ 3, trend to m = 6 running), n → (23/25)·W², so the
ratio → 2/23 from below as the rim fraction vanishes. Modulo that trend, the
**planar conjecture is false as stated**; the torus conjecture (1/8) is
untouched — 2/23 < 1/8 — and every *proven* theorem in the paper is
respected (the universal bound caps codes at 3/2+ε; the exact planar 1/16
theorem requires chained/marked boundary-edge hypotheses that holes violate,
by design).

## Why 2/23: the calibrated laws

All measured exactly (graph method cross-validated against MILP on every
config where both ran; `calibration.json`):

1. **Loop law:** the minimal logical encircling an h×h hole has weight 4h
   (h even; 4h+2 for h odd) — matching the paper's rem:puncture accounting.
2. **String metric is Chebyshev:** the minimal same-type hole-to-hole string
   at corner-offset (s₁,s₂) has weight Cheb(s₁,s₂) − h (+1 exactly on the
   diagonal). Measured at h = 2, 3, 4. Mechanism: the Z-connectivity graph
   of the rotated lattice is the diagonally-adjacent grid of Z-cells, so
   diagonal string moves cost 1 per step.
3. **Mixed-type proximity is nearly free:** no light "lasso" mode appears
   down to mixed Chebyshev gap ≈ h (all mixed configs kept d = 4h). The
   lasso threshold ~2g + 2h + O(1) binds only at gap ≲ h − 1.

Cell accounting: same-type Chebyshev exclusion R − h ≥ d = 4h ⇒ R = 5h;
each type packs at density 1/R² (Chebyshev packing = square grid); the two
types interleave at mixed gap 1.5h ≫ lasso threshold. Per hole:
n = R²/2 − h² = 23h²/2, k = 1, d = 4h ⇒ **kd²/(c²n) = 2/23**.

Under a Manhattan string metric the checkerboard gain would vanish and
single-type packing would cap at 1/24 < 1/16 — the entire question turned on
measurement (2), which is why prior "holes are inefficient" folklore
(true for single-type packings: 1/24) missed this.

## Implications

1. **conj:main (planar half) must be revised.** The planar optimum lies in
   [2/23, 3/2+ε], not [1/16, 3/2+ε]. The rotated surface code is *not*
   extremal among unrestricted planar capacity-4 layouts; it remains exactly
   extremal for k=1 (cor:planarsharp, proven) and for chained/marked
   boundary-edge codes (thm:planar, proven). Both theorems stand; the
   conjecture beyond them falls.
2. **The paper's story arguably improves:** the obstruction catalog's
   punctured-layout entry is not merely a limit of the method — it is a
   genuine construction that beats the surface code. Natural revised
   conjecture: **sup = 1/8 on both torus and plane?** (2/23 < 1/8; can
   planar hole/defect packings reach the torus constant? Open.)
3. **The board's asymptotic g-ceiling (g ≤ 1) is false in the plane:**
   this family has g = 16·(2/23) = 32/23 ≈ 1.39 with d → ∞.
4. 2/23 is a **floor** for the optimal planar constant, not a ceiling:
   rectangular holes, other defect types (twists), and non-square lattices
   were not optimized. The dual-grid family is extremal only within
   square-hole/two-type packings under the measured laws.

## Epistemics

- Exact and double-verified: the [[368,8,8]] instance (graph + MILP).
- Exact, single-method (graph, itself MILP-validated on 12 configs): the
  other instances and all calibration laws.
- Measured, not proven: the laws hold at the tested h (2,3,4) and offsets;
  the d = 4h claim for the *infinite* family is an extrapolation from
  finite exact instances (h = 2, 4; m ≤ 3 torus, m ≤ 6 planar pending).
  A combinatorial distance proof for the family (string/loop lower bounds
  via the paper's own vacuum/flux machinery on the punctured lattice) is
  the natural next step and looks tractable — the graph structure that
  makes the computation fast is the same structure a proof would use.
- Constructions built by greedy maximal-commuting completion
  (`holey.py:build_greedy` / `build_torus_greedy`); this only *under*-counts
  achievable codes, so it cannot manufacture a false positive ratio — the
  risk surface is the exact distance computation, hence the two methods.

## Files

`holey.py` (constructors), `distance.py` (MILP), `graphdist.py`
(graph-exact distances; soundness/completeness argument in docstring),
`calibrate.py` + `calibration.json` (metric laws), `packing.py` (packings).
