# Submission format (v0.1 to v0.4)

A submission is one JSON file describing one qLDPC code, placed under
`codes/`: a CSS code given by its X and Z checks, or (since 0.4) a general
stabilizer code given by one list of Pauli generators (see "Stabilizer codes"
below). The formal contract is `schema/code.schema.json`; this page explains
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

- `schema_version`: `"0.1"`, `"0.2"`, `"0.3"`, or `"0.4"` (0.2 added the
  optional `witness_provenance` block, 0.3 the optional
  `provenance.search_budget` and `locality.modules` blocks, 0.4 the
  `stabilizer` code type; older files remain valid unchanged).
- `name`: human-readable, e.g. `"[[72,6,6]] generalized weight-6 planar BB code"`.
- `code_type`: `"CSS"` or `"stabilizer"` (0.4). The fields below describe a
  CSS entry; a stabilizer entry replaces `checks.X`/`checks.Z` with
  `checks.S` and `distance.X`/`distance.Z` with `distance.P`, and may not
  carry `circuit`. The schema enforces the split by `code_type`.
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
  - `contributed_by` (optional): `{by, date, method?}` crediting who
    contributed these circuits. Schedule credit lives here, beside the
    artifact, not in `provenance.authors` — the same separation
    `witness_provenance` and `locality.contributed_by` use — so adding a
    circuit tier to an existing entry never changes its author list. It is
    what binds a contributor who is not a listed author of the code:
    `verify/check_authorship.py` admits such a PR only when it adds a FIRST
    circuit block and credits the PR author here. Replacing an existing one
    stays with the code's listed authors, which matters more here than for a
    layout because the tier is penalty-only — a donated schedule can lower
    the entry's recorded `d_circ`, so leaving replacement to the authors
    leaves a mediocre donated schedule theirs to beat. The committed files
    under `circuits/<slug>/` are part of the same claim, so editing them is
    an edit to the entry whether or not the JSON moves.
  - Circuits must be memory experiments with the canonical noise recipe
    (`verify/circuit_verify.py` documents and enforces it mechanically);
    noise placement is not a submitter degree of freedom, the schedule is.
    Every TICK layer must be genuinely parallel (no qubit operated on twice
    in a layer): layer count controls idle-data noise, so this is what makes
    a schedule's claimed parallelism -- and the resulting d_circ -- honest.
  - `logicals` and `gates` (optional; issue #1850, stage 1): claimed
    transversal logical gates, checked over GF(2) by
    `verify/transversal_gates.py` and listed on the code page. Witness-backed
    and penalty-only: a verified gate is a listed property and never ranks; a
    wrong claim fails verification. `gates` requires `logicals`.
    - `logicals`: `{X: [...], Z: [...]}`, k X-type and k Z-type logical
      representatives as sparse supports, the basis every gate claim is
      written in. `X_i` must lie in `ker(H_Z)`, `Z_i` in `ker(H_X)`, and
      `X_i` and `Z_j` must anticommute exactly when `i = j` (identity
      pairing, which also makes the basis independent modulo stabilizers).
      The claims name them `X0..X{k-1}` and `Z0..Z{k-1}`.
    - `gates`: a list of claims, each `{gate, permutation?, logical_action,
      name?, notes?}`. `gate` is `"permutation"` (a bare qubit permutation,
      then required), `"H"` or `"S"` (that Clifford on every qubit, composed
      with the optional permutation), or `"CX"` (a CX from qubit `i` of one
      block, the control, to qubit `permutation[i]` of a second block, the
      target; identity pairing when omitted). `permutation` lists the image
      of each qubit. `logical_action` maps each logical generator label to
      the list of generator labels whose product it is sent to; a generator
      not listed is claimed fixed, and a CX names the target block's
      generators with a prime (`X0'`, `Z0'`).
    - Verification: the gate must map every stabilizer generator into the
      stabilizer group (per block), and the image of every logical generator,
      reduced modulo stabilizers, must equal the claimed product. For `S`
      every X-check must have weight `0 mod 4`: `S` on every qubit sends `X`
      on a weight-`w` support to `i^w XZ` on it, a phase the GF(2) image
      cannot see, and for `w = 2 mod 4` the image is minus a stabilizer. The
      action is checked up to stabilizers only: a logical factor the gate
      introduces belongs in the claim's product list. Phases are invisible
      to the GF(2) image, so `S` and `S^dagger` share a claim. A claim whose
      induced action fixes every logical operator is rejected as a code
      automorphism rather than a logical gate. Surgery gadgets (stage 2 of
      the issue) are not part of this field.
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
      bounds what may merge, never how honestly it is checked. Two honest
      limits of that guarantee: the printed detection factor is the
      50%-power point of the difference statistic, so under-reports
      between it and the factor-2 admissibility bound sit in a gray zone
      where a lucky draw can survive (admissibility itself demands ~98%
      power at factor 2, so the zone is bounded); and the per-shot decode cost sets
      what the tier can admit at all -- at the pinned decoder's current
      speed, d = 5 memory circuits verify within budget and the d = 7 and
      d = 9 seeds do not (their honest claims alone would cost hours), so
      they fail closed until the decode loop gets faster. Statistical
      rather than bit-exact because BP is float arithmetic and cross-
      platform exactness is not a promise the board can keep; the gaming
      direction -- claiming a lower rate than the circuit earns -- is
      exactly what re-measurement detects.
- `locality` (optional): provide a layout and the verifier derives the locality
  class (`local-2d-single`, `local-2d-bilayer`, or `unrestricted`); omit it and
  the code is `unrestricted`.
  - `coordinates`: one `[x, y]` per qubit, indexed `0..n-1`, or one
    `[x, y, z]` per qubit for a 3D layout; every point in a layout has the
    same dimension (`coordinates_uniform_dimension`). The 2D-local classes
    need planar coordinates; a 3D layout gets the same cramming and spacing
    checks, lands in `unrestricted`, and is priced by the D = 3 geometric
    efficiency `g = 2 sqrt(2) kd/(n rho r^3)` (see TRACKS.md).
  - `layers`: physical layers (2 for a flip-chip bilayer, for example).
  - `modules` (optional, schema 0.3): one module id per qubit, indexed
    `0..n-1`, a non-negative integer naming the hardware module (chip,
    interconnected flip-chip module, photonically linked or shuttling zone)
    the qubit sits in. Ids need not be contiguous. When present, every qubit
    must carry one (`modules_cover_all_qubits`); the verifier then reports
    the checks whose support spans more than one module, the ports per
    module (the distinct other modules it shares a check with), and the
    qubits per module, and the code earns the Layer-3 flag `modular`. The
    field is independent of the coordinates, so it applies to a layout of
    any dimension, and neither the locality class nor any score reads it.
  - `interaction_radius`: claimed max check diameter in the layout; the
    verifier recomputes the true max check diameter and requires
    `measured <= claim`.
  - `contributed_by` (optional, schema 0.2): `{by, date, method?}` crediting
    who contributed this layout. Layout credit lives here, beside the
    artifact, not in `provenance.authors` — the same separation
    `witness_provenance` uses for refutation credit — so adding a layout to
    an existing entry never changes its author list, and it is what binds a
    first-layout contribution by someone who is not a listed author (see
    `circuit.contributed_by` for the same rule on circuits).
- `provenance`: `authors`, `construction` (how it was built), optional
  `references`, `date`, `notes`, `model`.
  - `origin`: `"baseline"` for a literature seed or `"submission"` for a code
    contributed through the challenge. This is provenance, not a novelty claim.
  - `novelty`: optional literature status for submissions:
    `"unknown"` (not audited), `"known_parameters"` (the `[[n,k,d]]` parameter
    set exists in the literature, though this entry may improve weight, layout,
    or construction details), or `"new_parameters"` (claimed novel after review;
    not a verifier-proved fact).
  - `search_budget` (optional; requires `schema_version: "0.3"`): what the
    search that produced this code cost, self-reported and unchecked (there
    is nothing trustless to check). All fields optional: `candidates_screened`
    (codes built and screened before this one), `ris_trials_per_side` (the
    deepest RIS budget spent per side on this code during the search),
    `cpu_hours`, `gpu_hours`, `llm_tokens` (an object keyed by model name as
    in `provenance.model`, value the integer token count, input and output
    combined), `wall_clock_hours`, `tool` (the search harness) and `notes`
    (what the numbers cover and leave out). It is about the code search, not
    the witness search: `witness_provenance.found_at_samples` budgets one
    operator, this budgets the discovery. `./qldpc submit` fills it from the
    `--budget-*` flags or `--budget-json`. The site can show it on the detail
    page and the research log can aggregate it, so the cost of a
    frontier-advancing code becomes comparable across entries and over time.
- `family` (optional): the construction family, a Layer-2 tag from a fixed
  vocabulary (`bivariate-bicycle`, `generalized-bicycle`, `2bga-coset`,
  `hypergraph-product`, `lifted-product`, `balanced-product`, `quantum-tanner`,
  `tile`, `topological`, `other`). It cannot be recovered from `H`, so it is a
  filter only, never a ranking. See `../TRACKS.md`.
- `tracks`: deprecated and ignored for ranking. Track membership (the locality
  and weight classes) is computed by the verifier from `H` and the layout; this
  self-declared field is kept only for backward compatibility. See `../TRACKS.md`.

## Stabilizer codes

A general stabilizer code (`code_type: "stabilizer"`, `schema_version:
"0.4"`) has no X and Z sides. It is given by its binary symplectic matrix
`S = (A | B)`, one row per generator, and one Pauli-weight distance side.

- `checks.S`: the generators, each `{"X": [...], "Z": [...]}`: the sorted
  qubit indices carrying an X factor and those carrying a Z factor, so
  generator `i` is `X^{A_i} Z^{B_i}`. A qubit in both lists carries `Y`. At
  least one list is nonempty; each list is capped at 32 entries and the
  check weight, `|A_i union B_i|` (the qubits the generator acts on, a `Y`
  once), at the same 32 as a CSS check. `checks.X` and `checks.Z` are
  forbidden on a stabilizer entry, and `checks.S` on a CSS one.
- The verifier checks isotropy, `A B^T + B A^T = 0` over GF(2)
  (`stabilizer_commutation`, the general form of CSS commutation), computes
  `k = n - rank S` (`k_matches_claim`), and rejects a submission whose every
  generator is pure X or pure Z (`stabilizer_code_is_not_css`): that is a
  CSS code and must be typed `CSS`, so the CSS entries keep their per-side
  semantics.
- `distance.P` (required; `distance.X` and `distance.Z` forbidden):
  - `value`: the claimed minimum Pauli weight of a nontrivial logical
    operator. `distance.d` must equal it (`d_matches_pauli_side`).
  - `confidence`: `"upper_bound"` or `"exact"`. The Pauli-weight certifier
    is not available yet, so `exact` is accepted as `upper_bound`
    (`distance_P_exact_flagged`), as CSS claims were before certification
    existed.
  - `witness`: one Pauli operator `{"X": [...], "Z": [...]}`. It must
    commute with every generator (lie in the normalizer, `ker (B | A)`), lie
    outside the row space of `S`, and have Pauli weight
    `|supp X union supp Z|` equal to `value` (`distance_P_witness`). The
    Hamming weight over the `2n` symplectic bits is not the distance: a `Y`
    counts once, and the report says how many `Y` factors the witness has.
  - `witness_provenance`: as for a CSS side.
- `circuit` is not accepted on a stabilizer entry: the memory experiments
  and their `d_circ` witnesses are per basis, and a general code needs a
  stabilizer measurement schedule the tier does not build yet.
- `locality`, `provenance`, `family`, and the slug `n-k-d.json` are
  unchanged. The locality class is computed over the generator supports.
- Identity. The exact-duplicate fingerprint is `rref(S)`; the
  permutation-invariant signature is the Weisfeiler-Leman refinement of the
  qubit/generator graph with every edge labeled X, Z, or Y. If a Hadamard on
  some qubit subset would make every generator pure, the verifier reports
  that subset and the fingerprint and signature of the CSS code it maps to
  (`css_equivalent`, `local_hadamard_css_equivalent`); the dedup gate then
  marks a match with a board entry as a duplicate of it (not a rejection).
- Refutation. The distance gate runs the random-information-set search on
  the normalizer, scored by Pauli weight, and the accelerated pass on the
  symplectic doubling `H'_X = (A | B)`, `H'_Z = (B | A)` (a CSS code on `2n`
  qubits whose Hamming weight bounds the Pauli weight from above), re-scoring
  every find by Pauli weight before it counts.
- Ranking. Stabilizer codes form a separate leaderboard: novelty, dominance,
  and records are computed among stabilizer codes only (`TRACKS.md`).

`./qldpc submit` builds such an entry from an `.npz` holding `s` (an
`m x 2n` array `(A | B)`) or `a` and `b`.

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
- `n <= 700`, or `n <= 1000` with max check weight `w <= 8` and claimed `d <= 40` (the verification-budget cap; raise-only; `qldpc_verify.admissible(n, w, d)`).
- At most 10000 X-checks and 10000 Z-checks.
- Max check weight 32 (issue #249: beyond this, validating a claim is not practical, and weight 32 is already beyond near-term hardware).
- At most 200000 total support entries across all checks.
- At most 1000 locality coordinate entries.
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
- Both distance sides are required for a CSS code. The verifier earns the
  global `d` only when both witnesses validate and `distance.d = min(dX, dZ)`.
  A stabilizer code has the single side `P` and `distance.d = P.value`.
