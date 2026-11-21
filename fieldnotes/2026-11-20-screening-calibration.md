---
title: "Calibrating the depth-proportional screening budget: a 2k to 2M trial RIS ladder over 59 landed reachability codes and 5 refuted candidates (issue #6196)"
date: 2026-11-20
author: "@vprusso"
topics: [reachability, screening-depth, distance-refutation, calibration, gating]
---

Issue #6196 asks for data behind the screening budget PR #6195 introduced in
`research/reachability_campaign.py`: `screening_trials(d)` is 2,000 plus
2,000 per unit of claimed d, with a mandatory deep rung of 200,000 plus
20,000 per unit of d once d reaches 20, capped at 2,000,000 trials per side.
The defaults were a first estimate. This note replays the witness search at
fixed rungs over the labeled corpus the 2026-11-17 sweep produced
(`fieldnotes/2026-11-17-submission-sweep.md`) and reads the budget curve off
the result.

## Method

Each entry ran `research/audits/leader_audit.py ladder` with rungs of 2,000,
20,000, 200,000, and 2,000,000 random-information-set trials on seeds 11,
12, 13, and 14, pair depth 64, four threads, through the gf2_fast backend
(`verify/gf2_fast.cpp`). The tool searches both Pauli sides each trial and
re-validates every witness against the raw matrices before recording it.
For each entry the record is the lightest weight found by the end of each
rung, the first rung at which the search reached the claim (found a logical
of weight at most the claim), and the first rung at which it beat the claim.
The claim is the board's d for a landed entry and the submitted d for a
refuted candidate. Pair depth 64 was chosen because the affine two-block
ladders behind this board's large entries used 24 to 80 and the tool's
default of 10 under-reads them (`research/audits/README.md`); a control at
depth 10 is reported below where it matters.

The corpus has two parts.

- 59 landed codes, a stratified sample of the 176 board entries whose notes
  name the reachability campaign, by block length (at most 200, 201 to 400,
  above 400) and claimed d (below 10, 10 to 19, 20 to 29, 30 and above),
  proportional to the strata.
- The 5 candidates the trusted gate refuted in CI during that sweep, taken
  from the closed pull requests #6154, #6152, #6146, #6138, and #6068. The
  fieldnote's count of 15 refused attempts includes refutations by the local
  gate whose candidate files never reached the repository; those are not in
  this corpus.

The run took 10.7 hours of wall time at four threads per entry and three
entries at a time on a machine shared with other jobs (median 9.5 minutes
per entry, maximum 25), so the per-entry seconds in the record are not
comparable across entries.

## Results

Landed codes, first rung at which the search reaches the board's d:

| claimed d | entries | 2,000 | 20,000 | 200,000 | 2,000,000 | never |
|---|---|---|---|---|---|---|
| below 10 | 33 | 33 | | | | |
| 10 to 19 | 13 | 7 | 4 | 2 | | |
| 20 to 29 | 8 | 2 | 1 | 5 | | |
| 30 and above | 5 | | 1 | 1 | | 3 |

By block length: all 10 entries with n at most 200 reach the claim at
2,000; of the 35 with n from 201 to 400, 25 reach it at 2,000, 2 at 20,000,
6 at 200,000, and 2 never; of the 14 above 400, 7 at 2,000, 4 at 20,000,
2 at 200,000, and 1 never.

Against the current defaults, 5 of the 59 landed claims are not reached
within `screening_trials(d)`: two in the 10 to 19 band that need the
200,000 rung while the default gives 30,000 and 40,000 (`301-138-18` at
d 14, `341-61-40` at d 19; both names carry the predicted distance, see
issue #7108), and the three the ladder never reaches at any rung (d 42, 33,
and 39 at n 347, 395, and 465). For those three the best weights found at
2,000,000 trials sit 4 to 6 above the claim, so no budget in this range
would have let a screen reproduce the gate's d; their witnesses came from
the construction, not from search, and a screen that fails to reach them
says nothing about them (the `inconclusive` verdict, which is never
corroboration).

One landed entry was beaten: the 2,000,000 rung on the entry filed as
`433-2-59` (d 41 on the board) found a Z-logical of weight 40, filed as a
distance revision in PR #7118.

Refuted candidates:

| candidate | submitted d | 2,000 | 20,000 | 200,000 | 2,000,000 | first rung below the claim |
|---|---|---|---|---|---|---|
| `433-68-59` | 59 | 17 | 17 | 17 | 17 | 2,000 |
| `409-2-68` | 68 | 58 | 58 | 58 | 58 | 2,000 |
| `353-4-29` | 29 | 27 | 27 | 27 | 27 | 2,000 |
| `287-31-38` | 29 | 29 | 29 | 29 | 26 | 2,000,000 |
| `287-34-36` | 26 | 26 | 26 | 26 | 26 | holds |

Three of the five over-claims die at the first 2,000-trial rung of the
gf2_fast ladder, including the two gross ones (59 against a weight-17
logical, 68 against 58), and a control at pair depth 10, the campaign's own
setting, also refutes `433-68-59` to 17 and `353-4-29` to 28 at 2,000
trials. One over-claim, `287-31-38`, needed the 2,000,000 rung to come down
from 29 to 26; the default budget for d 29 is 780,000, between the rungs
this ladder has, so whether it would have caught it is not decided here.
`287-34-36` holds at its submitted 26 (the pull request title carried the
predicted 36) and was closed for other reasons.

The campaign's screen is not this ladder: it is
`research/kit/surrogate.lightest_logical`, a pure NumPy random-information-set
search at pair depth 10, run at a flat 2,000 trials per side when the sweep
was made (PR #6195's curve came after). Re-running that search on the five
with ten seeds at 2,000 trials and four at 20,000 gives the miss probability
of a single screening seed:

| candidate | submitted d | seeds refuting at 2,000 | best at 2,000 | seeds refuting at 20,000 | best at 20,000 |
|---|---|---|---|---|---|
| `433-68-59` | 59 | 5 of 10 | 17 | 4 of 4 | 17 |
| `409-2-68` | 68 | 1 of 10 | 65 | 4 of 4 | 65 |
| `353-4-29` | 29 | 4 of 10 | 27 | 4 of 4 | 27 |
| `287-31-38` | 29 | 0 of 10 | 34 | 0 of 4 | 34 |
| `287-34-36` | 26 | 0 of 10 | 36 | 0 of 4 | 32 |

So at the flat 2,000 trials a single seed missed the gross over-claims
with probability one half to nine tenths, which is the 10% refutation rate
the sweep saw, and at 20,000 trials every seed catches them. The NumPy
search never reaches 29 on `287-31-38` at either budget (its best is 34),
where the gf2_fast backend reaches 26 at 2,000,000 trials; the margin cases
need the compiled backend, not more NumPy trials. The sweep notes' record of
"seeds [0], []" with one side's seed list empty is still worth a look in
the runner, since a side screened on no seed is screened at zero trials.

## What the curve says about the defaults

- Below d 10 the base of 2,000 is enough: every landed entry in the band
  is reached at the first rung.
- Between d 10 and 19 the base plus 2,000 per unit (22,000 to 40,000) misses
  2 of 13 landed claims that need the 200,000 rung. Lowering
  `DEEP_RUNG_MIN_D` from 20 to 10, so that the deep rung of 200,000 plus
  20,000 per unit applies from d 10, reaches both; this PR makes that the
  default. The cost is about 400,000 trials per side at d 10, which the
  gf2_fast backend runs in well under a minute on codes this size.
- From d 20 to 29 the existing deep rung (600,000 to 780,000) covers every
  landed claim, which all reach by 200,000.
- At d 30 and above the data cannot set a budget: two of five reach by
  200,000 and three are unreachable at 2,000,000. The cap stays.
- Gross over-claims are a single-seed-at-2,000-trials failure of the NumPy
  screen, not a shortfall of the curve: 20,000 trials catches every one of
  them on every seed, and PR #6195's curve already gives at least 22,000
  from d 10. The cheap place to catch them earlier is the gf2_fast
  pre-filter that runs before the NumPy screen is paid for: `GF2_TRIALS`
  moves from 2,000 to 20,000 in this PR, which the compiled backend runs in
  seconds. The margin cases (one to three units above the truth, as
  `287-31-38` and the two landed entries that needed 200,000) are the
  curve's job, and the one that needed 2,000,000 is beyond the NumPy
  search at any budget tested.

## Limitations

The landed sample is 59 of 176, and the refuted set is 5 rather than the
15 the sweep refused, so the refutation half of the curve rests on few
points. On the ladder, seeds were fixed per rung and not varied, so a rung that
misses a claim says one seed missed it; the seed-variation table above
covers the refuted five with the campaign's own search but not the landed
codes. The timing figures come from a shared machine and are not
throughput numbers.

## Reproduction

The corpus is the set of entries whose note names the reachability
campaign, sampled as described, plus the five code files in the closed
pull requests above. For one entry:

    uv run --extra research python research/audits/leader_audit.py ladder codes/<slug>.json \
        --ladder 2000:11 20000:12 200000:13 2000000:14 --pair-depth 64 --threads 4 \
        --witness-out <dir>/<slug>.witness.json

The per-entry record is the rung table below; the driver, the sample, and
the raw records are local run output and are not committed.

## Per-entry rung table

Lightest weight found by the end of each rung; "reaches claim at" is the
first rung whose best is at most the claim.

| entry | n | claim | 2k | 20k | 200k | 2M | reaches claim at | verdict |
|---|---|---|---|---|---|---|---|---|
| `287-34-36` (refuted candidate) | 287 | 26 | 34 | 32 | 31 | 26 | 2,000,000 | holds |
| `287-31-38` (refuted candidate) | 287 | 29 | 34 | 34 | 33 | 26 | 2,000,000 | refuted (lighter than the claim at 2,000,000) |
| `353-4-29` (refuted candidate) | 353 | 29 | 27 | 27 | 27 | 27 | 2,000 | refuted (lighter than the claim at 2,000) |
| `409-2-68` (refuted candidate) | 409 | 68 | 67 | 64 | 61 | 58 | 2,000 | refuted (lighter than the claim at 2,000) |
| `433-68-59` (refuted candidate) | 433 | 59 | 17 | 17 | 17 | 17 | 2,000 | refuted (lighter than the claim at 2,000) |
| `69-53-2` | 69 | 2 | 2 | 2 | 2 | 2 | 2,000 | holds |
| `70-56-2` | 70 | 2 | 2 | 2 | 2 | 2 | 2,000 | holds |
| `75-38-1` | 75 | 1 | 1 | 1 | 1 | 1 | 2,000 | holds |
| `82-56-2` | 82 | 2 | 2 | 2 | 2 | 2 | 2,000 | holds |
| `88-47-2` | 88 | 2 | 2 | 2 | 2 | 2 | 2,000 | holds |
| `88-67-2` | 88 | 2 | 2 | 2 | 2 | 2 | 2,000 | holds |
| `91-15-1` | 91 | 1 | 1 | 1 | 1 | 1 | 2,000 | holds |
| `96-51-2` | 96 | 2 | 2 | 2 | 2 | 2 | 2,000 | holds |
| `99-50-1` | 99 | 1 | 1 | 1 | 1 | 1 | 2,000 | holds |
| `145-18-8` | 145 | 8 | 8 | 8 | 8 | 8 | 2,000 | holds |
| `209-57-7` | 209 | 7 | 7 | 7 | 7 | 7 | 2,000 | holds |
| `209-10-15` | 209 | 15 | 15 | 15 | 15 | 15 | 2,000 | holds |
| `209-42-20` | 209 | 16 | 20 | 16 | 16 | 16 | 20,000 | holds |
| `209-10-21` | 209 | 20 | 20 | 20 | 20 | 20 | 2,000 | holds |
| `227-94-6` | 227 | 6 | 6 | 6 | 6 | 6 | 2,000 | holds |
| `255-197-1` | 255 | 1 | 1 | 1 | 1 | 1 | 2,000 | holds |
| `255-125-7` | 255 | 7 | 7 | 7 | 7 | 7 | 2,000 | holds |
| `263-73-7` | 263 | 7 | 7 | 7 | 7 | 7 | 2,000 | holds |
| `263-4-27` | 263 | 25 | 28 | 26 | 25 | 25 | 200,000 | holds |
| `277-14-4` | 277 | 4 | 4 | 4 | 4 | 4 | 2,000 | holds |
| `287-16-15` | 287 | 15 | 15 | 15 | 15 | 15 | 2,000 | holds |
| `287-6-28` | 287 | 27 | 27 | 27 | 27 | 27 | 2,000 | holds |
| `299-10-28` | 299 | 25 | 26 | 26 | 25 | 25 | 200,000 | holds |
| `301-141-20` | 301 | 14 | 18 | 14 | 14 | 14 | 20,000 | holds |
| `301-138-18` | 301 | 14 | 16 | 16 | 14 | 14 | 200,000 | holds |
| `305-204-1` | 305 | 1 | 1 | 1 | 1 | 1 | 2,000 | holds |
| `319-67-1` | 319 | 1 | 1 | 1 | 1 | 1 | 2,000 | holds |
| `319-65-2` | 319 | 2 | 2 | 2 | 2 | 2 | 2,000 | holds |
| `319-87-9` | 319 | 9 | 9 | 9 | 9 | 9 | 2,000 | holds |
| `341-61-40` | 341 | 19 | 20 | 20 | 19 | 19 | 200,000 | holds |
| `347-2-54` | 347 | 42 | 55 | 51 | 48 | 46 | never | inconclusive |
| `359-155-2` | 359 | 2 | 2 | 2 | 2 | 2 | 2,000 | holds |
| `359-153-3` | 359 | 3 | 3 | 3 | 3 | 3 | 2,000 | holds |
| `369-53-1` | 369 | 1 | 1 | 1 | 1 | 1 | 2,000 | holds |
| `371-137-9` | 371 | 9 | 9 | 9 | 9 | 9 | 2,000 | holds |
| `371-136-11` | 371 | 11 | 11 | 11 | 11 | 11 | 2,000 | holds |
| `371-130-18` | 371 | 15 | 15 | 15 | 15 | 15 | 2,000 | holds |
| `375-192-3` | 375 | 3 | 3 | 3 | 3 | 3 | 2,000 | holds |
| `375-102-5` | 375 | 5 | 5 | 5 | 5 | 5 | 2,000 | holds |
| `377-131-2` | 377 | 2 | 2 | 2 | 2 | 2 | 2,000 | holds |
| `377-24-15` | 377 | 15 | 15 | 15 | 15 | 15 | 2,000 | holds |
| `377-12-32` | 377 | 26 | 28 | 27 | 26 | 26 | 200,000 | holds |
| `389-70-48` | 389 | 17 | 17 | 17 | 17 | 17 | 2,000 | holds |
| `389-73-46` | 389 | 23 | 49 | 47 | 23 | 23 | 200,000 | holds |
| `395-10-59` | 395 | 33 | 60 | 57 | 52 | 39 | never | inconclusive |
| `407-221-2` | 407 | 2 | 2 | 2 | 2 | 2 | 2,000 | holds |
| `407-216-7` | 407 | 7 | 7 | 7 | 7 | 7 | 2,000 | holds |
| `417-10-6` | 417 | 6 | 6 | 6 | 6 | 6 | 2,000 | holds |
| `427-23-67` | 427 | 19 | 19 | 19 | 19 | 19 | 2,000 | holds |
| `429-22-4` | 429 | 4 | 4 | 4 | 4 | 4 | 2,000 | holds |
| `429-77-56` | 429 | 19 | 55 | 19 | 19 | 19 | 20,000 | holds |
| `431-4-23` | 431 | 22 | 23 | 22 | 22 | 22 | 20,000 | holds |
| `433-61-1` | 433 | 1 | 1 | 1 | 1 | 1 | 2,000 | holds |
| `433-2-59` | 433 | 41 | 56 | 44 | 41 | 40 | 200,000 | refuted (lighter than the claim at 2,000,000) |
| `437-22-22` | 437 | 20 | 21 | 21 | 20 | 20 | 200,000 | holds |
| `445-93-53` | 445 | 19 | 55 | 19 | 19 | 19 | 20,000 | holds |
| `453-2-35` | 453 | 32 | 33 | 32 | 32 | 32 | 20,000 | holds |
| `465-134-39` | 465 | 39 | 52 | 50 | 46 | 43 | never | inconclusive |
| `469-197-6` | 469 | 6 | 6 | 6 | 6 | 6 | 2,000 | holds |
