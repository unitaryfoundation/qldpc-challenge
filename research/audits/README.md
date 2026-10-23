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
    --witness-out <witness-file>

# triage a whole cell's leaders at one budget
uv run --frozen python research/audits/leader_audit.py screen \
    --trials 2000000 --seeds 51 --witness-dir <dir-for-witnesses> \
    codes/672-20-32.json codes/922-18-31.json

# a candidate against the board entry it would beat only on d, same budget
uv run --frozen python research/audits/leader_audit.py pair \
    <candidate>.json --trials 2000000 --seeds 51 \
    --pair-depth 64 --witness-dir <dir-for-witnesses>
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
| `refuted` | a logical lighter than the claim was exhibited. The claim is over-stated and `d <= ` the reading. File the distance revision as a correction to that entry, not as a new submission (see "Filing a distance revision"). |
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
| `684-12-77` (since tightened) | 200,000 | 71 | 89 | 85 (at 24/48) |
| `684-12-77` (since tightened) | 200,000 | 101 | 97 | **87** |

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
    <candidate>.json --trials 2000000 --seeds 51 52 \
    --pair-depth 64 --witness-dir <dir-for-witnesses>
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
| `redirect: ...` | the board entry's claim came down; file its distance revision as a correction to that entry |
| `credible: ...` | both claims held at matched depth; the gain survives the audit |
| `inconclusive: ...` | neither claim was reached; no information, and never corroboration |

Exit 2 when either side is refuted, so it gates like `ladder` and `screen`.
Exit 3 when there is no peer at all: that candidate is not making a d-only gain,
so this is not the question to ask of it -- use `screen`.

## The frontier over time: `frontier_history.py`

`leader_audit.py` re-measures one claim; `frontier_history.py` shows what the
claims have done to the board. It replays `codes/` along main's first-parent
chain (one step per landing, in landing order, dated by committer date) and
reports the **(n, k, d) Pareto frontier** after every step that moved it.
`d` stays in: without it the (n, k) frontier is won by rate alone
(`[[n, n-2, 2]]` exists for every even n), and the revisions this README opens
with are exactly the steps *down* the replay is there to show.

```
uv run --frozen python research/audits/frontier_history.py                 # summary + every step down
uv run --frozen python research/audits/frontier_history.py --out f.csv     # date,commit,codes,frontier_points,frontier_codes,hypervolume,note
uv run --frozen python research/audits/frontier_history.py --plot frontier_history.svg
uv run --frozen python research/audits/frontier_history.py --plot-history frontier_hypervolume.svg
```

Two charts, stdlib-only SVG:

* `--plot`: one panel per distance floor (d >= 4, 6, 8, 12, 16, 24; `--floors`),
  each the (n, k) staircase of the frontier codes clearing that floor, on log
  axes, at one snapshot per month (`--bucket`). The region gained between
  snapshots is tinted with the snapshot that gained it, a region lost is a red
  hatch, and today's codes carry an `n,k,d` label. Read across the panels: the
  right end of the d >= 4 staircase is rate, the d >= 24 panel is the board
  that is hard to move.
* `--plot-history`: the frontier's dominated hypervolume on a date axis, as a
  share of today's, every step down marked and the largest named
  (`[[882,18,30]]->29`, `-[[216,15,11]]`). Hypervolume is taken in log2
  coordinates against `(n_ref = 1000, k = 1/2, d = 1/2)`, so a code
  contributes `log2(n_ref/n) x (1 + log2 k) x (1 + log2 d)`; the number is the
  union of those boxes. The half-unit reference keeps `k = 1` codes from
  contributing nothing; a code at or above `n_ref` (`--n-ref`) contributes
  nothing.

* `--frames DIR` / `--gif frontier.gif`: the panel chart as an animation, one
  frame per day the staircases changed (a day that changed nothing on any
  panel folds into the frame before it, whose title then spans the dates it
  stayed current), each frame over the previous one in grey with the gain
  tinted and the loss hatched, and a strip that places the frame in time.
  The frames are stdlib SVG; the GIF needs `rsvg-convert` (librsvg) on PATH
  and Pillow, so run it as
  `uv run --frozen --extra research python research/audits/frontier_history.py --gif frontier.gif`.
  About 25 s and 2 MB for the board today; `--frame-ms` sets the pace.

The replay is only quotable if it ends where the repository is, and
`test_frontier_history.py` asserts exactly that: the replayed state equals
`git ls-tree -r HEAD -- codes/` read as (n, k, d), CSS only, with every blob
parsed. The committed SVGs are the charts as of the date in their titles;
regenerate them with the commands above.

