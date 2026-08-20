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

## Layer 2: family tags (provenance, never ranked)

The construction family cannot be recovered from `H`, which is exactly why it is a
filterable tag and not a board: a tag confers no ranking advantage, so there is
nothing to game by relabeling. Vocabulary: `bivariate-bicycle`,
`generalized-bicycle`, `2bga-coset`, `hypergraph-product`, `lifted-product`,
`balanced-product`, `quantum-tanner`, `tile`, `topological` (surface / toric /
color), `other`. On the board it is a filter, not a leaderboard.

## Layer 3: verified flags (earned badges)

Only things the verifier or a certificate can prove: the distance-confidence
tier, CSS commutation, and the locality class (which doubles as Layer-1
membership).

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

- a coordinate for every qubit (`coordinates` covers all `n`) and a declared
  number of physical `layers` (1 or 2; required whenever a layout is given);
- no cramming: at most `layers` qubits may share a site (the flip-chip stack),
  and distinct sites are >= 1 apart, so a check of diameter `r` genuinely spans
  `r` grid units and a small radius cannot be faked by collapsing qubits;
- short range: the measured interaction radius (largest check diameter) is within
  the class cap, 4.0 for `local-2d-single` and 7.0 for `local-2d-bilayer`.

A crammed or long-range layout simply earns no 2D-local class (it falls to
`unrestricted`); it is not rejected. "Short range" means a bounded, n-independent
diameter. The bilayer cap admits the weight-8 planar (tile-code) family: bulk
checks span about 5.83 and open-boundary corner stabilizers reach about 6.71,
both constant in n. The verifier also reports layout diagnostics (interaction
radius, qubits per site, minimum spacing, density, bounding box).

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
  - D = 2 only for now: the schema stores planar coordinates. The D > 2
    generalization changes the exponents (kd^(2/(D-1)) per the BPT bound)
    and is reserved.
  - The caps above stay what they are: coarse eligibility gates. g prices
    range continuously inside the class; a trivial sqrt(n)-range layout is
    not banned by g, just priced into irrelevance (g ~ n^-2).

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
  notes/150-30-10.md. The remaining two exceed the cap and stay bars only:
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
  confidence fields mirror. The remaining two exceed the cap and stay bars
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
