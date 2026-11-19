---
title: "Code-calculus rules: useful, valid, and board-advancing at 412/811"
date: 2026-11-19
author: "@mathysrennela"
model: "Beam 1.0"
topics: [code-calculus, rules, validity, board-advancing, pareto]

Sources: qldpc-challenge (this repo) for board data; code-calculus-dev on
github.com for the machine implementation and pinned replay.
---

## Summary

An audit of every board entry in `codes/` whose provenance attributes it to
the code-calculus (construction text or per-code note mentioning "code
calculus" / "priced calculus" / "construction calculus" / a named rule).
Result: **811 verified codes, of which 412 (50.8%) are board-advancing** (on a
per-cell Pareto frontier over `n, k, d, w`). The direct transformation rules
(`C-DELETE-CHECK`, `C-ADD-CHECK`, `E-PEEL`, `E-PUNCTURE`, `E-GRAFT`) account
for 515 of those codes and 225 of the board-advancing ones. The rules do
produce valid codes — all 811 pass `verify/qldpc_verify.py` with an earned
distance — but soundness remains unproved (Gates 2–7 unchecked) and every
distance is a witness-backed upper bound.

## Method

- Universe: all `codes/*.json` (3,686 entries) plus their `notes/*.md`.
- Calculus-attributed: construction contains "calculus"/"priced", or a rule
  token (`E-PUNCTURE`, `E-PEEL`, `E-GRAFT`, `C-DELETE-CHECK`,
  `C-ADD-CHECK`, `C-DIRECT-SUM`, `C-CSS`, `E-GLUE`, `E-EXTEND`,
  `E-LOCAL-HADAMARD`, `P-REBASE`), or the note mentions "code calculus" /
  "priced calculus" / "construction calculus" / "code-calculus".
- Validity: membership in `load_entries()` (trusted gate, `ok: true`, earned
  distance present). Board-advancing: membership in `compute_records()`
  (per-cell Pareto frontier over `n, k, d, w`).

## Counts

| Bucket | Codes | Board-advancing |
|---|---:|---:|
| All calculus-attributed | 811 | 412 (50.8%) |
| Direct rule tokens (sum) | 515 | 225 |
| Planner/greedy/search-derived (rest) | 296 | 187 |
| All board entries | 3,686 | 2,179 |

Per direct rule (construction field names the rule; mostly disjoint, 9 codes
name two tokens):

| Rule | Codes | Board-advancing |
|---|---:|---:|
| `E-PEEL` | 169 | 99 |
| `C-DELETE-CHECK` | 165 | 53 |
| `E-PUNCTURE` | 125 | 46 |
| `C-ADD-CHECK` | 53 | 24 |
| `E-GRAFT` | 3 | 3 |

Rule-level lessons:

- **`E-PEEL` is the workhorse** — 169 codes, 99 board-advancing (58.6%).
  Peeling a check set reliably lands on a frontier cell.
- **`E-GRAFT` is small but perfect** — 3/3 board-advancing; the pinned
  replay's graft child is one of them.
- **`E-PUNCTURE` and `C-DELETE-CHECK`** carry volume (125 and 165 codes)
  but lower hit rates (36.8% and 32.1%): deletion-style moves strip
  structure and often produce dominated children.
- **`C-ADD-CHECK`** (strict improvement) is rarer (53) but a third of its
  outputs (24) advance — consistent with Proposition 18.3 killing
  minimum-weight classes rather than blind addition.
- **`P-REBASE` (3 codes) produced 0 board-advancing** entries; the
  remaining rare rules (`C-CSS` 3/3, `C-DIRECT-SUM` 18/11, `E-GLUE` 94/37,
  `E-EXTEND` 8/1, `E-LOCAL-HADAMARD` 4/1) are too small to read a rate from.

## Validity check

Every one of the 811 codes is in `load_entries()` with `ok: true` and an
earned distance — zero failed the trusted gate. The pinned replay
(`machine/experiments/issue21_challenge_replay.json`, commit `9d30c66a`)
records a check addition, a row-space graft and a two-step deletion chain,
each with `challenge_verifier: {ok: true, failed_checks: []}` and earned
upper-bound distances. `machine/test_priced_calculus.py` (104 tests) and
`machine/test_pinned_replay.py` pass on the dev side.

## What did not work / limits

- **Soundness is not established.** Gates 2–7 are unchecked; hand derivations
  are evidence, not machine-checked proof. `unavailable` is withheld by
  design, and exact post-deletion distances are not claimed. The 412
  board-advancing codes are witness-backed upper bounds, not proofs of
  optimality.
- **Prices are inputs.** The consumer checks structural consistency and input
  shape, not the truth of supplied lower bounds or exhaustive
  minimum-weight-class enumerations. A "board-advancing" result is a
  Pareto-frontier claim under verified parameters.
- **Board-advancing ≠ globally optimal.** Distances are `upper_bound` tier
  unless a maintainer runs `verify/certify.py`; certification beyond the
  envelope (d ≤ 13, k ≤ 12) is out of reach.
- **Planner attribution is noisy.** 165 codes say only "derived by the
  code-calculus planner from a CSS parent" in their note while their
  construction is "Generalized bicycle" etc. They are counted as
  calculus-attributed but are search/planner products, not single-rule
  transforms; the 515 explicit-token count is the clean "rule created this"
  figure.
- **Attribution overlap.** Some notes name several rules in a chain; the
  note-level counts in the table are not additive with the explicit-token
  table.

## Implication for future searches

The rules are worth using as *generators* feeding the trusted gate, not as
oracles: ~51% of calculus-attributed codes advance a frontier cell, and
`E-PEEL` in particular is a high-yield move. But treat every staged distance
as a hypothesis the witness must confirm (the ledger's optimistic bound
over-claims; see the k-gap fieldnote), and never report a slug's distance
without reading `distance.X.value` / `distance.Z.value`. Soundness and price
truth remain separate, open obligations.
EOF
echo "written"; wc -c fieldnotes/2026-11-19-code-calculus-rules-evaluation.md