## Family concentration of the frontier: `family_concentration.py`

`site/build.py` (`family_concentration`) measures, for every CSS primary-track
cell and for the global CSS frontier, the share of the frontier's records held
by the top declared family and by the top two, the Herfindahl-Hirschman index
over families, and whether the cell's leader (largest kd^2/n) belongs to a
family other than that of the cell's earliest-dated member, which is where the
search moved a cell (issue #4025). It reads the same `cell_frontiers` and
`pareto` that award the star, and the site publishes it in `docs/stats.json`
and beside the frontier map's legend. This script records a dated measurement,
`family_concentration-<date>.json`, and prints the tables a fieldnote quotes,
so the shape of the frontier is a time series rather than a snapshot.

`family` is the board's one self-declared label (`research/AUTORESEARCH.md`:
filterable, never ranked), so every number here measures the declared tag, not
a property recovered from H; the derived provenance buckets under
`research/provenance/` are the computed axis wherever they cover an entry.
Nothing here ranks anything.

```
uv run python research/audits/family_concentration.py --markdown
```

## Who opened each cell and family: `cell_openings.py`

Issue #4029 asked whether the board should flag the entry that first
populates a cell, a family, or a geometry. The decision was no flag, and this
script is the record that stands in its place: for every populated cell key
(locality class, weight class, code type), the first entry by
`provenance.date` (ties by slug), the first entry per declared family tag, and
the first modular and 3D-layout entries, as `cell_openings-<date>.json` with
a table. On the board of 2026-10-23 three entries open all 24 cells, because
cells nest and the smallest, lowest-weight, most local code is in every cell
it qualifies for (the Steane code opened every CSS cell in 1996), and the
family half rests on the one self-declared label. First arrival is a fact
about the board's history, not a property of a code, so it is recorded here
and never shown as a badge, ranked, or scored.

```
uv run python research/audits/cell_openings.py --markdown
```

## Limits

