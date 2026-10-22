---
title: "Search-based exact distances for 12 board entries (d = 14 to 24): Crocker's Zenodo deposit bound to the board files, no certificate, no entry changes"
date: 2026-10-22
author: "@vprusso"
model: "Claude Fable 5.1 (Claude Code)"
topics: [exact-distance, exhaustive-search, evidence-tiers, sat-certification, zenodo-deposit]
status: active
---

Issue #3629 (@carsoncrocker) reports two exhaustive searches that find no logical
lighter than the listed d on 14 board entries and asks how that evidence should be
recorded. Two of the 14 have since closed in the SAT tier: 420-8-14 at level solver
(#3901) and 280-8-15 at level proof_log (#3666). This note records the other 12 the
way fieldnotes/2026-10-13-bb360-12-exhaustive-d24.md records 360-12-24: computational
evidence outside the board's certification tiers. No entry's distance, confidence, or
certification status changes.

Source: Zenodo, DOI 10.5281/zenodo.23423011 (Carson Crocker, published 2026-10-16,
CC BY 4.0), one file, release_qcodes_board.zip, md5 c0402c1a8abae88a53dad17d0f663e40
as Zenodo lists it, sha256 prefix 7e13549dca989b2b. The deposit covers 27 codes; the 12
below are its board entries.

## Binding to the board files

Checked 2026-10-22 against main at e94f70c5 with numpy and the rank routine in
verify/gf2.py, without running any code from the deposit:

- Nine records are the board's check lists verbatim, identical row sets on both sides,
  and carry the board's own witnesses: 432-4-23, 420-4-22, 420-6-16, 432-8-15,
  454-8-17, 316-8-16, 192-20-16, 210-26-14, and 510-16-24 (its record under the
  deposit's iceberg510/data is a copy of codes/510-16-24.json).
- Three records are two-block abelian builds from the source paper's polynomials:
  246-4-22, 310-10-22, 312-8-22. After the column permutation the deposit stores under
  data/equivalences, the X row spaces agree and the Z row spaces agree with the board
  file (no X/Z swap). Their witnesses are valid weight-d logicals of the deposit's
  build.
- n, k, and d agree with the board file in all 12.

## What the deposit shows

Both programs run the anchored connected-cluster search of Dumer, Kovalev, and Pryadko
with orbit anchoring after Rowshan and Devitt, at W = d - 1 on each side, and report
that no nontrivial logical of weight at most W exists. Program 1 is Python/numba;
program 2 is C, written by a separate agent without sight of program 1. For 510-16-24
both run at W = 22, and weight 23 is excluded by parity (every column of H_X and H_Z
has weight 3). There program 1 ran on a two-polynomial presentation of the code,
A = {0, 46, 82} and B = {0, 159, 165} on Z_255, mapped onto the board matrices by a
permutation the deposit stores under logs/board510, and program 2 ran on the board's
check lists. Seconds per side, from the deposit's logs/SUMMARY.md (510-16-24 summed
over its chunked logs):

| entry | d | max column degree | program 1 X / Z (s) | program 2 X / Z (s) | program 1 nodes X / Z |
|---|---|---|---|---|---|
| 510-16-24 | 24 | 3 | 1,152 / 1,231 | 1,658 / 1,565 | 4.35e8 / 4.38e8 |
| 432-4-23 | 23 | 3 | 1,994 / 1,845 | 512 / 1,156 | 8.28e8 / 8.37e8 |
| 420-4-22 | 22 | 3 | 454 / 429 | 290 / 403 | 3.36e8 / 3.24e8 |
| 246-4-22 | 22 | 3 | 421 / 421 | 950 / 986 | 2.50e8 / 2.53e8 |
| 310-10-22 | 22 | 3 | 371 / 373 | 797 / 646 | 1.40e8 / 1.45e8 |
| 312-8-22 | 22 | 3 | 486 / 474 | 587 / 592 | 1.85e8 / 1.84e8 |
| 454-8-17 | 17 | 3 | 666 / 470 | 467 / 256 | 3.34e8 / 2.45e8 |
| 420-6-16 | 16 | 3 | 2 / 2 | 1 / 1 | 7.4e5 / 8.0e5 |
| 316-8-16 | 16 | 6 | 275 / 1,061 | 305 / 1,273 | 1.13e8 / 4.07e8 |
| 192-20-16 | 16 | 4 | 29 / 28 | 79 / 76 | 1.41e7 / 1.39e7 |
| 432-8-15 | 15 | 3 | 1 / 1 | 0 / 0 | 2.8e5 / 2.8e5 |
| 210-26-14 | 14 | 4 | 5 / 2 | 3 / 4 | 5.2e5 / 5.1e5 |

## Limits

- One method, two implementations. The programs share the code definitions, the nauty
  orbits, the minimal-support argument, the anchoring scheme, the nontriviality test,
  the operator, and the AI tooling. A flaw in the method would affect both. No method
  from another family (SAT with a checked refutation, MILP dual bound,
  Brouwer-Zimmermann) has closed any of the 12.
- No proof artifact. Each lower bound is the claim that a search tree was exhausted,
  and nothing a checker can replay. Program 2's first version used a pruning bound that
  assumed column degree at most 3 and, on 192-20-16 at W = 16, reported none where a
  weight-16 logical exists. Version 2 uses the true column degree, and the three board
  entries with heavier columns (192-20-16, 210-26-14, 316-8-16) rest on version 2
  reruns. The deposit's quick_check.sh carries a positive control at W = d. A pruning
  error at lower weight that both programs share is not excluded.
- The deposit's reviews were by AI systems only. This note adds the binding check
  above and no rerun of the searches.

## Certificate status

- SAT tier reach on main (1,119 certificates at solver or proof_log): the largest
  certified d is 19 (361-1-19), every certificate at d >= 17 has k <= 2, and the
  largest k at d = 16 is 36 (302-36-16, 320-36-16).
- The October 2026 Perlmutter run (#3663 to #3667; verify/sat_certify.py with --proof,
  2,400 s per solve) covered the six entries here with n <= 400. Both paths timed out
  on both sides for 192-20-16, 210-26-14, 246-4-22, 310-10-22, and 312-8-22. For
  316-8-16, CryptoMiniSat closed the Z side UNSAT in 1,372 s while the proof path timed
  out, and the X side timed out on both paths. Crocker's runs at 3,600 s per solve
  timed out on all 12 (#3629).
- A rerun of all 12 plus 288-12-18 and 360-12-24 at 28,800 s per solve, same script
  and proof path, is queued on one Perlmutter CPU node as Slurm job 60124398 (36 h
  wall, submitted 2026-10-22, repo at e94f70c5). Anything that closes arrives as a
  certs/ PR. The d = 14 to 17 entries are the plausible closes; the d >= 22 entries are
  outside anything the tier has closed so far.

## Implication for searches

For these 12 entries the listed d is, on this evidence, the true distance, so a
distance-tightening search on them is expected to return nothing. A lighter witness on
any of them would refute a completed exhaustive search and should be reported on #3629
as well as filed as a revision, after re-measuring at matched depth
(research/audits/leader_audit.py pair). The entries stay at upper_bound until a
certificate exists.
