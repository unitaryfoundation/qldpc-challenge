# Tracks and leaderboards

A quantum code trades several quantities against each other (physical qubits n,
logical qubits k, distance d, check weight, geometric locality), so there is no
single leaderboard. The board is organized in three layers that answer different
questions: primary tracks you compete on (hard, computed constraints), family
tags you are labeled by (provenance), and verified flags you earn (proven
properties).

## Layer 1: primary tracks (the leaderboards)

The primary tracks are a grid of two nested axes, and membership is **computed by
the verifier** from `H` and the layout. You do not pick your tracks; the checker
derives them, so a track claim cannot be gamed.

Locality class, derived from the layout (one coordinate per qubit):

- `local-2d-single`: a single layer, interaction radius <= 4.0.
- `local-2d-bilayer`: up to two layers (the flip-chip regime), interaction
  radius <= 7.0.
- `unrestricted`: everything else, including any code with no layout.

These nest: a `local-2d-single` code also competes as `local-2d-bilayer` and
`unrestricted`.

Check-weight class, from the maximum row weight of `H_X`, `H_Z`:

- `weight-4` (w <= 4), `weight-6` (w <= 6), `weight-8` (w <= 8), `any weight`
  (no cap, the home for w > 8 codes).

These nest too: a `weight-4` code competes on every weight board.

Each (locality, weight) cell is a board. Within a cell the ranking is a Pareto
frontier over (n, k, d, w): a code is a record if no other code in the same cell
beats it on all of (n lower, k higher, d higher, w lower), with at least one
strict. There can be many co-leaders. `kd^2/n` is a sortable headline figure per
cell (see the caveat below), and never collapses the frontier into one rank.

Code type, from `code_type`, is a third cell dimension: CSS codes and general
stabilizer codes are ranked on separate leaderboards. A stabilizer code is
compared only with other stabilizer codes, so neither board's entries can
dominate the other's. They are kept apart because `kd^2/n` does not mean the
same thing for both: the two families decode differently, and how the figure
tracks a logical error rate is less settled for non-CSS codes.

A stabilizer code's check weight is the number of qubits each generator acts
on (a `Y` counts once) and its locality class comes from the generator
supports, so the (locality, weight) grid is the same on both boards. A code
that is CSS up to single-qubit Cliffords on some qubits (a Hadamard, an S,
any of the six) belongs on the CSS board: the verifier finds the Cliffords
and rejects the entry with its CSS image spelled out, so the stabilizer board
holds only codes that are non-CSS under every local Clifford.

