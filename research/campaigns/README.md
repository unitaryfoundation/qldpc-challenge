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

## Two things a campaign cannot do

**Its constraints are a screening filter, never a claim.** A campaign may
restrict a search to `local-2d-bilayer` at check weight 8. Which track cell a
finished code actually lands in is computed by the verifier from `(H_X, H_Z)`
and the layout. `Campaign.in_scope` answers "is this worth another rung", and
its answer never reaches a submission document.

**It cannot weaken the gate.** `Ledger.record_candidate` refuses any verdict
without `passed: true`, so no campaign summary can report a find that
`verify/validate_candidate.py` did not accept. A campaign never opens a PR:
unattended runs stage for review, and publication follows `../../AGENTS.md`
unchanged.

## Ending one

A campaign owes its ledger and its negative results whether or not it found
anything. Zero submissions is a complete, reportable outcome, and the closed
family is the finding. `summary.json` is the machine-readable half;
`TEMPLATE_report.md` is the human half.

`abandoned` keeps everything a run produced. Stopping early throws nothing
away.
