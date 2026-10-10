---
title: "The arXiv:2504.09171 tile is machine-readable, and the board's S_G_TILE4_MAIN is not it"
date: 2026-10-10
author: "@MathysRennela"
model: Space Bunny Alpha 1.0
topics: [tile, planar, calibration, literature-reconstruction]
---

Two published codes from arXiv:2504.09171 — `[[288,18,13]]` and `[[512,18,19]]`,
both B=4 weight-8 tiles — were cited as a bar that could not be reproduced from
the paper. Both are reproducible today. The tile is not figure-only: the arXiv
LaTeX source carries it as literal `\def` macros, and rebuilding from them
reproduces **both** of the paper's exact distances.

## The tile is in the source

`main.tex` lines 690-691, repeated verbatim at 763-764 for the second code:

```latex
\def\horizontalqubits{(0, 0), (0, 3), (2, 2), (3, 0)}
\def\verticalqubits{(0, 1), (1, 0), (1, 1), (3, 3)}
\def\boxsize{4}
```

The Z-tile is then derived, not chosen: it is the `(B-1-x, B-1-y)` reflection of
the X-tile with the edge orientation swapped, which is the paper's condition (T2).
The geometry is stated in the text — 9x9 and 13x13 bulk tiles, so with B=4 the qubit
lattices are 12x12 and 16x16, giving n = 2*L*L and k = 18 in both cases.

## The board's support is a different code

`research/local2d/boundary_engine.py` documented `S_G_TILE4_MAIN` as "the
B-support of the arXiv:2504.09171 B=4 tile". The A-support `S_F_TILE4` is right —
it is the published horizontal set exactly. The B-support is not:

| support | vertical edges | differs from published in |
| --- | --- | --- |
| published | `(0,1),(1,0),(1,1),(3,3)` | — |
| `S_G_TILE4_MAIN` | `(0,2),(1,3),(2,0),(3,3)` | 3 of 4 monomials |
| sibling, `codes/566-18-20` | `(0,1),(1,1),(2,0),(3,3)` | 1 monomial: `(2,0)` vs `(1,0)` |

The sibling is the "one support swap" that `codes/578-18-20`'s provenance already
describes. `S_G_TILE4_MAIN` is a third code that nobody had named.

## The measurement that separates them

Rebuilt with `build_planar`, each side witness-validated with
`verify/qldpc_verify.py`'s own `gf2.commutes` / `gf2.in_rowspace`:

| B-support | 12x12 (paper `[[288,18,13]]`, d=13) | 16x16 (paper `[[512,18,19]]`, d=19) |
| --- | --- | --- |
| published tile | **d <= 13** | **d <= 19** |
| `S_G_TILE4_MAIN` | d <= 11 | d <= 18 |
| sibling | d <= 11 | d <= 18 |

Budgets: 2,000,000 accelerator trials/side for the 16x16 readings, 1,500,000 for
the 12x12 ones. The published tile lands on both published numbers exactly, at two
independent sizes — that is the identification. The other two land one to two
below at both sizes, which is the signature of a different code rather than of a
mis-measurement.

One wrinkle worth recording: the published-tile build emits 48 Z-boundary
stabilizers of weight 12-18. All of them lie in the row space of the weight-8 rows
(rank 247 either way), so dropping rows of weight > 8 recovers the paper's weight-8
stabilizer set. A naive max-check-weight read on that build says 18, not 8.

## What this changes

- The `[[512,18,19]]` bar is seedable. `kd^2/n = 12.69` at n=512, k=18, weight 8,
  and at n=512 with d=19 it dominates `[[562,18,19]]`, `[[563,18,20]]`,
  `[[566,18,20]]`, `[[572,18,20]]` and `[[578,18,20]]`.
- `TRACKS.md` cites arXiv:2504.08887 as the figure-only precedent for not seeding
  the 2D-local bar. That reasoning does not transfer to 2504.09171, whose tile is
  machine-readable; this note supersedes it for the weight-8 bar. TRACKS.md is left
  as-is here and should be amended when the entry is filed.
- `codes/800-18-27.json`, `codes/882-18-29.json`, `codes/924-18-31.json` and
  `codes/968-18-31.json` cite this paper but are this repo's own constructions at
  the published geometry. They are fine entries; the attribution is what is wrong.

## The transferable lesson

`boundary_engine.py` already warns that `(n, k, w)` cannot see `S_g`, so a sweep
must calibrate on check matrices instead. This is the same trap one level up: a
support pair that reproduces its four board entries **perfectly, row for row** and
is still not the published code. Check-matrix calibration cannot catch it, because
the board entry is itself the thing that is wrong.

Calibrate against a number the *literature* published, and at a second size if the
paper gives one. A generator that lands on two independent exact values has been
checked against something external; a generator that reproduces its own entries has
only been checked against itself.

## Scope of the claim

Both published distances are reproduced as **witness-backed upper bounds**, not as
certified exact values. The paper's exactness rests on its own ILP; certifying
either code here is the maintainer-side `verify/certify.py` tier and is not
asserted. The readings above bound d from above only — nothing here claims a
logical lighter than 19 exists, or that the paper is wrong about anything.
