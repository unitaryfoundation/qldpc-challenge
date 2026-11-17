---
title: "Reachability campaign session: distance revisions, failed fills, and re-gating"
date: 2026-11-16
author: "@mathysrennela"
model: "Beam 1.0"
topics: [reachability, distance-revision, gating, code-calculus, pareto]
---

## Summary

A session on the reachability campaign and surrounding tooling. The campaign
itself (research/reachability_campaign.py) is healthy and progressing (idx 1450/3235,
~8.4 parents/min, ETA ~3.5h at session end). The highest-value outputs were
two distance revisions found by re-running the gf2_fast ladder on existing
board entries, plus a clear (negative) result on cheap d>=2 fills.

## What worked

### Distance revisions (2 PRs)

Re-running `verify/gf2_fast.distance_rand_witness` at 20k -> 200k -> 2M RIS
trials on two reachability-campaign children collapsed their Z-side bounds:
- `[[209,43,16]]` -> `[[209,43,15]]` (found weight-15 at 200k; 2M confirmed)
- `[[287,34,34]]` -> `[[287,34,30]]` (found weight-30 only at 2M)

Both are same-checks revisions of existing entries, submitted as PRs #5824 and
#5825. The X sides did not improve (22 and 37 respectively).

### Passing d>=2 submissions (4 PRs)

After regenerating refuted candidates from their checks (make_submission) and
re-gating, only 4 codes passed the gate as board-advancing d>=2:
- `[[145,18,8]]` (reachability) — PR #5827
- `[[33,10,2]]`, `[[38,17,3]]`, `[[70,48,2]]` (cc-d1-replace) — PRs #5828-5830

## What did not work (and why)

### Cheap d>=2 fills for missing n's

All 352 missing n's are >=86. The parity-check construction `[[n,n-2,2]]`
has check weight n, and the 7-cycle construction has weight ~0.57n. The
verifier caps max check weight at 32 (standard) / 8 (n>700). Every candidate
was rejected by preflight (`schema_valid (weight)`). **0 of 350 fills succeeded.**
Filling missing n's requires a bounded-weight (<=32) d>=2 search, not a
one-line construction.

### Code-calculus reductions as d>=2 producers

`cc_find_miss2.py` (C-DELETE-CHECK / E-PEEL / E-PUNCTURE on d>=2 parents)
produced 256 candidates, but the gate refuted all of them to d=1 (0 passed
as d>=2). The reductions remove structure and lower distance. They are useful
for d=1 gap-fillers, not d>=2.

### C-ADD-CHECK lifting d=1 -> d>=2

Enumerated all admissible added checks (max_weight 4, then 8) on 56 small
d=1 codes: 16,812+ checks, 0 survivors. A single added check almost never
eliminates every weight-1 logical.

## Re-gating matters

The board grew (2 revisions) between the first gating pass and the re-gate.
58 of 95 "ready" candidates were reclassified as dominated. Always re-gate
before promoting; stale verdicts overstate board-advancing status.

## Tools used

- `verify/gf2_fast` (distance_rand_witness) for the ladder.
- `research/kit/coordination.py gate` for verdicts.
- `research/kit/submit.py` (--reuse-witnesses, --fast-trials 200000).
- `verify/check_prose.py`, `verify/prepush_prose_check.sh`.

## Reproduction

Campaign: `uv run --extra research python -u research/reachability_campaign.py --resume`
Ladder: `PYTHONPATH=verify python -c "import gf2_fast; ..."` at 20k/200k/2M trials.
Gating: `uv run --extra research python research/kit/coordination.py gate <candidate>`.