A Clifford acting on blocks of two or more qubits is outside that test, and
its image of a board entry is a stabilizer code with the same `n`, `k`, and
code space whose distance was bought with check weight (issue #2802: an
m = 4 image of `[[500,100,16]]` reads `w` 26, `d <= 37`, `kd^2/n` 274
against the parent's 51). Block Clifford equivalence is not tested, so such
an entry declares it: `provenance.clifford_relabel_of` names the parent,
the verifier checks the parent exists with the same `n` and `k`, the entry
cannot also claim `new_parameters`, and the board marks it so its `kd^2/n`
is read as a relabeling and not as a construction result. An undeclared
one that is found is a provenance defect, corrected like any other.

A record whose only strict axis is `d` — the candidate ties an existing entry on
n, k and w and raises nothing but the distance — is a different kind of claim
from the rest of the frontier: both numbers are witness-backed *upper* bounds, so
the comparison says which search was deeper as much as which code is better, and
this is where the board has historically been wrong (the corrections are
recorded in `research/audits/README.md`). The submission gate reports that pattern instead of a
generic advance: `validate_candidate` returns `advances_by: ["d"]` in
`gates.novelty` together with `d_only_peers`, naming the entry that was beaten.
`d_only_gain` is the stricter of the two: it is true only when nothing but `d`
was gained anywhere on the board. The label is keyed on `d_only_peers` instead,
so it still names those entries — and still tells you to re-measure them — when
the candidate also beat some other entry on `k`, or `w`, or `n`.
The matched-depth pair audit (`research/audits/leader_audit.py pair`) then
re-measures the candidate and that entry on the same trials, seeds and pair
depth, and its `redirect` verdict — the board's number, not the candidate's, was
the soft one — is a distance revision, which is a correction to that entry
rather than a new submission (`research/audits/README.md`). The
board still ranks claims exactly as claimed; the flag says which claim to
re-measure first. It is a caution, not a rejection: a board-advancing code whose
only gain is on d is still worth submitting once the peer and the candidate have been
re-measured at matched depth.

## Layer 2: family tags (provenance, never ranked)

The construction family cannot be recovered from `H`, which is exactly why it is a
filterable tag and not a board: a tag confers no ranking advantage, so there is
nothing to game by relabeling. Vocabulary: `bivariate-bicycle`,
`generalized-bicycle`, `2bga-coset`, `hypergraph-product`, `lifted-product`,
`balanced-product`, `quantum-tanner`, `tile`, `topological` (surface / toric /
color), `other`. On the board it is a filter, not a leaderboard.

## Layer 3: verified flags (earned badges)

Only things the verifier or a certificate can prove: the distance-confidence
tier, CSS commutation (or, for a general stabilizer code, that its generators
commute), the locality class (which doubles as Layer-1 membership), and
`modular` (the layout assigns every qubit to a hardware module; see below).

Distance confidence is orthogonal to the tracks:

- `d<=` (upper bound): a submission exhibits an explicit logical operator of the
  claimed weight, and the verifier confirms it is a genuine nontrivial logical,
  so the distance is at most that weight. The claim is also refutation-tested:
  independent searches (the deep RIS + BP+OSD gate at PR time, and weekly
  fresh-seed sweeps of the whole board) try and fail to beat it. Evidence, not
  a proof.
- `d=` (exact): a server-side integer program has proven no lighter logical
  exists. This is NP-hard and does not scale, so large codes carry tight upper
  bounds while small and moderate codes are certified exact. The board shows an
  `exact` claim as an upper bound until a maintainer runs `verify/certify.py`.
  For a general stabilizer code the distance is a Pauli weight and the
  certifier does not yet minimize it, so every stabilizer entry is `d<=`.

Not a flag: first arrival. Issue #4029 asked whether the entry that first
populates a cell, a family, or a geometry should carry an `opens` badge. The
answer recorded there is no. Cells nest, so the smallest, lowest-weight, most
local code is the first entry of every cell it qualifies for (three entries
open all 24 cells on the board of 2026-10-23), the family half would rest on
the one self-declared label and give it something to be gamed for, and
"first" is a fact about the board's history rather than something the verifier
can prove about a code, which is what this layer is for. The history is kept
instead, as a dated record under `research/audits/` (`cell_openings.py`): the
first entry per cell, per declared family within a cell, and the first modular
and 3D-layout entries, with their dates. It is displayed nowhere on the board
and enters no ranking.

## Diagnostics (displayed, never ranked)

The verifier also reports, per code, a few properties that are computed from
data every submission already carries and that no track reads: the girth of
each side's Tanner graph (the shortest cycle in the check/qubit graph a decoder
runs on; "acyclic" when there is none), the row and column weight profiles of
`H_X` and `H_Z`, a census of small connected trapping sets (sets of `a` qubits
whose error pattern has syndrome weight `b`, counted by `(a, b)` up to a fixed
size under a cost cap, so a dense code reports how far the count got), and,
for a laid-out code, the Euclidean support diameter of each stored distance
witness. The diameter is an upper bound on how far the exhibited logicals
spread, not a minimum over all logicals: the witnesses bound the logical weight
from above and are not claimed minimal. The site shows these on code pages and
as sortable columns in the tables; they enter neither the Pareto frontier nor
any score.

An entry whose reproduction manifest carries a construction recipe also shows
the recipe rebuilt at neighboring sizes (`research/kit/multisize.py`,
`research/repro/multisize.json`): per size, whether the checks commute, the
code encodes, its Tanner graph is connected, and it stays within the caps. No
distance is searched at any size. A recipe that holds up at other sizes is
evidence of a construction rather than a tuned artifact; the result is shown
and never ranked.

## A note on kd^2/n

`kd^2/n` is the Bravyi-Poulin-Terhal saturation ratio. It is bounded and
meaningful for 2D-local or bounded-weight codes at comparable n (the surface code
sits near 1), but for high-rate codes with k and d both growing like n it grows
like n^2 without bound, so the cited large-block codes reach the hundreds. It is
therefore compared within a cell, among codes of comparable size and check
weight, not as a global record.

