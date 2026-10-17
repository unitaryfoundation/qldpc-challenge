# autoresearch quickstart

The minimal loop and the rules you may not break. Everything else is in
[`AUTORESEARCH.md`](AUTORESEARCH.md), the detailed manual; load the section you
need when you need it rather than all of it up front.

## Two rules

**No code is a "find" until `verify/validate_candidate.py` returns
`passed: true` for it.** The surrogate ranks candidates cheaply; it never
claims one. Never write your own distance check and never edit anything under
`verify/` — CI pins its hashes. If you think the gate is wrong, stop and tell
the human.

**A found low-weight logical is the most expensive data we produce — never
lose it.** Persist every candidate through `submit.make_submission` and
`submit.save_submission`, which embed the witness. An ad-hoc `python -c` that
prints a distance and exits throws away the part that cost the compute.
`save_submission` refuses a document the gate's verify step would refuse (a
direct sum, a check over the weight cap, a malformed or mistyped document) and
keeps it under `rejected/` beside the path with the failed checks, so fix the
document, or drop the code (issue #3616).

Unattended runs stage candidates in `research/candidates/` and stop there: no
writes to `codes/`, no commits, no PRs. A human decides what lands. Several
sessions stage there at once, so take a run directory from
`coordination.staging_dir()` rather than writing a flat `<n>-<k>-<d>.json`
another session is about to write too, and pass the name through
`coordination.unique_path(path, doc)`: `save_submission` refuses to write over
a different candidate, and `unique_path` gives the second one its own name.

## The loop

```
  pick a direction ─▶ build (HX,HZ) ─▶ prescreen ─▶ estimate distance ─▶ package ─▶ VALIDATE ─▶ stage
```

```bash
./qldpc recent --family <your family>    # what already landed, and what failed
./qldpc screened --family <your family>  # what was screened, at what depth, how it went
./qldpc targets                          # which track cells are open
```

If several sessions run at once, say where you are aiming, so a second one can
decide whether to build the same ladder:

```bash
./qldpc targets --claim weight-6/unrestricted --campaign <your campaign>
./qldpc targets                          # a live claim is printed per cell
./qldpc targets --release weight-6/unrestricted   # or let --ttl (2h) expire it
```

A claim is a note, not a reservation. Nothing enforces it, `verify/` never reads
it, and two sessions may hold one cell at once — the second write reports whose
claim it displaced rather than refusing, because your call is better made with
the information than without it. It is held by the session you are typing in:
one shell, one session, so `--claim` and `--release` agree without your
exporting anything (`QLDPC_RUN_ID` pins it for a harness that needs to). The
cell name is `<weight>/<locality>`; anything else is refused with the valid
names rather than written as a claim no reader can find.

```python
import sys; sys.path[:0] = ["research/kit", "verify"]
from bb import build_bb
from coordination import staging_dir, unique_path
from surrogate import distance_rand
from submit import make_submission, save_submission

# gate: duplicate -- the board already holds this code. Keep in step with the
# paragraph below; research/test_documented_examples.py fails if the two disagree.
HX, HZ = build_bb(6, 6, [(3, 0), (0, 1), (0, 2)], [(0, 3), (1, 0), (2, 0)])
d = distance_rand(HX, HZ, trials=600)        # an upper bound, never a proof
doc = make_submission(HX, HZ, name=f"[[72,12,{d}]] my BB code",
                      construction="Bivariate bicycle on Z_6 x Z_6.",
                      authors=["your-handle"], family="bivariate-bicycle",
                      confidence="upper_bound")
path = unique_path(f"{staging_dir()}/72-12-6.json", doc)   # research/candidates/<run_id>/...
save_submission(doc, path)                   # a second [[72,12,6]] gets its own name
print(path)
```

```bash
uv run --extra research python research/kit/coordination.py gate <the path it printed>
```

Exit 0 and `passed: true`, or it is not a find. The gate is the expensive step,
so screen widely and spend it only on survivors.

Two of the gate's refusals cost nothing to make yourself: a direct sum (a
stabilizer group in independent blocks on disjoint qubits) and a code the board
already holds. `search.screen` makes both before spending the distance screen
and flags a Weisfeiler-Leman signature match as `board_wl`,
`submit.make_submission` refuses to package a direct sum, and
`uv run python research/kit/prescreen.py <path>` repeats them on a staged file
(issue #3620).

That command runs `verify/validate_candidate.py` unchanged and writes the
verdict it returned to `<the path>.verdict.json`, beside the candidate. A
candidate the verifier's structural half refuses is not gated at all: the
command writes the failed checks to `<the path>.preflight.json` and exits 1.
Running the gate script directly prints the same verdict and writes nothing,
so the evidence for a find lives in a scrollback and is gone with the
session; the witness in the candidate file is only half of what a reviewer
needs. In code, `coordination.gate_and_record(path)` does the same and
returns the verdict.

**The example above will not pass, and that is the point.** `[[72,12,6]]` landed
on the board long ago, so the gate exits 1 with `passed: false` and
`duplicate: identical to board entry 72-12-6.json`. Read the snippet as the
mechanics, not as a candidate. Most of the obvious constructions are already
taken, so expect to choose your own parameters before anything passes, and
treat `duplicate` as the gate working rather than as a bug.

Sweep a whole family with `search.py` instead of one code at a time. Repeat
until the budget is spent, then report the survivors with their honest labels:
`upper_bound`, "advances this board cell", novelty unverified.

## Record what you screened

A family you screened and dropped leaves nothing behind: the staging directory
is gitignored, so the next session pays for the same search again. The one
committed record is `./qldpc screened`, and it can only answer **at what depth**
if a run wrote the depth. `research/kit/campaign.py` is what writes it, and
nothing calls it on your behalf:

```python
from campaign import Ledger, load_campaign, write_summary

camp = load_campaign("research/campaigns/<id>/campaign.json")   # see below
led = Ledger(camp)
led.start_experiment("bivariate-bicycle", seed=7, mode="novel_generation",
                     params={"l": 6, "m": 6})
led.record_screen(trials=300_000, d=6, backend="fast")   # the depth
led.record_verdict("not_run")      # screened, dropped before the gate
led.end_experiment()
write_summary(led.summary(), "research/campaigns/<id>/summary.json")
```

`record_screen` is the one that matters: `trials` is the budget the number was
read at, and a screening depth read at one budget is not comparable to the same
depth read at another. `not_run` is the ordinary and useful verdict — it says
the member was screened and discarded before the gate.

Two prerequisites, both real. It needs a `campaign.json`;
`campaign.scaffold_campaign` builds one, or copy
the smallest complete example —
`research/campaigns/smoke-bb-72/run.py` — or
[`campaigns/README.md`](campaigns/README.md), which documents the whole
contract. And a `summary.json` is what makes the run visible to the next
session; without one the work stays local.

## Where the detail lives

| You need | Read |
|---|---|
| recording a screen so the next session does not repeat it | `campaigns/README.md` |
| constructors, group algebras, coset codes | `AUTORESEARCH.md` §1 |
| the surrogate and its failure modes | §2 |
| sweeping a family, the escalation gate | §3 |
| packaging, layouts, the 2d-local tracks | §4 |
| exact confirmation for a standout | §6 |
| what the gate catches and why | Pitfalls |
| what a finished candidate looks like | Definition of done |
| every module in `research/kit` | Module reference |

Submitting on a contributor's behalf is a different workflow with different
permissions: see [`../CONTRIBUTING.md`](../CONTRIBUTING.md) and
[`../AGENTS.md`](../AGENTS.md).
