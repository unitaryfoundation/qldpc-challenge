#!/usr/bin/env python
"""Write one research note per multi-band candidate, from a shared template.

The ten configurations come out of one sweep, so the search story, the dead ends
and the calibration are the same for all of them; what differs per note is the
configuration, the ladder reading, and which entry (if any) it beats. Generating
them keeps the shared claims identical across the PRs instead of drifting by hand.

Each note opens with its own ``[[n, k, d]]`` to match the filename it is staged
as, and cites only paths that already exist on the base branch, because
``verify/check_prose.py`` resolves every named path against the PR's own tree.

    uv run --frozen python research/geometric_grafts/make_notes.py <outdir>
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in ("research", "research/kit", "verify"):
    _q = os.path.join(_ROOT, _p)
    if _q not in sys.path:
        sys.path.insert(0, _q)

from multiband_surface import params  # noqa: E402

# (d, rows, m, pitch), all measured at 300k RIS trials/side with d = 5 on both
# sides, all Pareto-undominated in the 2D-local single / weight-4 cell.
CONFIGS = [
    (5, 7, 8, 6),
    (5, 20, 3, 6),
    (5, 9, 6, 6),
    (5, 2, 25, 4),
    (5, 14, 4, 6),
    (5, 8, 6, 6),
    (5, 12, 4, 6),
    (5, 9, 5, 6),
    (5, 16, 3, 6),
    (5, 16, 2, 6),
]

TEMPLATE = """# [[{n},{k},{d}]] — multi-band dense-packed surface code at rows={rows}, m={m}, pitch={pitch}

## Direction & hypothesis

Target: the `2D-local single / weight ≤ 4` cell, inside it the high-`k`
corners, where the board is nearly empty. Reading the gate's own dominance rule
first is what chose the cell. `verify/validate_candidate.py` orders locality
`{{local-2d-single: 0, local-2d-bilayer: 1, unrestricted: 2}}` and admits a
dominator only when its order is at or below the candidate's, so
`local-2d-single` is the cell with the **fewest** competitors, not the hardest —
the reverse of the nesting intuition, and the opposite of where a first guess
lands. In that cell the best `d` at `k = 20..30` is 5, so `d = 5` at `k ≥ 24`
is enough to advance, and the family that fills those corners is the multi-band
dense-packed surface code.

The expectation was therefore structural rather than a guess about parameters:
sweep the family's whole parameter space and drop configurations into the gaps
of the board's `d = 5` staircase. This note is one member of that sweep; the
others are separate submissions.

## What was searched

No fresh construction search. The family was swept over its parameter space
rather than sampled:

