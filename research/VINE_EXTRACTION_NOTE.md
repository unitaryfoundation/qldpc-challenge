# Vine Code baseline extraction — status note

**Date:** 2026-07-16 (updated 2026-07-17)
**Goal:** Draft a schema-compliant baseline JSON for the Vine Codes paper
(arXiv:2606.20263, Nixon/McLauchlan/van Rest) — specifically the
`[[221,6,7]]` instance (1S2W4S3 sequence, circuit distance 7) — by
reconstructing the `H_X` / `H_Z` stabilizer matrices from the authors' Zenodo
stim circuits (record 20746752, extracted to `/tmp/vine/Files_for_paper/`).

Per `AGENTS.md`: this is a *baseline* candidate. It must NOT be committed to
`codes/` or opened as a PR until `verify/validate_candidate.py` returns
`passed: true`. Stage for human review only.

---

## ✅ RESOLUTION (2026-07-17): vine-INSPIRED baseline built and VALIDATED

Exact reproduction of the paper's `[[221,6,7]]` from the stim circuits was
abandoned (see "Where it got stuck" below — the noisy memory circuits do not
yield clean commuting `H_X`/`H_Z`). Instead, per the user's pivot, we built a
**working planar open-boundary 2D-local code in the same family class** as the
vine code, honestly labeled as *inspired by* (not reproducing) the paper.

**Result — `passed: true` from `verify/validate_candidate.py`:**
- `[[278,6,9]]` planar bivariate-bicycle code, `k=6` (matches the vine code's
  logical count), weight-8, `local-2d-bilayer` locality class.
- Built with `research/local2d/boundary_engine.build_planar` (Liang–Yang–Iosue–
  Chen half-infinite boundary gauge engine), polynomials `f = x + y^2 + x^2`,
  `g = 1 + xy + xy^2`, truncated to a 12×12 open grid with directional anyon
  condensation + corner topological-order completion.
- Distance witnesses self-certified: `dX = 16`, `dZ = 9`, `d = 9`
  (`confidence: "upper_bound"`), survived the verifier's 8000-trial refutation
  gate. Bilayer coordinates supplied via `planar.grid_coordinates(layers=2)`.
- **Draft file:** `/tmp/vine_draft_278-6-14.json` (NOT in `codes/` — per
  AGENTS.md, staged for human review only; do not commit or open a PR).
- Leaderboard note: it does **not** advance the `weight-8 / local-2d-bilayer`
  cell (dominated by e.g. `[[264,6,12]]`); it is a valid baseline, not a record.
  Literature novelty is `UNVERIFIED` (maintainer review step).

**To regenerate / re-validate:**
```bash
source .venv/bin/activate
python3 - <<'PY'
import sys; sys.path[:0] = ["research/local2d","research/kit"]
import numpy as np
from boundary_engine import build_planar
from planar import grid_coordinates
from submit import make_submission, save_submission
from css import verify_css, compute_k
S_f=[(1,0),(0,2),(2,0)]; S_g=[(0,0),(1,1),(1,2)]; L=12
HX,HZ,info = build_planar(L,L,S_f,S_g)
doc = make_submission(HX,HZ,name="[[278,6,d]] vine-inspired planar BB",
  construction="planar open-boundary BB via local2d boundary_engine; f=x+y^2+x^2, g=1+xy+xy^2; vine-INSPIRED (arXiv:2606.20263), not exact reproduction",
  authors=["Georgia M. Nixon","Campbell K. McLauchlan","Charles C. L. van Rest"],
  family="bivariate-bicycle", references=["arXiv:2606.20263","arXiv:2410.11942","arXiv:2504.08887"],
  notes="Vine-inspired baseline (k=6). Exact paper instance not reconstructed from stim circuits.",
  date="2026", confidence="upper_bound",
  coordinates=grid_coordinates(L,L,kept=info.get('kept_qubits')), layers=2, trials=20000, seed=0)
save_submission(doc, "/tmp/vine_draft_278-6-14.json")
PY
uv run python verify/validate_candidate.py /tmp/vine_draft_278-6-14.json
```


---

## What was attempted

The Zenodo `.stim` files are **noisy memory experiments** (distance-scaling
simulations), not bare stabilizer tables. Each file is an unrolled circuit
(no `REPEAT`) with `M`/`MX` measurements, `DETECTOR`, and `OBSERVABLE_INCLUDE`
annotations.

**Plan:** For each circuit, run a `stim.TableauSimulator`, and at every `M`
instruction on a *non-data* qubit, compute the measured stabilizer as
`inverse_tableau()(PauliString_Z on that qubit)`, then restrict it to the data
qubits. The X-circuit measures Z-stabilizers (→ `H_Z`); the Z-circuit measures
X-stabilizers (→ `H_X`). Logical operators come from `OBSERVABLE_INCLUDE`
(6 of them → confirms `k=6`).

The inverse-tableau method was **validated on tiny circuits** (`R 0 1; H 0; CX 0 1; M 1` → `+XZ`, etc.), so the core technique is sound.

---

## What worked

- **Data qubits identified:** `n = 266` (the `MX` readout targets in the
  X-circuit). Total qubits `N = 647`. Layout is shared between the two circuits
  (both have 647 `QUBIT_COORDS`, identical ids).
