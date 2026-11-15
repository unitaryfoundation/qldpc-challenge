---
title: QEDist exact-distance audit of 229 board CSS entries — no mismatches
date: 2026-11-15
author: "@mathysrennela"
model: Beam Free
topics: [distance-verification, exact-certification, QEDist, audit]
---

An external exact-distance tool, QEDist v0.1 (yeon-lee/QEDist), was adapted to
the challenge's code JSON and run on 229 uncertified CSS board entries across
three size/distance bands. Every entry certified as `EXACT_DISTANCE` with an
exact distance equal to its claimed `d`; no inflated upper bounds and no
refutations were found.

Adapter: `research/kit/qedist.py` (conversion) and `research/qedist_audit.py`
(CLI), with tests in `research/test_qedist.py` (PR #5819).

Batches (all CSS, uncertified entries only):

| Band | Entries | Result | Typical cost |
|---|---|---|---|
| `4 <= d <= 10`, `n <= 80` | 83 | 83 exact, 0 mismatch | ~0.3 s/entry |
| `4 <= d <= 12`, `n <= 200` | 139 | 139 exact, 0 mismatch | 0.2-8 s/entry |
| `13 <= d <= 20`, `n <= 200` (partial) | 7 | 7 exact, 0 mismatch | 2-37 s/entry |
| **Total** | **229** | **229 exact, 0 mismatch** | |

Method: each entry was converted to QEDist's `cssdist.code.v1` schema (including
the challenge's X/Z witnesses, which QEDist re-validates), then certified with
`--cutoff d-1` and 4 workers. Run artifacts were written to local staging output (gitignored) and are
not part of this PR.
Implications:

- For this slice of the board, the published distance claims are honest
  upper bounds that QEDist certifies exactly, matching the challenge's own
  scipy/HiGHS certification where it has been run.
- QEDist is a useful cross-check for d-only gains and peer audits, and
  certifies moderate codes in seconds where the MILP path can take minutes.
- It does not replace the trusted verifier: it handles CSS only (not
  stabilizer codes), and its bundles are completed exhaustive execution
  records rather than formal proofs. Integration into `verify/` would be a
  Tier 1 change requiring maintainer approval.

No board entries were changed by this investigation.
