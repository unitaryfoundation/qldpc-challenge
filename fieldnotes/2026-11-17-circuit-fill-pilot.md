---
title: "Circuit-filling pilot: 25 first tiers from 50 entries"
date: 2026-11-17
author: "@mathysrennela"
model: "Beam 1.0"
topics: [circuits, scheduling, pilot]
---

## Summary

A pilot of the circuit-filling campaign: run `research/circuit_autogen.generate` on
50 CSS entries (n <= 200) that had no circuit tier, stage the results, and
promote the survivors. Outcome: **25 of 50 (50%) produced a verifiable first
circuit tier**, all promoted as individual PRs (#6203-#6227). The other 25 hit
structural limits (mechanism/file caps or no claim within the clamp).

This follows the earlier Proxima-guided scheduling work (#6150): that note
covered improving existing circuit tiers; this one covers donating first tiers
to entries that had none.

## Pilot design

- Sample: 50 entries drawn stratified by family from the 946 eligible entries
  (CSS, no circuit tier, n <= 200).
- Generator: `research/circuit_autogen.generate(doc, rounds=d, seed=0,
  max_candidates=2, seconds=60)`.
- Each candidate verified with `verify/circuit_verify.py`; survivors staged under
  `research/candidates/pilot-circuit-fill/<slug>/`.

## Results

| Outcome | Count |
|---|---|
| OK (verifiable first tier) | 25 |
| No claim within clamp | 10 |
| Mechanism cap exceeded | 10 |
| Verify fail | 2 |
| File cap exceeded | 1 |
| Error (MemoryError) | 1 |

Representative survivors: `21-2-6` (d_circ 6), `67-6-5` (5), `46-8-7` (7),
`72-36-2` (2), `96-12-9` (9). Full list and PR numbers in the session log.

## Cost

~4 h wall clock for 50 entries (~5 min/entry). At that rate the full 946-entry
eligible pool is ~80 h, with an expected ~50% success rate before filtering.

## Filter recommendation

Tighten the bulk-campaign filter to `n <= 120` and `d <= 12`. The pilot's
failures were dominated by high-round (>= 15) and large (>= 150 qubit) entries
hitting the 135k-mechanism / 12 MB file caps or finding no claim within the
clamp. A tighter filter should push the OK rate well above 50%.

## Proxima status

The pilot used the existing `two-block` and `generic` schedule families. A
Proxima-style proximity scorer (DEM-level min-weight completion, monomial
permutation search for bicycle codes) is still unbuilt. The gating experiment
remains a bake-off: proximity ranking vs. RIS screening on the same entries and
budget. If proximity wins, invest in the port; otherwise the current families
are sufficient for baseline fill.

## Tools

- `research/circuit_autogen.py` (`generate`), `verify/circuit_verify.py`,
  `verify/check_authorship.py`
- Model: Beam 1.0
