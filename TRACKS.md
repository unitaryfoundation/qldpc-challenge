# Tracks and leaderboards

A quantum code is not a single number. You trade physical qubits n, logical
qubits k, distance d, check weight, and geometric locality against each other,
and separately you care how the code decodes under noise. So there is no one
leaderboard. Instead there are tracks (hard-constraint categories), and within
each track the ranking is a Pareto frontier, not a single winner.

## How ranking works inside a track

Two views of the same data:

- Frontier view: the set of Pareto-optimal codes over (n, k, d, w). A code is on
  the frontier if no other code in the track dominates it (no other has n' <= n,
  k' >= k, d' >= d, w' <= w with at least one strict). Check weight w is a
  frontier axis (lower is better) now that it is a plain property, not a track.
  There can be many co-leaders. A code is also a record if it is on the global
  (n, k, d, w) frontier across all codes, so a code in no track can still earn
  the star.
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

- Check weight is **not a track**. It is a plain code property `w` (the maximum
  stabilizer check weight), recomputed by the verifier, filtered on the board
  with the weight-range slider, and counted as a Pareto axis (lower is better).
  Reference targets at check weight 8: the Liang-Eberhardt-Chen k=12 family
  (arXiv:2504.08887, Sec. IV D) [[240,12,12]], [[292,12,14]], [[399,12,18]], and
  the coset two-block (2BGA) codes of arXiv:2606.17268 (carried as d<= upper
  bounds pending exact certification).
- `2d-local-bilayer`: geometrically 2D-local on up to 2 physical layers
  (the flip-chip regime of the bivariate-bicycle planar codes), with a stated
  `locality` block. Ranked within a maximum interaction radius (cap 7.0; see
  the locality section). Best on the board: kd^2/n ~ 8.0, [[294,12,14]] from
  the boundary engine (tile family). Open target: the published bar is
  kd^2/n ~ 9.75, the [[323,14,15]] tile code (arXiv:2606.19482; construction
  arXiv:2504.09171). Closing that gap needs the genuine tile-code truncation
  (planar open-boundary BB), a follow-on to the boundary engine.
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
- `high-rate` (large-block): high-rate qLDPC codes (large n, high k/n), ranked
  by kd^2/n in their own board so large codes do not dominate the small-code
  tracks. No verified entries yet. Open targets, cited as bars to beat rather
  than seeded as entries (their distance witnesses are not published and our
  verifier does not certify distance at these sizes): the Kasai-group codes
  [[9216,4612,<=48]] (arXiv:2601.08824) and [[16384,4142,<=40]]
  (arXiv:2604.20838). The challenge here is to land a code in this regime with
  a checkable distance witness; until then the bars stand as references, not
  board records.
A code may enter multiple tracks (list them all in `tracks`), or none — a
track-less code still appears in the table and on the global frontier; it is
just filtered by the `w` slider and property comparisons. A code only appears
on a track's board if it satisfies that track's constraints, which the verifier
checks (for example, `2d-local-bilayer` requires a `locality` block within the
radius cap).

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
  within the track cap, `4.0` for `2d-local-single` (`layers <= 1`) and `7.0`
  for `2d-local-bilayer` (`layers <= 2`). "Short range" means a bounded,
  n-independent diameter, not a specific tiny number. The bilayer cap admits
  the weight-8 planar (tile-code) family this track exists to chase: its bulk
  checks span about 5.83 and open-boundary corner stabilizers reach about 6.71,
  both constant in n. The cap rejects layouts whose range grows with the code.

The verifier also reports layout diagnostics (interaction radius, qubits per
site, minimum site spacing, qubits per unit area, bounding box) so a code's
geometric "dimension" is visible, not just its [[n, k, d]].

## Baselines and provenance

The boards are seeded with the codes from Liang, Eberhardt, Chen
(arXiv:2504.08887) as the reference baseline, attributed as theirs, so every
new submission is measured against the published state of the art rather than
an empty board.
