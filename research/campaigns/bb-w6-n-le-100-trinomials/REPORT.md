# bb-w6-n-le-100-trinomials: 120 random trinomial BB pairs at n <= 100, none above the cell's seeded bar

## What was asked

Whether random trinomial pairs on small tori Z_l x Z_m (n = 2lm between 40 and
100) hold a weight-6 CSS code with kd^2/n above 8.889, the best of the
unrestricted weight-6 cell at n <= 100 (codes/90-8-10.json, a seeded baseline).
The definition, `research/campaigns/bb-w6-n-le-100-trinomials/campaign.json`,
is the first filed with a direction card (issue #4028): the card states the
hypothesis, the cell and family, the bar and its axis, the budget, why the
test is cheap here, the novelty claim and what it is measured against, what a
positive result would be worth, the abandon criterion, and what a negative
result teaches. The budget: 120 screened candidates and half an hour of wall
clock.

## What was spent

120 of 120 candidates and 0.002 of 0.5 wall-clock hours; `budget_exhausted`
fired. The screen rejected 1,673 further draws for having no logical qubits
(k = 0), which were counted and not charged: a trinomial pair with k = 0 has
no distance to screen.

## What ran

`research/campaigns/bb-w6-n-le-100-trinomials/run.py` on main at 630185d7,
no accelerator: `sample_bb` (weight 3 per polynomial, l and m in 3 to 10,
n in 40 to 100, seed 0), k from `css.compute_k`, distance from
`surrogate.distance_rand` at 400 numpy RIS trials with seed 0. A candidate
whose screened kd^2/n cleared 8.889 would have gone to
`verify/validate_candidate.py` with refutation on; none did, so the gate was
not invoked and there is no manifest, as a campaign that submits nothing
needs none.

## What was tried

120 trinomial pairs with k >= 1, one experiment each, screened at 400 trials.
Screened distances: d = 2 for 5, d = 4 for 26, d = 6 for 49, d = 8 for 23,
d = 10 for 17. The best kd^2/n was 6.122 at [[98,6,10]] (l = 7, m = 7),
reached by several pairs; the bar is 8.889.

## Survivors

None. No candidate cleared the bar on screen, so none was sent to the gate.

## Negative results

The small-torus trinomial space at n <= 100 holds nothing above the seeded
bar at this depth: 120 pairs with k >= 1 top out at 6.122, below 90-8-10
(8.889) and 98-6-12 (8.816), both literature picks. A 400-trial screen is an
upper bound on d, so a candidate reads at or above its true kd^2/n here, and
the negative stands at the screen's depth. What it teaches, as the card said
in advance: the next session should spend its budget on larger tori or on
four-term polynomials rather than re-sampling trinomials at n <= 100.

## What the next searcher should know

- About 14 random trinomial pairs in 15 have k = 0 at these sizes; a sweep
  that charges them to its budget measures almost nothing.
- The pairs that do encode cluster at d = 6 and kd^2/n near 4; the known
  literature picks at n <= 100 are far above the random distribution, so
  beating them needs structure (the gross-code polynomial families) rather
  than draws.
- `summary.json` carries the card under `direction`, the 120 rows with their
  screened reading, and this negative, so the result is readable without this
  report.
