# Simulation pipeline: logical error rates of the dual-grid hole family

**Goal:** determine whether the [[23h²m², 2m², 4h]] family's 39% density
advantage over surface-code patches (4.3% over Gidney–Ekerå/Fujiu patch
fusion) survives at the *logical error rate* level — the gate for the
standalone paper. Toolchain: stim 1.14 + pymatching 2.3 + sinter 1.14
(all present locally).

## Stage 0 — phenomenological baseline (no circuits, fast go/no-go)

Code-level noise only: X/Z data errors at rate p per round + measurement
flips at q = p, stabilizers measured via noisy `MPP` (no ancillas, no
hooks). This isolates the two code-level risks from schedule effects:

- **Path-degeneracy entropy**: inter-hole strings have many
  minimum-weight representatives; loops have few. Degeneracy raises the
  logical-rate prefactor at equal distance.
- **Decoding-graph structure**: our codes are boundary-edge codes —
  every error flips ≤ 2 checks of a type — so the DEM is exactly
  graphlike and MWPM is the right decoder with no hypergraph issues.

Deliverable: logical error per round *per logical qubit* vs p for
dual-grid planar windows (h=2, m=2..4) against rotated patches at equal
qubit budget. **Go/no-go: if holes lose > ~2× per logical qubit here,
the practical paper dies early and cheaply.**

## Stage 1 — syndrome-extraction schedule (the creative piece, made mechanical)

One ancilla per check, 4 CX layers per round (weight-2/3 checks idle in
their missing layers). The risk is hook errors: an ancilla fault
mid-extraction propagates to 2 data qubits; if the pair lies *along* a
minimum-weight logical path, circuit-level distance drops below d. Holes
make this hard by hand: loops run in all four directions and strings run
diagonally (Chebyshev), so no single global CX order is obviously safe.

The plan converts design into **search-and-verify**:

1. **Parametrize** schedules by CX-order classes per region: bulk
   (standard rotated-code order pair as the seed), the four sides of
   each hole ring, hole corners, outer boundary. By periodicity of the
   pattern, one parameter set covers all holes of a type.
2. **Constrain**: per layer, each data qubit is touched by at most one
   CX (conflict-freeness); weight-2/3 checks choose which layers they
   occupy — extra freedom, also searched.
3. **Verify mechanically**: build the full noisy circuit in stim, then
   `search_for_undetectable_logical_errors` on the detector error model
   gives the exact circuit-level distance of the candidate schedule.
   Iterate local search over ring/corner orders until circuit distance
   = d (accept d−1 with a quantified λ penalty if the search stalls;
   the harmful patterns halve loops/diagonals, so even certifying
   > 3d/4 is meaningful progress over naive).
4. Deliverable: a schedule with machine-certified circuit distance for
   h=2, m=2/3 planar windows, plus the periodicity argument for larger m.

This is the same trick that made the distance computation tractable:
replace cleverness with exact certification in the loop.

## Stage 2 — circuit-level Monte Carlo

Uniform depolarizing circuit noise (gate, idle, reset/measure at p),
memory-X and memory-Z experiments, d rounds, MWPM (pymatching; optional
correlated-matching pass later). Instances: h=2 (d=8) at m = 2, 3, 4;
h=4 (d=16) at m = 2. Baselines at equal qubit budget: (a) tiled rotated
patches, (b) a reconstruction of Fujiu et al.'s horizontal fused row
(their clean case). Sweep p ∈ [10⁻³, 10⁻²], sinter orchestration,
~10⁸ shots at the low end (overnight local runs).

## Stage 3 — analysis and writeup

Per-logical-qubit error rate at equal qubit budget; λ (error-suppression
factor per distance step) for holes vs patches; teraquop-footprint
extrapolation (qubits per logical at 10⁻¹² target); the comparison table
vs patches / fusion / twists (twists cited as the different-tradeoff
frontier: weight-5 non-CSS, degree-3, no distance guarantees). Paper
positioning: *densest CSS weight-4 square-lattice planar memory with
certified code AND circuit distance*.

## Risks and mitigations

1. Stage-0 entropy loss → cheap early kill (or reframe as theory-only).
2. Schedule search stalls below d → quantify the gap; d−1 with good λ
   may still win at equal budget; report honestly.
3. Fusion baseline reconstruction mismatch → validate our Fujiu-row
   implementation against their published logical-error curves first.
4. Boundary observables: logical observables come from our exact
   graph-method witnesses (loop + string basis per hole) — already
   computed, no new machinery.
