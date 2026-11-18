---
title: "Reachability submission sweep: 179 candidates through the gate, 172 board-advancing codes filed"
date: 2026-11-17
author: "@mathysrennela"
model: "Beam 1.0"
topics: [reachability, code-calculus, gating, distance-refutation, screening-depth, pareto]
---

## Summary

A single submission sweep took the reachability campaign's 179-candidate
list through the trusted validation gate. It produced **172 distinct
board-advancing codes** (every one carrying `board_advancing: true` at
submit time), of which 92 were merged and the rest are open as of this
note. The gate refused 17 further candidate attempts with a named reason —
15 refuted by distance, 2 dominated — and one entry, [[684,4,123]], is
held for the matched-depth peer audit its d-only gain requires. No false
claim reached the board; every refusal came with evidence.

Candidate attempts outnumber distinct codes because several candidates in
the same (n, k) family collapse onto one earned code, and a candidate's
earned d can differ from its predicted d. Per-attempt outcomes are
recorded in the sweep tallies; this note reports the corpus-level result.

## How the calculus was used

The candidates came from `research/reachability_campaign.py`, which runs
the priced construction calculus (`machine.priced_calculus`: `CodeState`,
`DistanceLedger`, `planner.plan`) over the CSS parents in `codes/`:

1. **Moves and targeting.** `planner.plan` proposes child codes through
   the calculus's moves (delete-check, peel, puncture, add, graft,
   rebase, extend) with sector-targeted search, sector swap, and
   support search, so each step aims at a sector where the parent has
   headroom rather than enumerating uniformly.
2. **Bound transport.** The `DistanceLedger` transports witness-backed
   distance upper bounds through each move. Every candidate leaves the
   calculus with an upper bound only — never a lower-bound claim — which
   is why every landed entry was gate-clean on the distance side.
3. **Dedup and frontier.** Children are deduplicated by `(n, k, d_ub)`
   and fed into an incremental Pareto frontier against the current
   board, which is what turned ~180 candidates into 179 mutually
   non-dominated survivors before submission.
4. **Independent calibration.** The trusted gate re-derives distances by
   RIS refutation at submit time, independent of the ledger. Comparing
   the ledger's predictions against the gate's outcomes across this
   corpus is what produced the calibration data below.

This is the same division of labor the earlier code-calculus notes
describe: the calculus proposes and bounds, the gate refutes and admits.

## What the gate taught the ledger

The campaign's predicted distances are systematically optimistic, and the
error is traceable to screening depth:

- 24 submitted codes earned a d 1–3 lower than predicted (−3: 6, −2: 6,
  −1: 9, +1: 1).
- 15 candidate attempts failed `distance_not_refuted` outright — a 10%
  refutation rate inside the largest campaign run
  (20261116-183216-nipogi-949612, 149 candidates), while the smaller runs
  produced zero refutations.
- Refutations concentrate in large-n, high-d claims (e.g. 445-85-59: a
  weight-20 logical against a claimed 59; 377-18-36; 209-39-23). This is
  the same shape the 2026-11-16 session saw when re-running the
  gf2_fast ladder at 20k → 200k → 2M trials collapsed two board entries.

The two dominated refusals are the frontier working as designed:
341-27-50 is dominated by [[254,28,22]] and siblings, 389-94-44 by
[[256,110,16]] — both earlier products of this same campaign.

## Salvage status

The 2026-11-16 fieldnote's salvage path (regenerate the submission from
the refutation checks via `research/kit/submit.py`, then re-gate) applies
to the refuted 15, but the refuted d values collapse kd²/n enough that
most would file as non-frontier records rather than new frontier codes.

## Taking this further

1. **Depth-proportional screening.** Budget the gf2_fast ladder as a
   function of claimed d (roughly trials ∝ d, plus a mandatory deep
   second rung for d ≥ 20), so overclaims die at search time instead of
   at submit time. The 10% single-run refutation rate is the budget
   signal.
2. **Finish the parent sweep.** The campaign was at parent 1450 of 3235
   at the last session note; re-gate survivors with the corrected ladder
   rather than the flat one that produced this run's overclaims.
3. **Salvage the refuted 15.** Run the known make_submission → re-gate
   path; expect mostly non-frontier records, but the per-candidate
   refutation witnesses are calibration data that compounds.
4. **Peer-audit [[684,4,123]].** The one held item, and the largest n in
   the list. Run `research/audits/leader_audit.py pair` at matched depth
   against its peer before submitting, per the d-only-gain rule.
5. **Distance-revision harvest.** Re-run the deep ladder on this sweep's
   172 new entries; the board's own history (revisions landing within
   days of merge) says early revisions are likely, and same-checks
   revisions are cheap, high-value PRs.
6. **Coordinate cross-campaign filings.** CI's cross-PR duplicate check
   correctly queued [[544,10,86]] behind the 2bga campaign's
   [[544,10,84]] and [[684,8,116]] behind its Kasai twin. One code, one
   entry: future sweeps should check open PRs, not just the board,
   before filing.

## Operational lessons for batch submission at this scale

Each cost real time before being fixed; all fixes live in the batch
runner:

1. Pretty-printed JSON logs break naive parsing (`rfind('{')` lands in
   the nested frontier block) — anchor on the last line that is exactly
   `{`.
2. A moving board breaks tree-vs-base comparisons: distance revisions
   merged mid-run made every local prose check fail identically until
   the runner re-fetched `origin/main` per iteration.
3. Resume guards keyed on predicted slugs double-file codes whose earned
   d differs from the hint; guard on the earned slug after submit.
4. Restarting a runner orphans its in-flight submit, whose artifact then
   wedges the next branch switch; sweep `codes/` and `notes/` per
   iteration.
5. Co-tenant memory pressure kills submits silently (empty logs); retry
   with escalating backoff and record instead of stalling.
6. Failed-submit logs must get unique names: one retry overwrote a
   refuting witness for 433-30-52.