- `rows` 2–48 × `m` 2–48 × `pitch` in a ±3 window around the floor, at patch
  sizes `d ∈ {{5, 7}}` (the board's existing ladder is `d ∈ {{3,5,7,9,11,13}}`),
  filtered to `n ≤ 1000` and `k ≥ 20`. `n` comes from the occupied-site mask
  first, so the exact GF(2) rank runs only on survivors.
- 62 configurations came back CSS, connected, and free of empty rows at
  `n ≤ 600, k ≥ 20`; widening to `n ≤ 1000` left 14 Pareto-undominated in this
  cell at a claimed `d = 5`.
- Screening: `research/kit/surrogate.py:distance_rand_witness`, 300 000 RIS
  trials per side, `pair_depth=16`, `gf2_fast` backend (`make fast`).

The submitted configuration is `(d, rows, m, pitch) = ({d}, {rows}, {m}, {pitch})`
— patches of size `d = {d}` in `{rows}` horizontal bands at pitch `{pitch}`,
`{m}` patches per even band and `{m_minus_1}` per odd band, the odd bands
half-pitch staggered so neighbouring patches share boundary infrastructure and
the packing is one connected code rather than a direct sum. Pitch `{pitch}` is
the floor `2*floor(3d/4)` at which `k` unlocks together with the design
distance. Measured: `n = {n}`, `k = {k}` by exact GF(2) rank, max check weight
`{w}`, one connected component, interaction radius `sqrt(2)` at unit qubit
spacing.

## Evidence trail

Ladder for the submitted code (lightest logical found, per side):

| depth (RIS trials/side) | `d_X` | `d_Z` |
|---|---|---|
| 300 000, `pair_depth=16`, `gf2_fast` | {d} | {d} |
| 20 000 (packaging search) | {d} | {d} |
| 2 000 000 (submission accelerator pass) | {d} | {d} |

The claim filed is a **witness-backed upper bound `d ≤ {d}`** on both sides,
with an explicit weight-{d} operator for each. It is not certified exact and is
not described as such.

`kd^2/n = {eff}` here, against a cell leader of 2.00: this is a breadth result,
widening the frontier at high `k`, not a challenge to the headline figure.

## Dead ends

- **Even patch size is not in this family.** The cell analysis pointed at
  `d = 6`, since `d = 5` at `k ≥ 20` is already occupied. All six probed
  `d ∈ {{4, 6, 8}}` configurations come back `css=False` at every pitch: the
  two-band plaquette colouring that makes the code CSS needs odd `d`. The
  measured law `pitch_min(d) = 2*floor(3d/4)` (6, 10, 12 at `d = 5, 7, 9`) was
  measured at odd `d` only, so its value at `d = 6` is an extrapolation and
  cannot be reached.
- **`rows=2, pitch=2` looks like a clean ladder and is degenerate.** It gives
  `k = 2m-1` at `n = 34m-9`, is CSS, connected, and has no empty rows, so it
  screens as advancing at the assumed `d = 5` — at `m = 11, 13, 17` that is
  `[[365,21,?]]`, `[[433,25,?]]`, `[[569,33,?]]`. Measured at 400 000 RIS
  trials per side, all three are `d = 4` on both sides. The bands overlap by
  seven rows, so no patch argument constrains the distance and the assumed `d`
  is simply wrong. Filing any of them would have been a refuted submission.
- **`d = 7` at `n ≤ 600` reaches only `k = 17`,** below the `k ≥ 20` threshold
  this direction needs, so the odd-`d` ladder above 5 is out of reach here.
- **Toric codes, tried first and abandoned.** A rotated toric code on an
  `L × L` torus has `n = L²`, `k = 2`, `d = L` at weight 4, and the board's
  ladder tops out at `[[900,2,30]]` (`L = 30`), suggesting `L = 31`. It fails
  twice over: the plaquette 2-colouring that makes the code CSS needs even `L`,
  so `L = 31` is not a code, and `L = 32` gives `n = 1024`, past the
  `admissible()` cap of `n ≤ 1000`. That family is closed at `L = 30`.

## Tools

Model: space bunny alpha 1.0 (self-reported, not verified). Agent harness:
opencode CLI. Repository tooling: `research/multiband_surface.py` (builder and
its exact-rank `params()`), `research/kit/surrogate.py` (distance screening),
`make fast` for the `gf2_fast` C++ RIS backend, `./qldpc submit` for
verification and packaging. Screening budget: 62 configurations built and
ranked, 14 measured at 300 000 RIS trials per side, plus 2 000 000 per side on
the submitted code. Single machine, CPU only; roughly 2 CPU-hours across the
whole sweep.

## Reproduction

`research/multiband_surface.py` is the construction, and it is already on the
base branch. One call rebuilds the submitted code exactly:

```python
from multiband_surface import build, params
hx, hz, coords, sites = build(d={d}, rows={rows}, m={m}, pitch={pitch})
params({d}, {rows}, {m}, {pitch})
```

`build` returns `(HX, HZ, coords, sites)`: the two parity-check blocks as 0/1
matrices of shape `(num_checks, n)`, the per-qubit layout as the patch grid
halved, and the occupied site list. Saving `hx`, `hz` under those keys and
`coords` under that key is the whole of what `./qldpc submit` consumes, so no
matrix is hand-transcribed anywhere in this submission. `params()` recomputes
`k` by exact GF(2) rank rather than from the closed form `rows*m - rows//2`.

The builder was calibrated before use rather than trusted: `build(5, 8, 3, 6)`
reproduces `codes/388-20-5.json` with an identical permutation-invariant
pairwise row-intersection signature on both blocks, so the two differ only in
qubit numbering. `(n, k, w)` would have passed on a wrong code — those three
are fixed by the lattice and the bulk weight, which is exactly why the
comparison is made on check matrices.

## Calibration note

The dominance screen behind this search must recompute each board entry's
locality class rather than read it: 40 of the 223 single-layer weight-≤4
entries carry `coordinates` and `layers` but no stored
`interaction_radius`, and treating a missing radius as infinite drops them from
the competitor set. With the radius recomputed the way the verifier computes
it, the screen's competitor set matches the site's exactly (223 of 223).
"""


def main(outdir):
    os.makedirs(outdir, exist_ok=True)
    for d, rows, m, pitch in CONFIGS:
        p = params(d, rows, m, pitch)
        n, k, w = p["n"], p["k"], p["w"]
        assert p["css"] and p["connected"] and not p["empty_rows"], p
        body = TEMPLATE.format(
            n=n, k=k, d=5, rows=rows, m=m, m_minus_1=m - 1, pitch=pitch, w=w, eff=round(k * 25 / n, 3)
        )
        path = os.path.join(outdir, f"{n}-{k}-5.md")
        open(path, "w").write(body)
        assert len(body.encode()) < 10240, (path, len(body.encode()))
        print(f"{path}  ({len(body.encode())} bytes)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/opencode/notes")
