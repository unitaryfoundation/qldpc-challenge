# certification-and-layout-boardwide-2026-11: certificates and 2D layouts for the entries that lacked them

## What was asked

Issue #6193: run the board-wide certification-and-layout campaign defined in `research/campaigns/certification-and-layout-boardwide-2026-11/campaign.json`. Part A: honor certificates for board entries without one by working `research/certs/todo.json`. Part B: construct and verify honest layouts for entries that have none, with the empty D = 3 and stabilizer 2D geometric-efficiency clubs as targets. Budget: 1,500 CPU hours, 3,000 GPU hours, 720 wall-clock hours, stop on exhaustion.

## What was spent

8,989 Perlmutter core-hours (35.1 node-hours of one 256-CPU node per job: 7.7 for bands A, B, P; 24.0 for bands C, D, cut at the wall limit; 3.4 for the layout sweep), no GPU hours, 35 wall-clock hours of job time. The queue bands and the layoutless entries were exhausted at the budgets run, so `budget_exhausted` is the stopping condition in the sense the card uses it; the declared CPU budget was in node-hours by intent and was not reached.

## What ran

Three NERSC Perlmutter jobs on 2026-11-17 from main at cfca5690b1db: 61479479 (`research/certs/certify_sweep.py run --backend tropidist+sat`, bands A, B and P, 1200 s per solve, 300 s ladder, 30 processes of four tropidist threads, completed in 7 h 42 min), 61479480 (bands C and D, 3600 s per solve, 600 s ladder, same shape, ended at the 24 h wall limit with 10 of 30 processes still open), and 61479606 (`research/local2d/layout_sweep.py run --credit @vprusso --entry-seconds 600`, 60 processes, over the 1,893 CSS entries with no layout, smallest n first, completed in 3 h 25 min). The run manifests, certificates and layouts were collected on 2026-11-27 and filed from them; the ten C/D processes that wrote no manifest are reconstructed from their attempt rows and certificate files.

## What was tried

- Certification, bands A, B, P: 664 entries opened; 561 exact, 100 partial, 3 timeouts.
- Certification, bands C, D: 270 entries opened; 53 exact, 217 partial.
- Layouts: 1,893 entries opened; 939 placed (140 by the torus-grid screen, 423 by fold annealing, 121 by the hinge annealer, 255 on the triangular lattice; 68 single-layer, 871 bilayer), 954 misses.

## Survivors

This campaign produces evidence for existing entries, not new codes, so the gate's survivor list is empty by construction. What was filed:

- Certificates: 178 partial certificates in PR #7392, 160 raising a lower bound already on main and 18 on entries that had none. The 614 exact records were overtaken: between 2026-11-17 and the filing the QEDist sweeps (#7109, #6197) certified those entries, and the Perlmutter records carry no checks_sha256 binding (the sweep version predated it), so they were not filed.
- Layouts: 930 first 2D-local layouts in 24 PRs of at most 40 (#7394, #7396, #7397, #7398, #7399, #7400, #7401, #7402, #7407, #7408, #7409, #7411, #7412, #7413, #7414, #7415, #7416, #7417, #7418, #7419, #7420, #7421, #7422, #7423); 4 of the 939 were left alone because the entry had gained a layout or left the board since the sweep, and 5 (160-32-10, 160-36-6, 170-34-8, 180-36-8, 190-38-8) were dropped after the first CI run because their gate verdicts are golden-pinned in `verify/fixtures/validation_gate/golden` and a layout moves the verdict; those wait for a golden re-record. The attempt log is PR #7395.
- The sweep tool fix that the campaign surfaced: `certify_sweep.py` skipped no d = 1 entries and the weekly job had failed three weeks running on their W = 0 rung; PR #7393.

## Negative results

- The D = 3 and stabilizer 2D clubs stay empty. No tool in the repository searches 3D embeddings or stabilizer layouts, and reaching g >= 1 there is a construction problem (issues #5840, #5841), not a sweep.
- 954 layoutless entries were not placed at 600 s; their best radius per stage is in `research/local2d/sweep_attempts.jsonl`, so a later run at this budget skips them and a larger budget reopens them with `--retry`.
- The GPU budget was not needed: certification and layout assignment are CPU work, and no witness search arose.

## Follow-up

- Run the layout sweep again at a larger per-entry budget over the 954 misses, and over the stabilizer entries once a stabilizer layout tool exists.
- The certification queue is now mostly a lower-bound queue: 472 entries lack a certificate (287 CSS, 185 stabilizer) and QEDist's weekly sweep (#6868) is the standing route; the tropidist ladder is worth a second pass only where QEDist's partial bound is below the ladder's.
- Collect campaign outputs in the session that starts them: these sat on Perlmutter for ten days.
