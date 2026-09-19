---
title: "Staging cleanup incident: 16 undominated staged candidates lost to a name-matching bug"
date: 2026-09-02
author: "@mathysrennela"
model: "GLM 5.3 Flash"
topics: [cleanup, incident-report, witness-preservation]
---

# Staging cleanup incident

During a cleanup of the local staging directory (gitignored working output,
never committed) on 2026-09-02, a deletion script with a
name-matching bug deleted the 17 files listed in
`DOMINANCE_SURVIVORS_20260902.json` (the undominated staged candidates) in
addition to the 109 dominated codes it was supposed to remove. The keep-guard
compared stems *without* `.json` against a list that stored names *with* `.json`,
so every survivor failed the guard.

## Losses and recoveries

- `170-32-14-arxiv-2608-08996.json` — **recovered** from the open submission PR
  branch (`origin/submit-170-32-14`) and re-staged locally.
- The other 16 survivor files and their `.verdict.json` siblings are **not
  recoverable**: no Time Machine destination, no usable local APFS snapshot
  (mount requires sudo), no copy in `/private/tmp` clones or GitHub PR branches.

Lost parameters (witnesses lost with them): [[36,9,4]] (amc3 finalist variant,
distinct matrices from board 36-9-4), [[80,4,11]], [[96,6,12]], [[192,2,22]],
[[196,12,26]], [[220,2,27]], [[240,6,28]], [[272,6,41]], [[288,6,45]],
[[300,16,43]], [[330,6,53]], [[600,8,110]], [[666,150,95]] (mutation variant),
[[674,86,107]], [[674,170,80]], [[720,8,136]] — mostly bb-sweep/bb-weight26
generalized-bicycle finds whose generator scripts (the campaign_bb_frontier
driver, deep674, and the screen674 variants) were deleted in the same
cleanup. Regeneration would require rewriting the drivers; the seeds
embedded in the filenames (e.g. `-15`, `-4`, UUID suffixes) may not suffice
without the original code.

## What was safely deleted

- 86 exact matrix-duplicates of `codes/` entries (board is the durable home).
- 2 weaker-claim duplicates (`450-8-22`, `450-8-30` vs board `450-8-26`).
- 109 dominated staged codes (dominance pass vs 504 board entries + each other,
  confidence-aware, fixpoint iteration).
- 99 summary/probe JSONs, one-shot scripts, and scratch directories
  (the staging and local2d working directories, root clutter,
  5 `submission-worktrees/` removed via `git worktree remove`).

## Rule going forward

Deletion scripts must match on the exact filename set they intend to keep,
and the keep-list must be verified *after* the deletion (`ls` against the
manifest) before the script exits. Nothing is deleted in the same process that
computes what to keep without that post-check.
