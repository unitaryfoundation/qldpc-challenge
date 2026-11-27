---
title: "Lower-bound campaign scalability: weak bounds above 2 are cheap, exact closure is not"
date: 2026-11-27
author: "@MathysRennela"
model: "unspecified"
topics: [certification, lower-bounds, tropidist, sat]
---

## Summary

A short hands-on pass over the lower-bound queue (issue #6192) to test whether
the existing tooling can produce certified lower bounds above 2 at scale. Result:
weak bounds (`d >= 3`) are cheap and parallelize well; exact closure and the
high bands (C/D) are not, and need the campaign's cluster budget.

## What was run

- Stabilizer (band P), `research/certs/tropidist_certify.py` via
  `research/certs/certify_sweep.py --backend tropidist`: 12 entries completed
  before stopping, including partials such as `d >= 9` and `d >= 8` at 300 s.
- Small CSS (band A), `verify/sat_certify.py` via the sweep with
  `--ladder 60 --tlim 120`: 3 entries certified exact in under 90 s total.
- A large band A entry (`371-136-11`) did not finish at 600 s, confirming that
  sequential single-machine sweeps stall on big instances.

## Findings

1. **Weak bounds are the scalable target.** Capping the ladder budget
   (`--ladder 60`) proves `W = 2` and stops, yielding `d >= 3` without paying
   for higher rungs. This keeps per-entry cost to minutes.
2. **Stabilizer entries are the best ROI.** tropidist closes them in seconds;
   172 are queued and can be cleared on a modest machine.
3. **Band A CSS is mixed.** Small instances close in seconds; large ones can
   exceed a 600 s ladder. Splitting by `n` and using short ladders helps.
4. **Bands C/D are not a laptop task.** Nothing certified on main resembles them;
   they need the Perlmutter-style 30-process runs.
5. **d = 1 placeholders must be skipped.** They produce a `W = 0` rung that the
   certificate schema rejects; the sweep now skips them as `d_one`.

## Recommendation

Use cluster job arrays with short ladder budgets for weak bounds, prioritize
band P and small band A, and leave C/D to the weekly route. Record every
attempt in `research/certs/attempts.jsonl` so the sweep does not reopen work.
