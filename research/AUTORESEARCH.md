# autoresearch: find new qLDPC codes for a direction

Tool-agnostic guide for an LLM (or any agent, or a human newcomer) doing autoresearch on the
qLDPC challenge. Point your model at this file — nothing here is specific to any one agent
tool. It is both the **operating manual for the research loop** and the **reference for the
`research/` starter kit**: constructing a code, estimating its distance, and packaging a
verifiable submission.

A run does not need all of it. [`QUICKSTART.md`](QUICKSTART.md) is the loop and the rules on
one page; come back here for the section the run actually reaches.

The default path in `research/` is pure NumPy. An optional bit-packed C++ RIS backend can be
built with `make fast` for larger screens and confirmation runs; Python still validates its
witnesses.

Layout:

```
research/
  kit/         the core toolkit: constructors, surrogate, search + samplers, packaging
  local2d/     open-boundary planar (2D-local) codes: builders + distance-scaling theory
  candidates/  staging area for validated finds (gitignored working output)
  README.md    the map: every top-level script, its status, and which of two look-alikes to use
```

For in-process imports, put `research/kit` (and `verify/`) on `sys.path`; every kit module
imports its siblings by bare name (`from bb import build_bb`).

## The one rule that makes this trustworthy

**No code is a "find" until `verify/validate_candidate.py` returns `passed: true` for it.**

- Never write your own distance check, "good enough" heuristic, or convergence logic to judge
  a candidate. The screening surrogate is for *ranking candidates cheaply*, never for
  *claiming* one. The gate is the only thing that decides.
- **Never edit anything under `verify/`** — that is the trusted stack (verifier, refuter, the
  gate). CI pins its hashes; tampering fails the build and is pointless. If you believe the
  gate is wrong, **stop and tell the human**; do not route around it.
- Believe the gate. If it reports `refuted`, your code's real distance is lower than you
  thought — that is the surrogate fooling you, not a gate bug.

```
uv run --extra research python research/kit/coordination.py gate candidate.json   # exit 0 iff passed
```

