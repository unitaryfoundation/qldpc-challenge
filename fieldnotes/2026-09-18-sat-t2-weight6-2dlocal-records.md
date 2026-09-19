---
title: "SAT t=2 campaign: three new weight-6 2D-local frontier records ([[16,6,3]], [[25,9,3]], [[36,12,3]])"
date: 2026-09-18
author: "@mathysrennela"
model: "DeepSeek V4 Flash"
topics: [sat-search, weight-6, local-2d-single, frontier-record, hackathon-1155, t2-detection]
related:
  - fieldnotes/2026-09-18-sat-2dlocal-campaign.md
  - fieldnotes/2026-09-18-hackathon-1155-frontier-map-and-playbook.md
---

# SAT t=2 campaign: three new weight-6 2D-local frontier records

Hackathon (#1155) SAT-search session. Prior SAT campaigns (2026-08-25 →
2026-09-08) mined **t=3 detection** (d≥4) at small grids and hit budget walls
(6×6/8×8 w6/t3). This session found that **t=2 detection (d≥3)** is a
dramatically cheaper encoding that still yields board-advancing codes, and
used it to place three new frontier records in the **weight-6 ×
local-2d-single** cell. All three are hackathon-eligible (interaction radius
≤ 4, n ≤ 1000, w ≤ 8, d ≤ 40).

## Results (all gate-passed, staged for review)

| Code | n | k | d | w | interaction radius | gate |
|---|---|---|---|---|---|---|
| `[[16,6,3]]` | 16 | 6 | 3 | 6 | 3.16 | passed, advances weight-6 × local-2d-single |
| `[[25,9,3]]` | 25 | 9 | 3 | 6 | 4.00 | passed, advances weight-6 × local-2d-single |
| `[[36,12,3]]` | 36 | 12 | 3 | 6 | 4.00 | passed, advances weight-6 × local-2d-single |

Each is a new nondominated point in the weight-6 × local-2d-single cell:
at its n it sits beside the existing lower-k d=4 point (`[[16,4,4]]`,
`[[25,5,4]]`, `[[36,6,4]]`) as a higher-k d=3 alternative, and `[[25,9,3]]`
strictly dominates the prior `[[37,7,3]]` on n. `[[36,12,3]]` is the best
kd²/n of the three (12·9/36 = 3.0).

## Method

`research/local_sat.py` `enumerate_local_sat_codes` with `shared_t3=True`
(the fast encoding), `solver="cadical"`, `stream=True`, per-solve
conf/time budgets. Config per record:

- `[[16,6,3]]`: n_side=4, G=5, w=6, t=2, radius=2.0
- `[[25,9,3]]`: n_side=5, G=8, w=6, t=2, radius=2.0
- `[[36,12,3]]`: n_side=6, G=12, w=6, t=2, radius=2.0

The t=2 CNF builds in ~0.5–1.5 s and enumerates ~100 codes in seconds —
orders of magnitude cheaper than the t=3 instances that walled the prior
campaigns. The max k at each n is set by the minimum G that still satisfies
t=2 detection: G=5→k=6 at n=16, G=8→k=9 at n=25, G=12→k=12 at n=36.
Lower G is UNSAT (too few checks to detect all weight-≤2 errors); higher G
drops k (rank sum grows). G=11 at n=36 (k≥13) is budget-walled.

## Evidence trail