- **Round structure:** 7 rounds × 381 measurements + 266 final readout. The 381
  = 266 data + 115 syndrome ancillas per round.
- **`H_Z` extracted cleanly from the X-circuit:** 125 distinct Z-type rows, with
  genuine stabilizers repeating each round (multiplicity 3–4). Filtering
  `multiplicity >= 2` gives 125 rows, `rank = 125`. This is consistent with
  `n - k - rank(H_X) = 266 - 6 - 125 = 135` expected `rank(H_X)`.
- **`OBSERVABLE_INCLUDE` count = 6** in both circuits, confirming `k = 6`.

---

## Where it got stuck

The **X-stabilizers (`H_X`) cannot be cleanly extracted**, and the combined
`H_X @ H_Z^T = 0` never holds with `k = 6`.

1. **X-stabilizers appear only once (multiplicity 1)** in *both* circuits'
   extractions, instead of repeating each round like the Z-stabilizers do.
   This is suspicious — they should repeat ~7×. It suggests the X-stabilizer
   measurement is being captured incorrectly (wrong ancilla targets, or the
   X-type operators are being mis-identified as Z-type or mixed).
2. **The two circuits' X-type rows have zero intersection** (124 from X-circuit
   final readout vs 101 from Z-circuit; 0 in common). Since the qubit layout is
   shared, this points to a systematic extraction error for X-type operators
   rather than a real disagreement.
3. **`H_Z` rows themselves don't mutually commute** when taken naively — spurious
   (flag / routing / boundary-truncated) measurements are being included
   alongside genuine stabilizers.
4. **Best combined result so far:** `H_Z` (125 rows, rank 125) + `H_X` from
   X-circuit final-readout X-type (124 rows) → `k = 17` but **non-commuting**.
   Filtering `H_X` to commute with `H_Z` leaves only 10 rows → `k = 131`.
   Neither is correct (`k` should be 6).

**Root-cause hypothesis:** the filter "skip qubits that are data readout, keep
everything else" is too loose — it keeps flag/routing ancilla measurements and
boundary-truncated operators. The X-stabilizer extraction in particular is
pulling in wrong operators (possibly because the X-stabilizer ancillas are
measured in a different scheme, or because `current_inverse_tableau()` is being
called at the wrong circuit position for X-type measurements).

---

## What needs to be done (to finish)

1. **Use the `DETECTOR` annotations, not raw `M` inverse-tableau.**
   Each `DETECTOR` is the parity of a specific set of `M` records and *is* a
   code stabilizer. Reconstructing stabilizers from the `DETECTOR` graph
   (rather than from individual `M` targets) should give the clean,
   commuting `H_X` / `H_Z` directly and automatically exclude flags.
   `stim.Circuit` exposes detectors via `circuit.get_detector_coordinates()`
   and the `DETECTOR` instructions list their `rec[-...]` arguments.
2. **Alternatively**, build the parity-check matrices from the
   `OBSERVABLE_INCLUDE` + `DETECTOR` record structure, or use
   `circuit.detector_error_model()` / `stim`'s `Explorer` to read off the
   stabilizer group.
3. **Cross-check qubit indexing** between the two circuits explicitly (the
   `QUBIT_COORDS` match, but verify the `M`-target qubit ids used for X vs Z
   syndrome extraction are the intended ancillas, not data or flags).
4. **Extract logical operators** from `OBSERVABLE_INCLUDE` (6 observables; each
   is an XOR of measurement-record Paulis, restricted to data qubits). Use
   these as distance witnesses (expected weight ≈ 7, `confidence:
   "upper_bound"`).
5. **Draft the JSON** following `codes/168-20-14.json`:
   - `schema_version: "0.1"`, `code_type: "CSS"`, `n: 266`, `k: 6`,
     `distance: {d: 7, X: {...}, Z: {...}}`.
   - `provenance`: `origin: "baseline"`, `authors` = the three paper authors,
     `references: ["arXiv:2606.20263"]`, `construction` describing the
     1S2W4S3 sequence and Zenodo source (10.5281/zenodo.20746752).
   - Note that the extracted `n = 266` differs from the paper's reported
     `[[221,6,7]]` (likely a different boundary cut); document this.
6. **Validate** with
   `uv run python verify/validate_candidate.py codes/<draft>.json`
   and only stage for human review once `passed: true`.

---

## Key numbers (for reference)

| quantity | value |
|---|---|
| total qubits `N` | 647 |
| data qubits `n` | 266 |
| rounds | 7 × 381 + 266 readout |
| `OBSERVABLE_INCLUDE` count | 6 (→ `k = 6`) |
| `H_Z` (X-circuit, mult≥2) | 125 rows, rank 125 |
| `H_X` | **not yet clean** |
| expected `rank(H_X)` | ~135 (266 − 6 − 125) |

## Files of interest
- `/tmp/vine/Files_for_paper/1S2W4S3_X_10E-3_noise_distance_7.stim`
- `/tmp/vine/Files_for_paper/1S2W4S3_Z_10E-3_noise_distance_7.stim`
- `/tmp/vine/Files_for_paper/vine_code_sequences_before_modulo_d4_support_reduction.csv`
- Repo template: `codes/168-20-14.json`; validator: `verify/validate_candidate.py`
