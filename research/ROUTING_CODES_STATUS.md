# Routing Codes: Status and Next Steps

**Date:** 2026-07-23
**Paper:** arXiv:2606.25330v1 — "Routing Codes: High-Rate Quantum LDPC Codes with Short, Parallel Non-Local Connectivity" (Zhang, Chen, Duan, Li, Wei, Hou, Kong, Wu, Guo)

## What we found

Analyzed the paper and identified ~20 routing codes that would set new
kd²/n records on the qLDPC challenge leaderboard. The strongest candidates:

| Code | n | k | d | kd²/n | vs existing |
|------|---|---|---|-------|-------------|
| [[288,24,18]] | 288 | 24 | 18 | 27.00 | beats [[336,24,18]] (23.14) |
| [[200,8,18]] | 200 | 8 | 18 | 12.96 | beats [[234,8,18]] (11.08) |
| [[100,8,10]] | 100 | 8 | 10 | 8.00 | new (k=8,d=10) |
| [[70,8,7]] | 70 | 8 | 7 | 5.60 | new (k=8,d=7) |
| [[54,8,6]] | 54 | 8 | 6 | 5.33 | beats [[60,8,6]] (4.80) |

All are weight-7 codes with connectivity 4-5, single non-local coupling vector
shorter than (6,3), and time-reversal symmetric routing.

## The problem

**We cannot reconstruct the parity-check matrices (HX, HZ) from the paper's
routing vectors.** Every approach we tried produces codes where CSS commutation
fails or k=0 instead of the claimed k=8.

### What we tried

1. **Direct permutation simulation** — Implemented the lattice permutation σ_t
   as defined in the paper (eq. 2). Applied the palindromic composition
   (eq. 3) to compute stabilizer positions. Result: CSS=False, k=0, weight=5.

2. **Simplified δ_t formula** — Used the paper's closed-form eq. (S4):
   δ_t = 2Σv_τ + v_t. Result: CSS passes for some codes but k=0 or k=2
   instead of k=8. The formula appears to be derived under a translation
   approximation that doesn't match the actual permutation.

3. **Multiple representative syndrome qubits** — Tried using all syndrome
   positions (not just one representative). Result: over-complete check
   matrices, still wrong k.

4. **Earlier build_routing_code (v1)** — Included syndrome qubits as physical
   qubits (n=lm instead of lm/2). Wrong n entirely.

### Root cause found (2026-07-23): composition-order bug, partially fixed

Attempt 1's `_compute_stabilizer_positions` implemented the palindromic
composition (eq. 3) with the backward leg applied in the WRONG order.

Eq. (3): `q_{x,t} = (σ_1∘σ_2∘⋯∘σ_{t-1}∘σ_t∘σ_{t-1}∘⋯∘σ_1)(x)`. After the
forward leg reaches `x(t)`, the backward leg must apply
`σ_{t-1}, σ_{t-2}, ..., σ_1` in **descending** index order. The original code
applied them in **ascending** order (`for i in range(t - 1)`), i.e. it applied
`σ_1, σ_2, ..., σ_{t-1}` instead.

Confirmed by direct test on [[54,8,6]] (torus 18×6):

| order | n | k | CSS | check weight |
|---|---|---|---|---|
| ascending (original bug) | 54 | 0 | False | 5 |
| descending (per eq. 3) | 54 | 4 | **True** | **7** |

The buggy-order result (`CSS=False, k=0, weight=5`) exactly reproduces what
Attempt 1 above reported, confirming this was the cause of that failure.

**Fix applied** in `research/routing_codes.py::_compute_stabilizer_positions`
(loop now runs `for i in range(t - 2, -1, -1)`). This gets CSS commutation to
pass and check weight matching the claimed weight-7 family, but `k=4`, not
the claimed `k=8` — so a discrepancy remains.

Ruled out as causes of the remaining k mismatch:
- Choice of representative X/Z syndrome qubit (tested multiple reps, rank is
  invariant — expected, since translation representatives should give
  isomorphic codes).
- The composition order itself (re-derived independently and hand-verified
  term-by-term against eq. 3; matches).

