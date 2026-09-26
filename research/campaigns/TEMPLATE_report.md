# <campaign id> — <one line: what was searched and what came of it>

<!-- The human half of a campaign's output, beside summary.json. Written when
the campaign ends, including when it ends with nothing to submit: a closed
family is a finding, and the next searcher pays for it twice if it is not
written down. Every path named here must exist in the tree;
research/candidates/ is gitignored working output and cannot be cited.
Delete this comment. -->

## What was asked

The objective, the search space and the budget, in a sentence each. Link the
definition: `research/campaigns/<id>/campaign.json`.

## What was spent

Budget consumed against budget declared, and which stopping condition fired.
Both are in `summary.json`; restate them here so the report reads alone.

## What was tried

One line per experiment: family, generator, seed, sweep size, screening depth.
Numbers, not prose. "13,200 weight-5 divisor pairs on Z_129 at 1.5k RIS trials"
tells the next searcher something; "we swept the family" does not.

## Survivors

Each validated survivor as `[[n,k,d]]`, its weight, its cell, and what the gate
said. A survivor is a candidate the gate accepted; it is not a board entry
until a human submits it. If there are none, say so here rather than leaving
the section out.

## Negative results

The walls. Families that screened well and collapsed, structural approaches
that produced k=0, ladders that fell over, regions with nothing in them. State
what was ruled out and at what budget, so the boundary is reusable.

## Follow-up

What the next campaign on this direction should do differently, and what it
should not repeat.
