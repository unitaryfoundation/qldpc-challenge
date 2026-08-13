# Scope: yoked dual-grid hole memories

**Question:** does yoking (Gidney–Newman–Brooks–Jones outer parity codes,
arXiv:2312.04522) compose with the dual-grid hole family — and if so, does
the composition beat the current storage frontier (yoked patches, ~3×
logical/physical in the teraquop regime at p = 10⁻³), which is what
Gidney-2025's sub-million-qubit RSA estimate (arXiv:2505.15917) uses for
idle storage?

## Why composition could more than multiply

Two stacking effects, one multiplicative and one *amplified*:

1. **Packing carries through (×1.39, low risk).** Yokes are an outer code
   over stored logicals; the inner memory's footprint enters linearly.
   If yoke checks cost comparable overhead, yoked dual-grid ≈ 1.39 ×
   yoked patches by density alone.
2. **Inner quality is amplified by the yoke (the sleeper).** Yoked
   density gains come from shaving inner distance: the outer code
   (distance 2 for 1D yokes, 4 for 2D) suppresses inner logical errors
   as p_inner^2 or p_inner^4. An inner memory with a 3–8× lower
   per-logical rate (our Stage-0 measurement, pending circuit-level
   confirmation) therefore gains 9–64× (1D) after the yoke — worth
   roughly one to two further inner-distance steps, i.e. another
   ~(d−2)²/d² ≈ 25% area at d = 16. Composition target:
   **~1.8× over yoked patches**, or ~5–6× over plain patches.

If the full chain holds, the Gidney-2025 machine's storage component
shrinks ~1.8×; at a storage-dominated footprint that's a ~25–30% total
qubit reduction — the first version of this work that would genuinely
touch the RSA numbers. Every link must hold, though; kill-conditions below.

## The architectural observation that makes this plausible

Yokes need joint logical parity measurements across stored qubits (rows
of X⊗X or Z⊗Z via lattice surgery, measured rarely). For patches this
costs workspace rows between patches. For the dual-grid family:

- The product of two same-type hole logicals X̄ᵢX̄ⱼ **is the inter-hole
  corridor string** — the weight-4h operator along the corridor.
- Measuring it = temporarily activating a strip of modified checks along
  the corridor — precisely the defect-fusion / strip-surgery primitive of
  the braiding era, in a corridor that **already exists in the layout**.

So the yoke checks of a hole-row are measured *in place*, through the
corridors, with no dedicated workspace rows — the dual-grid geometry is
"pre-wired" for exactly the joint measurements the yoke needs. Where
yoked patches pay area for surgery workspace, yoked holes may pay ~none.
This is the concrete reason the composition could beat 1.39×-times-yoke
rather than lose overhead to it.

## Research questions, ranked by risk

1. **(Highest risk) Corridor-surgery primitive fidelity:** does the
   temporary strip measurement of X̄ᵢX̄ⱼ preserve fault distance during
   the merge window (the analog of d rounds of lattice surgery)? The
   Chebyshev wiggle-room that resists hook scheduling (our Stage-1
   finding) will also appear here. Mitigation: same certify-in-the-loop
   method; the primitive is small enough to certify exactly.
2. **Basis completeness:** 1D yokes need one basis; 2D yokes need both.
   Z̄ products of X-holes are co-loops (annuli), not corridor strings —
   measuring those may need genuine annular surgery (harder). A 1D-yoke
   design using only string-parities may be the right first target.
3. **Inner circuit-level rate** (Stage-2 dependency): the 3–8× cushion
   must survive syndrome extraction, including the current d_circ 6/8
   deficit — or the geometry-relaxation variant (R = 5h+1) must recover it.
4. **Outer decoding and yoke scheduling:** should port unchanged from
   the yoked-patch paper (yokes rare, outer decoder trivial); verify no
   interaction with hole matching graphs.
5. **Access latency:** unpack cost for computation (fuse/unfuse, ~d
   rounds) — same hierarchy role as dense packing / yoked patches; not
   a differentiator, just needs an honest table entry.

## Phased plan

- **Phase A (1–2 sessions):** design + stim-certify the corridor-surgery
  parity measurement between two X-holes: build the merged-strip check
  configuration, certify fault distance of the merge window, measure its
  logical fidelity vs a patch lattice-surgery control. Kill-condition:
  merge-window fault distance < d/2 with no schedule fix.
- **Phase B:** small yoked-row memory sim — one 1D yoke over an m-hole
  row vs a yoked-patch row at equal qubit budget, teraquop-style
  extrapolation of logical error per stored qubit. Kill-condition: no
  net win vs yoked patches at p = 10⁻³.
- **Phase C:** GE-style resource re-estimate: swap the storage layer of
  the Gidney-2025 accounting for yoked dual-grid, recompute total qubit
  count. This is the "does it touch RSA" number.

Phase A is the same scale of work as the current schedule search and
reuses all of its machinery. B is a paper-sized effort on its own; a
positive A+B is plausibly a second paper ("yoked hole memories") with
the resource-estimate delta as its headline.
