---
title: "code-calculus v0.2 greedy gated campaigns: 20+ distinct board-advancing points from C-DELETE-CHECK, E-PEEL, E-PUNCTURE"
date: 2026-11-12
author: "@MathysRennela"
topics: [code-calculus, priced-calculus, greedy, sector-swap, board-advancing, deletion, peel, puncture]
---

# code-calculus v0.2 greedy gated campaigns

This note records the first board-advancing output of the v0.2 greedy
campaigns that compose the calculus's three productive moves with the new
sector-targeted search, sector swap, support search, and Pareto ranking.

## What was run

Two campaigns, both driven by research/campaigns/cc-run-campaign-greedy-2026-11-11/run.py
on CSS parents from codes/:

- cc-greedy-gated (n <= 10, 3 steps, budget 16): 38 board-advancing
  candidate files, 20 distinct (n, k, d) points.
- cc-greedy-ext (n <= 28, 3 steps, budget 32): 215 board-advancing
  candidate files, 170 distinct (n, k, d) points. Stopped at n = 28.

Total across both runs: 253 board-advancing candidate files, 177 distinct
(n, k, d) points.

Excluding the submitted points, the remaining staged candidates number 243
files / 174 distinct points. Their Pareto frontier is 96 distinct
(n, k, d, w, cell) points (112 files); ignoring the locality cell, 51
distinct (n, k, d, w) points (63 files) are mutually non-dominating.

14 of these frontier points were submitted as PRs (5385, 5391, 5395-5407),
all verified board-advancing against the base board. The remaining 82 were
not submitted (downgraded, colliding, or not yet attempted).

## n <= 20 re-run (corrected script, staged deep-verify)

Re-ran the greedy campaign with the staged deep-verify enabled (2k -> 20k ->
200k -> 2M trials, stopping early on downgrade). Result: 182 candidates
gated, 68 finds, 0 downgraded, 6 refused (collisions / d-only gains). All
68 survived the deep pass without distance correction.

However, all 30 non-colliding-screened survivors turned out to have slugs
that collide with existing board entries after the deep pass, so no new
submissions resulted from this run. The deep pass kept the distance unchanged
but the (n,k,d) point was already occupied. This is the variant-collision
case, not inflation.

Net: the corrected pipeline prevents inflated distances (0 downgrades) but
the board is now dense enough that most surviving points are variants of
existing entries rather than new slugs.

Each step calls machine.planner.plan with sector_targeted=True (target
sector chosen per parent by infer_target_sector), sector_swap=True
(E-LOCAL-HADAMARD at T=Q), support_search (bounded witness search to
tighten the ledger), and ranking="pareto" with domination pruning. The
top non-prune survivor is applied with apply_operation, exported via
export_challenge_entry (witness-backed upper bounds only), and validated
with verify/validate_candidate.py through coordination.gate_and_record.
Only gate-passing candidates are counted.

## Moves involved

The candidates are 1-3 step compositions of:

- C-DELETE-CHECK
- E-PEEL
- E-PUNCTURE
- occasional E-LOCAL-HADAMARD sector swap

## Distinct advancing points (n <= 10 run)

(5,3,1), (6,3,1), (7,5,1), (8,4,2), (8,5,1) x3,
(8,6,1) x4, (9,2,3) x2, (9,3,3) x2, (9,4,2),
(9,6,1) x5, (10,3,3) x5, (10,4,2), (10,4,3) x4,
(10,4,4), (10,6,1), (10,7,1), (11,3,3), (11,3,4),
(11,4,3), (12,6,2).

## What did not work

- cc-sector-swap-css alone (n <= 200): 0 board-advancing; every gated
  child was an exact duplicate or a refutation.
- cc-strict-addition-css: 0 feasible strict improvements across ~1,159
  admissible supports (n <= 20), consistent with v0.1's 0/736.
- cc-glue-css: 0 successful glues in the probe (seam certificate not
  satisfiable without a proper seam enumerator).

## Reproduction

    QLDPC_RUN_ID=cc-greedy-gated uv run --extra research \
      python research/campaigns/cc-run-campaign-greedy-2026-11-11/run.py \
      --n-cap 10 --steps 3 --budget 16

Staged survivors are gitignored working output (local staging only); the
campaign definition is research/campaigns/cc-run-campaign-greedy-2026-11-11/campaign.json.

## Final submission results

