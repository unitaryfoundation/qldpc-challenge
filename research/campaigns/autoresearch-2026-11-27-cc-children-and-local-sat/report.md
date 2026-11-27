# autoresearch-2026-11-27-cc-children-and-local-sat: single-step code-calculus children of the week's new CSS entries, and weight-4 d = 3 SAT rungs in the thin 2D-local cells

## What was asked

Two directions in one unattended session, each against the board-advancing
rule of AGENTS.md (a candidate counts when no entry in its track cell is at
least as good on n, k, d, and check weight). Direction A: the single-step
children (C-DELETE-CHECK, E-PUNCTURE, E-PEEL, E-GRAFT) of the 32 CSS entries
added to codes/ between 2026-11-24 and the board commit, enumerated by the
code-calculus planner and screened at the reachability campaign's
depth-proportional budget. Direction B: bounded 2D-local SAT rungs
(research/local_sat.py through research/sat_rungs.py) for weight-4 codes at
d = 3 in the single-layer and bilayer cells where the board was thin.
Definition: `research/campaigns/autoresearch-2026-11-27-cc-children-and-local-sat/campaign.json`.
Budget: 600 candidates screened, 3 wall-clock hours.

## What was spent

30.3 wall-clock hours summed over eight parallel workers and the SAT probes
against 3 declared (the code-calculus screen's large-n tail ran far past its
intended bound, see the follow-up); 290 candidates screened of 600. No
stopping condition fired; the session ended when the last probe returned.

## What ran

`summary.json` carries the snapshot (board commit e43a53888, clean tree) and
the discovery block: the 32 parent slugs with the sha256 of each parent's
bytes at that commit, the planner pinned to code-calculus-dev commit
830767f96aa3, and the funnel. Screens: gf2_fast information-set trials at
6,000 (d = 2 parents) to 840,000 (n = 276 at d = 14) per child plus a 1,500 to
3,000-trial NumPy pass on the side the accelerator does not report, seed 1127.
SAT: CaDiCaL 1.9.5 through python-sat, 3,000,000 conflicts per rung (2,000,000
for the last three), 15 to 45 minutes of wall clock each. Gate:
verify/validate_candidate.py through research/kit/coordination.py on every
staged candidate. No manifest: nothing from this run is submitted.

## What was tried

Direction A: 23,465 children planned from 32 parents in 247 s; 6,865 dropped
before screening because the board dominates them even at the planner's
optimistic distance bound; 119 undominated points; 290 children screened
(at most 4 per point, 20 per parent, 4 for parents above n = 300). Every one
of the 290 came in below the planner's bound: 173 by one, 72 by two to nine,
and the punctures of the n >= 370 parents by 19 to 81, and 160 of them,
every child of the twenty d = 2 pair-partition parents, screened to d = 1.
95 were dominated at the screened d, 22 by a sibling in the batch, 13 staged
and gated. Direction B: 21 rungs, listed one per row under the summary's
experiments with their conflict counts.

## Survivors

All 18 gate-passed candidates are board-advancing with an empty
`dominated_by`; none is on the board, and none has been submitted.

Direction B, exact d = 3 by the kit's certifier (evidence, not a board
certificate), max check weight 4:

| code | class | beats |
|---|---|---|
| [[25,5,3]] | local-2d-single, radius 4.0 | 30-4-3, 30-5-1, 30-5-2, 34-4-3, 34-5-1, 34-5-2, 36-4-3, 36-5-1, 36-5-2, 37-5-3 |
| [[36,6,3]] | local-2d-single, radius 4.0 | 36-4-3, 36-5-1, 36-5-2, 37-5-3, 37-6-1, 43-6-2, 44-6-3, 48-6-3, 50-6-3 |
| [[49,7,3]] | local-2d-single, radius 4.0 | 49-7-2 (d only; matched-depth audit credible at 1,000,000 trials, seeds 51 and 52), 50-6-3, 51-7-3 |
| [[32,6,3]] | local-2d-bilayer, radius 3.606 | nothing: a frontier extension |
| [[50,10,3]] | local-2d-bilayer, radius 5.657 | nothing: a frontier extension |

Direction A, unrestricted, screening-depth upper bounds (the gate's own
refutation pass at these sizes was short, so the submission path's
2,000,000-trial pass is the real test of the d values):

| point | w | copies | move | parent | advances on |
|---|---:|---:|---|---|---|
| [[255,73,7]] | 8 | 1 | E-PUNCTURE | 256-68-12-b | d, k, n |
| [[256,69,8]] | 8 | 3 | C-DELETE-CHECK | 256-68-12-b | d, k, n |
| [[275,103,10]] | 12 | 2 | E-PUNCTURE | 276-98-14-b | k, n |
| [[127,41,4]] | 8 | 1 | E-PUNCTURE | 128-36-6 | tie |
| [[127,36,5]] | 8 | 2 | E-PEEL, E-GRAFT | 128-36-6 | tie |
| [[275,105,9]] | 12 | 1 | E-PUNCTURE | 276-98-14-b | tie |
| [[511,137,7]] | 8 | 3 | E-PUNCTURE | 512-132-16 | tie |

## Negative results

The twenty d = 2 pair-partition parents have no single-step child at d >= 2:
all 160 screened to d = 1 at 6,000 trials. Every E-PUNCTURE child of a parent
with n >= 370 lost more than half its distance. The weight-4 d = 3 SAT ladder
is satisfiable in under 11 minutes at 5x5, 6x6, 4x4x2, and 5x5x2 at
G = ceil(0.8 n / 2) generators per side (one G higher at 7x7), and walls at
3,000,000 conflicts from 8x8 and 6x6x2 up; the weight-8 t = 2 rungs at the
counting limit walled at 5x5, 6x6, and 7x7; the one satisfiable t = 3 rung
(4x4x2 G = 14) produced only direct sums. The summary's negative_results
carry each rung with its assumptions and the change that would reopen it.

## Follow-up

The four rungs that would each be board-advancing if satisfiable and walled
only at 2,000,000 to 3,000,000 conflicts are 8x8 G = 27 ([[64,10,3]]), 9x9
G = 34 ([[81,13,3]]), 6x6x2 G = 30 ([[72,12,3]]), and 7x7x2 G = 41
([[98,16,3]]); a 20,000,000-conflict rerun is the next step. The
code-calculus screen should cap its NumPy side pass or skip parents above
n = 400: at n ~ 680 the 1,500-trial side pass took tens of minutes per child
and was most of the overrun. The planner's bound on the n >= 370 punctures
was off by 19 to 81, so a puncture of a large parent is not worth a screen
until the planner's distance model accounts for it.
