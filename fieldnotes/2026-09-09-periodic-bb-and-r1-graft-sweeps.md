---
title: Two sweeps that produced frontier points the verifier then rejected: a periodic bivariate-bicycle cell, and r=1 lattice grafts of two board codes
date: 2026-09-09
author: "@MathysRennela"
model: DeepSeek V4 Flash 0731 and Omen Alpha 1.0
topics: [bivariate-bicycle, lattice-graft, tanner-connectivity, local2d, periodic]
---

Reclassified from the submission notes of three entries removed by
`14095599` (`Remove disconnected legacy board entries`): `162-36-4`,
`214-15-11` and `261-16-12`. Two unrelated campaigns, recorded together
because they share the reason they are gone — see the last section.

## Campaign A: periodic bivariate-bicycle, aiming at a high-rate cell

The bivariate-bicycle family (arXiv:2308.07915) commutes automatically over
`Z_l x Z_m`: any monomial choice yields a valid CSS code, so the family can be
swept exhaustively at small torus sizes. The 2026-07-16 weight-6 sweep targeted
the `unrestricted / weight-6` cell, which was dominated by high-distance codes
(`[[360,12,24]]`, eff 19.2) but thin in high-rate points: the goal was a
distinct Pareto point at `k/n > 0.2` rather than another distance-first entry.

**Searched:** periodic BB enumeration (`research/kit/bb.py`, `build_bb`) over
`Z_l x Z_m`, weight-3 monomials per side (max check weight 6), `n = 2 l m` up
to 162, screened at 400 RIS trials with `min_k = 4`, `min_d = 4` (sampler
`enumerate`, seed 7, 2026-07-16). The sweep script was not retained; the
survivor's parameters are below.

**Evidence:** n = 162, k = 36, max check weight 6, CSS commutation holds.
Screen read `d <= 4` at 400 trials; fresh witnesses on 2026-08-15 at 8000
trials, seed 7, weight-4 on each side, verified in the opposite check kernel
and outside its own rowspace. Trusted gate passed, refutation clean,
`dominated_by: []`. Score `kd^2/n = 36 * 16 / 162 = 3.556`.

**Dead ends — three siblings from the same sweep, all below the frontier:**

- `[[162,12,8]]` — dominated by `[[144,12,12]]`, `[[144,16,8]]`, `[[128,12,8]]`.
- `[[168,18,6]]` — dominated by `[[144,24,6]]` (smaller n, higher k, same d).
- `[[168,6,12]]` — dominated by six weight-6 entries including `[[98,6,12]]`
  and `[[140,6,14]]`.

Only `[[162,36,4]]` survived the Pareto check — the usual pattern for periodic
BB at this size: k and d trade off sharply and only the high-k / low-d corner
had headroom.

## Campaign B: r=1 lattice grafts of two board codes

The r=1 lattice-graft move (arXiv:2504.08887 Sec. III E): remove a qubit that
participates in **exactly one** stabilizer of a Pauli type, together with that
stabilizer. Commutation is preserved automatically and k is unchanged exactly
(rank arithmetic), so n falls at held k and distance tier — a frontier win in
the source's own (weight x locality) cell. The hypothesis was that laid-out
board codes carry remove-and-rebind slack that the check-deletion census
cannot reach, because this move changes n rather than k.

**Searched:** a board-wide sweep over every board code with a 2D layout and
claimed `d >= 3`, defending each code's own claimed d as the floor (conservative
— a claimed d is an upper bound, so a loose claim only costs removals, never
soundness). Per chain: max 2 removals, seeds `{0, 1}`, randomized candidate
order; each removal accepted only after a fixed-seed 1200-trial screen **then**
two independent 2500-trial fresh-seed confirmations, plus a full 3-removal
block gate (multi-seed) every 3 accepted steps; failures rolled back and the
qubit blacklisted. **23 gate-passed codes staged, 7 board-advancing.**

**Evidence:** both surviving points took 2 removals, every step passing the
per-step screen, the 2-seed confirm and the block gate (`d_rand >= 11` and
`>= 12` respectively); final (n, k) = (214, 15) and (261, 16) re-derived by
GF(2) rank at packaging. Final claim `d <= 11` and `d <= 12` per side,
upper_bound confidence.

**Dead ends:**

- Deep grafts (up to 14 removals on the same move set) also pass the gate but
  do not advance the board — **depth is the wrong axis; the light -2 removal is
  the advancing currency.**
- The identity-transfer packaging gap: without the tool's original-qubit
  identity output the source layout cannot be transferred honestly. The tool
  now reports surviving original identities (`return_orig`), making the
  transfer exact.
- Long randomized distance screens are a memory hazard on macOS (issue #966):
  run them solo and chunked.

## Reproduction

Campaign A:

```python
from research.kit.bb import build_bb
from research.kit.css import compute_k, verify_css

HX, HZ = build_bb(9, 9,
                  A_terms=[(0, 0), (0, 3), (3, 3)],
                  B_terms=[(0, 0), (3, 0), (3, 3)])
assert verify_css(HX, HZ) and compute_k(HX, HZ) == 36
```

Campaign B: `graft_r1_safe(HX, HZ, max_removals=2, seed=0, d_floor=11,
return_orig=True)` from `research/local2d/boundary_engine.py`, applied to the
source entries. Both source entries were themselves removed from the board, so
they are pinned rather than cited as paths:
taken from github.com/unitaryfoundation/qldpc-challenge @ `14095599^`,
`codes/216-15-11.json` and `codes/263-16-12.json`. The chain is deterministic
for the fixed seed and returns the surviving ORIGINAL qubit identities, so the
source layout's coordinates are subset by identity to rebuild the 214- and
261-qubit codes with their locality blocks.

## Why none of them is on the board any more

All three failed the **`tanner_connected`** check introduced by issue #921:
their parity-check graphs are not connected. They were grandfathered by a
temporary migration exception in `verify/verify_all.py`
(`LEGACY_DISCONNECTED`, a warning rather than a failure), and `14095599`
removed the exception and all 35 entries at once.

The reusable content here is therefore not a board claim but two pieces of
method: the periodic-BB high-rate cell is thin because of the k/d trade, and
the r=1 graft is a cheap n-reduction move whose useful range is shallow (-2)
rather than deep. Both remain available to any later searcher; the entries
that carried them do not.
