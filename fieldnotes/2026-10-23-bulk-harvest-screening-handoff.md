---
title: "Bulk arXiv harvest screening handoff (2026-10-23)"
date: 2026-10-23
topics: [literature, triage, arxiv-watch, screening, handoff]
author: MathysRennela
---

## Purpose

This note is a prompt/handoff for a follow-up agent. It points at two CSVs
produced by a full back-poll of the arXiv QEC query and asks that agent to
investigate whether the listed papers contain codes or code constructions
worth reconstructing.

## Source data

- Full poll: `research/arxiv_watch.py --days 13000` (all QEC-relevant papers
  since the start of arXiv). Ledger: `research/literature/arxiv-ledger.jsonl`
  (2,094 papers).
- Triage: `triage()` in `research/arxiv_watch.py`. `screened_in` is a
  hard-signal gate (family/structure term or an unattributed `[[n,k,d]]`),
  not a score threshold. `tier` is `strong` / `candidate` / `background`.
- A paper is "investigated" once it carries a `review` verdict in the ledger
  (`relevant` / `not-relevant` / `uncertain` with a non-empty `reason`).

## What to investigate

The snapshot CSVs produced at handoff time were session-local working output
and are deliberately not cited as evidence. The authoritative set lives in the
ledger; query it directly:

- `uv run --frozen python research/arxiv_watch.py --list relevant --full`
  (498 papers verdicted `relevant`, i.e. they introduce a code or code
  construction; these are the reconstruction leads)
- `uv run --frozen python research/arxiv_watch.py --list uncertain --full`
  (39 papers verdicted `uncertain`, possibly relevant; closer read needed)

Note: screening of the remaining unreviewed papers may still be in progress
when this note is used, so more `relevant`/`uncertain` verdicts can appear.
The CSVs are point-in-time snapshots. For the current, authoritative set,
query the ledger directly instead of (or in addition to) the CSVs:

- `uv run --frozen python research/arxiv_watch.py --list relevant --full`
- `uv run --frozen python research/arxiv_watch.py --list uncertain --full`

Each ledger row carries `claimed_params` and the verdict `reason`; the
abstract is one click away via the derived arXiv link.

Each row's `claimed_params` are unverified claims read out of the abstract
(see `research/literature/README.md`: state a claim as a claim).

## Task for the follow-up agent

For each paper in the two CSVs:

1. Read the abstract (fetch via arXiv API / the link in the ledger; the
   ledger stores only identity + tier + claimed_params, not the abstract).
2. Decide whether it actually introduces a reconstructable code/construction
   (not just a decoder, architecture, or analysis of an existing code).
3. If yes, check admissibility against `CONTRIBUTING.md` resource limits:
   `n <= 700`, or `n <= 1000` with max check weight `w <= 8` and claimed
   `d <= 40`.
4. Check the claim against the board: `./qldpc recent`, `codes/*.json`, and
   the track it would land in (`TRACKS.md`). Most admissible claims are
   already matched or dominated; then the construction, not the instance, is
   the lead.
5. Reconstruct the code from the paper and run
   `uv run --extra research python research/kit/coordination.py gate <path>`.
   Only `passed: true` makes it a find. Persist survivors through
   `research/kit/submit.make_submission` + `submit.save_submission` with a
   `spec=` when a recipe applies (see `AGENTS.md`).
6. Record or revise the verdict in the ledger with
   `research/arxiv_watch.py --review <id> --status ... --reason '...'`.
   A re-review moves the old verdict into `reviews`.

## Constraints (from AGENTS.md / AUTORESEARCH.md)

- No code is a "find" until the gate returns `passed: true`. Never write a
  private distance/quality check or edit `verify/`.
- In unattended autoresearch, candidates stay in the session-local staging
  area under `research/`; do not write to `codes/`, commit, or open a PR.
- That staging area is gitignored working output and must never be cited as
  evidence in a note or PR body.
- Every path cited in a note/PR body must resolve in the PR's own tree.

## Polling discipline (important)

Screening of the remaining unreviewed papers may still be in progress while
you work. New `relevant` / `uncertain` verdicts can be added to the ledger
at any time, and a paper you already processed could in principle be
re-verdicted (old verdict moves into `reviews`).

Therefore, **whenever you start a new task or pick up a new batch of papers,
re-poll the current state** rather than trusting a previously saved CSV:

1. Re-run the two ledger queries above (`--list relevant`, `--list uncertain`)
   and diff against your working set; add any new rows to your queue.
2. Rebuild the CSV snapshots from the live ledger if you need them on disk:
   `uv run --frozen python research/arxiv_watch.py --list relevant --full`
   (redirect to a file), or read `claimed_params`/`reason` straight from the
   ledger JSON.
3. Before recording your own verdict, re-check that the paper is still in
   its expected status (`unreviewed`/`uncertain`); if it has moved, reconcile
   rather than overwriting.

Treat the ledger as the single source of truth and the CSVs as disposable
caches.

## Suggested starting order

Sort the relevant leads by claimed `kd^2/n` and admissibility; prioritize
papers with small, in-range `n` and explicit constructions (pair-partition,
coset, lifted-product, bivariate/multivariate bicycle, Tanner, etc.). The
uncertain papers should be read first to resolve their status before any
reconstruction spend.

## Provenance

Produced by the bulk screening pass of 2026-10-23. The ledger holds the
verdicts (`relevant`/`not-relevant`/`uncertain`) and `claimed_params` for
every paper; this note is the handoff, not the evidence trail.
EOF
echo written