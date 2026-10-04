# Campaigns

A campaign is a bounded, reproducible search task: what to look for, where to
look, how much may be spent, and when to stop. It is the input to the loop in
[`../AUTORESEARCH.md`](../AUTORESEARCH.md), not a replacement for it, and it is
not a submission mechanism.

```
campaign  →  many experiments  →  many candidates  →  few validated survivors
          →  human review      →  optional PR
```

| Object | What it is | Where it lives |
|---|---|---|
| Campaign | the task: objective, constraints, methods, budget, stopping | `research/campaigns/<id>/campaign.json`, validated by `schema/campaign.schema.json` |
| Experiment | one run: a family, a budget slice, a seed | a row in the ledger |
| Candidate | one packaged code and the gate's verdict on it | staged in `research/candidates/` (gitignored) |
| Artifact | the submission JSON, its verdict, and any `certs/` entry | `codes/` and `certs/`, only after a human submits it |

## Running one

```python
import sys; sys.path[:0] = ["research/kit", "verify"]
from campaign import Ledger, load_campaign, write_summary
from validate_candidate import validate_candidate

camp = load_campaign("research/campaigns/<id>/campaign.json")
led = Ledger(camp)
led.start_experiment("lifted-product", seed=7)
led.spend(cpu_hours=1.5, candidates_screened=250)
led.record_candidate(doc, validate_candidate(doc))   # refused unless passed
led.end_experiment()
if led.stop_reason():
    write_summary(led.summary(), "research/campaigns/<id>/summary.json")
```

`research/campaigns/smoke-bb-72/run.py` is the same thing end to end, small
enough to run in a test.

## The run contract

Depth, trials, and seeds passed as free-form argv leave no record of what a
lane ran at. Two distances read at different budgets are not comparable, which
is why `leader_audit.py pair` re-runs both sides at matched depth; that repairs
the problem after the fact, and `run_contract` records the same fact up front.

```json
"run_contract": {
  "template": "python research/cyclic_gb.py --m {m} --trials {trials} --seed {seed}",
  "parameters": { "m": 337, "trials": 2000000, "seed": [51, 52] }
}
```

Every placeholder in the template needs a value in `parameters`, and every
value needs a placeholder, so the declared depth cannot drift from the
invocation. `research/campaigns/w8-2dlocal-n700-1000/campaign.json` carries a
worked one.

`Ledger.start_experiment` stamps the resolved parameters and a
`contract_hash` onto the experiment row, and `summary()` carries the contract
and its hash. Two summaries with the same `contract_hash` screened at the same
depth: matched depth becomes a field comparison rather than a reconstruction
from two shell histories.

The sweeps read it:

```
python research/cyclic_gb.py --campaign research/campaigns/<id>/campaign.json
```

Flags still work, because a campaign file nobody may depart from is a campaign
file nobody passes. An explicit flag wins and is reported as a deviation, on
the experiment row and on stdout, instead of being absorbed:

```
campaign w8-2dlocal-n700-1000, contract 4660072e3076bb42: lx=20 trials=300000 ...
  deviation: trials contract=100000 used=300000
```

The contract constrains nothing a campaign may claim. A candidate is a find
when `verify/validate_candidate.py` says so and at no other point.

## Two things a campaign cannot do

**Its constraints are a screening filter, never a claim.** A campaign may
restrict a search to `local-2d-bilayer` at check weight 8. Which track cell a
finished code actually lands in is computed by the verifier from `(H_X, H_Z)`
and the layout. `Campaign.in_scope` answers "is this worth another rung", and
its answer never reaches a submission document. It narrows the ladder and does
not forbid staging: a strong candidate that falls outside the declared window
should still be packaged, validated and reported, and an out-of-scope screen is
not a negative result, because nothing was measured.

**It cannot weaken the gate.** `Ledger.record_candidate` refuses any verdict
without `passed: true`, and `Ledger.best_score` reads the objective off the
recorded survivors, so neither a find nor a `target_reached` stop can rest on
a candidate `verify/validate_candidate.py` did not accept. A campaign never
opens a PR: unattended runs stage for review, and publication follows
`../../AGENTS.md` unchanged.

## Ending one

A campaign owes its ledger and its negative results whether or not it found
anything. Zero submissions is a complete, reportable outcome, and the closed
family is the finding. `summary.json` is the machine-readable half;
`TEMPLATE_report.md` is the human half. A committed `summary.json` is what
`./qldpc recent` lists under campaign summaries (status, experiments,
survivors, frontier advances, negative results, families), and
`./qldpc recent --json` hands the same fields to the next session as data,
so a closed family is learned from the summary rather than from the report.

`abandoned` keeps everything a run produced. Stopping early throws nothing
away.

The ledger is held in memory, so a kill loses it. Pass `journal=` and every
experiment is appended to a JSONL file as it closes, which narrows the loss to
the experiment in flight:

```python
from coordination import staging_dir
led = Ledger(camp, journal=f"{staging_dir()}/ledger.jsonl")
...
back = Ledger.from_journal(camp, path)      # everything that had closed
```

One journal per executor. `Ledger.merge` folds two of them into one, keyed by
`(family, seed)`, so the same family at the same seed is counted once and its
budget is not charged twice, and survivors are unioned on the verifier's
fingerprint. That is what turns two executors handed the same campaign file
into one campaign rather than two results a human compares by hand.

