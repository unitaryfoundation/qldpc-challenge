# audits: re-measuring the leaders before trying to beat them

The boards rank witness-backed distance **upper bounds**. A frontier is
therefore a set of claims, and the board's own history says some of them are
inflated: `[[882,18,30]]` was revised to 29 (PR #1165), `[[684,12,81]]` to 66
(issue #896), and `[[396,10,39]]` to 37 (issue #899). Spending a campaign
against a bar that is one or two units soft is wasted budget, so the first step
of a campaign is to re-measure the bar on fresh seeds.

`leader_audit.py` is the harness for that:

```
# is this leader's number real? escalating ladder, fresh seeds each rung
uv run --frozen python research/audits/leader_audit.py ladder \
    codes/360-12-24.json \
    --ladder 1000000:101,102,103,104 5000000:201,202,203 20000000:301,302,303 \
    --witness-out /tmp/360-12-24.witness.json

# triage a whole cell's leaders at one budget
uv run --frozen python research/audits/leader_audit.py screen \
    --trials 2000000 --seeds 51 --witness-dir /tmp/screen-witnesses \
    codes/672-20-32.json codes/922-18-31.json

# a candidate against the board entry it would beat only on d, same budget
uv run --frozen python research/audits/leader_audit.py pair \
    research/candidates/<n>-<k>-<d>.json --trials 2000000 --seeds 51 \
    --pair-depth 64 --witness-dir /tmp/pair
```

It exits 2 if any claim is refuted, so it can gate a script. The other codes are
kept distinct from 2 for exactly that reason:

| code | meaning |
|---:|---|
| 0 | every claim `holds` or came back `inconclusive` |
| 2 | at least one claim was `refuted` -- the gate signal |
| 3 | the invocation or an entry was unusable: a malformed or seedless ladder rung, an entry whose checks do not commute, or an entry whose recorded `k` is not the `k` of its own matrices. A mistyped command must not be mistakable for a refutation, and a refutation of something that is not the claimed CSS code is not a refutation. |

## What it does

* Loads a board entry straight from `codes/`, so the object measured is the one
  the verifier ranks (including any reduction or layout the entry carries).
* Recomputes `k` and CSS commutation from the raw check matrix rather than
  trusting the entry's own fields.
* Runs random-information-set search on both Pauli sides jointly, using the
  bit-packed `verify/gf2_fast` accelerator when built (`make fast`) and the
  pure-NumPy `research/kit/surrogate.py` path otherwise.
* Re-validates every witness in pure Python against the raw sparse matrices:
  support size equals the weight, `H_opp v = 0` over GF(2), and `v` outside the
  row space of `H_own`. A bug in the accelerator cannot put an unbacked number
  in the log -- a proposal that fails this re-check is printed as `DISCARDED`
  and can neither move the reading nor reach the witness file.
* Refuses to score an entry whose recomputed `k` is not its recorded `k`, or
  whose checks do not commute, and exits 3 instead. The GF(2) bases behind the
  search are built once per entry and reused across seeds.

A recorded `seed` does not reproduce a reading across backends: the accelerator
consumes it directly, while the NumPy path derives the two sides' independent
streams from `np.random.SeedSequence(seed).spawn(2)`. Compare readings taken on
the same backend, and record which one produced the number.

## Persist the witness while the ladder is still running

Pass `--witness-out` (ladder) or `--witness-dir` (screen). The support of the
lightest logical seen so far is printed and written **on every new best**, not
once at the end: a rung can be killed by a time limit, and the witness behind
the lightest reading is the artifact a distance revision needs. Re-running a
killed 8M-trial rung at `n = 684` costs about fifteen minutes of wall clock.

`--witness-out` is cleared at the start of a ladder run, so a file left behind by
an earlier run cannot survive a run that finds nothing and then read as that
run's artifact (stale `verdict: refuted` included). `--witness-dir` writes one
file per entry, named after the entry's path within the repo rather than its
basename, so `codes/672-20-32.json` and a same-named copy elsewhere cannot
overwrite each other.

## Reading the output

| verdict | meaning |
|---|---|
| `refuted` | a logical lighter than the claim was exhibited. The claim is over-stated and `d <= ` the reading. A distance revision is a valid submission on its own. |
| `holds` | the search reached exactly the claimed weight and found nothing lighter. Evidence, not proof. |
| `inconclusive` | the search did not even reach the claim (or found nothing above it in one direction). Says nothing about the code. |

These three tokens are exactly what the tool prints and writes, lowercase, so a
script can match them directly. A rung that never ran -- no seeds, or no trials
-- is a usage error (exit 3), not an `inconclusive` verdict.

**`inconclusive` is the trap.** For dense low-rate entries RIS can sit several
units *above* the claim at a budget that fully refutes a structured one -- e.g.
`[[684,20,72]]` reads 84 at 2M trials against a claim of 72, while its
sibling `[[684,12,66]]` was refuted 81 -> 66 by the same tool at 8M.
A reading above the claim is never corroboration: only a reading *at* or
*below* it carries information. Match the budget to the rate, as issue #899
argues.

## Set `--pair-depth` to the depth the claim's own ladder used

Every trial combines the `pair_depth` lightest reduced rows pairwise. The
accelerator's default of 10 suits small codes, but the ladders behind this
board's affine two-block entries used 24 to 80, and reading such a claim at
depth 10 measures the candidate set rather than the code:

| entry | trials | seed | depth 10 | depth 64 |
|---|---|---:|---:|---:|
| `codes/684-12-77.json` | 200,000 | 71 | 89 | 85 (at 24/48) |
| `codes/684-12-77.json` | 200,000 | 101 | 97 | **87** |

Depth 64 costs about 1.4x depth 10, not 45x -- the per-trial cost is dominated
by the elimination, not the pair phase. So an `inconclusive` verdict taken at a
shallower depth than the claim's own ladder is an artifact of the instrument and
must not be reported as evidence about the code. The default stays 10 so
existing invocations do not change meaning.

## The pair audit: a win that is only a win on d

A construction pins n, k and check weight, so a candidate built the same way as
an existing board entry can only beat it on `d` -- and `d` is the upper bound
that inflates. `pair` measures a candidate and the board entries it would beat
on `d` alone at one identical budget:

```
uv run --frozen python research/audits/leader_audit.py pair \
    research/candidates/<n>-<k>-<d>.json --trials 2000000 --seeds 51 52 \
    --pair-depth 64 --witness-dir /tmp/pair
```

The peers default to every `codes/` entry with the same n, k and max check
weight and a lower claimed d -- the pair over which the Pareto comparison has
exactly one strict axis; `--peer` names them instead. Candidate and peers are
measured with the same trials, seeds, pair depth and witness re-check, because a
number read deeper on one side than the other is an artifact of the instrument,
not a distance difference. One of four decisions comes out:

| decision | meaning |
|---|---|
| `drop: ...` | the candidate's own claim came down at its own budget; do not package it |
| `redirect: ...` | the board entry's claim came down; the submission is its distance revision |
| `credible: ...` | both claims held at matched depth; the gain survives the audit |
| `inconclusive: ...` | neither claim was reached; no information, and never corroboration |

Exit 2 when either side is refuted, so it gates like `ladder` and `screen`.
Exit 3 when there is no peer at all: that candidate is not making a d-only gain,
so this is not the question to ask of it -- use `screen`.

## Limits

These are upper-bound searches. `holds` never upgrades a claim to the exact
(`d=`) tier -- that needs `verify/certify.py`, whose measured envelope is
`d <= 13, k <= 12`. The syndrome-decoder cross-check in `decode/distance.py` is
a genuinely different mechanism but is dominated by RIS at these budgets
(issue #1148); it is corroboration when it agrees, and not evidence when it is
weaker.
