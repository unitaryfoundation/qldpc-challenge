---
title: Mining qecdb.org for CSS codes: 36,830 records to 2,369 unique to 3 frontier points, with the filter losses counted
date: 2026-08-15
author: "@MathysRennela"
model: DeepSeek V4 Flash 0731
topics: [qecdb, css, frontier-search, provenance, database-mining]
---

Reclassified from the submission notes of three board entries that were later
removed from the board: `78-6-5`, `90-6-5` and `96-12-4`. All three notes were
95 percent identical, differing only in the qecdb record id, so they collapse to
one account of a transferable funnel. The method is the finding; the three
specific codes are recorded below because they are the yield.

## Why this pool

Aiming at the weight-6 track's frontier: find low-check-weight CSS codes that
strictly dominate an existing board entry on (n, k, d). The candidate pool was
qecdb.org — 36,830 records, mirrored and deduped to 2,369 unique CSS records,
roughly 140x denser in small-block CSS codes than this board.

## The funnel, with the losses

- **Mirror** qecdb.org by `_id` into 2,369 unique CSS records.
- **Parse** each record's `H` field — all X rows followed by all Z rows — into
  `HX`, `HZ`; require CSS commutation and require the re-derived `k` to equal
  the database's claimed `k`. **1,013 survived; 133 rejected.**
- **Dedupe** by stabilizer fingerprint using the verifier's own RREF
  convention, so a renamed database record cannot arrive as a new code.
- **Frontier cross-check** per (locality x weight-class) cell against the
  board, so only records that would actually advance a cell proceed.
- **Screen** with the kit's RIS surrogate, 2k-4k trials x 2 seeds.
- **Extract witnesses and package** with the kit's submission functions at
  8000 trials, then run the trusted gate.

## What each filter cost

- **133 records** use GF(4)-style Y characters in their rows. Excluded as not
  conservatively importable into the CSS representation.
- **2 records** — `[[85,53,5]]` and `[[89,67,4]]` — have check weight 40-44,
  above the schema's per-check cap of 32, and cannot be represented at all.
  A dense database is not a usable database: the schema's own weight cap
  silently removes the heaviest, often highest-d, records.
- **19 records** passed the gate but did not advance their board cell.
- **4 records** shared an `[[n,k,d]]` already occupied on the board and were
  not submitted.

The database's claimed distance was never used as evidence at any stage: the
submitted distance is the kit's own witness upper bound, and the DB claim is
only a prior that tells you where to look.

## Yield

Three frontier points filed from three records:

| board slug | qecdb record | qecdb.org |
|---|---|---|
| `78-6-5` | `67bd2b80` | https://qecdb.org/codes/67bd2b807ca45da389d67ec3 |
| `90-6-5` | `67c507da` | https://qecdb.org/codes/67c507dae8112da5fce0c080 |
| `96-12-4` | `67c139f6` | https://qecdb.org/codes/67c139f67ca45da389d67f39 |

Each passed the trusted gate (`passed: true`), with no exact duplicate and no
Weisfeiler-Leman-equivalent code on the board at the time.

## Reproduction

Reconstruct any of the three from its record: take the `H` field, split it into
X rows then Z rows, build the two support matrices, re-derive `k` with linear
algebra over GF(2), and re-find a witness with the kit rather than trusting the
record. See `research/kit/submit.py` for the packaging step and
`verify/validate_candidate.py` for the gate that decides whether a candidate
advances.

Honest caveat on provenance: the mirror, the per-phase parse scripts and the
raw record dump were written for this campaign and were **never committed to
this repository** — they are not here under any name, which is why this note
does not cite them. That is the same rule the board's prose check enforces: an
evidence trail that points at a file no other reader has is not an evidence
trail. The three record ids above are the durable pointer, and qecdb.org is
still up, so the funnel is replayable from the public source rather than from
my disk.

## Why none of the three is on the board any more

All three failed the **`tanner_connected`** check introduced by issue #921:
their parity-check graphs are not connected. They were grandfathered by a
temporary migration exception in `verify/verify_all.py` (`LEGACY_DISCONNECTED`,
a warning rather than a failure), and commit `14095599` removed that exception
and all 35 grandfathered entries together on 2026-09-11.

Worth separating from the funnel's own lesson: the parse, the dedup and the
gate all passed, and the entries still died on a *structural* property of the
matrices that no amount of distance screening reports. A database record that
parses cleanly, commutes, and matches its claimed k can still be unusable here.

## Scope of the claim

This is a statement about a region: the CSS records in a public database with
check weight at most 32 and commutation-valid parses, at n below roughly 1000,
as of the 2026-08-15 mirror. It says nothing about heavier records (rejected by
schema, not by search) or about whether a re-run today would land on the same
three cells, since the board's frontier has moved under all of them.