## Locality is proven, not asserted

The locality class is computed from the layout, never trusted. A class is earned
only by an honest layout:

- a coordinate for every qubit (`coordinates` covers all `n`, every point
  `[x, y]` or every point `[x, y, z]`) and a declared number of physical
  `layers` (1 or 2; required whenever a layout is given);
- no cramming: at most `layers` qubits may share a site (the flip-chip stack),
  and distinct sites are >= 1 apart, so a check of diameter `r` genuinely spans
  `r` grid units and a small radius cannot be faked by collapsing qubits;
- short range: the measured interaction radius (largest check diameter) is within
  the class cap, 4.0 for `local-2d-single` and 7.0 for `local-2d-bilayer`.

A crammed or long-range layout simply earns no 2D-local class (it falls to
`unrestricted`); it is not rejected. "Short range" means a bounded, n-independent
diameter. The bilayer cap admits the weight-8 planar (tile-code) family: bulk
checks span about 5.83 and open-boundary corner stabilizers reach about 6.71,
both constant in n. The verifier also reports layout diagnostics (dimension,
interaction radius, qubits per site, minimum spacing, density, bounding
box). A 3D layout passes through the same cramming and spacing checks but
earns no 2D-local class; it is scored by the D = 3 geometric efficiency
below.

## Modular layouts

A layout may also assign every qubit to a hardware module
(`locality.modules`, one integer per qubit): a chip in a multi-chip
assembly, a flip-chip module joined to others by interconnects, a
photonically linked or shuttling zone. The locality tracks cover monolithic
2D and flip-chip bilayers; a modular machine falls to `unrestricted`, where
the board cannot tell a code whose checks rarely cross a module boundary
from an expander. Module membership is the same kind of cheap, checkable
structure as the coordinates, so the verifier reads it the same way: an
assignment must cover every qubit, and from it the verifier reports the
checks spanning more than one module (count and which), the ports each
module needs (the distinct other modules it shares a check with), and the
qubits per module. A code with such an assignment earns the Layer-3 flag
`modular`, and the site shows the diagnostics on its page. The module field
is independent of the coordinates, so it does not tie the layout to two
dimensions. Nothing else reads it: the locality class is computed from the
coordinates as before, g is unchanged, and the primary-tracks grid gains no
axis. Gate scheduling and routing cost across modules are out of scope.

## Circuit tier

An entry may ship the syndrome-extraction memory circuits it would run on,
`memory_x.stim` and `memory_z.stim` under `circuits/<slug>/`, with the
detector error models the pinned stim derives from them committed beside
them. The tier records `d_circ` per basis: the size of an exhibited set of
error mechanisms in that basis's detector error model that no detector sees
and that flips a logical observable, the circuit-level counterpart of the
low-weight logical the code tier stores. The verifier re-derives the detector
error model, checks the witness against it, and rejects a circuit that is not
a memory experiment of this code under the canonical noise recipe. The
schedule is the submitter's degree of freedom, the noise placement is not.
Like the code tier, `d_circ` is a witness-backed upper bound.

The tier is penalty-only: `d_circ` is clamped to `<= d`, so a circuit can
lower what the board shows for an entry and never raise it. The memory
experiment runs `rounds >= d` noisy extraction rounds, so a schedule cannot
earn a higher circuit distance by measuring fewer rounds than the code
distance. Nothing else changes: the entry stays in the same cells and keeps
its place on the (n, k, d, w) frontier, the site marks it with a gear chip
carrying the lower of its two `d_circ` values, and the circuit tab lists the
entries that have one.

The tier has caps: n at most 200, a cap on the error mechanisms per memory
detector error model at `rounds = d`, and a cap on the size of each committed
file. The numbers and the reasoning live with the constants `MAX_CIRCUIT_N`,
`MAX_DEM_MECHANISMS`, and `MAX_CIRCUIT_FILE_BYTES` in
`verify/circuit_verify.py`, decided on #2797 and #2811: the tier is for
instances that can be built and understood now, the mechanism cap is what the
refutation search covers in the gate's budget per basis, and the files stay
plain text so a witness is auditable in a diff. The caps are raise-only, with
a decision on the issue tracker. The fields are in `schema/SCHEMA.md` under
`circuit`.