The n <= 60 unrestricted greedy campaign (corrected script, staged
deep-verify) produced 166 deep-verified finds. After full-gate verification
(distance_not_refuted with fresh seeds), 216 of 542 candidates passed and
168 were board-advancing, of which 135 had new (non-colliding) slugs.

All 135 were submitted (one PR per code). As of the final tally:
- 169 merged by maintainers
- 19 closed (collisions or dominated)
- 10 still open (5487-5498)

The 2D-local campaign (n <= 99) produced 99 deep-verified finds. After
full-gate verification, 153 of 593 checked candidates passed but 0 are
submittable: distance_not_refuted (fresh-seed refutation) rejects all of
them. The multi-seed deep-verify (issue #409) reduced but did not
eliminate inflation. The 2D-local route remains blocked on distance
verification. See code-calculus-dev issues #375, #388, #409.

## Campaign summary table

| Campaign | n-cap | Gated | Deep-verified finds | Full-gate PASS | Board-advancing | New slugs |
|---|---|---|---|---|---|---|
| cc-greedy-gated | 10 | 65 | 38 | 29 | 20 | 3 (5-3-1, 6-3-1, 9-4-2) |
| cc-greedy-ext | 28 | 286 | 215 | - | 170 distinct | 14 submitted |
| cc-greedy-n20 | 20 | 182 | 68 | - | 47 | 0 (all collide) |
| cc-greedy-n60 | 60 | 1281 | 166 | 216 | 168 | 135 |
| cc-greedy-n61-100 | 100 | 339 | 28 | 12 | 12 | 12 (5579-5590) |
| cc-greedy-2dlocal-v2 | 99 | 1567 | 99 | 153+ | 153+ (unverified) | 0 submitted |

Total merged to the board: 169 codes (unrestricted, d=1/d=2).
Issues opened: code-calculus-dev #375, #388.

## n = 61-100 unrestricted greedy extension

The unrestricted greedy pipeline was extended past the n <= 60 sweep with
the staged deep-verify kept on. Of 339 gate-called candidates, 28 passed
the gate, 16 of those were refused or collided at the deep-verify stage
(variant/collision slugs), and 12 survived as board-advancing new slugs,
each from a 3-step chain off one of four parents:

| Parent | Chain produced |
|---|---|
| 64-34-2 | 64-35-2, 64-36-2, 64-37-2 |
| 68-36-2 | 68-37-2, 68-38-2, 68-39-2 |
| 72-39-1 | 69-50-1, 70-48-1, 71-44-1 |
| 76-40-2 | 76-41-2, 76-42-2, 76-43-2 |

All 12 were submitted as one-code PRs (#5579 to #5590) with the rule
named in the PR title. The deep pass produced 0 downgrades; the 12 are
9 d=2 points and 3 d=1 points.

## Issues opened

- code-calculus-dev #375: staged distance checks and auto-variant naming
- code-calculus-dev #388: layout inheritance violates site_occupancy
- code-calculus-dev #430: 2D-local distance inflation follow-up
- code-calculus-dev #431: E-GLUE seam enumerator / row-id minting
- code-calculus-dev #432: exporter/run_campaign auto-variant + staged deep-verify
- code-calculus-dev #433: default screening depth for d >= 2

## Lessons learned

1. A 1000-trial RIS screen overestimates distance for many codes; the
   2M-trial deep pass corrects it downward, turning screened
   board-advancing points into dominated ones. Board-advancing status must
   be checked on the corrected distance, not the screened one.
2. Greedy multi-step composition (C-DELETE-CHECK, E-PEEL, E-PUNCTURE with
   sector swap and Pareto ranking) is the productive route; sector-swap
   alone, strict C-ADD-CHECK, and E-GLUE produced nothing at tested sizes.
3. Using --force on submit overwrites existing codes when a downgraded slug
   collides. Variant suffixes (e.g. 10-7-1-d) are required for same
   (n,k,d) codes.
4. d-only gains require a matched-depth peer audit (research/AUTORESEARCH.md
   section 5b) before submission.

## Suggested improvements

- Code calculus: add a staged distance check to the ledger (try increasing
  trial counts until the claimed distance is reached or refuted) and a
  confidence field on witnesses, so transport can distinguish screened from
  deep bounds.
- Sweep scripts: deep-verify every gate-passing candidate before staging;
  skip candidates whose corrected distance differs from the screened one;
  never use --force; auto-append variant suffixes on slug collision.
- Increase default screening depth for d >= 2 candidates, or filter by a
  minimum trial count before claiming board-advancing.
