---
title: "Reachability campaign pipeline: discover, stage, and track Pareto-optimal codes in one pass"
date: 2026-11-15
author: "@mathysrennela"
model: "Beam 1.0"
topics: [reachability, parentage, pareto, pipeline, code-calculus]
---

## Summary

A unified campaign script (`research/reachability_campaign.py`) that collapses
the old two-step workflow — `analyze4.py` (reachability analysis) followed by
`route_a_recover.py` (parentage recovery) — into a single parallelised pass.
In one run over the CSS parents it (1) derives child codes via the code-calculus
planner, (2) saves each new `(n, k, d)` child as a full submission document
(matrices + parentage), (3) tracks an incremental Pareto frontier, and
(4) checkpoints after each chunk for crash recovery.

The key inefficiency in the old workflow was that the analysis ran the planner,
recorded only parameter tuples, then threw away the matrices and parentage.
Route (a) then re-ran the same planner to recover them — redundant work that
only reproduced ~40 of 285 Pareto targets. The unified pass eliminates this
by saving matrices and parentage during the initial analysis.

## What was searched

- **Parents:** all CSS codes in `codes/` with `n ≤ N_MAX` (default 1000),
  sorted by `n`. Configurable via `N_MAX`.
- **Planner:** `planner.plan(st, led, target=1, ...)` on each parent,
  deriving child codes via code-calculus transformations (glue, add-check,
  puncture, extend, etc.).
- **Children:** each child's `(n, k, d_ub, w, locality, weight-class)` is
  computed. Children whose `n` is in the missing set (not yet covered by any
  board code) are retained.
- **Dedup:** by `(n, k, d_ub)` across the entire run.
- **Parallelism:** multiprocessing across parents (default 4 workers).
  ~112 parents/min with 4 workers vs. ~1 parent/min single-threaded.

## Evidence trail

- The analysis proved 285 Pareto-optimal targets (mutual non-dominance among
  non-dominated children) from ~2231 parents.
- Route (a) (parentage recovery) reproduced ~119 of these by re-running the
  planner on parents with `n ≤ 400`.
- The unified pass aims to reproduce all reachable targets in a single pass,
  saving each as a staged candidate in the gitignored working-output directory.
- Each candidate is a full submission document (HX/HZ checks, distance witness,
  provenance). Gate validation (`coordination.py gate`) is still required
  before promotion.

## Dead ends

- **Route (b) (construction search):** BB/HP/LP/BP samplers produced 19 codes,
  none matching Pareto targets exactly. Speculative but useful for discovery
  outside the analysis's target set.
- **Exact (n,k,d) matching is rare:** the planner produces many children per
  parent, but only a few match a specific Pareto target. Dedup and the
  incremental Pareto filter keep this manageable.
- **Board growth invalidates domination:** codes non-dominated at analysis time
  may be dominated by newer board entries at gate time. The gate is the final
  arbiter.

## Tools

- Code-calculus planner (`machine.priced_calculus`, `machine.planner`).
- `research/kit/submit.make_submission`, `save_submission` for packaging.
- `research/kit/coordination.staging_dir`, `unique_path` for safe staging.
- Multiprocessing (`multiprocessing.Pool`) for parallelism.
- Checklist tracking (`pareto_checklist.json`) with file-based locking.

## Reproduction

```bash
# Full run (all parents n <= 1000):
uv run --extra research python -u research/reachability_campaign.py

# Resume from checkpoint:
uv run --extra research python -u research/reachability_campaign.py --resume

# Targeted (small n, more workers):
N_MAX=400 WORKERS=8 CHUNK_SIZE=50 uv run --extra research python -u research/reachability_campaign.py
```

Requires the `code-calculus` repository (set `CALCULUS=/path/to/code-calculus-dev`).
Checkpoint and outputs go to the directory given by `CKPT`/`OUT_REACH`/etc.
(defaults to a gitignored working directory under the repo).

## Pipeline stages (for reuse)

1. **Analyze + Stage** (this script): planner → children → save matrices + parentage → checkpoint
2. **Pareto tracking**: incremental frontier, checklist with found/gated/promoted/submitted
3. **Gating**: `coordination.py gate <candidate>` → `.verdict.json`
4. **Promotion**: `qldpc submit` or `promote.py` → `codes/` + note + PR body
5. **Prose check**: `check_prose.py` / `prepush_prose_check.sh`
6. **Submission**: `qldpc submit --open-pr` (human authorization required)

The script is reusable: run after each batch of new submissions (new parents
produce new children). Yield diminishes over time as the board saturates
(expected: ~100 codes first run, ~30-60 second, ~10-30 third, ~5-15 ongoing).