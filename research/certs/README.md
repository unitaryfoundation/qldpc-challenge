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
| `sides.X`, `sides.Z` | what `verify/certify.py` decides per side: `generators` (one MILP each, k per side), `lp_vars` (n + rank + 1) and `lp_constraints` (rank + 2) of each MILP, the rank being the side's kernel matrix's. A stabilizer entry has the single side `P` and no certifier |
| `peers` | the honored solver and proof_log certificates within 25% of its n and within 2 of its d: how many, and the median of their recorded seconds (worse side) |
| `band` | A: three or more peers, median under 600 s. B: a peer under 3,600 s, or n <= 400 and d <= 16 (what the October 2026 Perlmutter run closed at 2,400 s per solve). C: n <= 700 and d <= 24, beyond any peer but inside what the tier has reached (largest certified d is 19). D: n > 700 or d > 24, which nothing certified on main resembles. P: stabilizer, no certifier yet |
| `measured_shape` | when `research/cost/cost_table.json` exists, the nearest measured shape and how its certification run ended there (exact, MILP limit, wall cap) |
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
#3629's 28,800 s per solve runs sit and mostly time out.

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
(stabilizer entries, entries whose side values differ from `d`, entries that
already have a `certs/` file) and runs `verify/sat_certify.py` with the proof
path on the rest, one time limit per solve (600 s by default), until the job
budget is spent (four hours by default). Each entry runs in a subprocess
under a hard wall clock of six solves plus five minutes, because the solver's
own limit is advisory: CryptoMiniSat checks it between search rounds, and a
442-qubit instance ran nine minutes past a 60 s limit in testing. Each entry
opened is one line of `attempts.jsonl`, committed to `main` by the workflow:

| field | meaning |
|---|---|
| `slug`, `n`, `k`, `d`, `band`, `position` | the entry and where the queue had it |
| `date`, `head`, `run`, `tlim` | when, from which commit, in which Actions run, at what limit per solve |
| `outcome` | `exact` (both sides UNSAT at `d - 1`), `timeout` (a side did not finish, or the wall clock killed the entry), `refuted` (a side found a lighter logical; the witness is in `witness`), `error` (the certifier refused: a pairing set that does not span `k`, or the two encodings disagree) |
| `level` | `proof_log` when drat-trim verified both sides' refutations, `solver` when CryptoMiniSat closed both sides and the proof path did not finish on one |
| `sides` | per side the status, the seconds, and whether the proof was verified |

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
uv run python research/certs/certify_sweep.py stage --out-dir research/out/certify_sweep   # copy into certs/
uv run python research/certs/certify_sweep.py pr-body --out-dir research/out/certify_sweep --out body.md
```
