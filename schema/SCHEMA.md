# Submission format (v0.1)

A submission is one JSON file describing one CSS qLDPC code, placed under
`codes/`. The formal contract is `schema/code.schema.json`; this page explains
the fields and, more importantly, what the verifier actually checks.

## Why this shape

Two principles drive the format:

1. Everything cheap and trustless is mandatory and machine-checked. n, k,
   CSS commutation, check weight, and the distance upper bound are all hard
   arithmetic facts that the verifier confirms in milliseconds. You cannot
   submit a code whose claimed k is wrong, or whose checks do not commute.

2. Distance is split into a self-certifying upper bound and a separately
   earned exact tier. Computing a code's distance is NP-hard, so we do not
   ask the submitter to prove it from scratch. Instead you attach a witness:
   an explicit logical operator of the claimed weight. The verifier checks
   the witness is a real nontrivial logical, which certifies `d <= value`
   with no trust required. Claiming `d = value` exactly additionally requires
   server certification (a bounded exact solver or a verifiable certificate);
   until that lands, an exact claim is shown as an upper bound.

## Fields

- `schema_version`: `"0.1"` or `"0.2"` (0.2 added the optional
  `witness_provenance` block; 0.1 files remain valid unchanged).
- `name`: human-readable, e.g. `"[[72,6,6]] generalized weight-6 planar BB code"`.
- `code_type`: `"CSS"` (the only type in v0.1).
- `n`: physical qubit count. Must match the qubit indices used in `checks`.
- `k`: claimed logical qubit count. The verifier recomputes
  `k = n - rank(H_X) - rank(H_Z)` over GF(2) and requires an exact match.
- `checks.X`, `checks.Z`: the parity checks as sparse supports. Each is a list
  of checks; each check is the sorted list of distinct qubit indices (0-based,
  `< n`) it acts on. So `H_X` has `len(checks.X)` rows.
- `distance.d`: claimed code distance, must equal the minimum over the
  earned X and Z side distances.
