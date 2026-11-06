---
title: "3D layouts and the D=3 geometric efficiency g: what a small campaign found"
date: 2026-10-30
topics: [3d, layouts, geometric-efficiency, layer-codes]
author: MathysRennela
---

Closes #4163: a campaign to reach `g >= 1` for a `d >= 3` code with a D = 3
layout, via the layer-code construction (Williamson–Baspin, arXiv:2309.16503)
and via attaching 3D coordinates to an existing code.

## What was tried

1. **Direct layer-code construction (Williamson–Baspin, arXiv:2309.16503).**
   Attempted scaffolds for the `[[4,2,2]]` input. The naive defect-coupling
   checks failed CSS commutation (`k=-8`, `commutes=False`). Section VI of
   the paper specifies the checks only as inline figures (a 3D lattice
   drawing with red/blue highlighted regions and their adjacent-edge
   supports), not as text, so transcription requires reading ~8 figures for
   the `[[11,3,3]]` case alone. Not completed; no citable artifact exists.

2. **Batch-gate sweep for a base code.** Ran `coordination.py gate` across
   the staged-candidate pool (local working output, not citable as
   evidence). Thousands passed all three gates. The first `d >= 3`
   board-advancing survivor was an `[[11,3,3]]` CSS code (`weight-6`,
   witness-backed `d <= 3` on support `[0,1,7]`).

3. **Attach a 3D layout.** Gave the `[[11,3,3]]` code a compact 3×3×3 grid
   (spacing 1, `layers=1`) as `locality.coordinates`. The gate passed
   (`verify`, `refute`, `dedup` all green; `board_advancing: true`,
   `advances_by: ["n"]` over `[[12,3,3]]`). The code and note are in PR #4239
   (`codes/11-3-3-f.json`, `notes/11-3-3-f.md`).

## Why g >= 1 did not land

The D = 3 score is `g = 2·sqrt(2)·k·d/(n·ρ·r³)`. For the `[[11,3,3]]` entry
with the compact grid: `r = 3.0`, `ρ = 1`, so

    g = 2·sqrt(2)·3·3 / (11·1·3³) ≈ 0.086

The `r³` term dominates: any check whose support spans several lattice units
pushes `g` far below 1. The `[[4,2,2]]`-based layer code is worse — `N = 6L²`
grows quadratically with patch size `L` while `D` grows at most linearly, so
`g ∝ 1/L` and the best achievable value is `g ≤ 0.67` (capped by the input's
`d = 2`). Asymptotically a good-LDPC input gives `g → c` for an unspecified
Theta-prefactor `c`; `g ≥ 1` would need `c ≥ 1`, which the paper does not
guarantee.

## Verdict

Switching to 3D coordinates does **not** by itself lift `g` past 1 for existing
or small layer-code instances. The only `g ≥ 1, d ≥ 3` example in the
reference material is the `[[4,2,2]]` code on a plaquette (`g = 2`), which is
excluded from the headline by `GEO_MIN_D = 3`. Reaching `g ≥ 1` at `d ≥ 3`
appears to require a genuine 3D-native construction that saturates the BPT
bound with a favorable constant — not delivered by the paths tried here.

## Outcome

- PR #4239 lands a gate-passing, board-advancing `[[11,3,3]]` with an honest
  3D layout (valid `unrestricted` entry, `g ≈ 0.086`).
- The `g ≥ 1` target of #4163 is **not** met; closing the issue with this
  negative result recorded.