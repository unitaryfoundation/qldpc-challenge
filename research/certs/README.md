# The certification queue

`todo.json` lists every board entry whose distance is a witnessed upper bound
and no honored certificate, what certifying it would take, and the order the
work should go in (issue #4027). `certification_queue.py` writes it from
`codes/` and `certs/`; the `certification-queue` workflow regenerates it every
Monday on `main`, so a certificate that lands removes its entry and a distance
that changes re-lists the entry at the new value. Nothing in it is a distance
claim: every `d` stays an upper bound until a certificate says otherwise.

Who is in it is decided the way the site decides the `d=` tier: an entry is
exact only when `certs/<slug>.json` says `d_exact` and agrees with the entry's
current distance and side values (`site/build.py`, `cert_consistent`); every
other entry is here.

Per entry:

| field | meaning |
|---|---|
| `n`, `k`, `d`, `w`, `cells` | the shape and the primary-track cells it competes in |
| `record` | on a cell's Pareto frontier or the global one (`compute_records`, the star on the board) |
| `sides.X`, `sides.Z` | what `verify/certify.py` decides per side: `generators` (one MILP each, k per side), `lp_vars` (n + rank + 1) and `lp_constraints` (rank + 2) of each MILP, the rank being the side's kernel matrix's. A stabilizer entry has the single side `P`, which only the tropidist backend certifies |
| `peers` | the honored solver and proof_log certificates within 25% of its n and within 2 of its d: how many, and the median of their recorded seconds (worse side) |
| `band` | A: three or more peers, median under 600 s. B: a peer under 3,600 s, or n <= 400 and d <= 16 (what the October 2026 Perlmutter run closed at 2,400 s per solve). C: n <= 700 and d <= 24, beyond any peer but inside what the tier has reached (largest certified d is 19). D: n > 700 or d > 24, which nothing certified on main resembles. P: stabilizer, tropidist backend only |
| `measured_shape` | when `research/cost/cost_table.json` exists, the nearest measured shape and how its certification run ended there (exact, MILP limit, wall cap) |
| `certified_lower_bound` | when `certs/<slug>.json` is a partial certificate, its `d_lower`: the entry stays in the queue, and the sweep reopens it at that bound (issue #4718) |
| `position` | rank under the rule below |

The rule, also in the file's `rule` field: records first, then band A to D with
P last, then cheapest first (the peers' median seconds, then n), then slug. A
cheap certificate on an entry no frontier needs buys less than a dear one on a
record, so value enters before cost. `next_ten` is the head of the queue, the
successor list for #3629-style work.

The peers' seconds come from certificates produced on different machines
(Perlmutter nodes and laptops) under different time limits, so a band is an
estimate from what has closed, not a promise. Band A entries are the ones
`verify/sat_certify.py --proof` should close in minutes; C and D are where
#3629's 28,800 s per solve runs sit and mostly time out. The tropidist
backend below closed band A and B entries in seconds and a band C entry
(512-18-19, Z side) in five minutes on a laptop.

Filing a certificate the queue produced follows #3666: the certifier's own
record, a `certs/proof_log_batch.jsonl` row when the proof path verified, and
a PR touching only `certs/`.

```
uv run python research/certs/certification_queue.py            # writes todo.json
uv run python research/certs/certification_queue.py --check    # exit 1 if the committed queue is stale
```

## The weekly sweep

`certify_sweep.py` works the head of the queue, and the `certify-weekly`
workflow runs it every Monday at 12:00 UTC, after the queue has regenerated
(issue #4148). In queue order it skips what a certificate at `d` cannot help
(stabilizer entries unless the tropidist backend runs, entries whose side
values differ from `d`, entries that already have a `certs/` file) and runs
`verify/sat_certify.py` with the proof path on the rest, one time limit per
solve (600 s by default), until the job budget is spent (four hours by
default). Each entry runs in a subprocess
under a hard wall clock of six solves plus five minutes, because the solver's
own limit is advisory: CryptoMiniSat checks it between search rounds, and a
442-qubit instance ran nine minutes past a 60 s limit in testing. Each entry
opened is one line of `attempts.jsonl`, committed to `main` by the workflow:

| field | meaning |
|---|---|
| `slug`, `n`, `k`, `d`, `band`, `position` | the entry and where the queue had it |
| `date`, `head`, `run`, `tlim` | when, from which commit, in which Actions run, at what limit per solve |
| `outcome` | `exact` (both sides UNSAT at `d - 1`), `partial` (both sides proved a bound of at least 2 below the claim; `d_lower` says which), `timeout` (a side did not finish, or the wall clock killed the entry), `refuted` (a side found a lighter logical; the witness is in `witness`), `error` (the certifier refused: a pairing set that does not span `k`, or the two encodings disagree) |
| `level` | `proof_log` when drat-trim verified both sides' refutations (of the top UNSAT rung each, on a partial certificate), `solver` when CryptoMiniSat or tropidist closed both sides and no proof was checked |
| `sides` | per side the status, the seconds, whether the proof was verified, the `lower_bound` the side proved when it did not close, and the ladder's `rungs` (`W:status`) |
| `backend` | `sat` or `tropidist`: which certifier produced the row; `upgrade` says what the SAT path did after tropidist closed an entry |
| `ladder`, `start`, `raised` | the per-side ladder budget in seconds; the rung a reopened partial certificate resumed at; `{from, to}` when the run raised a filed bound |

The log is what keeps the sweep from reopening the same entries: an entry that
timed out or errored at a limit is not reopened at that limit or a shorter one
(`--retry` or naming it in `--slugs` does), a refuted entry is never reopened
until its claim changes, and a certified entry is left alone for 14 days
while its certificate lands (after that its PR was never opened or never
merged, and the entry is solved again). What closes is written in the #3666 shape, the certifier's
record without its per-side proof blocks plus a `proof_log_batch.jsonl` row
for a proof_log certificate, and the workflow stages it on a
`certs/weekly-<date>` branch, runs `verify/check_certs.py` and a replay of the
quick proof_log certificates there, and opens the certs-only PR. A refuted
side opens an issue with the witness weights instead and fails the run.

A pull request the Actions token opens gets no `pull_request` runs, so close
and reopen it, or push an empty commit, to start the PR's own checks. A
fine-grained token in the `SWEEP_PR_TOKEN` secret makes its owner the PR
author and the checks start on their own. The run's output directory (the
staged certificates, `run.json`, the summary) is uploaded as a workflow
artifact for 30 days whatever happens after the sweep, so a failed stage
step or a closed PR loses no solving, and `stage` records what it copied in
`staged.json`, which is what the PR body lists.

```
uv run --extra research python research/certs/certify_sweep.py run --tlim 600 --job-seconds 14400
uv run --extra research python research/certs/certify_sweep.py run --tlim 120 --ladder 300   # with partial certificates
uv run python research/certs/certify_sweep.py stage --out-dir research/out/certify_sweep   # copy into certs/
uv run python research/certs/certify_sweep.py pr-body --out-dir research/out/certify_sweep --out body.md
```

### The ladder and partial certificates

`--ladder SECONDS` (issue #4230) asks each side at W = 1, 2, ... up to
`d - 1` instead of at `d - 1` alone, spending at most that many seconds per
side (`--tlim` stays the limit per solve). UNSAT at W is the theorem
`d >= W + 1` whatever happens above it, so an entry that does not close in
budget still leaves a proven lower bound, and the run stages it as a partial
certificate: `d_exact` false, `d_lower` the largest `W + 1` at which both
sides returned UNSAT, per side `proved_min` and the `ladder` of rungs, and
`verification.checks_sha256` binding the file to the entry's matrices. The
board shows such an entry as the interval `d_lower <= d <= d`; the exact tier
is the case `d_lower == d`. Cost grows three- to five-fold per rung on board
entries, so ten minutes per entry proves about half the witnessed distance
at n of a few hundred, and the ladder ascends and stops rather than searching.

The weekly workflow runs with a ladder budget (its `ladder` input, 300 s per
side by default; `0` turns it off). A partial certificate already in `certs/`
is not a closed entry: the sweep reopens it at its own `d_lower` when
`--retry` or `--slugs` names it or the ladder budget is larger than the one
the file recorded, and `stage` replaces the file only when the run raised the
bound or closed the entry, keeping the old rungs ahead of the new ones so the
file shows the whole ascent. A run whose first new rung times out files
nothing and says so in its attempt row. The tropidist backend's per-side
`lower_bound` on a side that did not close is filed the same way, at the
solver level and without a ladder, on CSS entries and on stabilizer entries
(the single Pauli-weight side `P`, bound to the generator set by
`checks_sha256`; issue #4718). Under `--backend tropidist` a partial
certificate on file is reopened when `--retry` or `--slugs` names it or
`--tlim` is larger than the `tlim_per_solve` it recorded, and the tool starts
at the filed `d_lower` (`tropidist_certify.py --kmin`) instead of re-proving
the thresholds below it; the file is replaced only when the bound rose, and
records the bound it was raised from.

## The tropidist backend

`tropidist_certify.py` (issue #4716) runs tropidist, the exact-distance tool
of Cheng, Guo, and Pan, "Certifying quantum code and circuit distances at
scale" (arXiv:2611.08247; github.com/Fanerst/tropidist, MIT), on a board
entry. The tool computes the least weight of a vector `e` with `H e = 0` and
`L e != 0` by exhaustive evaluators (a cut-rank dynamic program, a
weight-truncated version of it, and a weight-bounded search with covering
bounds and symmetry) and reports a proved lower bound, the lightest vector it
found, and when each bound was reached. On the paper's 74-instance benchmark
it certifies 70 where HiGHS, the engine of `verify/certify.py`, certifies 13
and plain SAT 15.

A CSS entry is asked one problem per side, in `verify/sat_certify.py`'s
convention (side X: `H = H_Z`, `L` = the Z-type logical representatives). A
stabilizer entry is asked one problem in Pauli weight: each qubit becomes
three mechanisms X, Z, and Y, a row of `H` is a generator's symplectic
product with each mechanism, and a row of `L` the same for each of the 2k
logical representatives. A minimum never selects two mechanisms on one qubit
(their product is the third at weight one with the same syndrome and label),
so the least mechanism count is the Pauli distance. This is the only
certifier the board has for stabilizer entries.

The record is filed in the #3666 shape at `verification.level` `solver`: the
lower bound is exhaustion inside the tool's kernel, with completeness proved
in the paper but nothing a third party can replay, which is the level the
HiGHS and CryptoMiniSat records hold. The vector the tool returns is
re-verified with `verify/heuristic_distance.py` before anything is written;
a vector lighter than the claim is a refutation. The `solver` string names
the tool and the commit it ran at.

`certify_sweep.py run --backend tropidist+sat --tropidist <checkout>` runs
the tool first and hands a CSS entry it closed to the SAT proof path, filing
the proof_log record when that finishes and the tool's record otherwise. An
entry the tool did not close is not retried with SAT in the same run (the
paper's benchmark gives SAT little chance where the tool's search did not
finish), and a tool error falls back to SAT. `--backend tropidist` runs the
tool alone. The backend is opt-in: the scheduled certify-weekly run stays on
the SAT path, and a workflow_dispatch run with `backend` set to `tropidist`
or `tropidist+sat` fetches the tool at the commit pinned in `TROPIDIST_REF`
and runs it.

Measured on a laptop (one kernel thread; the tool's OpenMP build is not
available on macOS) against entries the queue listed: 132-30-12 (band A,
predicted 340 s per side) closed in 8 s per side, 330-66-12 in 1 s,
300-60-14 in 9 s, 144-6-15 in 10 s, 144-10-16 (band B, predicted 1,413 s) in
30 s, 576-292-8 in 1 s; 512-18-19 (band C) closed its Z side in 297 s and
reached d >= 17 on the X side in 600 s; 372-130-16 reached d >= 15 on both
sides in 600 s. Stabilizer entries 40-9-6 and 90-21-10 closed in under 15 s;
144-10-16-b reached d >= 15 in 600 s.

```
uv run python research/certs/tropidist_certify.py codes/40-9-6.json --tropidist /tmp/tropidist --tlim 600
uv run python research/certs/tropidist_certify.py codes/372-130-16.json --tropidist /tmp/tropidist \
    --tlim 3600 --kmin 15     # resume above a filed partial certificate's d_lower
uv run --extra research python research/certs/certify_sweep.py run --backend tropidist+sat \
    --tropidist /tmp/tropidist --threads 4 --tlim 600 --job-seconds 14400
```

## Cross-checking the stabilizer certificates

A stabilizer entry's certificate comes from the tropidist backend alone,
at the solver level, so `stabilizer_crosscheck.py` (issue #4939) checks each
one by means that share nothing with the tool: brute force over every Pauli
operator of weight at most d - 1 when their number is within `--brute-max`
(exact; feasible up to about n = 17 at d = 7), `verify/certify.py`'s HiGHS
integer program on the same three-mechanisms-per-qubit encoding (exact when
it finishes, a different solver on a different formulation), and
`verify/heuristic_distance.py`'s randomized Pauli search at a stated trial
budget (a consistency check, not a proof). A certificate is confirmed when
brute force or the MILP finishes with nothing lighter and the search agrees,
contradicted when any of the three exhibits a lighter nontrivial logical
(re-verified with `valid_pauli_logical` and recorded), and unconfirmed
otherwise. The record is `stabilizer_crosscheck-<date>.json`; a
contradiction exits 3.

```
uv run --extra certify python research/certs/stabilizer_crosscheck.py --all --tlim 300 --trials 200000
uv run --extra certify python research/certs/stabilizer_crosscheck.py --slugs 40-9-6 90-21-10
```

The run of 2026-11-06 (`stabilizer_crosscheck-2026-11-06.json`: 300 s per
MILP solve, 200,000 RIS trials, brute force up to 2e7 Paulis) confirmed 10
of the 11 certified entries and contradicted none. The nine entries with
n <= 17 were confirmed by all three checks (brute force over at most 1.1e7
Paulis, 17 s for 17-1-7; each MILP under 30 s). 40-9-6 has 1.7e8 Paulis
below its distance, beyond the enumeration, and was confirmed by the MILP in
34 minutes with the search agreeing. 90-21-10 is unconfirmed: the enumeration
is out of reach (1.4e16 Paulis), each of the 42 MILP solves (one per logical
representative) hit the 300 s limit, and the search's lightest logical at
200,000 trials weighs 10, so that certificate rests on tropidist's verdict
alone, with the heuristic bound agreeing.
