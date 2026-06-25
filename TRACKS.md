# Tracks and leaderboards

A quantum code is not a single number. You trade physical qubits n, logical
qubits k, distance d, check weight, and geometric locality against each other,
and separately you care how the code decodes under noise. So there is no one
leaderboard. Instead there are tracks (hard-constraint categories), and within
each track the ranking is a Pareto frontier, not a single winner.

## How ranking works inside a track

Two views of the same data:

- Frontier view: the set of Pareto-optimal codes over (n, k, d). A code is on
  the frontier if no other code in the track dominates it (no other has n' <=
  n, k' >= k, d' >= d with at least one strict). There can be many co-leaders.
- Cell view (the code-tables style): a grid keyed by (k, d); each cell holds
  the smallest known n, with a challenger history. This is the view people
  usually screenshot.

`kd^2/n` (the encoding-efficiency figure the 2D-locality literature uses) is a
sortable column and a reasonable per-track headline number, but it never
collapses the frontier into one rank.

Every entry also carries a distance-confidence label, orthogonal to the track:
`d<=` (self-certified upper bound) or `d=` (server-certified exact). They are
shown distinctly; an exact record outranks an equal upper-bound one.

## Initial tracks

These are where we have data and verification today. More can be proposed by PR.

- `weight-6`: CSS codes with all stabilizer checks of weight <= 6, any
  connectivity. The headline frontier. Sub-thresholds `weight-4`, `weight-8`
  exist as separate tracks. The `weight-8` track is seeded with coset
  two-block (2BGA) codes (arXiv:2606.17268), currently carried as distance
  upper bounds (d<=) pending exact certification. Further reference targets
  that could be added as baselines: the Liang-Eberhardt-Chen weight-8 k=12
  family (arXiv:2504.08887, Sec. IV D) [[240,12,12]], [[292,12,14]],
  [[399,12,18]], and the published 2BGA codes of arXiv:2606.17268.
- `2d-local-bilayer`: geometrically 2D-local on up to 2 physical layers
  (the flip-chip regime of the bivariate-bicycle planar codes), with a stated
  `locality` block. Ranked within a maximum interaction radius. Current best
  known 2D-local efficiency is kd^2/n ~ 9.75, the [[323,14,15]] tile code
  (arXiv:2606.19482; tile-code construction arXiv:2504.09171), which is the bar
  to beat. Reaching it on the board needs a tile-code generator (planar
  open-boundary BB with tile truncation), a possible follow-on to the existing
  boundary engine.
- `bivariate bicycle (periodic)`: bivariate bicycle codes on a torus
  (periodic boundary conditions), no 2D-local layout. Seeded with the
  canonical codes of Bravyi et al (arXiv:2308.07915).
- `generalized bicycle`: univariate quasi-cyclic codes from two circulant
  polynomials (the one-variable cousin of bivariate bicycle codes), seeded
  from the literature (arXiv:2203.17216).
- `topological`: the foundational topological codes (surface, toric, color),
  whose distance is exact by construction. The surface-code baseline.
- `2d-local-single`: 2D-local on a single layer (surface-code-like
  connectivity). Stricter; mostly a baseline track.
A code may enter multiple tracks (list them all in `tracks`). It only appears
on a track's board if it satisfies that track's constraints, which the
verifier checks (for example, `weight-6` requires measured max check weight
<= 6).

### 2D-locality is proven, not asserted

Claiming a `2d-local-*` track requires a `locality` block with a coordinate for
every qubit, and the verifier proves the claim rather than trusting it. A bare
distance/efficiency number is not enough: a code that is not actually
short-range would otherwise sit on the 2D-local frontier unfairly. The verifier
enforces:

- a layout: one coordinate per qubit (`coordinates` covers all `n`);
- no cramming: at most `layers` qubits may share a site (the flip-chip stack),
  and distinct sites are >= 1 apart, so a check of diameter `r` genuinely spans
  `r` grid units and a small radius cannot be faked by collapsing qubits;
- short range: the measured interaction radius (largest check diameter) is
  within the track cap, `4.0` for `2d-local-single` (`layers <= 1`) and `6.0`
  for `2d-local-bilayer` (`layers <= 2`). The caps sit above the seeded planar
  baselines (max measured radius 4.472 on bilayer) with margin.

The verifier also reports layout diagnostics (interaction radius, qubits per
site, minimum site spacing, qubits per unit area, bounding box) so a code's
geometric "dimension" is visible, not just its [[n, k, d]].

## Baselines and provenance

The boards are seeded with the codes from Liang, Eberhardt, Chen
(arXiv:2504.08887) as the reference baseline, attributed as theirs, so every
new submission is measured against the published state of the art rather than
an empty board.
