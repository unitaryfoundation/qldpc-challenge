# cc-v032-direction8-applicability: move applicability over the CSS board, by family and by pool

## What was asked

Issue #7377, direction 8: re-run the parents of the v0.2 negative pilots
(issue #6198 campaigns 2, 3, 4, and 6) through code-calculus v0.3.2's
`move_applicability_report` and record, per move family, the domain size,
the derived count, the usable count, and the dominant refusal or screen, as
the calibration input for whether those campaigns failed because the moves
were inapplicable or because the search missed them; and turn the per-step
records into a board-wide table. Runner and tables:
`research/campaigns/cc-v032-direction8-applicability/run.py` and `aggregate.py`.

## What was spent

64.9 CPU-hours over 3,529 parents (median 16 s per parent, 584 s at most),
about 5.9 hours of wall time on one laptop: the 2,776 parents up to n = 500 on
ten workers (5,532 s), then the 753 above on six and then fourteen workers
(5,035 s for the first 204, 10,646 s for the rest). No parent failed.

## What ran

`run.py` against code-calculus v0.3.2 (github.com/unitaryfoundation/code-calculus @
474104a257f79019a61bb3e8d9c7ae25e43047a6) over every CSS entry of `codes/` at
fdccaecfc: `CodeState.from_challenge` on the entry, then
`move_applicability_report(state, weight_cap=state.w(), rebase=n <= 100)`.
The weight cap is the parent's own displayed check weight, so a usable child is
one no heavier than its parent; `P-REBASE` tries every elementary row mix
(quadratic in the row count: 37,812 mixes and nine minutes at n = 288) and was
asked for only up to n = 100, 1,133 parents. The four pools are the parent
definitions of the v0.2 campaigns the direction names (issue #6198): C2
(delete-check chains into k-heavy cells: d >= 8, w <= 8), C3 (weight shedding:
d >= 8, w >= 8), C4 (puncture and peel chains toward missing n: n >= 500,
d >= 6), C6 (sector-swap rebalance: d_X != d_Z). They are labels on the records,
not separate runs. `aggregate.py` builds the tables (`result-table.json`),
`analyze.py` the readings (`result-readings.json`); `result-reports.jsonl` is
every per-parent record with the refusal and screen names coded by
`result-legend.json`.

## The board-wide table

3,529 parents.

| family | parents asked | domain | derived | usable | parents with a usable child | dominant blocker (share of blocked) |
|---|---|---|---|---|---|---|
| C-DELETE-CHECK | 3529 | 850,421 | 850,421 | 718,019 | 3009 | weight_one_logical (100%) |
| E-PEEL | 3529 | 2,004,654 | 168,851 | 123,401 | 2064 | E-PEEL unique-touch fails: q is not in exactly one displayed X-row (49%) |
| E-PUNCTURE | 3529 | 1,002,327 | 1,002,327 | 697,322 | 2822 | weight_one_logical (83%) |
| E-GRAFT | 3529 | 2,004,654 | 1,882,488 | 160,060 | 2107 | over_weight_cap (93%) |
| P-REBASE | 1133 | 918,892 | 918,892 | 35,524 | 429 | over_weight_cap (98%) |
| E-EXTEND | 3529 | 2,008,183 | 4,779 | 35 | 32 | E-EXTEND addition fails opposite-sector commutation (100%) |

## The pools

C2: 1154 parents

| family | parents asked | domain | derived | usable | parents with a usable child | dominant blocker (share of blocked) |
|---|---|---|---|---|---|---|
| C-DELETE-CHECK | 1154 | 395,871 | 395,871 | 371,778 | 1154 | weight_one_logical (100%) |
| E-PEEL | 1154 | 842,060 | 30,709 | 29,734 | 774 | E-PEEL unique-touch fails: q is not in exactly one displayed X-row (50%) |
| E-PUNCTURE | 1154 | 421,030 | 421,030 | 333,432 | 1132 | weight_one_logical (98%) |
| E-GRAFT | 1154 | 842,060 | 828,876 | 30,429 | 776 | over_weight_cap (98%) |
| P-REBASE | 123 | 310,242 | 310,242 | 3,014 | 5 | over_weight_cap (100%) |
| E-EXTEND | 1154 | 843,214 | 1,154 | 0 | 0 | E-EXTEND addition fails opposite-sector commutation (100%) |

C3: 1158 parents

| family | parents asked | domain | derived | usable | parents with a usable child | dominant blocker (share of blocked) |
|---|---|---|---|---|---|---|
| C-DELETE-CHECK | 1158 | 387,191 | 387,191 | 378,843 | 1157 | weight_one_logical (100%) |
| E-PEEL | 1158 | 887,236 | 9,897 | 9,785 | 298 | E-PEEL unique-touch fails: q is not in exactly one displayed X-row (50%) |
| E-PUNCTURE | 1158 | 443,618 | 443,618 | 405,118 | 1138 | weight_one_logical (96%) |
| E-GRAFT | 1158 | 887,236 | 884,159 | 22,817 | 328 | over_weight_cap (100%) |
| P-REBASE | 98 | 229,630 | 229,630 | 6,308 | 8 | over_weight_cap (100%) |
| E-EXTEND | 1158 | 888,394 | 1,158 | 0 | 0 | E-EXTEND addition fails opposite-sector commutation (100%) |

C4: 613 parents

| family | parents asked | domain | derived | usable | parents with a usable child | dominant blocker (share of blocked) |
|---|---|---|---|---|---|---|
| C-DELETE-CHECK | 613 | 366,899 | 366,899 | 347,687 | 613 | weight_one_logical (100%) |
| E-PEEL | 613 | 823,318 | 25,306 | 24,189 | 289 | E-PEEL unique-touch fails: q is not in exactly one displayed X-row (50%) |
| E-PUNCTURE | 613 | 411,659 | 411,659 | 345,563 | 613 | weight_one_logical (97%) |
| E-GRAFT | 613 | 823,318 | 811,156 | 26,226 | 289 | over_weight_cap (98%) |
| P-REBASE | 0 | 0 | 0 | 0 | 0 | - |
| E-EXTEND | 613 | 823,931 | 613 | 0 | 0 | E-EXTEND addition fails opposite-sector commutation (100%) |

C6: 622 parents

| family | parents asked | domain | derived | usable | parents with a usable child | dominant blocker (share of blocked) |
|---|---|---|---|---|---|---|
| C-DELETE-CHECK | 622 | 171,920 | 171,920 | 152,587 | 503 | weight_one_logical (99%) |
| E-PEEL | 622 | 398,612 | 22,461 | 14,184 | 317 | E-PEEL unique-touch fails: q is not in exactly one displayed Z-row (49%) |
| E-PUNCTURE | 622 | 199,306 | 199,306 | 150,712 | 503 | weight_one_logical (84%) |
| E-GRAFT | 622 | 398,612 | 372,107 | 28,629 | 336 | over_weight_cap (93%) |
| P-REBASE | 216 | 133,520 | 133,520 | 8,270 | 60 | over_weight_cap (90%) |
| E-EXTEND | 622 | 399,234 | 1,030 | 35 | 32 | E-EXTEND addition fails opposite-sector commutation (100%) |

## Reading

- Deletion and puncture apply almost everywhere. 84 percent of the 850,421
  single deletions and 70 percent of the 1,002,327 punctures give a usable child;
  3,009 and 2,822 of the 3,529 parents have at least one. What blocks the rest
  is a child with a weight-1 logical (distance 1), 100 and 83 percent of the
  blocked candidates. The usable share grows with n: deletions 42 percent at
  n <= 50, 88 percent at 201 to 500; punctures 11 to 76 percent.
- Peels need a qubit of column weight 1 in their sector, and that precondition
  is exact: 2,432 parents have such a qubit, 2,064 have a usable peel, and no
  usable peel occurs without one. Only 8 percent of the 2,004,654 peel
  candidates derive at all; the unique-touch premise refuses the rest, split
  evenly between the two sectors.
- Grafts derive almost always (94 percent) and are almost never usable (8
  percent): the child is heavier than its parent 93 percent of the time. The
  same for rebases below n = 100: 3.9 percent of 918,892 mixes usable, 98
  percent of the blocked over the cap, and only 11 of 1,121 parents have a
  rebased child lighter than the parent, each by one unit (w 21 to 20). A
  puncture, by contrast, leaves a lighter display for 142 parents
  (`469-192-11`: w 18 to 10), a deletion for 48, a graft for 62.
- Extension is closed on this board. Of 2,008,183 bounded additions, 4,779
  derive and 35 are usable, in 32 parents, every one a d = 1 placeholder
  (`14-7-1-b`, `15-6-1`, `27-12-1`, ...); the refusal is opposite-sector
  commutation, 100 percent of the blocked. This agrees with v0.1's 0 of 736
  strict `C-ADD-CHECK` improvements.
- 242 parents have no usable child in any family asked: 160 of them at
  n <= 50, 2 above n = 500. Their blockers are the small-code ones (every move
  leaves a bare qubit or a weight-1 logical) and empty graft and extend domains.

For the v0.2 pilots the direction asks about:

- Campaign 2 (delete chains into k-heavy cells, C2, 1,154 parents): deletion
  is usable for every parent and 94 percent of candidates, puncture for 1,132
  parents. The moves apply; whatever limited that campaign was downstream of
  applicability (distance after the chain, dominance, dedup).
- Campaign 3 (weight shedding by rebase and graft, C3, 1,158 parents): with
  the cap at the parent's weight, rebase was usable for 8 of the 98 parents it
  was asked for and graft for 328 of 1,158, with 100 percent of the blocked
  candidates over the cap. The moves do not shed weight in one step; the
  campaign failed on applicability, not on search.
- Campaign 4 (puncture and peel chains from n >= 500, C4, 613 parents):
  puncture is usable for all 613 parents and 84 percent of candidates; peel
  for 289 parents and 2.9 percent of candidates. Puncture chains apply
  everywhere in the pool; peel chains are confined to the parents with
  column-weight-1 qubits.
- Campaign 6 (sector-swap rebalance, C6, 622 asymmetric parents): the swap is
  not a report family, but the deletions that follow it are usable for 503 of
  the 622 parents and 89 percent of candidates; the 35 usable extensions on
  the board all sit in this pool, on its d = 1 members.

Caveats. "Usable" is search control: a child passes the screens (no bare
qubit, no weight-1 logical, connected, within the cap) and nothing is said
about its distance beyond that. The report is single-step; a chain can open
what one step cannot. The cap at the parent's weight counts any heavier
child as blocked, which is the reading the weight-class cells want but not
the only one.

## What the next searcher should know

- The C3 question with the cap relaxed to the next weight class, to measure
  how much weight a rebase or graft child adds rather than whether it stays
  under the parent's; and the same families after an `E-LOCAL-HADAMARD`
  rebalance, which the report does not cover.
- Depth-2 chains on C2 and C4: the single-step table says the first move
  applies; the second move's applicability on the children is the number the
  v0.2 campaigns actually needed.
- The 242 dead parents are a stop-list for the planner (`result-readings.json`,
  `dead_parents`); 240 of them are below n = 500.
- Cost model for the library: without `P-REBASE` the report costs about
  0.35 s per qubit (343 s at n = 996); with it the row mixes dominate from
  n = 150 on. A `families=` argument on `move_applicability_report` would let
  a consumer ask for one family without paying for the rest.