## Measured-rate tier

On the same committed circuits an entry may also carry a measured logical
error rate, `circuit.ler`: per basis, a list of points, one per physical
error rate on a fixed grid (`P_GRID` in `verify/ler_verify.py`), each
recording the shots, the failures, the seed, the pinned decoder, the
per-round rate, and its confidence interval. `d_circ` is a floor. This is
the rate a simulation sees, prefactors included, and it is what separates two
schedules with the same `d_circ`. The grid is fixed so that entries are
compared only at equal p. The site never compares rates measured at
different physical rates, and the measured-rate frontier (over n, k, and the
rate, with d and w not entering) is computed per p over verified points only.

A point whose per-shot failure fraction exceeds one half is saturated, since
the per-round conversion reads it as one half whatever the circuit does, and
is rejected. Which rates are informative depends on the code, which is what
the grid is for. There is no clamp like `d_circ <= d`, because a rate has no
code-level bound to clamp to. The gaming direction is claiming a rate lower
than the circuit earns, and that is what replication tests.

Verification is by re-measurement with an independent seed, sized to
discriminate rather than to a fixed shot count. At PR time the gate tries the
points from the highest rate down inside a wall budget per basis and must
verify at least one. A point the budget cannot check to the admissibility
bound is deferred, with every lower point, to the weekly post-merge run
(`verify/ler_replicate.py`), which re-measures every point with a long budget
and several seeds and writes a receipt per entry under `receipts/ler/`. The
site shows each point as verified, failed, unverifiable, or pending, and a
failed or unverifiable point does not count toward the frontier. The budgets
and thresholds are the constants in `verify/ler_verify.py`, the fields and
verification rules are in `schema/SCHEMA.md` under `circuit.ler`, and the
decisions are #1278 and #2812.

## Two efficiency scores

