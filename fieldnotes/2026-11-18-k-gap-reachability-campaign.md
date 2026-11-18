---
title: "k-gap reachability campaign: 13 board-advancing fills and the ledger-optimism lesson"
date: 2026-11-18
author: "@mathysrennela"
model: "GLM-5.3-Flash"
topics: [reachability, k-gap, code-calculus, pareto, gating]
---

## Summary

A k-gap variant of the reachability campaign (the mode is added in PR #6495
to research/reachability_campaign.py, which until now staged only children
whose n was missing from the board): `TARGET=k` stages children that raise
k for an n already on the board instead. A stress run (n <= 20) and a full
run (n <= 100) produced 292 staged k-raising children, of which 13 survived
the trusted gate as board-advancing; each is filed as its own PR
(#6716, #6717, #6722, #6735, #6740, #6749, #6755, #6763, #6772, #6778,
#6779, #6780, #6781). The run's most useful output was not the codes but a
measurement of how badly the planner ledger's optimistic distance bound
over-claims, and how far the campaign's snapshot domination check diverges
from the gate.

## What worked

### The TARGET=k mode and the 13 survivors

1093 CSS parents with n <= 100 (WORKERS=2, CHUNK_SIZE=25, screening 500
RIS trials per side with gf2_fast pre-filtering) produced 292 children
whose k exceeds the current board maximum for their n. Trusted gating
(coordination.py gate, fresh-seed refute pass at 4.5k-5.3k RIS trials)
of the 23 with witnessed d >= 2 left 13 board-advancing entries: eleven
strictly advance at least one axis, two are pure frontier extensions.
The strongest is [[61,30,3]] (kd^2/n 4.43, advances k and n in
weight-9plus/unrestricted, PR #6716); [[98,54,2]] is the only one that
advances d itself (weight-8, PR #6781). All thirteen are d = 2-3
high-rate fills: the k-gap mode trades distance for rate by construction,
since the removal moves that raise k also strip structure.

### Witness-first reporting

After the first batch was found to be mis-described (see below), every
reported number was re-read from the staged documents' witness fields
rather than from staged slugs. The witnessed distance of a candidate is
the only claim the gate reads; the slug is decoration.

## What did not work (and why)

### The ledger's optimistic bound over-claims the slug

The campaign stages children under <n>-<k>-<d_ub>.json with d_ub from the
planner ledger. 264 of the 292 staged slugs over-claim relative to the
witness the staging search itself found: 222 of the 292 children witnessed
to d = 1 (deletion/peel raises k and strips structure in one move). The
four frontier codes of the stress run were first reported to the operator
as d = 3/2/2/2 from their slugs; all four are d = 1 by witness. Lesson:
read distance.X.value / distance.Z.value before reporting anything, and
treat the staged slug as a hypothesis the witness must confirm.

### Campaign snapshot domination diverges from the gate

The campaign's dominated() check compares against a board snapshot taken
at load time. [[15,10,3]] passed it as non-dominated and the gate then
named [[14,10,1]] as its dominator (both are d = 1; the snapshot predates
nothing relevant, the campaign's rule is just looser about the cell).
Conversely the gate dominated [[93,30,5]] (kd^2/n 8.06, the run's
headline by the ledger bound) with the existing [[80,32,6]], and
[[95,26,5]] with [[90,26,5]]. Ten of the 23 deeper candidates were
dominated. Always re-gate; the campaign's Pareto bookkeeping is a
scheduling heuristic, not a verdict.

### Process failures worth recording

The first submission batch failed twice before any PR opened: a stray
untracked file in codes/ broke the board loader and left the PR body's
frontier section as an unfilled placeholder that the prose pre-flight refuses, and the
drafted bodies cited a repro manifest the ./qldpc submit flow does not
write. Both were fixed by removing the stray file and writing per-code
research notes (notes/<slug>.md) that describe the recipe inline. A
cleanup step also deleted committed files under notes/ with a wildcard;
they were restored from HEAD within a minute. Wildcards on tracked
directories are banned in this workspace from now on.

## Reproduction

Campaign: `TARGET=k N_MAX=100 WORKERS=2 CHUNK_SIZE=25 TRIALS=500
GF2_TRIALS=500 uv run --extra research python -u
research/reachability_campaign.py` (mode added in PR #6495; the file on
main carries the n-targeting original). Gating per candidate:
`uv run --extra research python research/kit/coordination.py gate
<path>`. Submission per candidate: `./qldpc submit <candidate>
--authors @mathysrennela --model "GLM-5.3-Flash" --harness "OpenCode
agent harness" --family other --construction "code-calculus v0.3rc
k-gap fill" --note-file <note> --no-circuit --open-pr --base-ref
origin/main`.

## Tools

- Model: GLM-5.3-Flash; harness: OpenCode agent harness.
- unitaryfoundation/code-calculus-dev @ 74889f1 (planner.plan, v0.3.0).
- research/kit/surrogate.lightest_logical (witness screening),
  gf2_fast pre-filter (verify/gf2_fast.cpp), verify/validate_candidate.py
  via research/kit/coordination.py gate (verdicts).
- Compute: two workers, about 2 hours wall clock for the full run, plus
  23 gate runs at about 2 minutes each.
