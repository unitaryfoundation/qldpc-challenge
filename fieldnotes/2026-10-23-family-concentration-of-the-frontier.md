---
title: "Family concentration of the frontier, first measurement: generalized-bicycle holds 42% of the CSS frontier's records, the top two 54%, and the search has moved 5 of 12 cells off the literature's best family"
date: 2026-10-23
author: "@vprusso"
model: "Claude Fable 5.1 (Claude Code)"
topics: [frontier, family, concentration, diagnostics, board-shape]
status: active
---

Issue #4025 (@MathysRennela) asks for the shape of the frontier by family to be a
published number rather than a caveat. This note records the first measurement, on
main at d5a2a7406 (2,728 entries, 2,532 CSS), made by
research/audits/family_concentration.py; its record is
research/audits/family_concentration-2026-10-23.json. The metric is computed in
site/build.py from the same per-cell and global Pareto frontiers over (n, k, d, w)
that award the star, and the site publishes it in docs/stats.json and beside the
frontier map's legend.

## What is measured

- For each of the 12 CSS primary-track cells and for the global CSS frontier: the
  share of the frontier's records held by the top declared family and by the top
  two, and the Herfindahl-Hirschman index (HHI, the sum of squared family shares:
  1/families for an even split, 1 for a single family).
- Whether the search moved a cell: the cell's leader (largest kd^2/n) belongs to a
  family other than the incumbent's, where the incumbent is the same leader taken
  over the cell's literature baselines alone (provenance.origin baseline), the best
  the seeded literature had there.
- Entries rendered as family "other" are entries without a family tag. They are
  reported as untagged: in every denominator, never a family in the top list or the
  HHI.

Cells nest (a weight-4 code is also in the weight-6, weight-8, and weight-any
cells), so a code counts in every cell it qualifies for, and the global row is the
unrestricted, weight-any cell by construction.

## The caveat, which travels with every number

`family` is the one self-declared label on an entry (research/AUTORESEARCH.md:
filterable, never ranked). Everything here measures the declared tag, not a property
recovered from H, and is displayed, never ranked. The derived provenance buckets in
research/provenance/derived.json are the computed axis wherever they cover an entry.

## First measurement, 2026-10-23

Global CSS frontier: 1,413 records, 14 named families and 187 untagged (13%).
generalized-bicycle holds 596 (42%) and bivariate-bicycle 170 (12%); the top two hold
54%; HHI 0.207. The search has moved 5 of 12 cells to a family other than the
literature's best there.

| cell | members | records | top family (share) | top two | HHI | incumbent -> leader | moved |
|---|---|---|---|---|---|---|---|
| local-2d-bilayer~weight-4 | 256 | 189 | local-2d-single (46%) | 80% | 0.331 | topological -> topological | no |
| local-2d-bilayer~weight-6 | 661 | 371 | generalized-bicycle (28%) | 51% | 0.189 | bivariate-bicycle -> generalized-bicycle | yes |
| local-2d-bilayer~weight-8 | 1,043 | 556 | generalized-bicycle (37%) | 52% | 0.195 | pair-partition-cpm -> pair-partition-cpm | no |
| local-2d-bilayer~weight-any | 1,130 | 604 | generalized-bicycle (37%) | 52% | 0.190 | pair-partition-cpm -> lifted-product | yes |
| local-2d-single~weight-4 | 243 | 179 | local-2d-single (48%) | 85% | 0.367 | topological -> topological | no |
| local-2d-single~weight-6 | 353 | 239 | local-2d-single (36%) | 65% | 0.229 | bivariate-bicycle -> bivariate-bicycle | no |
| local-2d-single~weight-8 | 418 | 277 | local-2d-single (31%) | 57% | 0.185 | bivariate-bicycle -> tile | yes |
| local-2d-single~weight-any | 419 | 278 | local-2d-single (31%) | 56% | 0.184 | bivariate-bicycle -> tile | yes |
| unrestricted~weight-4 | 271 | 195 | local-2d-single (44%) | 78% | 0.311 | topological -> topological | no |
| unrestricted~weight-6 | 931 | 528 | generalized-bicycle (30%) | 47% | 0.160 | 2bga-coset -> 2bga-coset | no |
| unrestricted~weight-8 | 1,828 | 964 | generalized-bicycle (37%) | 50% | 0.178 | pair-partition-cpm -> pair-partition-cpm | no |
| unrestricted~weight-any | 2,532 | 1,413 | generalized-bicycle (42%) | 54% | 0.207 | pair-partition-cpm -> generalized-bicycle | yes |

## Reading it

- generalized-bicycle and bivariate-bicycle hold 54% of the global frontier's
  records and 53% of the board's entries (1,436 of 2,708 when the issue was
  opened), so the frontier's shape follows the entry mix: the two families are not
  more concentrated on the frontier than in what was submitted.
- The weight-4 cells are the literature's. The local-2d-single and topological tags
  hold 78% to 85% of their records, HHI above 0.3, and their leaders are the
  topological codes the baselines already led with.
- Concentration falls as the weight cap loosens: HHI 0.31 to 0.37 at weight 4, 0.16
  to 0.23 at weight 6, 0.18 to 0.21 at weight 8 and above, as more families reach
  those cells.
- The five moved cells are where a submitted family overtook the seeded one: the
  bilayer-local board at weight 6 (generalized-bicycle over bivariate-bicycle) and
  weight-any (lifted-product over pair-partition-cpm), the single-layer board at
  weight 8 and weight-any (tile over bivariate-bicycle), and the unrestricted
  weight-any cell (generalized-bicycle over pair-partition-cpm).

## Re-measuring

```
uv run python research/audits/family_concentration.py --markdown
```

writes a record dated by the run beside the script (today's is
research/audits/family_concentration-2026-10-23.json) and prints the table above, so
later measurements extend the series this note starts. docs/stats.json carries the
current values under family_concentration on every site build.

## Limits

- A declared label is what is counted (above); an entry tagged by its construction
  family rather than by what H is isomorphic to is counted under its tag.
- A record counts once per cell it sits on, so the per-cell rows are not disjoint
  and do not sum to the global row.
- The frontier is repo-local (TRACKS.md): a published code not yet seeded is on none
  of these frontiers, and a cell's incumbent is the best of the baselines seeded so
  far, not the literature's best.
- Leader ties are broken by date, then slug.