These are upper-bound searches. `holds` never upgrades a claim to the exact
(`d=`) tier -- that needs `verify/certify.py`, whose measured envelope is
`d <= 13, k <= 12`. The syndrome-decoder cross-check in `decode/distance.py` is
a genuinely different mechanism but is dominated by RIS at these budgets
(issue #1148); it is corroboration when it agrees, and not evidence when it is
weaker.

## Filing a distance revision

A revision is a **correction to the existing entry**, not a new submission.
The matrices do not change, so the candidate pipeline is the wrong door: a
code whose `H_X` and `H_Z` match a board entry fingerprints as a duplicate,
and `verify/validate_candidate.py` is for new codes. It will tell you so, and
name the entry you are revising.

File it the way every merged correction has been filed:

1. `git mv codes/<n>-<k>-<old-d>.json codes/<n>-<k>-<new-d>.json`, and the
   note beside it. Keep the note's text: the revision record goes on top and
   the previous note follows under `## Original note, with the file paths
   updated`, with its paths pointed at the new slug. If the search narrative
   belongs elsewhere, move it to a dated `fieldnotes/` entry in the same PR
   instead, as PR #3053 did for `[[502,102,50]]`. `verify/check_prose.py`
   fails a revision whose new note and fieldnotes keep less than 70% of the
   old note's body lines (issue #3388).
2. Lower the side that came down and store the witness that lowered it, with
   `witness_provenance` recording who found it, at what budget, and with
   which tool. `d` is the minimum over the sides. The `found_by` handle has
   to be yours: `verify/check_authorship.py` refuses a `witness_provenance`
   the PR adds that does not name the PR author. Leave `survived_samples`
   out unless you mean it, because a survival stamp makes
   `verify/gate_changed.py` price the edit as a `stamp` rather than a
   `tightening` and run the deep battery on it.
3. Update the `name` field and the note's first `[[n,k,d]]`, which has to
   match the filename.
4. Leave everything else alone. `verify/check_authorship.py` binds a
   non-author to exactly this: the distance claim and an appended
   `provenance.notes` sentence. Any other change to `provenance.*` is the
   constructor's and will be refused.

`verify/gate_changed.py` classifies a revision with no survival stamp as a
`tightening` diff and gives it the standard pass, because the entry already
faced the deep battery when it merged and the claim only came down. Add a
stamp and it goes deep instead, which is correct but slower.

Worked examples in the history: `[[684,14,72]]` to `[[684,14,54]]`,
`[[540,12,44]]` to `[[540,12,41]]`, `[[682,140,83]]` to 66.

## Permutation equivalence between two entries

`permutation_equivalence.py` decides whether two entries are one code: it
applies an exhibited qubit permutation to the first entry's checks and tests
that the X and Z row spaces land exactly on the second's. The pairs settled
so far, with their permutations and the blob hashes of the files they were
checked against, are in `permutation_equivalences.json`; running the script
with no arguments re-checks every one of them from git, so the record
survives the removal of the duplicate it names. For a new pair:

```
uv run python research/audits/permutation_equivalence.py FIRST.json SECOND.json --perm "[...]"
```

A hit means the pair falls under "One code, one entry" in `CONTRIBUTING.md`.

## The recapture census: how much of L is known

The weekly sweep (`verify/refute_board.py`, run by `refute-weekly.yml` with a
fresh seed each Monday) now writes down every logical it finds at weight at
most the claimed distance, not only the one that beat the claim
(`verify/recapture.py`, issue #2897). Each entry's record carries the run and
file seed, the trials, the battery, and every logical as an operator id (the
vector) and a class id (its coset modulo the side's own checks), with its
weight. The raw records are a workflow artifact; what the repository keeps is
`recapture/incidence.json`, the per-logical count of runs it was found in, per
entry, side, battery, and weight, which the summary job folds each sweep's
records into and commits.

`recapture.py` estimates the census from that table:

```
uv run python research/audits/recapture.py report                       # every entry with captures
uv run python research/audits/recapture.py report --slug 72-12-6 --unit cls
uv run python research/audits/recapture.py report shard-0.jsonl shard-1.jsonl   # from raw records
uv run python research/audits/recapture.py fold --table recapture/incidence.json shard-*.jsonl
```

Per weight class with captures it reports the distinct logicals seen, how many
were seen in exactly one run and in exactly two, a bias-corrected Chao estimate
(the incidence form; runs are the sampling units) with a 95% interval, the
coverage (seen over estimated), and the mean number of runs each observed
logical was found in. After a refutation at weight w, the row at w says
whether w is the floor or the tip. Without one, the row at the claimed
distance says how complete the census of the minimum-weight class is.

Read it with the calibration in mind (`test_recapture_census.py`). On the
5 x 5 toric code, whose ten weight-5 X operators are enumerated, the interval
covers the truth 20 of 20 times once each observed operator has been
recaptured about five times on average, and fails in both directions below
that; a class under that mean is marked sparse, and a width-zero interval is
a statement about the sample, not a proof of completeness. A class whose runs
keep finding new operators past 5,000 distinct ids, or that hit the sweep's
per-side cap of 1,000, is censored: its count is a floor and no estimate is
made. Nothing here is a gate input or a board column; `verify/` reads neither
the records, the table, nor the report.

## Deciding what the WL signature only flags: `permutation_audit.py`

The gate has two dedup outcomes, an identical fingerprint and a shared
Weisfeiler-Leman signature, and `verify/two_block_equivalence.py` decides the
cyclic two-block family outright; every other flagged pair waits for a human
(issue #3427). `permutation_audit.py run` walks every pair of board entries
that share a WL signature with different fingerprints, and every literature
match in `research/provenance/derived.json`, and gives each one of four
verdicts: `equivalent` with the permutation (nauty on the typed Tanner graph,
or on the basis-independent hypergraph of all low-weight row-space vectors
when the rank allows), re-verified on the row spaces with the negative
control; `inequivalent` when a basis-independent invariant differs in both
orientations (ranks, the dimension of the intersection of the X and Z row
spaces, the exact low-weight enumerator); `gb_family_no` when the two-block
decider finds no unit map, which is the family verdict and not a proof
against other permutations; `undecided` otherwise. Equivalent pairs with two
different distance claims are flagged, since the lighter witness transports.

```
uv run --extra research python research/audits/permutation_audit.py run --out research/audits/permutation_audit-<date>.json
uv run --extra research python research/audits/permutation_audit.py recheck research/audits/permutation_audit-<date>.json
```

The 2BGA literature matches are rebuilt from their archive rows on the GAP
tables under `research/kit/groups/`; the QECDB matches are fetched from the
database's API and the fetched rows are kept in the record. Nothing here is a
gate input; `recheck` re-verifies every recorded permutation from the blob
hashes it cites, as `permutation_equivalence.py` does for its ledger.