The site shows two figures of merit (issue #276); both normalize the rotated
surface code to 1, but they answer different questions.

- **Operational efficiency** `kd^2/n`: the Bravyi-Poulin-Terhal saturation
  ratio, incumbent-relative. Bounded and meaningful for 2D-local /
  bounded-weight codes at comparable n; grows with n for high-rate codes, so
  it is compared within tracks.
- **Geometric efficiency** `g = 4 k d^2 / (n rho^2 r^4)` (written `f` in
  the working notes): the same ratio priced
  by the layout the code ships with. `r` is the measured interaction radius
  (max check diameter, Euclidean, in units of the unit qubit spacing), `rho`
  the layer count. The constant 4 = (sqrt 2)^4 puts the surface code
  (r = sqrt 2, rho = 1) at exactly 1. The `rho^2` factor is the capacity
  charge: it is the unique exponent that makes re-packaging a layout into
  layers score-neutral (folding halves the area within reach, gaining
  (sqrt 2)^4 = 4 in r^4, and pays exactly 4 in rho^2), so layers are neither
  free nor forbidden -- they must earn their density.

  Conventions and guards:
  - g is computed from any honest layout accepted by the verifier; the caps
    decide the cell, not the score. A layout outside a locality cap therefore
    remains in `unrestricted` while still receiving its continuously computed
    (usually smaller) g. A code without a layout has no g. That is a
    certification status, not a property: such a code may still be
    geometrically local (e.g. on a torus, or simply unlayouted) -- it is not
    thereby an "expander code".
  - g inherits the distance tier: computed from an upper-bound d it is an
    upper bound. So is kd^2/n, which is monotone in d in the same way, so the
    site marks neither -- the distance column carries the one `d <=` that
    governs both, and marking g alone read as if kd^2/n were the firmer number.
  - The headline card requires d >= 3: g is scale-free, so d = 2 tilings
    (a [[4,2,2]] block on one plaquette scores g = 2) would "beat" the
    surface code without encoding anything asymptotic. No known d = 3-4
    code with an honest layout comes near 1, but no theorem caps that band
    either; the threshold will be raised (or replaced by the d_min(w, rho)
    rule of the working notes) if a small-d packing exploit materializes.
  - D = 3: a layout may carry `[x, y, z]` coordinates (one dimension per
    layout; a mix is rejected). The BPT bound in D dimensions is
    kd^(2/(D-1)) = O(n), so for D = 3 the ratio is kd/n. The exponents on r
    and rho follow from the same coarse-graining that gives r^4 and rho^2 in
    the plane: a cell of side r holds rho r^D qubits, and the bound for the
    cell-level range-1 code charges that factor to the power 2/(D-1), so
    D = 2 pays (rho r^2)^2 and D = 3 pays rho r^3. Folding into layers stays
    score-neutral (r^3 shrinks by rho, rho grows by rho). The score is

        g = 2 sqrt(2) k d / (n rho r^3)      (D = 3).

    The constant (sqrt 2)^3 fixes the reference at the same nearest-neighbor
    cubic-lattice radius r = sqrt 2 as the surface code: a code that
    saturates kd = n at that radius scores exactly 1. The stated reference
    is the [[4,2,2]] code on one plaquette (kd = n, r = sqrt 2, rho = 1),
    the smallest such code; like the D = 2 normalization it sits below the
    d >= 3 headline threshold. For orientation, the 3D toric code on an
    L^3 periodic cubic lattice (edge qubits, scaled to unit spacing, so
    r = sqrt 2) scores 1/L^2, which records that it does not saturate the
    3D bound; layer codes (arXiv:2309.16503) do. The declared dimension is
    the priced dimension: a planar code submitted with z = 0 is scored by
    the D = 3 form, which for d >= 3 is the smaller number, so nothing is
    gained by mis-declaring. A 3D layout earns no 2D-local class (the caps
    are planar) and competes in `unrestricted` with its g; D = 2 scores are
    unchanged, and g is compared within a dimension, not across.
  - The caps above stay what they are: coarse eligibility gates. g prices
    range continuously inside the class; a trivial sqrt(n)-range layout is
    not banned by g, just priced into irrelevance (g ~ n^-2).

## Scalable families at surface-code parity

An entry with an honest layout, `d >= 3`, and `g >= 1` matches or beats the
rotated surface code under the pricing above. "A scalable family with g > 1"
has been used for five different claims (issue #4160), and a reviewer can hold
a submission only to the bar it names, so the five are listed here, strictest
first. None of them ranks anything: the board ranks by the Pareto frontier
over `(n, k, d, w)` within a track cell, and `g >= 1` is a property an entry
has or lacks. A PR claiming one of these bars names it in the "Surface-code
parity bar" line of the PR body (the template carries the line) and in the
note's "Direction & hypothesis" section.

Every rung, under every bar, is an ordinary submission. It passes the trusted
gate (`verify/validate_candidate.py`), ships a distance witness (an upper
bound is accepted, and g then inherits that tier), carries the layout its g is
computed from, declares a construction family from the Layer-2 vocabulary (a
locality class is a track, not a family), and comes with a note following
`notes/TEMPLATE.md`. g is `site/build.py::geo_score` as defined above. At the
surface-code point `r = sqrt 2`, `rho = 1` of `local-2d-single x weight-4` it
reduces to `k d^2 / n`, so `g >= 1` there is `k / n >= 1 / d^2`.

1. **Asymptotic family**: `n` and `d` both grow and g tends to a constant
   `c > 4/3`. A closed form or parametric recipe gives `(n, k, d)` as
   functions of one or two growing parameters and produces
   `local-2d-single x weight-4` codes with honest layouts at infinitely many
   sizes, with `d` unbounded and `liminf g >= c` for a stated `c > 4/3`. The
   4/3 is the reported large-`d` constant of the dense-packed ladder and of
   its multi-band variant
   (`fieldnotes/2026-08-29-triplet-reverse-engineering-and-manifold-subtraction.md`,
   `fieldnotes/2026-08-31-multiband-sweep-and-exact-d4-sat.md`); a
   construction whose constant exceeds it is new. Acceptance: at least three
   gate-passed rungs at distinct, growing `d` (for example 5, 7, and 9) whose
   g moves toward `c` as the closed form predicts, and a note stating the
   closed form and the asymptotic. One-off codes and `d = 2` tilings are out
   of scope.

2. **Size scaling at fixed distance**: `d` fixed, `n` growing, `g >= 1`
   throughout. The distance need not grow. Acceptance: at least three
   gate-passed rungs at one `d` with `n` strictly increasing within the cap
   (`n <= 700`, or `n <= 1000` at `w <= 8` and `d <= 40`), each at `g >= 1`,
   mutually non-dominated on `(n, k)` or dominating an existing entry. No
   closed form is required. A recipe in the reproduction manifest
   (`repro/<slug>.json`, construction stage) is preferred because it lets the
   family be rebuilt at other sizes. Prefer `d >= 5`: a `d = 3` slice is the
   one most exposed to a change in the headline threshold.

3. **Reproducible recipe**: one `g >= 1` rung plus multi-size evidence.
   Acceptance: a gate-passed rung with `g >= 1` and `d >= 3` whose
   reproduction manifest carries a construction recipe, and the recipe
   rebuilt at three or more sizes passing the structural checks recorded in
   `research/repro/multisize.json` (checks commute, the code encodes, the
   Tanner graph is connected, the caps hold; `research/kit/multisize.py`). No
   distance is claimed at the other sizes and no asymptotic constant is
   claimed. This is the least evidence of a construction the board records,
   and the floor at which a family claim rests on more than one point.

4. **Pointwise parity**: a single code. Acceptance: a gate-passed code with
   `d >= 3`, an honest layout, and `g >= 1`. No family, recipe, or asymptotic
   is claimed, and the note need not claim one. Such a code is
   board-advancing whenever it is undominated in its cell, so it is worth
   submitting. It carries the tier of its distance, and if the headline
   threshold `GEO_MIN_D` is raised a `d = 3` entry loses its headline
   eligibility without losing its place on the board.

5. **New mechanism**: `g > 1` at `w <= 4` in `local-2d-single` by a route
   other than those on the board (perimeter logicals of the dense-packed
   ladder, the multi-band boundary refund, chamfered and hole-lattice surface
   codes; `fieldnotes/2026-08-29-g-parity-agenda.md` records them).
   Acceptance: a gate-passed rung with `g > 1` and `d >= 3`, a note
   describing the mechanism and the free parameter that grows `n` or `d`,
   and a sketched family (closed form or recipe). A recipe that rebuilds at
   three or more sizes also meets bar 3. Reproducibility is required; an
   asymptotic proof is not.

Bars 1 to 3 are judged on a statement about the family, so a later change to
the headline threshold does not retire them; the entries such a change would
affect are bar-4 codes at small `d`. For orientation, on 2026-10-30 the board
held 186 eligible entries at `g >= 1`, all at `w = 4` in `local-2d-single`
and all at upper-bound distances, with `d` from 3 to 31. The largest g was
1.76 at `d = 4` ([[957,105,4]]), then 1.68 at `d = 3`, 1.35 at `d = 5`, and
1.27 at `d = 13`, and every member at `d >= 15` is a [[d^2,1,d]] surface code
at exactly 1.

## Reference bars

- 2D-local efficiency: the published weight-8 exact bar is kd^2/n ~ 12.7, the
  [[512,18,19]] tile code (arXiv:2504.09171, ILP-exact); the strictly
  nearest-neighbour directional-tile [[323,14,15]] (arXiv:2606.19482) reaches
  ~9.75 at the higher check weight 11; at moderate size the planar weight-8
  [[282,12,14]] (arXiv:2504.08887, v3+) reaches ~8.34. Best on the board so far:
  [[294,12,14]] at kd^2/n 8.0 (an upper bound, not yet certified exact), which
  the published [[282,12,14]] strictly dominates. Like the Kasai codes below,
  [[282,12,14]] is cited as a bar rather than seeded: its bulk polynomials are
  in the paper's text, but its boundary stabilizers (including secondary gauge
  operators that are not truncations of bulk terms) and the 10 grafted-away
  qubits are specified only in figures (Figs. 7 and 28), with no machine-readable
  data published, so a faithful reproduction is not currently possible.
- Weight-8, any connectivity: the double-cover 2BGA [[168,20,14]]
  (arXiv:2606.17268, Table 4, distance stated exact there) reaches kd^2/n ~ 23.3,
  beating the board's previous best [[180,20,14]] at 21.8 (an uncertified upper
  bound); it strictly dominates both n=180 coset submissions. Now seeded as a
  baseline (codes/168-20-14.json), so the board reflects it directly.
