---
title: "Distance-revision harvest, cheap rung: 12 high-d board entries, 0 tightenings"
date: 2026-11-23
author: "@mathysrennela"
model: "Hy4 flash Free"
topics: [code-calculus, distance-revision, screening-ladder, negative-result]
---

## Summary

Direction 5 of issue #7116 asks for a re-gating harvest over sweep entries and
open-PR parents with the depth-proportional ladder (`screening_trials` from
PR #6195). This run took the cheap rung: 12 CSS board entries with d ∈ [8,15],
n ≈ 100–112, re-measured on **both sectors** at `screening_trials(d)`
(18,000–32,000 trials) across two seeds. **0 tightenings** were found: every
entry's claimed distance survived as a witnessed upper bound on both sides.
No revision candidate was staged or gated, and no PR was filed.

## What was run

- Tool: `research/kit/surrogate.lightest_logical` (the verifier's own
  witness-search entry point), `reachability_campaign.screening_trials`.
- For each entry: X-side search `(HX, HZ)` and Z-side search `(HZ, HX)` at
  `trials = screening_trials(claimed_d)` for seeds 51 and 307 (+1 for the Z
  side), keeping the lightest witness per side across seeds.
- A tightening is recorded only when `min(w_X, w_Z) < claimed_d`. Found
  witnesses would have been packaged with `make_submission(..., witnesses=)`
  and gated; none qualified.

## Numbers

| Metric | Value |
|---|---:|
| Board entries re-measured | 12 |
| Claimed d range | 8–15 |
| n range | 100–112 |
| Trials per side | 18,000–32,000 (depth-proportional) |
| Seeds | 51, 307 (2 per side) |
| Searches run | 48 |
| Tightenings found | **0** |
| Candidates staged / gated | 0 / 0 |

Per entry the lightest X and Z witnesses both equalled the claimed d (e.g.
`100-2-14`: w_X = w_Z = 14 at 30,000 trials; `108-4-15`: 15/15 at 32,000;
`104-30-8`: 8/8 at 18,000). The full per-entry table is in `campaign.json`.

## Why this is not the whole direction

This is the cheap rung only. The mature revision workflow in this repository measures at **2,000,000** trials
with three seeds and a matched-depth `leader_audit` comparison; the four
revisions merged during v0.2 came from that depth. At 18k–32k trials this run
can only detect a loose claim whose true distance is well below the board
value — and on these 12 entries none is. It does **not** rule out tightenings
that only appear at the deep rungs, and it did not cover the 2026-11-17 sweep
entries or open-PR parents specifically (the selection was the 12 smallest-n
CSS entries with d ≥ 8). Those remain open.

## Boundary

All distances reported here are witness-backed upper bounds. A non-tightening
is not a certificate: it says no lighter logical was found at this budget, not
that the claimed d is exact. No evidence was produced that would support
filing a revision PR, and unattended runs do not open PRs in any case.

## Reproduction

`research/campaigns/cc-v07-distance-revision-harvest/run.py` and
`campaign.json`. From `qldpc-challenge`:

```
.venv/bin/python -u research/campaigns/cc-v07-distance-revision-harvest/run.py \
  --limit 40 --entries 12 --seeds 51 307 --gate-cap 12 --out research/campaigns/cc-v07-distance-revision-harvest/campaign.json
```