That is `verify/validate_candidate.py` run unchanged, with its verdict also written to
`candidate.verdict.json` beside the candidate. Calling the gate script directly gives the same
verdict on stdout and keeps nothing (issue #2781).

or in-process (add `verify/` to the path first):
`import sys; sys.path.insert(0, "verify"); from validate_candidate import validate_candidate`.
The verdict's `gates` block is your evidence; `labels` are what you show the human.

## The loop

```
  pick a direction ─▶ build (HX,HZ) ─▶ estimate distance ─▶ package ─▶ VALIDATE ─▶ stage
    a track cell        bb.py           surrogate.py        submit.py  validate_   for review
    + a family          group_algebra   (witness is free)              candidate
                        coset.py
                            │                                   ▲
                 sweep a family with          (optional) confirm the distance exactly
                 search.py (screen→rank)      with distance.py before promoting a standout
```

If you were handed a campaign definition
(`research/campaigns/<id>/campaign.json`, see
[`campaigns/README.md`](campaigns/README.md)), load it first: its constraints
bound the search below, and its `stopping` conditions, not the budget alone,
end the run. It cannot weaken the gate. Without one, nothing below changes.

0. **Read the shared record first**: `./qldpc recent` (new codes, research
   notes, fieldnotes) and `./qldpc screened --family <family>` (which members
   were already screened, at what depth, and what the gate said: the staging
   directory is gitignored, so this is the only committed record that a
   family was tried and dropped), `./qldpc negatives --family <family>` (why
   earlier campaigns closed a route, under which assumptions, and what change
   would make it worth retrying), then the `fieldnotes/` entries touching
   your intended family — blocked routes and calibration findings live there, and repeating
   them wastes the budget. Recent literature is part of that record:
   [`literature/README.md`](literature/README.md) is the arXiv watch, and its
   ledger says which new papers a human read and what they concluded
   (`uv run --frozen python research/arxiv_watch.py --list relevant`, no network
   needed). Screening there is triage and a distance in an abstract is a claim,
   so a lead from it still has to be reconstructed and passed through the gate
   below before it is a find.
1. **Pick a direction** → a track cell + a family + a budget (below).
2. **Build** `(HX, HZ)` from a constructor.
3. **Estimate** distance cheaply with the surrogate (gets you the witness for free).
4. **Search** a whole family with `search.py` to find the best candidates.
5. **Package** with `submit.make_submission`, then **validate** with the gate — keep only
   `passed: true`.
6. **Stage** survivors for review; loop until the budget is spent, then report.

Recording is not step 7, it is what happens *during* the loop: `kit/campaign.py`'s
`record_screen` is the only thing that writes a screening depth, and without a `summary.json` at
the end none of it reaches `codes/`-adjacent committed state, so the next session repeats the
search. See [`campaigns/README.md`](campaigns/README.md) and the `kit/campaign.py` row below.

To watch the whole loop run once (build → package → the real verifier in-process):

```
uv run python research/test_smoke.py
```

## Organizing the agents that run the loop

The loop above is written for one agent. Several now run it against this repository at once,
and one session often spawns helpers, so who does what is a separate question from what gets
done. Left to a session to invent, it has gone wrong in the ways the fieldnotes record:
parallel sessions racing one shared checkout
(`../fieldnotes/2026-09-08-check-deletion-campaign-retrospective.md`, "submit from isolated
worktrees") and two of a sweep's advances turning out to be parameter duplicates of
concurrent work (`../fieldnotes/2026-09-30-422-amplification-yield.md`). The open
autoresearch write-up of ECDSA.fail (arXiv:2609.09582; the "parallel, role-separated, and
clean-context agents" practice in its section 4.3 and the framework in its Algorithm 3)
describes the organization that worked there, and the primitives it rests on already exist
here: `kit/coordination.py` for per-run staging and advisory cell claims, `kit/campaign.py`
for the shared ledger, and git worktrees for isolation. This section says how to combine
them (issue #4234). Nothing in it changes what may be claimed: the gate decides, as above,
and the rules of this section only decide where the budget goes and who reads which record.

### Three roles

- **A research agent owns one hypothesis**: one family at one parameter range, aimed at one
  cell. It builds, calibrates the generator against a board entry (section 3), screens with
  `search.screen`, works out why the screen came out as it did (a divisor that was never
  shared, a lattice that decoupled, a ladder that was still descending), writes each
  reading with `record_screen` and `record_verdict`, and stages the survivors. It returns
  a compact conclusion, not a narrative: the parameters tried, the depth they were read
  at, the best reading, the verdict, and one sentence on the mechanism. Everything else it
  learned is in its ledger journal or is lost.
- **An engineering agent turns survivors into clean artifacts**, one candidate at a time. It
  packages (`submit.make_submission`, `submit.save_submission` with the `spec=`), runs the
  gate (`coordination.py gate <path>`), runs the matched-depth audit when the gain is on `d`
  alone (section 5b), and, when a human has authorized a submission, renders the note, the
  `codes/` document, and the PR body with `kit/promote.py`. It never widens the search, and
  it is the one that commits a sampler that is good enough to graduate into `kit/search.py`.
- **An orchestrator allocates and stops.** It reads the shared record first (step 0 of the
  loop), writes the direction card, hands each worker one hypothesis and one budget, merges
  the workers' ledgers, stops a route that the direction card's abandon criterion or the
  escalation gate's ladder facts (section 3b) say is stalled, and writes `summary.json`. It
  does not screen or gate anything itself: its context is the one that has to stay small
  and whole for the length of the campaign.

One agent can play all three in turn, and in a single session usually does. The split is
between concerns, and it matters most when the concerns are split across contexts, because
each role then sees only what it needs.

### One hypothesis per fresh-context worker, in its own worktree

A worker that has read fifty ladders carries their conclusions into the fifty-first, and two
workers sharing one transcript share one blind spot. So a worker starts with an empty
context and gets exactly four things: the campaign file, its one hypothesis (family,
parameter range, cell), a budget in the units the campaign spends, and the committed record
for that family (`./qldpc screened --family <family>`, `./qldpc brief --cell <cell>`, and
the `fieldnotes/` touching it). It gives back two: the path of its ledger journal and the
compact conclusion above.

What is isolated, and the mechanics this repository already has for each:

- **The checkout.** `git worktree add <dir> <base>` gives the worker its own tree, so a
  speculative rewrite of a sampler cannot change the baseline the other workers compare
  against, and a worker that dies leaves nothing half-edited in the shared checkout.
- **The staging directory.** `coordination.staging_dir()` is `research/candidates/<run_id>/`
  under the worker's own checkout, so two workers writing `<n>-<k>-<d>.json` cannot
  overwrite each other, and the directory name says which worker to ask. `run_id` is unique
  per process; set `QLDPC_RUN_ID` when a harness wants a readable name or wants two processes
  to share one shelf. Staging, the verdict cache, and the cell claims all live under the
  checkout that wrote them: a claim made from a worktree is not listed by `./qldpc targets`
  in another, so the orchestrator makes the cell claim from its own checkout and the workers
  make none.
- **The filename.** `coordination.unique_path(path, doc)` gives a second candidate with the
  same `[[n,k,d]]` its own name, and `save_submission` refuses to write over a different
  candidate at a path it is handed.
- **The ledger.** `Ledger(camp, journal=f"{staging_dir()}/ledger.jsonl")`, one journal per
  worker, because two processes appending to one file interleave partial lines. The
  orchestrator folds them with `Ledger.merge`, which keys experiments by `(family, seed)` so
  the same deterministic work is counted once, and unions survivors on the verifier's
  fingerprint so one code found twice is one survivor.
- **The gate verdict.** A gate run is per candidate and its verdict is written beside that
  candidate (`<path>.verdict.json`). A worker reports candidates that passed, never a
  family that did.

Two costs follow from the isolation. A fresh process pays the gate's board pass once
(421 s on the machine of section 3d), so a worker gates its survivors in one process rather
than one process per candidate. The orchestrator, not the worker, is where duplicates
between workers are caught: two workers given adjacent parameter ranges can stage the same
code, and `Ledger.merge` folds the survivors, but it cannot fold two staged files, so the
orchestrator checks the merged survivors' fingerprints before anything is packaged.

### Bake-offs

When several routes could spend the budget, give each the same screening budget first,
compare them on one instrument, keep the best few, and only then deepen. The instrument is
the `efficiency` field on `search.screen` records (`kd^2/n`, the board's per-cell headline
figure), read at the same `trials=` and `backend=` for every route and compared within one
cell, never across cells. The matched budget is what makes the comparison about the routes
rather than about who spent more: `distance_rand` returns an upper bound that comes down
with trials, so a route screened deeper looks worse at the screen, and a route whose
ladder was fed more budget looks better at the ladder, and neither difference is a
difference between the codes. Weigh each route's `screen_quality` from the ledger summary
beside its efficiency: a family whose screen does not rank candidates the way the gate does
cannot be deepened on the strength of its screen readings. `search.screen_adaptive` is the
same idea inside one route (widening stages, dropping what cannot reach the target); the
bake-off is across routes, and together they approximate a beam search over the campaign's
families, which is how the ECDSA.fail participants described theirs.

Deepen the survivors with the ladder and the escalation gate (section 3b), budgeted by the
costs in section 3d, and record every route the bake-off dropped: a `record_screen` at the
bake-off depth, `record_verdict("not_run")`, and a `record_negative` naming the route, so
the next session sees that the route lost a comparison at that depth rather than that it was
never tried.

### A claim is a hypothesis until a second run reproduces it

One worker's survivor is a hypothesis. It becomes a result when a second, independent run,
with a fresh context and its own worktree, reaches the same code and the same bound.
Independence means the second run shares none of the first's state: not its transcript, not
its seeds, and not its verdict cache, which lives under the first worker's staging
directory and is therefore not seen from another checkout. Three levels, in order of cost:

1. **Rebuild from the recipe alone.** `python research/kit/rebuild.py --constructor
   <module.function> --params '<json>'` prints the verifier's fingerprint of the code the
   recipe builds; it must equal the `candidate.fingerprint` in the staged candidate's
   `.verdict.json`. A code the recipe cannot rebuild is not a result, whatever its bound.
2. **Re-measure at matched depth.** `research/audits/leader_audit.py screen <candidate>
   [<peer> ...] --trials <N> --seeds <fresh seeds> --witness-dir <dir>` reads the candidate
   and any peer it beats at one budget. For a gain on `d` alone this is already required
   before packaging, as `leader_audit.py pair` (section 5b), and the `drop`, `redirect`,
   `credible`, and `inconclusive` decisions there apply unchanged: `inconclusive` is no
   information, never corroboration. Keep the witness directory; a lighter logical found
   here is the most expensive object the campaign produces.
3. **The gate, run by the reviewer.** `coordination.py gate <path>` from the reviewer's own
   checkout, so the random search is spent again rather than served from the first
   worker's cache.

The ECDSA.fail teams also had agents from different model families read one another's
conclusions before a claim was trusted. The equivalent here is a reviewer that reads the
compact conclusion and the ledger journal and tries to break them, and its opinion has the
status the escalation gate already gives a judgment model's verdict: advisory, kept in the
staging journal, and never repo evidence. The evidence is the gate verdict beside the
candidate and the witness files, and nothing a reviewer writes adds to or subtracts from
them.

### The shared state is the ledger

ECDSA.fail's agents kept their shared state in hypothesis queues, iteration logs,
scoreboards, and regression records rather than in any one agent's context. The equivalents
here are the direction card (the hypothesis), the ledger journal (the iteration log),
`./qldpc targets` and `./qldpc brief` (the scoreboard), and `./qldpc screened` (the record of
what was tried, at what depth). Per-agent scratch notes have no equivalent, on purpose: a
reading that is not in a journal is lost when the worker's context is, so the ledger is
the only place a reading goes, and the merged `summary.json` is the only thing the campaign
hands to the next one (`campaigns/README.md`, "Ending one").

## 1. Pick a direction and a family, build `(HX, HZ)`

A **direction** is a concrete target: a track cell (locality class × weight class, e.g.
`unrestricted × weight-6`) plus a family/approach and a budget. If the user's direction is
vague, translate it: look at the board (`codes/*.json`, the site, `TRACKS.md`) for a **sparse
cell** or a **record to beat**, and aim there.

Write the direction down before building. A campaign's `direction` block (the direction
card, `research/campaigns/README.md`) holds the hypothesis, the cell and family, the entry to
beat and on which axes, the budget in the units the run spends, why it is feasible here, what
is claimed to be new and against what, what a positive result is worth as a statement, the
abandon criterion `research/kit/escalation.py` can enforce, and what a negative result would
teach. `scaffold_campaign(..., card={...})` writes it and `summary.json` carries it, so the next
session can tell a direction abandoned for a reason from one nobody came back to.
`research/campaigns/bb-w6-n-le-100-trinomials/campaign.json` is a filled-in example.

When a direction closes, record the negative with what it assumed and what would reopen
it: `led.record_negative(what, detail, assumptions=[...], revisit_if="...")` (issue #4233,
`campaigns/README.md` "Ending one"). `./qldpc negatives --family <family>` reads these back
across every committed campaign, so a later session learns not only that a route was tried
but whether the reason it failed still applies. A negative without them records that a
route failed, not whether the reason still holds.

Track membership is **computed by the verifier**, not declared: the check-weight class
(`weight-4`/`weight-6`/`weight-8`) is derived from the max row weight of `H_X`, `H_Z`, and the
locality class from the layout (none → `unrestricted`). The `family` tag below is the only
self-declared label, and it is filterable, never ranked. The weight column is the class each
family typically lands in.

| Module | `family` tag | Typical weight class | CSS holds because |
|---|---|---|---|
| `bb.py` | `bivariate-bicycle` (torus Z_l × Z_m, the "gross code" family) | `weight-6` | abelian circulants commute |
| `group_algebra.py` | `generalized-bicycle` (2BGA on **any** finite group) | `weight-6` | left/right multiplication commute |
| `coset.py` | `2bga-coset` (G/H cosets, record efficiencies; non-normal H) | `weight-8` | left action commutes with right action by the normalizer |
| `nonabelian_lp.py` | `lifted-product` (LP of two base matrices over F_2[G], G non-abelian; the mitten / ZSZ-LP shape of arXiv:2607.28795, arXiv:2607.27644) | `weight-8` (entry weights set it: 6 to 9) | entries of A act by the left regular representation, entries of B by the right one, and the two commute |

`bb.py` is the place to start — the simplest, and any choice of monomials is a valid code.
`group_algebra.py` generalizes it to non-abelian groups (which can reach odd `k`); `coset.py`
generalizes further to the highest known efficiencies. For the `2d-local-*` tracks, build with
the open-boundary planar engine in `local2d/` (see its README for the full loop). For a family
the kit can't sweep, write a new `sample_<family>` generator (same `(spec, HX, HZ)` shape as
the ones in `kit/search.py`) — good ones graduate into `kit/search.py`.

```python
from bb import build_bb, KNOWN
HX, HZ = build_bb(l=6, m=6, A_terms=[(3,0),(0,1),(0,2)], B_terms=[(0,3),(1,0),(2,0)])
```

Check the basic parameters with `css.py`:

```python
from css import compute_k, verify_css
assert verify_css(HX, HZ)          # H_X H_Z^T = 0 over GF(2)
k = compute_k(HX, HZ)              # = n - rank(HX) - rank(HZ), exactly what the verifier recomputes
```

To make a **new** code, change the monomials / group / supports. A code is only *interesting*
if it advances a cell's Pareto frontier over (n, k, d) — see `../CONTRIBUTING.md`.

## 2. Estimate the distance (and get a witness for free)

Distance is the hard part: computing it exactly is NP-hard, so the board uses a **trustless
witness** — you attach an explicit low-weight logical operator and the verifier confirms it,
certifying `d <= value`. `surrogate.py` finds that witness for you:

```python
from surrogate import distance_rand, lightest_logical
d = distance_rand(HX, HZ, trials=600)        # an UPPER BOUND on min(dX, dZ)
wx, x_witness = lightest_logical(HX, HZ)     # lightest X-logical: (weight, support)
wz, z_witness = lightest_logical(HZ, HX)     # lightest Z-logical
```

**This is the one place honesty matters most:**

- `distance_rand` returns an **upper bound**. It found *a* logical of that weight, so
  `d <= value`; it is Monte Carlo, **not a proof**. A high `d` at low trials usually means the
  search hasn't found the light logical yet — *not* that the code is good.
- The matching submission confidence is `"upper_bound"`. An `"exact"` claim is a *separate,
  server-certified tier* (`../verify/certify.py`) — don't mark `exact` unless you mean to earn it.
- `mixed_volume(S_f, S_g)` gives a fast, matrix-free **upper bound on k** for bivariate
  constructions — use it to screen candidate exponent sets before you ever build a matrix.

You do not need to convince yourself the distance is right — that is the gate's job (step 5).
The surrogate is only to *rank candidates cheaply*.

## 3. Search a family

Building one code is step one; *discovering* a good one means sweeping a family. `search.py` is
a generic funnel: generate candidates → screen each cheaply → rank by efficiency and Pareto
frontier.

**Calibrate the generator against a known board entry before you sweep it.** A generator
pointed at the wrong parameters still returns well-formed `n`, `k` and `w`, so a sweep of the
wrong family is structurally indistinguishable from a real negative — it just reports numbers
that mean something else. Rebuild one entry you can check and assert it matches:

```python
import json
import numpy as np
from boundary_engine import build_planar, S_F_TILE4, S_G_TILE4_MAIN

HX, HZ, _ = build_planar(21, 22, S_F_TILE4, S_G_TILE4_MAIN)   # [[924,18,31]]
board = json.load(open("codes/924-18-31.json"))
built = {tuple(np.nonzero(r)[0].tolist()) for r in np.asarray(HX, dtype=bool)}
assert built == {tuple(r) for r in board["checks"]["X"]}
```

Compare the **check matrices, not `(n, k, w)`**. Those three are the wrong instrument here:
`n` and `k` are fixed by the lattice and `w` by the bulk weight, so none of them responds to
half the parameters. At the 21×22 lattice above, swapping the B-support for a wrong one still
reports `(924, 18, 8)` — while sharing only 38 of the board entry's 475 X check rows. An `assert`
on `(n, k, w)` passes on the wrong code, which is the failure this step exists to catch.

The construction string of the matching `codes/<n>-<k>-<<d>>.json` names the parameters that
produced it. Read it before inventing your own — for most families the board entry *is* the
calibration target, and only a handful of entries record their parameters at all, so this is
worth doing once and reusing. Prefer the module's named constants (`S_F_TILE4`,
`S_G_TILE4_MAIN`, …) to literals: the supports **are** the family, and a different pair is a
different code rather than a variant of this one. Name every pair the board records, and scope
each name to the entries that actually attest it — a support set that is constant across one
paper's entries is not constant across the function's.

```python
from search import screen, pareto_frontier, sample_bb, update_leaderboard
records = screen(sample_bb(400, seed=7), min_k=4, min_d=4, trials=250)
records[:5]                       # best by k*d^2/n (the board's headline metric)

# ``auto`` uses gf2_fast when available and otherwise falls back to NumPy.
records = screen(sample_bb(10_000, seed=7), min_k=4, min_d=4, trials=2_000,
                 backend="auto", threads=8)
pareto_frontier(records)          # the non-dominated codes over (n, k, d)
update_leaderboard("board.json", records)   # merge + persist, so a sweep can resume
```

`screen` consumes any iterable of `(spec, HX, HZ)` triples, where `spec` is a JSON-serializable
description of how the code was built — so you can point it at **your own generator** for any
family. `sample_bb` is a ready-made one; a 2BGA or coset sampler over `group_algebra` / `coset`
has the same shape. `backend="fast"` requires `make fast`; `threads=` controls its CPU workers.
The `trials` value is backend-specific: NumPy iterations and fast RIS samples are
not comparable screening budgets. All screening values remain upper bounds, and
finalists must still pass the validation gate.

**Two refusals the gate makes before any distance work, `screen` makes for you**
(`kit/prescreen.py`, issue #3620). A candidate whose stabilizer group splits into
independent blocks on disjoint qubits is a direct sum, not one code, and the gate
refuses it structurally; 25 of the 64 gate runs at `n <= 64` in the ten days before
that issue died this way, most of them from one small-torus generator whose
arithmetic-progression supports decoupled the lattice. A candidate whose fingerprint
the board already holds is a duplicate, and one that shares a board entry's
Weisfeiler-Leman signature is probably a permutation of it; the weight-6 band drew
ten such flags in the same window, each a gate run spent re-deriving a board code.
`screen` and `screen_adaptive` drop the first two and carry the third as `board_wl`
on the record (`board="drop"` drops it too, `board=None` skips the board), and
count every outcome in `audit=`:

```python
audit = {}
records = screen(my_generator(), min_k=4, min_d=4, trials=250, audit=audit)
audit   # candidates, rejected_disconnected, rejected_board_exact,
        # rejected_board_wl, flagged_board_wl, rejected_repeat, ...
```

A high `rejected_disconnected` is a generator bug: fix the index set, not the
filter. A high `flagged_board_wl` says the family is already dense on the board
and the budget belongs elsewhere. The checks are the verifier's own arithmetic
imported from `verify/` (`_stabilizer_block_count`, `css_fingerprint`,
`signature`) run against the gate's own board index, so they decide exactly what
the gate decides and nothing the gate would not.

**Check a sampler's reach before you sweep it.** Each of the four samplers above carries its
ceiling at the end of its docstring, and the binding one is usually the *check weight*, not `n`.
Measured over 3000 draws each at their defaults:

| sampler | max `n` | max check weight |
|---|---|---|
| `sample_bb` | 240 | 6 |
| `sample_dihedral` | 320 | 8 |
| `sample_metacyclic` | 320 | 8 |
| `sample_kasai_affine` | 684 | 8 |

Every one of the board's 25 most efficient entries has a check weight of at least 12, and they sit
at `n` between 630 and 682. So the sweep above — `sample_bb` at 250 trials — cannot reach the
efficiency frontier in any cell, and a large sweep of it will spend its budget producing records
that are dominated on arrival. For the weight-6 `unrestricted` cell the frontier runs from `n`
12 out to 960 with a best `kd²/n` of 30.48, and its *competitive* region starts around `n >= 400`,
well past what `sample_bb` builds.

Raise `weight=` on a 2BGA sampler to lift the check-weight cap, or widen `l_range`/`m_range` on
`sample_bb`; `weight` is the number of monomials per side, so the check weight is `2 * weight`.
`sample_kasai_affine` is the one sampler whose `n` already reaches the frontier's band, and it
needs only `weight` raised to compete there. Which of these pays off is a research question, not a
mechanical one — the recent high-weight entries came from targeted defining sets rather than
rejection sampling, so read `fieldnotes/` for your family before spending a large sweep.

### 3b. Spend the ladder wisely: the escalation gate (optional)

Deep confirmation is the bottleneck
(`../fieldnotes/2026-07-01-confirmation-is-the-bottleneck.md`), and a screen
artifact chased too far is how it gets wasted
(`../fieldnotes/2026-09-20-screening-traps-at-n-900.md`: 5.3M trials on a
ladder whose first fresh deep rungs had already settled below the bar).
`kit/escalation.py` is the rung-boundary gate against exactly that: at each
ladder rung it weighs *promote to the next depth / hold and re-run fresh
seeds / abandon this ladder*.

The division of labor is strict, and mirrors the gate discipline above:

```python
from escalation import rung_brief, apply_verdict, append_journal
brief = rung_brief(n, k, rungs=[(20_000, 22), (100_000, 20)],
                   bar=106.11, family="pair-partition", spec={"P": 113},
                   next_rung_trials=1_000_000, budget_remaining=8_000_000)
# make the jev_decide call from brief["jev_request"] (the agent harness does
# this; the kit itself stays offline), then enforce it:
decision = apply_verdict(brief, verdict)
append_journal(decision, brief, path=os.path.join(staging_dir(), "escalation.jsonl"))
```

- `rung_brief` computes the facts deterministically from the ladder (best
  bound, flat fresh-seed rungs, efficiency vs the cell bar, budget), and
  formats the `jev_decide` request.
- The judgment model weighs them; **`apply_verdict` owns the policy in code**.
  The default is hold. Abandon is honored only when the ladder proves it safe:
  best bound already below the bar, two fresh rungs flat at that bound, and no
  frontier flag. A still-descending ladder can never be abandoned — the
  screen-to-settled inflation is unbounded. Missing, malformed, escaped, or
  low-confidence verdicts hold.
- A hold destroys nothing: every rung reading is a witnessed low-weight
  logical, and upper bounds stay valid whatever the gate says.
- Jev verdicts are advisory model output, **not repo evidence**: they live in
  the staging journal (gitignored), never in notes, fieldnotes, or PR bodies.

Skipping the gate is always sound — it changes where trial budget goes, never
what can be claimed. To evaluate it, run one campaign with the gate and one
without, and compare trials-spent-to-abandon against the flat-settled point
(the 2026-09-20 metric) on the same families.

The same gate stops a route that was entered knowing it regresses (section 3e).
What differs for such a route is not the stop but the card's statement of what
made it worth starting.

### 3d. Budgeting a sweep: what a rung costs, measured

`research/cost/cost_table.md` (issue #4026; regenerated by `research/cost/measure.py`, see
`research/cost/README.md`) measures, on one laptop, what each step of confirming a candidate
costs at twenty board shapes that cover the cap corners. The constants are that machine's; the
shape of the curve is what to budget from. Per cell, per candidate:

| cell | n | gate (verify, refute, dedup) | RIS 20,000 trials per side (Python) | accelerator 2,000,000 trials | exact certification (60 s per MILP, 120 s cap per side) |
|---|---|---|---|---|---|
| w <= 8, n ~ 100 | 96 to 100 | 9 to 12 s | 13 to 20 s | 7 to 12 s | both sides exact in 8 to 26 s at d <= 10; d = 14 hits the cap |
| w <= 8, n ~ 300 | 294 | 11 to 13 s | 75 to 85 s | 80 to 90 s | cap on both sides |
| w <= 8, n ~ 700 | 682 to 700 | 14 to 18 s | 600 s at k = 20; 250 to 1,550 s implied from the 2,000-trial rate, growing with k | 270 to 800 s | cap |
| w = 9 to 32, n ~ 700 | 682 to 700 | 18 to 45 s | 1,000 to 5,300 s implied (k = 352: 5,200 s) | 760 to 1,670 s | cap |
| any w, n ~ 1,000 | 960 to 1,000 | 15 to 22 s | 900 to 1,350 s implied | 840 to 1,190 s | cap |
| stabilizer (Pauli weight), n ~ 100 | 90 | 13 s | 72 s (one side) | 57 s | no certifier |
| stabilizer, n ~ 700 | 662 to 761 | 20 to 36 s | 680 to 6,700 s implied, growing with k and w | 860 s to 53 min | no certifier |

The gate is bounded whatever the shape: the structural pass is seconds, the refutation runs
under a 10 s wall cap that its last trial can overrun (42 s at k = 352), and the board dedup is
one warm lookup (the first gate call in a fresh process
pays the board pass once, 421 s on that machine). What grows with shape is the deep rung and
the certifier, so the deep rungs are the sweep's budget. At the `qldpc submit` default depth
(20,000 RIS trials per side plus 2,000,000 accelerator trials) one candidate costs under a
minute at n ~ 100, about 4 minutes at n ~ 300, between 13 minutes (w <= 8, small k) and 3.4
hours (k = 352) at n ~ 700, and 45 to 65 minutes at n ~ 1,000. Exact certification closes in
seconds at n ~ 100 for d <= 10 and nothing above that within the cap, so it is the post-hoc
tier for standouts that `fieldnotes/2026-07-01-confirmation-is-the-bottleneck.md` already
described, never a sweep step.

Budget a sweep as survivors = hours x 3,600 / (deep-rung seconds for the cell), after a screen
that costs nothing by comparison (the 400-trial numpy screen reads a candidate in well under a
second at n ~ 100; `research/campaigns/bb-w6-n-le-100-trinomials/` screened 120 in 70 s), and
plan the exact tier separately for the one or two codes the sweep would promote. A time in the
table is a measurement on one machine, not a guarantee; CI runners are not that machine.

### 3c. Above check weight 8: sample the ideal, not the support

Every one of the board's 25 most efficient entries is a cyclic generalized-bicycle code,
`H_X = [circ(a) | circ(b)]` over `Z_m` with `m` near 340 and check weight 12 to 32, and none of
them came from random supports. For that family `k = 2 deg gcd(a, b, x^m - 1)`, so a random pair
of supports has `gcd` 1 or `x + 1` and encodes `k = 0` or `2`: at check weight 12 on `Z_315`,
`Z_330`, and `Z_341`, 150 of 180 random draws had `k = 2` and none had `k` above 12, and
`fieldnotes/2026-08-15-dead-ends-and-leads.md` records the same at prime orders 251 to 347 and
weights 8 to 14. Raising `weight=` on a rejection sampler therefore buys check weight and nothing
else; the ceiling is not the weight, it is that random supports do not share a divisor.

The frontier entries fix the divisor first. `sample_cyclic_gb` does that: an odd `m`, a divisor
`g` of `x^m - 1` whose degree puts `2 deg g` inside `k_band`, and `a`, `b` drawn as sparse
multiples of `g`, so `k` is designed rather than hoped for.

```python
from search import screen, sample_cyclic_gb
records = screen(sample_cyclic_gb(200, m_range=(330, 345), weight=(12, 16), k_band=(120, 200),
                                  seed=7), min_k=100, min_d=20, trials=2000, backend="fast")
```

The factorization of `x^m - 1` is done in `kit/gf2poly.py` over GF(2), so the kit stays
numpy-only; `research/cyclic_gb.py` is the full designed-divisor search stack (ideal enumeration,
fertile-ideal selection, deep confirmation) and needs sympy. Read it, and the construction strings
of the `Z_341` and `Z_337` entries, before spending a large sweep here: the frontier codes came
from many ideals and many words per ideal, not from one draw.

### 3e. Non-monotonic routes: when to accept a temporary regression

Everything above this point climbs. A candidate is kept when it reads above the bar and its
ladder is dropped when it settles below, and the gate rewards exactly that. Climbing is the
right default and the wrong only move. The ECDSA.fail write-up (arXiv:2609.09582, section
4.3.3) puts the problem as "a scalar score rewards immediate progress but may suppress
architectures that require temporary regressions", and its participants' answer was to
restructure a component while tolerating a worse score, repair it afterward, and so reach
circuit families that strict hill climbing had rejected. The board has the same shape:
`research/audits/frontier_history.py --plot-history` draws the frontier's hypervolume as a
step function, flat between the landings that changed a family, and the motto's "a code
that beats no existing entry is still a frontier extension" already says that the
frontier, not the leader, is the objective. Section 3b is the stopping half of this
discipline; this section is the starting half (issue #4237).

**When a route is worth entering worse.** Three signals, each a fact in the record rather
than a feeling about the family:

- A lattice of small improvements that all fail the same way. Every neighbor of the current
  best settles at the same bound, or dies on the same check (the same divisor never shared,
  the same lattice decoupling). `./qldpc screened --family <family>` and the campaign's
  negative results are where that shows; climbing further on that lattice re-measures the
  wall.
- A family whose parameter space is untouched: no screened row, no fieldnote, no literature
  verdict touching it. Its first candidates will read below a cell's tuned leaders, and at
  that point the reading says nothing about the family.
- A construction that would win only if a specific property held: a transform whose output
  the cell has never seen, conditional on a symmetry, a factorization, a commuting pair, or
  a layout the family does not have as built.

**The precondition-search move.** For the third signal, do not ask whether the transform
applies. Write down what would have to hold for it to work, as properties a script can
check, then search for the transform that establishes them. ECDSA.fail reports this as the
strategy that reached its best architecture: a construction that was in print before the
challenge began went untransferred while the question was whether it applied, and the
adaptation came once its prerequisites were stated and a construction establishing them
was searched for. Here the same move reads "a weight-6 planar code at k >= 8 needs checks
that commute across a seam; which quotient of which group gives a seam with that
property?", which names a search, where "is there a weight-6 planar code at k >= 8" names
none. Each prerequisite the family cannot be given is a negative result with its reason;
record it with `record_negative` so the next session does not re-derive it.

**Staging an intermediate without losing it.** The first candidate on such a route usually
passes the gate and is dominated: `passed: true`, `board_advancing: false`, and
`dominated_by` naming the entries that beat it. That is a fact to record, not a rejection.
`AGENTS.md`'s rule holds, a dominated code is a non-frontier result and is never submitted
as a frontier code, and when the code is the base of the next route the record has to say
more than that:

- Stage it as any other candidate (`save_submission` under `coordination.staging_dir()`,
  then `coordination.py gate <path>`), so its witness and its `dominated_by` list are kept
  beside it.
- Record it in the ledger as a survivor that did not advance the frontier:
  `led.record_candidate(doc, verdict)` keeps `board_advancing: false` and the gate's labels,
  and `led.record_verdict("dominated")` marks the experiment's member, so the summary lists
  it under `survivors` with `advanced_frontier: false` and `./qldpc screened` shows it to
  the next session.
- Say why it is expected to improve, in the experiment's `note=` while the route is open,
  and as a `record_negative` whose text names the condition that would reopen it when the
  route is parked. A parked route is a negative with a revisit condition, not a dead end.
- Re-read `dominated_by` at every rung. The route has paid off when a candidate built from
  the intermediate is no longer dominated in its cell, which the gate reports as
  `board_advancing: true`; until then every reading is an upper bound on an intermediate
  and is labeled as one.

**The card.** A campaign that enters a route this way says so in its direction card:
`direction.non_monotonic` holds `why_worth_starting` (which of the three signals, in a
sentence), `regresses_on` (the axes the first candidates are expected to lose on),
`precondition` (what must hold, and the transform searched for to establish it), and
optionally `base` (the board slug or staged intermediate the route starts from). The stop
is the card's existing `abandon_criterion`, applied through section 3b's gate exactly as
for a climbing route: a non-monotonic route gets no second stopping rule, and a ladder that
is still descending is still never abandoned. What the field adds is the statement of what
made the route worth starting, so a later session reading `summary.json` can tell a route
entered on purpose and parked from one that drifted off the frontier.

```python
card["non_monotonic"] = {
    "why_worth_starting": "every weight-6 trinomial neighbor of 90-8-10 at n <= 100 "
                          "settles at d = 10 by 20,000 trials; the lattice is a wall",
    "regresses_on": ["d", "kd2_over_n"],
    "precondition": "a four-term pair whose supports share a divisor of x^l - 1 of "
                    "degree at least 4; search sparse multiples of such divisors, "
                    "not random supports",
    "base": "90-8-10",
}
```

## 4. Package a submission

`submit.py` turns `(HX, HZ)` plus a little provenance into a schema-valid submission. It
recomputes n/k, asserts CSS, extracts the witnesses, and **pre-checks each witness against the
verifier's own criteria**, so the document it returns is built to pass:

```python
from submit import make_submission, save_submission
doc = make_submission(
    HX, HZ,
    name="[[72,12,6]] my BB code",
    construction="Bivariate bicycle on Z_6 x Z_6, A = x^3+y+y^2, B = y^3+x+x^2.",
    authors=["your-handle"],
    family="bivariate-bicycle",
    references=["arXiv:2308.07915"],
    confidence="upper_bound",
)
```

Stage the result under this session's own directory rather than a shared flat name:

```python
from coordination import staging_dir, unique_path
out = staging_dir()                            # this run's own staging directory
save_submission(doc, unique_path(f"{out}/{n}-{k}-{d}.json", doc))
```

`save_submission` raises `CandidateCollision` rather than write over a candidate that is not the
one in hand. Several sessions stage at once and the flat `<n>-<k>-<d>.json` convention hands two
of them the same filename, so the second write used to delete the first one's witness. Re-writing
the same candidate is not a collision, and `unique_path` gives a second candidate with the same
parameters its own name.

`save_submission` also refuses, with `PreflightFailure`, a document the gate's verify step would
refuse: before writing it runs `prescreen.preflight`, the verifier's structural half
(`qldpc_verify.verify(doc, refute=False)`), so what it refuses is exactly what the gate refuses
on the checks before its distance search. The document and the report go to `rejected/` beside
the path, so the witness is kept, and the message says which kind of fix there is: a
`construction` or `weight` failure is the code's and no edit fixes it, `packaging`, `typing`,
`witness`, or `layout` is the document's and the code may be fine. Of 355 gate runs staged in
the ten days before issue #3616, 41 were refused on these checks, and the gate had spent the
random search on most of them first, since a structural failure does not stop the verifier from
earning and then refuting a distance. `preflight=False` writes the document anyway.

Two sessions aiming at the same board cell is a cost, not a correctness problem, but it is a
wasted ladder, so say where you are going before you start one:

```bash
./qldpc targets --claim weight-6/unrestricted --campaign <id> --ttl 180
./qldpc targets                        # live claims are marked on their cell
./qldpc targets --release weight-6/unrestricted
```

The claim is a note to other sessions and nothing more. It lives in a gitignored directory beside
the staging area, `verify/` never reads it, no gate consults it, and it expires — a session
that was killed an hour ago cannot squat on a cell by never releasing it. Crucially it is not a
lock: two sessions may hold one cell simultaneously, and the second write reports the claim it
displaced rather than refusing, because refusing would be enforcing something, and the gate is
the only thing here entitled to enforce anything. Read the claim, then decide.

It is held by the session, not by the process: one shell, one session, so the sequence above
works from a terminal without exporting anything (`QLDPC_RUN_ID` pins it for a harness). The
cell name is `<weight>/<locality>`, checked against the board's own axis names — a name that is
not a cell is refused with the valid ones rather than written as a claim nobody can find.

A recipe makes the search replayable. `search.screen` takes `(spec, HX, HZ)` triples; a spec
carrying `constructor` (`<module>.<function>` under `research/kit`) and `params` (its keyword
arguments) is a recipe `research/kit/rebuild.py` can run. Pass it to
`save_submission(doc, path, spec=spec)` and it is kept as `<stem>.recipe.json` beside the staged
candidate. `kit/promote.py` reads it from there (or from a `recipe` key in the plan) and writes
`repro/<slug>.json` from the final document, with the committed file's hash, into the bundle it
assembles; that manifest is what `qldpc reproduce --construction` re-derives the entry from
(`repro/144-12-12.json` is the worked example, and `submit.write_repro_manifest` is the writer).
Without a recipe the manifest says `not_reproducible`, which is the honest default, not a
failure; without a spec no manifest is written and `reproduce` derives its stages from the entry
alone.

For a small CSS candidate (n <= 90, screened d <= 8) try `escalation.exact_first(HX, HZ, d)`
before the first deep rung: the certifier closes those in seconds, and `d =` beats a ladder's
`d <=`. Anything but `outcome == "exact"` leaves the ladder as it was.

Above that band, `escalation.cc_first(HX, HZ, d)` asks Qubitserf's connected-cluster exact
distance where the calibration in `../fieldnotes/2026-10-14-qubitserf-what-it-is-for.md` says it
reaches (n <= 937, screened d <= 12, a 30 s cap: 211 of 211 certified entries agreed with the
board's certifiers, median 0.08 s over 279 codes), and `escalation.exact_or_cc_first` dispatches
between the two with the certifier staying the decider inside its band. The connected-cluster
answer is a screen, never a certifier: `screen_inflated` says the screened reading is too high
and names the weight to search a witness at, `confirmed` says a deeper ladder cannot lower it,
`timeout` leaves the ladder as it was, and none of them ends a ladder or sets
`confidence: exact`. Without the out-of-band Qubitserf build the stage returns
`outcome: unavailable` and nothing else changes. The caps are module constants that name the
calibration record, so a re-measurement changes them in one place (issue #3438).

Before any of this, `./qldpc brief --cell <weight>/<locality> --family <tag>` prints one bounded
snapshot: the cell's frontier and bar, what the registry says was screened for the family, what
landed recently, and the fieldnotes that touch it (`--json` for the record).

`make_submission` runs the witness search itself and records it: each side's
`witness_provenance` carries `found_by` (the authors as `@handles`, or `found_by=` when the
operators came from someone else), the date, `found_at_samples` and `survived_samples` equal to
`trials`, the tool, and the seed. That block is what a later refuter has to beat, and
`verify/check_authorship.py` reads credit from it, so the document declares schema `0.2`.

`family` is a filterable Layer-2 tag, never ranked. You do **not** declare which tracks you
enter: the verifier computes primary-track membership (the weight and locality classes) from `H`
and the layout. To enter the `2d-local-*` tracks, give the code a layout — pass
`coordinates=[[x,y], ...]` or `[[x,y,z], ...]` (one per qubit) and `layers=`; `submit.py` fills the `locality` block
and computes the interaction radius, and the verifier derives the locality class from it.

## 5. Validate with the gate (do not skip)

Run `validate_candidate` on the packaged doc (see **The one rule** above). Keep only
`passed: true`. The verdict's `gates` are your evidence; its `labels` are what you show the
human. This — not the surrogate, not your own judgment — is what decides whether you have a find.

Before you pay for the gate on a staged file, `uv run python research/kit/prescreen.py <path>`
runs the verifier's structural half on the document (`prescreen.preflight`), repeats the two
cheap refusals (one connected code, not already on the board), and exits 1 when the gate would
refuse the candidate for any of them. `coordination.py gate` and `gate_and_record` make the
preflight refusal themselves: a candidate that fails it is not gated, the verifier's failed
checks are written to `<path>.preflight.json` instead of a verdict, and `PreflightFailure` is
raised (exit 1 from the command). `make_submission` refuses to package a direct sum and
`save_submission` refuses to stage anything the preflight fails, so a staged file normally fails
this only when the board moved under it or it was staged with `preflight=False`.

The random distance search inside the gate is the expensive part, so do not pay twice for the
same answer:

```python
from coordination import validate_cached, gate_and_record
verdict, reused = validate_cached(doc)         # gate now, refutation reused
verdict, out = gate_and_record(path)           # the same, from a staged file, verdict kept beside it
```

`validate_cached` calls `verify/validate_candidate.py` exactly as you would, every time. What it
reuses is `gates.refute`, which reads the candidate and nothing else and costs 8.3 s of the 8.4 s
a warm validation takes. `dedup` and `novelty` are claims about `codes/` at a point in time, so
they are recomputed on every call and `reused: True` does not mean `board_advancing` is old. An
entry is served only while the validator source is unchanged, a refutation once found is never
downgraded by a later run that missed it, and the reuse is subtractive: it can turn a pass into a
failure and never the other way around. The cache lives in the gitignored
the staging directory's `.verdicts/` folder. Nothing in it is evidence, and deleting it costs compute rather
than correctness. `gate_and_record` feeds a refutation recorded in the candidate's own
`.verdict.json` back into the cache when the cache has lost it, so a lighter logical found on an
earlier run of the same document is not searched for again (issue #3616).

## 5b. A win only on d: audit the peer before you package

A construction pins n, k and check weight, so a candidate built the same way as an existing
board entry can only beat it on `d` — and `d` is the one axis that is a witness-backed
*upper* bound, i.e. the one that inflates. When the gate comes back with

```json
"gates": {"novelty": {"advances_by": ["d"], "d_only_gain": true,
                      "d_only_peers": ["[[72,6,6]] w=6 72-6-6.json"]}}
```

and the label `advances the <cell> board ONLY on d over <peer>: distance is the suspect
axis`, assume **your** number is the soft one until a matched-depth measurement says
otherwise. `d_only_gain` means the *whole* board advance was on `d`; `d_only_peers` is
the list to act on, and it is non-empty even when the candidate also beat some other
entry on `k` (the label then still names those peers, as
`advances the <cell> board on d, k; its gain over <peer> is d-only: ...`).
The board has been wrong this way before (the corrections are listed in
`audits/README.md`), and chasing an inflated d is how a campaign ends with nothing.

So measure both numbers at one budget before spending anything on packaging:

```bash
uv run --frozen python research/audits/leader_audit.py pair \
    "$STAGING"/<n>-<k>-<d>.json --trials 2000000 --seeds 51 52 \
    --pair-depth 64 --witness-dir <dir-for-witnesses>
```

The peers are chosen automatically — every board entry with the same n, k and max check
weight and a lower claimed d — or name them with `--peer`. Both sides get the same trials,
seeds and `--pair-depth`: a number read on your candidate at a deeper budget than the peer
is an instrument artifact, not a distance difference. One of four decisions comes out:

| decision | meaning | do this next |
|---|---|---|
| `drop: ...` | your own claim came down at its own budget | drop the candidate; the ladder was right, the packaging would have been wrong |
| `redirect: ...` | the board peer came down | persist the witness first (it is the most expensive object in the loop), then file the peer's **distance revision**: a correction to that entry, not a new submission, per [Filing a distance revision](audits/README.md#filing-a-distance-revision) |
| `credible: ...` | both claims held at matched depth | the gain survives; package it (step 4) |
| `inconclusive: ...` | neither claim was reached | no information at all; go deeper or stop, and never report it as corroboration |

Exit code 2 means a claim was refuted on either side, so `pair` can gate a script exactly
like `ladder` and `screen`. Keep `--witness-dir`: the lighter logical found in a refuted
peer *is* the revision (see **The one rule** above).

## 6. Confirm the distance exactly (optional, for a standout)

The surrogate and the gate both certify an *upper bound*. To go further on a code the human wants
to promote, `distance.py` confirms a raw `(HX, HZ)` two ways by reusing the repo's own server-side
certifiers — no need to hand-write a submission first:

```python
from distance import exact_distance, decoder_distance
exact_distance(HX, HZ, tlim=600)         # scipy MILP: proves d= exact, per side
decoder_distance(HX, HZ, trials=200000)  # BP+OSD: independent upper-bound evidence
```

- `exact_distance` wraps `verify/certify.py` (the `d=` tier): it proves no lighter logical
  exists. A `d_exact: True` result means an `"exact"` submission is legitimate (a maintainer
  re-runs the same certifier).
- `decoder_distance` wraps `decode/distance.py`: a *different* mechanism, so agreement is real
  corroboration.

Everything in `research/` that reaches past numpy runs under the `research` extra:

```
uv run --extra research python your_script.py
```

It installs `scipy` (the MILP behind `exact_distance`), `ldpc` (the BP+OSD
decoder behind `decoder_distance`), `python-sat` and `pycryptosat` (the SAT
certifier behind `sat_exact_distance` and the exact distances in
`kit/census_css.py`), and `pynauty` (the nauty canonicalizer in
`kit/census_css.py` and the automorphism count in `kit/supports.py`). Installing
only `scipy` and `ldpc` by hand looks like it works and does not: the census
then canonicalizes only through n = 6 and reports numbers that are not
comparable with the full run, and the automorphism count falls back to a capped
enumeration. The constructors, surrogate, search, packaging, and the campaign
ledger need nothing beyond the default install; the ledger validates with
`jsonschema`, which is a base dependency.

That is the same invocation CI uses for the test suite. Without it `load_campaign` fails with
`CampaignError: jsonschema is required to validate a campaign`, which reads like a broken kit
rather than a missing flag.

## 7. Circuit tier: search the schedule (optional, for an entry that has one)

The code-search loop above finds codes. The circuit tier (`../TRACKS.md`) is the same
shape one level down, and nobody has searched it: the 160-odd entries with
`circuits/<slug>/` carry the standard schedules #1026 backfilled, and
arXiv:2610.23832 and arXiv:2610.31352 found that standard schedules are far from what a
search against a frozen evaluator reaches. `kit/circuit_search.py` is that search for one
entry: `H`, the layout, the noise recipe, and the round count stay fixed; the schedule
(interleaved two-block slot assignments, layout zigzag pattern pairs, edge-coloring orders
of the generic sequential extraction) is the search space; the evaluator is
`verify/circuit_verify.py`, called and never edited.

```
uv run --extra research python research/kit/circuit_search.py 72-12-6 --attempts 12 --seconds 60
uv run --extra research python research/kit/circuit_search.py 64-18-8 --attempts 6 --seconds 120 --ler
```

Each attempt is staged under `research/candidates/<run>/circuit-search/<slug>/attempt-NN/`
with the four circuit files, the circuit block, the entry with the block in place, the
verifier's verdict, and a `notes.md` saying what the schedule was and what the screen and
the deep search read; `ledger.jsonl` has one line per attempt, improving or not, and
`summary.json` the baseline, the ranking, and the survivors. Score is `d_circ` per basis,
the lower basis first, read off the same RIS search the generator and the gate use at
twice the gate's trial budget; `--ler` adds the per-round logical error rate at one grid
rate for the baseline and every evaluated schedule, which is what separates two schedules
at the same `d_circ`. Three things the loop cannot do, by construction: raise `d_circ`
above `d` (the tier is penalty-only), promote anything (a survivor is staged for a human;
promotion replaces the entry's `circuit` block and `circuits/<slug>/` in one PR with
`circuit.contributed_by.by` naming the schedule's author, the binding
`verify/check_authorship.py` checks), or settle a value (every `d_circ` is a witness-backed
upper bound, and the gate's own refutation search is what a promoted schedule survives).
Build on the staged lineage of earlier runs rather than starting fresh; the papers' records
came from agents reading each other's attempts.

## Pitfalls (these are why the gate exists)

- **The surrogate distance is an UPPER BOUND** (step 2). Trust the gate's refutation, not your
  screening number.
- **"Advances the board" ≠ "novel".** The gate labels literature novelty `unverified` — it only
  dedups against *this board*. Never call a candidate a discovery. Say: "advances the `<cell>`
  board; novelty vs the literature unverified."
- **`upper_bound` is not `exact`.** The gate certifies an upper bound (`d<=`); an exact (`d=`)
  claim needs server certification (step 6). Only pursue it for a standout the human wants.
- **Beating an equal (n, k, w) board entry on `d` alone is the inflation pattern** (step 5b).
  The construction left `d` as the only free axis, so re-measure the peer and your candidate
  at matched depth (`leader_audit.py pair`) before you treat the gain as real. This is
  caution, not disqualification: a board-advancing code that gains only on `d` stays
  worth submitting once re-measured.
- **Not beating a leader is not a failure.** A board-advancing code that beats no entry
  extends the frontier and is worth submitting. Report it as board-advancing, not as a loss.
- **A direct sum is not a code** (issue #3620). A generator whose supports decouple the lattice
  builds independent blocks whose `[[n,k,d]]` is a sum over blocks, and the gate refuses it before
  any distance work. `screen` drops these and `make_submission` refuses to package one; a high
  `rejected_disconnected` in `screen`'s audit is the generator's bug, not the filter's.
- **Weight-6 and small `n` mostly re-derive the board.** A WL-signature match (`board_wl` on a
  `screen` record) is a gate run that would likely come back `possibly equivalent`. Treat a
  family whose flags pile up as saturated and move the budget.

## Field notes

Operational field experience lives in [`../fieldnotes/`](../fieldnotes/),
rendered in the site's research log. Read the entries touching your family
before spending budget (step 0 of the loop), and add one when a campaign learns
something the next one should not have to re-learn.

## Definition of done (a candidate you may surface)

- `validate_candidate` → `passed: true` (verifies, not refuted, not a board duplicate).
- Labeled honestly: `confidence: upper_bound`; novelty vs literature flagged unverified;
  "advances this board cell," not "discovery."
- **Staged for review — never committed to `codes/`, never a PR.** The human decides what lands
  (and opens any PR — see `../CONTRIBUTING.md`). This stage-only rule governs unattended
  autoresearch runs; a contributor driving their own agent interactively submits under
  `../CONTRIBUTING.md` instead ("Contribute with an LLM"), where the agent may open the PR
  from the contributor's account.

## Output & housekeeping

- **Capture the evidence; draft the note only where it will be submitted.** Your sweep
  counts, ladder traces (including collapses), and dead ends are required content either
  way — capture them while they are cheap to capture. Where they go depends on the mode:

  - *Unattended, stage-only* (the default this document governs): record them in the
    run's **manifest**, not in a drafted note. One note per staged candidate is the
    largest generative step in the loop and most of those candidates are never
    promoted, so the notes are written and never read. Worse, a note drafted against
    a staging path cannot cite its own evidence: the staging tree is gitignored
    and `verify/check_prose.py` rejects it. The manifest carries the snapshot,
    resolved parameters, seeds, screening counts, dead ends and survivor verdicts,
    so nothing is lost by deferring the prose. `kit/promote.py` renders the note, the
    `codes/` document and the PR body from that one record once a human authorizes a
    submission, so the ladder is transcribed once rather than three times.
  - *Contributor-driven* (an agent a contributor is driving interactively, per
    `../CONTRIBUTING.md`, "Contribute with an LLM"): draft the **research note**
    (`notes/TEMPLATE.md` format) beside the candidate, because that path submits.

  Findings not attached to any candidate (blocked routes, calibration results) belong
  in a drafted `fieldnotes/` entry in either mode. Record the ladder as rungs rather
  than as prose.
- Write each surviving candidate's **submission JSON + its full validator verdict** to a staging
  folder (`coordination.staging_dir()` gives this run its own one under the staging root;
  `coordination.gate_and_record(path)` writes the verdict as `<path>.verdict.json`, which is
  the artifact this bullet asks for), and print a short ranked summary:
  `[[n,k,d]]`, cell, efficiency `kd²/n`, board-advancing?, and the honest labels.
- **Persist any new constructor code you wrote** and a brief decision journal, so the run is
  reproducible and a good `sample_<family>` can later graduate into `research/`.
- Respect the budget (time / iterations / until-one-find). Log progress. Stop and report — do
  not silently keep going.

## Module reference

| File | What it gives you |
|---|---|
| `kit/css.py` | `compute_k`, `verify_css`, and the re-exported GF(2) core (`rref`, `rank`, `kernel_basis`, `logical_basis`, ...) shared with the verifier |
| `kit/campaign.py` | `Ledger`, `load_campaign`, `write_summary`, `write_manifest`: the campaign contract and the **screening registry**. `record_screen` is what writes a screening depth and `record_verdict` what says how it ended — the two calls that make a run visible to the next session, and `record_negative(..., assumptions=, revisit_if=)` what makes a closed route reusable, read back by `./qldpc negatives` (issue #4233). Validates against `schema/campaign.schema.json` with `jsonschema`, a base dependency, so it runs under a bare `uv run`; see [`campaigns/README.md`](campaigns/README.md) |
| `kit/gf2poly.py` | GF(2) polynomials as ints: `factor_squarefree` (x^m - 1 over GF(2), no sympy), `designed_divisor`, `sparse_multiples`, `cyclic_gb`, `designed_k`; the designed-divisor route behind `search.sample_cyclic_gb` (section 3c) |
| `kit/bb.py` | `build_bb`, `poly_matrix`, `KNOWN` (known BB codes to start from) |
| `kit/group_algebra.py` | `build_2bga` + group builders: `perm_group`, `cyclic_product`, `dihedral`, `metacyclic`, `sym`, `alt`; `small_group` reads a committed GAP SmallGroup table from `kit/groups/` (exported by `kit/groups/cayley_table.g`), `build_2bga_small_group` is its recipe form |
| `kit/coset.py` | `build_coset` + `subgroup_closure`, `left_cosets`, `normalizer` |
| `kit/surrogate.py` | `distance_rand`, `lightest_logical` (witnesses), `mixed_volume` (k upper bound) |
| `kit/search.py` | `screen`, `screen_adaptive`, `pareto_frontier`, `update_leaderboard` (the funnel; `audit=` counts what the pre-pass dropped, `board=` sets how a board match is handled) + samplers: `sample_bb`, `sample_dihedral`, `sample_metacyclic`, `sample_kasai_affine` (all capped at check weight 8 by default), `sample_cyclic_gb` (designed k, check weight 24 to 32; section 3c) |
| `kit/prescreen.py` | `block_structure`, `identity`, `board_index`, `lookup`, `prescreen`: the two refusals the gate makes before any distance work (a direct sum, a code the board holds) and the WL flag it admits with, decided with the verifier's own arithmetic against the gate's own board index (issue #3620). `preflight`, `describe_preflight`: the verifier's structural half on a packaged document, the checks the gate's verify step would fail it on, in the verifier's words and sorted into a fault in the code or in the document (issue #3616). Run on a staged file: `python research/kit/prescreen.py <path>` |
| `kit/escalation.py` | `rung_brief`, `apply_verdict`, `append_journal`, `exact_first` (certify small CSS candidates before the first deep rung), `cc_first` and `exact_or_cc_first` (the connected-cluster pre-stage beyond the certifier's band, a screen that aims the ladder and never ends it; a no-op without the Qubitserf build) — the rung-boundary escalation gate (step 3b): deterministic ladder facts + fenced judgment-model verdict; advisory only, never repo evidence |
| `kit/submit.py` | `make_submission`, `save_submission`, `validate`, `write_recipe`, `read_recipe` (the spec kept beside a staged candidate), `write_repro_manifest` (the `repro/<slug>.json` manifest for `qldpc reproduce`) |
| `kit/circuit_search.py` | `search(slug, ...)`: the circuit-tier schedule search of section 7, over every applicable family of `research/circuit_autogen.py`, staging every attempt with its verdict and notes under `research/candidates/`, scoring by `d_circ` per basis (and LER with `--ler`); `verify/circuit_verify.py` is called, never edited |
| `kit/rebuild.py` | runs a `{constructor, params}` recipe and prints the verifier's fingerprint; the construction stage of `qldpc reproduce` |
| `kit/coordination.py` | `run_id`, `session_id`, `staging_dir`, `unique_path`, `validate_cached`: collision-safe staging and refutation reuse when several sessions run at once. `gate_and_record`, `PreflightFailure`, `quarantine`: the gate from a staged file, refused before it runs when the verifier's structural half would fail the document, with the verdict or the preflight report kept beside the candidate (issue #3616) (`session_id` is the shell a claim belongs to, `run_id` the process that wrote it). `claim`, `release`, `read_claim`, `live_claims`, `prune_claims`: advisory, expiring cell claims (`qldpc targets --claim`): a note to other sessions, never a lock, and never read by `verify/` |
| `kit/promote.py` | `promote`, `promote_all`, `script_for`: the submission tail for a candidate the gate already passed. Renders `codes/<slug>.json`, `notes/<slug>.md`, the PR body, and `repro/<slug>.json` when the candidate was staged with a recipe, from one evidence record, runs the gate and `check_prose` in order, and returns one JSON report. Writes files; never runs git or gh |
| `kit/distance.py` | `exact_distance` (MILP, `d=`), `sat_exact_distance` (SAT, `d=`), `decoder_distance` (BP+OSD), `weight_one_logical_exists`, `sat_lower_bound`, `sat_screen` (SAT-based lower-bound screening helpers), `qubitserf_screen`/`resolve_screen` (exact distance via the out-of-band Qubitserf build; a screen, never a certifier) — needs the `research` extra |
| `kit/census_css.py` | exhaustive small CSS-code census up to qubit permutations and global X/Z swap, through n = 8 with the nauty canonicalizer (pynauty, in the `research` extra; n <= 6 without it); exact distance uses the trusted SAT certifier |
| `kit/products.py` | classical combining products: `hypergraph_product`, `lifted_product`, `balanced_product` + a sampler each; the lifted/balanced ones cover the multi-block protographs `kit/lp_protograph.py` specializes |
| `kit/lp_protograph.py` | general lifted-product codes with matrix protographs, plus the SCE-paper protograph catalog (arXiv:2606.24808, Supplemental S7) |
| `kit/annihilator.py` | the single-block annihilator attack on two-block CSS entries (issue #2706): write `H = [A \| B]` and search the kernel of either block alone for a low-weight vector. A way to re-price an existing entry, not a way to build one |
| `kit/doubling.py` | free Z2 double-cover ("doubling") for bivariate bicycle codes: the `s=2` complement to `spectral.cover_k`, which handles odd covers only |
| `kit/spectral.py` | spectral (Frobenius-orbit) screening for semisimple BB codes, from arXiv:2608.27565, restricted to the binary semisimple case: `cover_k` and the odd-cover machinery |
| `kit/phantom.py` | the phantom-code construction of arXiv:2609.16542 — `build_phantom_outer` and the rest of the three consolidated pieces |
| `kit/gauss_law.py` | the quantum Gauss's law codes of arXiv:2608.00165 — `classical_gauss_law_1d`, `optimal_1d_multiplicities` (Theorem III.5's optimal duplication counts) and `quantum_gauss_law_1d`, the CSS code `[[N d(d+1)/2, N, d]]`; the family's `kd^2/n = 2d/(d+1)` is below 2 by construction, so it is a construction, not a board lead |
| `kit/tensor_network.py` | the tensor-network codes of arXiv:2009.10329 — `glue` (Theorem 1's index contraction, done at the group level), the SWO08 `[[6,1,3]]` block and the `[[11,1,3]]` code it produces; the block is non-CSS and the paper's 7-qubit state is not abelian, so the family is not submittable |
| `kit/coset_gap.py` | the coset two-block codes `Q_G^H(ahat, bhat)` of arXiv:2606.17268 — `build(ell, m, s, ahat, bhat)` assembles the check matrices inside GAP (`SmallGroup`, `Core`, `Normalizer`, `LeftCosets`, `Representative`), so no coset-representative convention is re-derived in Python; `PAPER_INSTANCES` transcribes all 29 published instances, and every one reproduces its stated (n, k) |
| `local2d/planar.py` | fast greedy open-boundary builder, exact planar distance (scipy MILP), `grid_coordinates` for the bilayer layout |
| `local2d/boundary_engine.py` | the general open-boundary construction (`build_planar`), `reduce_weights`, `graft_r1`/`graft_r1_safe` (qubit removal) |
| `local2d/transfer.py` | `distance_slope`: predict d(L) scaling from (f, g) before building large lattices |
| `local2d/corner_detector.py` | `detect`: L-independent bounded-vs-growing distance classification |
| `../verify/validate_candidate.py` | the trusted gate: verify + refute + dedup + novelty, one verdict |
| `test_smoke.py` | the runnable end-to-end example (build → package → real verifier), also CI's drift gate |

Each module is runnable on its own (`uv run python research/kit/<module>.py`, likewise
`research/local2d/<module>.py`) and prints a small self-test / demo. The kit covers the
periodic / group-algebra / coset families and the weight-bounded tracks; `local2d/` covers the
open-boundary planar engine for the `2d-local` tracks (see `local2d/README.md`).