- `distance.X`, `distance.Z` (both required):
  - `value`: claimed minimum weight of a nontrivial logical of that type.
  - `confidence`: `"upper_bound"` or `"exact"`.
  - `witness`: support of a logical operator of that Pauli type and weight
    `value`. An X-witness must lie in `ker(H_Z)` and outside `rowspace(H_X)`;
    the Z-witness mirrors it. This is what makes the upper bound trustless.
  - `witness_provenance` (optional; requires `schema_version: "0.2"`, and the
    schema enforces that; issue #611): who found this witness, when, and at
    what budget — `found_by` (list of `@handles`), `date`, `found_at_samples`,
    optional `survived_samples`, `tool`, and `seeds`. Refutation credit lives
    here, attached to the operator contributed, rather than in
    `provenance.authors`, which stays reserved for the code's constructors.
    The two budgets are deliberately separate because they are opposite kinds
    of evidence: `found_at_samples` is the budget the witness turned up at and
    says nothing about whether something lighter exists, while
    `survived_samples` is the largest budget a deep search has spent on this
    side without finding anything lighter — only a null result may write it.
    `survived_samples` is what actually constrains the distance and tells the
    next refuter the budget they need to beat; a deep sweep that finds nothing
    records its null result by raising it.
- `circuit` (optional; requires `schema_version: "0.2"`; RFC 0001, issue #505):
  the circuit tier. The entry additionally ships syndrome-extraction memory
  circuits under `circuits/<slug>/` — `memory_x.stim`, `memory_z.stim`, and
  their derived `memory_x.dem`, `memory_z.dem` (committed so witnesses are
  checkable without running stim) — and claims a witness-backed circuit-level
  distance per basis. The tier is penalty-only: the recorded `d_circ` is
  clamped to `<= d`.
  - `d_circ.X`, `d_circ.Z`: per-basis claims, mirroring `distance.X/Z`:
    - `value`: claimed circuit-level distance of that basis's memory
      experiment; must equal `|witness|` and be `<= d`.
    - `confidence`: `"upper_bound"` (the only tier so far; an exact tier via
      MILP over `H_dem` is deferred future work).
    - `witness`: sorted 0-based indices of `error(...)` instructions in that
      basis's committed flattened `.dem`, counted in file order. The XOR of
      their detector sets must vanish (the fault set is undetected) and the
      XOR of their observable sets must not (it flips a logical) — the
      circuit-tier analogue of the low-weight logical the code tier stores.
  - `rounds`: noisy extraction rounds per memory circuit; must be `>= d`.
  - `stim_version`: the stim that derived the `.dem` files; must equal the
    version pinned in `uv.lock` (the verifier re-derives the `.dem` and
    requires an exact mechanism-for-mechanism match -- probabilities only to
    float tolerance, since their last ulps are architecture-sensitive and the
    distance tier never reads them -- so a version bump surfaces as a diff on
    that artifact).
  - `ancilla_coordinates` (optional): one `[x, y]` per non-data qubit in
    circuit index order; required only for the geometric circuit tier
    (Phase B, not yet checked).
  - Circuits must be memory experiments with the canonical noise recipe
    (`verify/circuit_verify.py` documents and enforces it mechanically);
    noise placement is not a submitter degree of freedom, the schedule is.
    Every TICK layer must be genuinely parallel (no qubit operated on twice
    in a layer): layer count controls idle-data noise, so this is what makes
    a schedule's claimed parallelism -- and the resulting d_circ -- honest.
  - `ler` (optional): the measured logical-error-rate tier, on
    the same committed circuits. `d_circ` is a floor; this is the rate a
    simulation actually sees, prefactors included. Per basis (`ler.X`,
    `ler.Z`):
    - `p`: the physical rate; fixed at the canonical `0.001` so rates are
      comparable across entries.
    - `shots`, `failures`, `seed`: the measurement. The stim sampler is
      seeded, so (shots, seed, stim version) determine the sample; a shot
      fails when the pinned decoder's predicted observable flips disagree
      with the sampled ones. `failures >= 100` is the floor that matters:
      the tier exists to compare prefactors between schedules with equal
      d_circ, which differ by 1.2-2x, and 100 failures puts ~10% error on
      the claim so a factor-1.5 difference is resolvable. Better circuits
      pay more shots for the same floor; that is the price of claiming a
      smaller rate. Values at the minimum `rounds = d` also carry a
      10-30% time-boundary bias relative to the long-round limit; it is
      the same convention for every entry, so comparisons stand, but treat
      the absolute number accordingly.
    - `decoder`: `"bposd-cs-10"`, the one pinned decoder (BP+OSD exactly as
      `decode/distance.py` pins it, with the DEM's own probabilities as the
      channel prior). MWPM is deliberately not offered: matching needs a
      decomposable DEM, which the weight-6+ codes this board is about do
      not produce -- and pymatching accepts an undecomposed DEM silently,
      dropping every mechanism above two detectors before decoding, so an
      MWPM number on these codes answers an easier problem. Expect board
      values to read ~1.5x better than the decomposed-MWPM numbers familiar
      from the surface-code literature; that offset is the pinned decoder
      seeing hyperedges whole, not an error.
    - `ler_per_round`, `ci95`: the per-round rate via the parity-aware
      conversion, and its Wilson 95% interval; both must recompute exactly
      from `failures`/`shots`/`rounds`.
    - Verification (`verify/ler_verify.py`) re-measures with an independent
      seed and rejects a claim outside sampling error. The replica is sized
      to discriminate (a target expected-failure count, not a fixed shot
      count), under a wall budget per basis; when the budget cannot afford
      a replica that would catch a factor-2 under-report, the claim fails
      as unverifiable within budget instead of merging weakly checked. The
      tier's statistical meaning wins over gate cost by design: the budget
      bounds what may merge, never how honestly it is checked. Statistical
      rather than bit-exact because BP is float arithmetic and cross-
      platform exactness is not a promise the board can keep; the gaming
      direction -- claiming a lower rate than the circuit earns -- is
      exactly what re-measurement detects.
- `locality` (optional): provide a layout and the verifier derives the locality
  class (`local-2d-single`, `local-2d-bilayer`, or `unrestricted`); omit it and
  the code is `unrestricted`.
  - `coordinates`: one `[x, y]` per qubit, indexed `0..n-1`.
  - `layers`: physical layers (2 for a flip-chip bilayer, for example).
  - `interaction_radius`: claimed max check diameter in the layout; the
    verifier recomputes the true max check diameter and requires
    `measured <= claim`.
  - `contributed_by` (optional, schema 0.2): `{by, date, method?}` crediting
    who contributed this layout. Layout credit lives here, beside the
    artifact, not in `provenance.authors` — the same separation
    `witness_provenance` uses for refutation credit — so adding a layout to
    an existing entry never changes its author list.
- `provenance`: `authors`, `construction` (how it was built), optional
  `references`, `date`, `notes`, `model`.
  - `origin`: `"baseline"` for a literature seed or `"submission"` for a code
    contributed through the challenge. This is provenance, not a novelty claim.
  - `novelty`: optional literature status for submissions:
    `"unknown"` (not audited), `"known_parameters"` (the `[[n,k,d]]` parameter
    set exists in the literature, though this entry may improve weight, layout,
    or construction details), or `"new_parameters"` (claimed novel after review;
    not a verifier-proved fact).
- `family` (optional): the construction family, a Layer-2 tag from a fixed
  vocabulary (`bivariate-bicycle`, `generalized-bicycle`, `2bga-coset`,
  `hypergraph-product`, `lifted-product`, `balanced-product`, `quantum-tanner`,
  `tile`, `topological`, `other`). It cannot be recovered from `H`, so it is a
  filter only, never a ranking. See `../TRACKS.md`.
- `tracks`: deprecated and ignored for ranking. Track membership (the locality
  and weight classes) is computed by the verifier from `H` and the layout; this
  self-declared field is kept only for backward compatibility. See `../TRACKS.md`.

## What the verifier reports

`python verify/qldpc_verify.py codes/your-code.json` prints a JSON report:
per-check pass/fail, the computed `n, k, ranks, max_check_weight,
interaction_radius`, and an `earned_distance` block giving the tier each side
actually earned (an `exact` claim shows as `upper_bound` here and is flagged
for server certification). Exit code 0 iff every required check passes.

## Public CI limits

The public submission path has generous resource limits so malformed or hostile
JSON cannot force unbounded dense-matrix allocation in CI. Current automatic
limits are:

- JSON file size: 5 MB.
- `n <= 700` (the verification-budget cap, issue #249; raise-only).
- At most 10000 X-checks and 10000 Z-checks.
- Max check weight 32 (issue #249: beyond this, validating a claim is not practical, and weight 32 is already beyond near-term hardware).
- At most 200000 total support entries across all checks.
- At most 600 locality coordinate entries.
- Dense verifier intermediates capped at 50000000 cells.
- Circuit tier: at most 25000 DEM error mechanisms per memory circuit
  (verification-budget rule: the refutation gate must be able to search the
  DEM; raise-only as the search stack improves).

These are far above the current board entries. A larger code should be handled
through a maintainer-run path until the verifier is sparse end-to-end.

## Conventions and gotchas

- A repeated qubit index within a single check is rejected (it would XOR
  away and silently change the code).
- Store `interaction_radius` as the exact measured value, not a rounded one;
  a value rounded down below the true diameter will fail the `<=` check.
- Both distance sides are required. The verifier earns the global `d` only when
  both witnesses validate and `distance.d = min(dX, dZ)`.
