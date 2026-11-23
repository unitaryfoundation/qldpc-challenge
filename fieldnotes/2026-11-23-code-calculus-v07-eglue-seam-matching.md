---
title: "Systematic E-GLUE seam matching: the enumerator works, but only cross-factor seams produce admissible children"
date: 2026-11-23
author: "@mathysrennela"
model: "Hy4 flash Free"
topics: [code-calculus, e-glue, seam-enumeration, board-advancing, negative-result]
---

## Summary

Direction 6 (formerly 7) of issue #7116 re-opens the v0.1 directions: stabilizer
parents, ledger lower-bound pruning, reverse search, and systematic `E-GLUE`
seam matching. This note runs the last of those. The v0.2 probe reported **0
successful glues** "because the seam certificate was not satisfiable without a
proper seam enumerator." code-calculus now exposes
`enumerate_seam_checks(left, right, max_size=3)`; using it over 40 pairs of
small CSS board parents produced **29,224 seams**, of which **14,426 span both
factors**, and **25 gate-passing children, 9 board-advancing** (2 distinct
`(n,k,d,w)` points, both d=1). The old zero is explained: the default
`max_size=3` yields **no cross-factor seams at all**, so every glued child is a
direct sum and the gate refuses it before distance.

## What was run

- Tool: code-calculus PR #624 worktree @ `6b02aba`, `enumerate_seam_checks`
  and `apply_operation({"op":"E-GLUE", ...})`; gated with the trusted gate.
- Parents: 24 CSS board entries, n ∈ [8,16]; 40 deterministic pairs. The right
  factor was shifted to a disjoint qubit namespace and its row ids re-minted
  with `relabel_identifiers` (E-GLUE refuses overlapping namespaces/used sets).
- Seam certificate `{"move_words":["U","U"], "evidence":...}`; one cross-factor
  seam per child, up to 3 per pair; `max_size=4`. Each child was staged with
  `make_submission` (8,000 witness trials), `save_submission(..., spec=)`, and
  gated. Dedup against board + open PRs (3,695 entries).
- Control run at `max_size=3`: 28 pairs, 4,744 seams, **0 cross-factor**, 0
  connected children — all refused as "not one code". At `max_size=4` the same
  pair type yields 30–136 cross seams.

## Numbers

| Metric | Value |
|---|---:|
| Pairs | 40 |
| Seams enumerated | 29,224 |
| Cross-factor seams | 14,426 (49.4%) |
| Children applied and validated | 120 |
| Derive failures | 0 |
| Duplicates (board + open PRs) | 0 |
| Gated (cap 25) | 25 |
| Gate `passed: true` | 25 |
| `board_advancing: true` | **9** |
| Distinct `(n,k,d,w)` among the 9 | **2** |
| Witnessed d among all gated children | d=1 (25/25) |
| d-only gains | 0 |

The two distinct points are `[[20,11,1]]` w=6 (from 10-4-1+10-8-1 and
10-4-2+10-8-1) and `[[20,12,1]]` w=6 (from 10-5-1+10-8-1). The nine staged
files have no exact fingerprint duplicates; three WL-signature overlaps mark
probable permutations. All were d=1, so none approaches the thin high-distance
cells. The 83 remaining children were not gated only because the 25-gate cap
was reached, not because they failed.

## The other three sub-items

- **Stabilizer parents / symplectic state model.** Already exercised: the
  v0.1 pilot (`research/campaigns/cc-stabilizer-parents-2026-11-05/`) used 54
  stabilizer parents and produced **176 board-advancing** children (240/248
  gated passed, 8 exact duplicates), from 172 E-PUNCTURE and 4 E-PEEL children.
  The board now holds **262 stabilizer entries** (n 5–761, d 2–86). Those codes
  are dominated by CSS entries at the same `(n,k)` because the two boards are
  ranked apart by rule — an occupancy fact, not a move failure. The machine
  side has `SymplecticState`, `SymplecticLedger`, and the `SYM-*` / `X-SYMPLECTIC-*`
  move set, but no `from_challenge` loader and no admitted calculus layer, so
  re-running it needs a document adapter rather than a new search.
- **Ledger lower-bound pruning for delete/peel/puncture.** Still unavailable,
  and correctly so: the transported lower endpoint is 0 for these moves, and
  supplying a nonzero bound would be a proof obligation, not a consumer
  shortcut. No script or fieldnote claims it done. The measured consequence is
  that reachability pruning removes only 5.4% of derivable children
  (`research/audits/cc_reachability.py`). This remains a code-calculus-dev
  obligation, not a campaign task.
- **Reverse search.** No design, script, or helper exists in either repo
  (grep for `reverse|inverse|unapply|backward` in `planner.py`, `sequence.py`,
  and all fieldnotes returns nothing relevant). The only "direction 6" prior
  art is a *forward* reachability prune from #4478. This is genuinely unrun and
  needs a design decision before a campaign can be specified.

## Boundary

One seam per child, `max_size=4`, parents n ≤ 16, 3 seams per pair, gate cap 25.
No multi-seam chains, no larger parents, no deep distance ladder, and no
promotion of any staged child. Every distance is a witness-backed upper bound.

## Reproduction

`research/campaigns/cc-v07-eglue-seam-systematic/run.py` and `results.json`.
From `qldpc-challenge` with `CODE_CALCULUS_PATH` at PR #624:

```
.venv/bin/python -u research/campaigns/cc-v07-eglue-seam-systematic/run.py \
  --n-lo 8 --n-hi 16 --parents 24 --pairs 40 --seams-per-pair 3 \
  --max-size 4 --gate-cap 25 --open-prs --out research/campaigns/cc-v07-eglue-seam-systematic/results.json
```

No PR was opened for any find; promotion remains a human decision.