- High-rate / large-block: Kasai's codes [[9216,4612,<=48]]
  (arXiv:2601.08824) and [[16384,4142,<=40]] (arXiv:2604.20838), cited as bars
  rather than seeded (their distance witnesses are not published and the verifier
  does not certify distance at these sizes). The challenge is to land a code in
  this regime with a checkable distance witness.
- High-rate, weight-9 (any connectivity): the mitten codes of arXiv:2607.28795,
  non-abelian lifted-product codes at 20% rate. Six of the paper's eight
  processor codes fit under the n <= 700 cap (#377): [[150,30,10]],
  [[200,40,12]], [[300,60,14]], [[500,100,16]], [[540,108,18]] and
  [[630,126,<=20]], reaching kd^2/n ~ 20 to 80. Five of those six are seeded
  from this paper; [[150,30,10]] was already on the board from the ZSZ-LP
  seeding below and keeps that provenance, for the reason worked out in
  notes/150-30-10.md. The remaining two exceed the 700 cap and, at check
  weight 9, do not qualify for the extended tier (n <= 1000 needs w <= 8 and
  d <= 40), so they stay bars only:
  [[780,156,<=22]] (kd^2/n ~ 96.8) and [[975,195,<=24]] (~115.2). The
  construction is fully
  specified (a 1x2 base matrix over F_2[G] for a non-abelian G, their
  Definition 4) and the authors publish their check matrices, so the seeded
  entries are reconstructions checked against the authors' own matrices rather
  than parameter claims. Note the paper evaluates these at the circuit level
  (logical error rate under noise), not by kd^2/n.
- High-rate, weight-9, second construction: the ZSZ-LP codes of
  arXiv:2607.27644, balanced products of rate-1/2 classical LDPC codes sharing a
  non-abelian Z_l1 semidirect_q Z_l2 symmetry, also at 20% rate and check weight
  9. Twelve of the paper's fourteen instances fit under the n <= 700 cap, from
  [[60,12,6]] up to [[700,140,22]]. Unlike the mitten entries above these are
  not baselines: the paper's author submitted them directly (#357 to #368), so
  they carry origin `submission`. The paper's distances are SAT-exact through
  [[320,64,14]] and upper bounds above it, which the board's per-side
  confidence fields mirror. The remaining two exceed the 700 cap and, at
  check weight 9, do not qualify for the extended tier, so they stay bars
  only: [[775,155,<=22]] (kd^2/n ~ 96.8) and [[840,168,<=24]] (~115.2). Its
  Table 3 lists the group parameters (l1, l2, q) and the trinomials a, b, c, d
  for every instance, and each submission repeats its own generators in its
  construction string, so every entry is checkable against the paper rather
  than a bare parameter claim.
  This family and the mitten codes above reach the same design point by
  different routes: both sit at rate 1/5 with weight-9 checks, and since
  kd^2/n = rate * d^2, their over-cap bars coincide numerically at any shared
  distance (96.8 at d = 22, 115.2 at d = 24). [[150,30,10]] is not merely
  comparable but the same code in both papers.
  [[270,54,10]] over ZSZ(18,3,13) uses this construction without being a paper
  instance, so it is an independent submission rather than a reproduction.

## Baselines and provenance

The boards are seeded with selected reference codes from the literature,
attributed to their authors, so a submission is measured against known codes
rather than an empty board: the bivariate-bicycle codes of Bravyi et al
(arXiv:2308.07915), the planar codes of Liang, Eberhardt, Chen (arXiv:2504.08887),
the generalized-bicycle codes of Panteleev-Kalachev (arXiv:1904.02703) and
Wang-Pryadko (arXiv:2203.17216), the twisted-torus / generalized-toric codes of
Liang, Liu, Song, Chen (arXiv:2503.03827), and the Kitaev surface / toric and
Steane codes.

This seed set is not an exhaustive snapshot of the literature. Notable families
not yet seeded include the LLM-search CSS catalog of arXiv:2606.02418 and the
two-block group-algebra database (arXiv:2306.16400). So the on-board frontier is
a repo-local frontier, and a code that leads a cell here may still be matched or
beaten by a published code that has not been seeded yet. Seeding these is tracked
as follow-up work.