Each staged candidate carries a witness-backed `upper_bound` distance (d=3
with explicit weight-3 logicals on both X and Z sides) and a full
`validate_candidate` verdict: `verify.ok=true`, `refute.refuted=false` (no
lighter logical in the gate's RIS trials), `dedup` clean, `board_advancing`
true. The gate is the claim; the surrogate was used only to pick the
highest-k code per config.

## Dead ends (do not re-mine)

- **t=3 (d≥4) at these grids remains budget-walled** — n=25/36 w6/t3 and
  w8/t3 need overnight budgets (consistent with 2026-09-08 closure). The
  d=4 frontier points (`[[16,4,4]]`, `[[25,5,4]]`, `[[36,6,4]]`) are not
  reachable by a cheap in-session t=3 search.
- **Weight-8 2D-local t=3** at n=25/36 (radius 2.0, the hackathon-eligible
  radius) is empty (UNSAT); radius 4.0 is budget-walled. The weight-8
  2D-local single cell is structurally sparse because weight-8 checks are
  too heavy to be local — only `[[16,6,4]]` (Reed-Muller) sits there.
- **Weight-4 t=2** at n=16/25 is UNSAT (the k=2 frontier `[[16,2,4]]` is
  effectively optimal for t=2).
- **n=49 (7×7) w6/t2** is budget-walled at every G tried (13–17).

## Tools

`research/local_sat.py` (5 backends, shared_t3, per-solve budgets,
`calibrate_local_cnf` budget predictor) and the kit modules
css/surrogate/submit/search, `verify/validate_candidate.py`
(trusted gate, untouched). The weight-8 screen and the bounded campaign
driver live in `research/sat_search.py`; the overnight runner pattern is
described in the night-campaign section below. Compute: interactive
MacBook session, no overnight runs.

## Reproduction

```python
from local_sat import enumerate_local_sat_codes
gen = enumerate_local_sat_codes(6, 12, 6, 2, 2.0, seed=7, max_codes=120,
    solver="cadical", conf_budget=1_000_000, time_budget=90.0,
    stream=True, shared_t3=True)
# pick the highest-k yielded code, package with make_submission(coordinates=...,
# layers=1), validate with validate_candidate.
```

## Next moves

1. **Human review + promotion** of the three staged candidates (local
   staging output; now promoted via PRs #1232–#1234, one code per board
   point). The `[[25,9,3]]` and `[[36,12,3]]` dominate the earlier staged
   `[[25,7,3]]`/`[[36,9,3]]` (removed).
2. **Night campaign for d=4**: t=3 at n=25/36 w6 with an overnight budget
   could add higher-k d=4 points beside the existing `[[25,5,4]]` /
   `[[36,6,4]]`. The t=2 result shows the encoding is sound; only the
   budget was missing.
3. **n=49 (7×7) w6/t2** with a longer budget (G=15–16) may yield a
   `[[49,k,3]]` frontier point; the 7×7 grid needs more conflicts than the
   interactive session allowed.

## Follow-up (same day): submissions opened + night campaign prepared

**Three PRs opened** (contributor-driven, explicit authorization), one code
per PR, each built in a clean worktree, prose-checked against committed
content (CI-equivalent), pushed from the fork, and opened against
`unitaryfoundation/qldpc-challenge`:

- PR #1232 — `[[16,6,3]]` (branch `submit-16-6-3`)
- PR #1233 — `[[25,9,3]]` (branch `submit-25-9-3`)
- PR #1234 — `[[36,12,3]]` (branch `submit-36-12-3`)

Each carries `notes/<slug>.md` (research note) and a `provenance.notes`
entry confirming the gate's dedup found no exact/WL-equivalent entry. The
`verify` CI check (distance gate) was still running at handoff.

**Night campaign prepared** (a local2d runner script, staged locally;
adapted from the 2026-09-08 find-codes runner). Targets the
higher-distance rungs that were budget-walled in-session:

- T1: 5×5 (n=25) t=3 w6, G=10,11,12 → `[[25,k,4]]` w6, k≥6
- T2: 6×6 (n=36) t=3 w6, G=12,13,14 → `[[36,k,4]]` w6, k≥7
- T3: 7×7 (n=49) t=2 w6, G=15,16 → `[[49,k,3]]` w6, high k
- T4: 5×5/6×6 t=4 (d≥5) w6, cryptominisat → the d≥5 axis

Incremental checkpointing (report.json + per-stage records written as
found), stage caps, same-point + dominance filters, gate packaging.
Smoke-tested (enumerates `[[25,5,4]]` at t=3, matching the board). Launch:

```
caffeinate -is uv run --with python-sat python <night_runner.py> --total 10
```

Run the night-campaign protocol (AC power, `pmset disablesleep 1`, smoke
check, morning teardown `disablesleep 0`) per the night-campaign skill.

## Night campaign results (completed 2026-09-18 ~16:54, ~3.1h)

All four stages finished (faster than the 10h cap — the search spaces
exhausted early). Two new frontier records, both gate-passed and submitted:

| Stage | Config | Result | Submission |
|---|---|---|---|
| T1 | 5×5 t=3 w6 G=10,11,12 | no new point (cell closed) | — |
| T2 | 6×6 t=3 w6 G=14 | **[[36,8,4]]** (k=8, d=4) | PR #1272 |
| T3 | 7×7 t=2 w6 G=16 | **[[49,17,3]]** (k=17, d=3) | PR #1276 |
| T4 | 5×5/6×6 t=4 w6 crypto | empty (d≥5 not reached) | — |

Both new codes are weight-6, 2D-local single-layer, interaction radius 4.0
(hackathon-eligible). Each was deep-confirmed at 100k RIS trials (no logical
lighter than the claimed d on either side) before submission, and each
passed the trusted gate (`passed=true`, `board_advancing=true`,
`refuted=false`). `[[36,8,4]]` dominates `[[36,6,4]]`; `[[49,17,3]]`
dominates `[[58,16,3]]`, `[[65,17,3]]`, `[[51,12,3]]`.

Cumulative hackathon SAT haul (all in weight-6 × local-2d-single):
`[[16,6,3]]` (#1232), `[[25,9,3]]` (#1233), `[[36,12,3]]` (#1234),
`[[36,8,4]]` (#1272), `[[49,17,3]]` (#1276).