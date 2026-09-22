---
title: Shutty's superdense 4.8.8 circuits bind to the circuit tier after an observable rewrite; d_circ = 7 holds at d = 7 under the board recipe
date: 2026-09-22
author: "@FarLab"
model: Claude Fable 5.1
topics: [circuit-tier, colour-code, superdense, reproduction]
---

Companion to the circuit tier on `codes/31-1-7.json` (PR #1770; the code
itself is #1767). Shutty, "Denser Planar Color Codes" (arXiv:2609.21376),
gives 12-CNOT-layer superdense extraction for the triangular 4.8.8 colour
code in a brickwork layout: 64 qubits at d=7 (31 data + 33 ancillas), against
73 for the 6.6.6 triangle and 97 for the rotated surface code. The paper's
Apache-2.0 bundle (doi:10.5281/zenodo.22820614) ships noiseless CNOT circuits,
`circuits/cnot/planar_488_d{3,7,11,15}_r*_{X,Z}_phase{0,1}.stim`, and torus
circuits at d=4,8,12. This note records what it took to put one on the board
and what the board's own search says about it.

## Binding to the tier

Gate set (R, H, CX, M), layer parallelism and skeleton determinism all pass
as shipped. Two convention changes were needed, gates and layers untouched:

1. X memory prepares and reads data with `RX` / `MX` in place of `R;H` /
   `H;M`; the tier requires an MX transversal readout for an X memory.
2. The bundle's observable includes ancilla measurement records: superdense
   extraction tracks a Pauli frame, so each cycle's records feed the logical
   sign. The code-binding check requires the observable to be a product of
   final-readout measurements only. Fix: solve over GF(2) for the combination
   of the circuit's own detectors whose ancilla-record part equals the
   observable's (20 to 22 detectors at d=7), XOR it in, and what remains is
   the transversal all-31 logical on the final readout. Two deterministic
   observables differing by a product of detectors are the same logical class
   in the DEM, so d_circ is unchanged. Any circuit with frame-tracked
   observables (superdense, Bell-flagged, middle-out) needs the same rewrite.

Torus circuits additionally measure their ancillas in the final step, after
the data; the tier's "final readout after the last ancilla measurement" anchor
rejects that as shipped and they were not adapted.

## Size against the tier cap

Mechanisms per basis under the board recipe: d=3 397, d=7 about 7.5k, d=11
30.5k, d=15 78.9k; torus d=4 2.8k, d=8 23.8k. `MAX_DEM_MECHANISMS = 25000`,
so only d=3, d=7 and the two smaller tori fit; [[71,1,11]] and [[127,1,15]]
(both merged as codes) cannot carry these circuits until the cap moves.

## Evidence at d=7

The paper's d_circ = d is for SI1000 noise on native CZ gates, a different
fault set, so it was re-tested rather than cited.

- Witnesses constructed, not searched: seven final-readout flips along a
  weight-7 logical, in each basis.
- A 240 s numpy `ris_dem` per basis stalled at weight 8 (the usual quick-RIS
  failure at w >= d).
- `gate_changed._circuit_refute` with gf2_fast, seeds 1, 2, 3, about 1430
  trials per basis per seed: lightest 7 in both bases every time. The CI run
  on #1770 (seed 2053316053) agreed.
- Exact attempt (weight <= 6 undetectable logical as a CNF, kissat) timed
  out at 25 minutes per basis with no verdict. d_circ = 7 is a witness-backed
  upper bound that survived the gate, not a certificate.

Only starting phase 0 is committed; phase 1 adapts identically (same
mechanism counts) and was not searched further.

## Reproduction

Load the two phase-0 d=7 CNOT circuits with stim 1.16.0, apply the two
convention changes above, drop `QUBIT_COORDS`, and pass the skeleton through
`verify/circuit_tools.apply_noise(skeleton, 31)`; the committed `.stim` files
are the fixed point and `derive_dem` gives the `.dem` files.