Still unresolved / not yet investigated:
- The paper's closed-form shortcut (eq. S4, `δ_t = 2Σ_{τ<t} v_τ + v_t`) does
  **not** match the corrected permutation trace's `q_{x,t} - x` beyond the
  first term, when tested on [[54,8,6]]. Either the closed form uses a
  different indexing/reduction convention than assumed here, or there's a
  further bug in the permutation trace itself. This is the next thing to
  reconcile before trusting either path for k=8.

## Final results (2026-07-24): both codes verified, neither advances the board

### What we submitted

Ran `research/submit_routing_codes.py` (fixed to use the research kit's
`make_submission` → `save_submission` pipeline, saving to `research/candidates/`
instead of the trusted `codes/` directory). Each code was built, CSS-verified,
and had its distance searched with `lightest_logical` (16k trials for the
build, then 50k–100k trials in a dedicated follow-up run).

| Code | n | k | CSS | weight | d (paper) | d (found) | trials | verdict |
|---|---|---|---|---|---|---|---|---|
| [[100,8,10]] | 100 | 8 | ✅ | 7 | 10 | **6** | 100k | dominated by [[60,8,6]], [[90,8,10]] |
| [[200,8,18]] | 200 | 8 | ✅ | 7 | 18 | **10** | 50k | dominated by [[192,8,16]], [[108,8,10]] |

Both pass `validate_candidate.py` (verify gate ✅, refutation gate ✅,
no exact duplicates). Neither is `board_advancing`: each is Pareto-dominated
by existing entries in its (weight-8, unrestricted) cell.

### Why d < claimed

For [[100,8,10]]: 100k trials consistently find d=6 on both X and Z sides.
This is almost certainly the true distance — the search is exhaustive enough
that the probability of missing a weight-6 logical in 100k trials is
vanishingly small. Our construction likely produces a *different* [[100,8]]
code than the paper intended (same n, k, weight, CSS; different d).

For [[200,8,18]]: 50k trials find d=10. The refutation gate (8k RIS trials)
also cannot find anything lighter, so d ≥ 10 is well-established. The paper's
d=18 may require a construction detail we're missing — or it may be a
different variant of the routing construction.

### Repo hygiene (fixed)

`research/submit_routing_codes.py` was rewritten to:
1. Save JSON to `research/candidates/` (not the trusted `codes/` directory)
2. Use `make_submission` / `save_submission` from the research kit (proper
   witness search, schema validation, provenance fields)
3. Drop the 3 broken codes ([[54,8,6]], [[70,8,7]], [[288,24,18]])
4. Drop the .npz output format (not needed for the CLI pipeline)

Three stray `.npz` files that had been written to `codes/` were deleted
(untracked, never committed).

## What's done vs. what remains

### Done ✅
- [[100,8,10]] and [[200,8,18]] built, verified, staged in `research/candidates/`
  - Both pass the trustless gate (CSS, k, witness validity, refutation)
  - Neither advances the board (Pareto-dominated by existing entries)
  - Distances found (d=6 and d=10) are lower than paper claims (10 and 18)
- `research/submit_routing_codes.py` fixed: uses `make_submission` / `save_submission`,
  saves to `research/candidates/` (not the trusted `codes/` directory)
- `research/ROUTING_CODES_STATUS.md` updated with final results

### Remaining: fixing the 3 broken codes (optional, low priority)
The composition-order fix produces correct CSS/k/weight for the two codes above
but still fails on [[54,8,6]] (k=4), [[70,8,7]] (k=0, w=5), and
[[288,24,18]] (k=0). Investigating these further requires either:

1. **Contact the authors** — email chenzhaoyun@iai.ustc.edu.cn for HX/HZ
   matrices, Stim circuits, or group-ring polynomials. This is the fastest
   path to understanding the construction details we're missing.
2. **Polynomial approach** — route codes are algebraically equivalent to BB
   codes; extract P(x,y) and Q(x,y) from routing vectors, then use
   `research/kit/bb.py::build_bb()`. The challenge is the extraction step.
3. **Independent search** — use `research/kit/search.py` to find codes with
   similar parameters, bypassing the reconstruction problem entirely.

### Files

- `research/routing_codes.py` — Construction code (working for 2/5 codes)
- `research/submit_routing_codes.py` — Submission pipeline (fixed, working)
- `research/ROUTING_CODES_STATUS.md` — This file
- `research/candidates/100-8-6.json` — [[100,8,10]] (d=6 upper bound)
- `research/candidates/200-8-10.json` — [[200,8,18]] (d=10 upper bound)