`write_summary(led.summary(), ".../summary.json")` still overwrites in place
whenever it is called, and the status it records is `paused` until a stopping
condition fires.

## The run manifest

`summary.json` says what a campaign found. It does not say what produced it:
which code snapshot ran, at what depth, with which seeds. Those lived in a
shell history, so a note quoting "5.3M trials" pointed at nothing a reviewer
could open. `manifest.json` is the other half.

```python
led = Ledger(camp,
             manifest="research/campaigns/<id>/manifest.json",
             params={"trials": 2_000_000, "ladder": [[2000, 12], [20000, 11]],
                     "seeds": [51, 52], "workers": 8})
```

It is rewritten at every experiment boundary, so a kill leaves a manifest for
everything that closed. It records:

| field | why it is there |
|---|---|
| `snapshot` | git HEAD, plus a hash of the working-tree diff and whether there was one. HEAD alone does not identify a run: campaigns are normally run from a tree with edits in it, and two such runs give different numbers from one sha |
| `params` | the depth, ladder, seeds and workers actually invoked, recorded as given rather than re-derived from the campaign file |
| `seeds`, `experiments`, `consumed` | what was run and what it cost |
| `negative_results` | the dead ends: collapsed ladders and closed routes. A stage-only run drafts no note (`../AUTORESEARCH.md`, "Output & housekeeping"), so if these are not here they are lost with the staging directory |
| `survivor_verdicts` | `(n, k, d)` and a fingerprint of each survivor's gate verdict, enough to detect one whose verdict changed between the run and the PR |
| `logs` | excerpts promoted out of gitignored `*.log` files |

`snapshot` and `params` are also written into `summary.json`, so a summary
separated from its manifest still identifies its own run.

### Logs

`*.log` is gitignored, which is right for a multi-gigabyte trial log and wrong
for the six lines a written claim rests on. Promote those:

```python
led.attach_log(f"{staging_dir()}/lane3.log",
               why="the 5.3M trial count in the note")
```

The excerpt is the tail, capped, with the full file's sha256 and a
`truncated` flag beside it. Say in `why` which claim it supports: an excerpt
nobody can connect to an assertion is weight without evidence.
`verify/check_prose.py` rejects a `*.log` citation and points here.

### When a manifest is required

Any campaign whose numbers appear in `notes/` or `fieldnotes/` commits its
manifest beside the note, and the note cites it. A campaign that submits
nothing does not need one.

## The screening registry

`research/candidates/` is gitignored, so a family screened and discarded
leaves nothing behind and the next session pays for it again. The committed
record is the summary, and the registry is what the summaries add up to
(issue #2726).

Three fields on each experiment row carry the outcome rather than the tally,
and `research/kit/campaign.py` writes them:

```python
led.start_experiment("generalized-bicycle", seed=7,
                     mode="novel_generation",
                     params={"ring": "Z_341", "a_support": "6+4x2"})
led.record_screen(trials=300_000, d=78, backend="fast")
led.record_verdict("not_run")      # screened and dropped before the gate
led.end_experiment()
```

| Field | What it carries |
|---|---|
| `params` | the construction parameters that identify this family member, beside the resolved run parameters. A family name alone cannot say whether this member was tried |
| `screened` | the lightest weight the screen found, the trial count it was read at, and which backend read it. The depth is part of the reading: NumPy iterations and fast-RIS samples are not comparable budgets. A sampled reading must carry its trial count; a structural or solver reading has none, and records what it searched instead, rather than borrowing a number from somewhere else |
| `verdict` | `passed`, `refuted`, `held`, `duplicate`, `dominated`, or `not_run`. `not_run` is the ordinary case and the useful one: it says the member was screened and dropped before the gate |
| `mode` | how the candidate was arrived at. The kit's samplers are rejection sampling with no memory between candidates, which is `novel_generation`; a survivor count cannot distinguish a budget spread across a family from one spent mutating a single lineage |

`summary()` also computes `screen_quality`: per family, the Spearman rank
correlation between the screened distance and the gate outcome, with the pair
count beside it. Rank correlation and not error, because `distance_rand` at
low trials is a ranking instrument rather than a measuring one, so an error
bar against a depth-mismatched number would be fiction. A family whose screen
orders candidates the way the gate does can be trusted to spend a ladder
budget on the right rung; one whose screen does not is good for discarding
and not for choosing. The correlation is `null`, not `0.0`, when the rows
carry no spread: nothing was tested is a different statement from the screen
is uninformative.

Summaries are validated against
[`../../schema/campaign_summary.schema.json`](../../schema/campaign_summary.schema.json)
on the way out, so a reporting bug surfaces where the summary is written.

### Reading it

```
qldpc screened --family generalized-bicycle --param ring=Z_341
qldpc screened --param n_side=5 --param t=3 --json
```

Parameters match as a subset, so a query on the ring alone finds every member
screened over it. The answer is the committed record of what was tried, at
what depth, and how it went. It is advisory: the gate remains the only thing
that admits a code, and a row saying `passed` records that
`verify/validate_candidate.py` once said so, nothing more.

### Backfilled summaries

A summary reconstructed from prose after the fact carries a `backfilled`
block naming the sources it was read out of. A backfilled row carries what
its source stated and nothing more: where a seed or a screening depth was
never written down, the field is absent rather than guessed. The September
2026 campaigns are backfilled this way, three of them generated from their
own committed audit JSON rather than typed from the prose around it.
