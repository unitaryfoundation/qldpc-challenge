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
uv run python verify/validate_candidate.py candidate.json   # exit 0 iff passed
```

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

0. **Read the shared record first**: `./qldpc recent` (new codes, research
   notes, fieldnotes), then the `fieldnotes/` entries touching your intended
   family — blocked routes and calibration findings live there, and repeating
   them wastes the budget.
1. **Pick a direction** → a track cell + a family + a budget (below).
2. **Build** `(HX, HZ)` from a constructor.
3. **Estimate** distance cheaply with the surrogate (gets you the witness for free).
4. **Search** a whole family with `search.py` to find the best candidates.
5. **Package** with `submit.make_submission`, then **validate** with the gate — keep only
   `passed: true`.
6. **Stage** survivors for review; loop until the budget is spent, then report.

To watch the whole loop run once (build → package → the real verifier in-process):

```
uv run python research/test_smoke.py
```

## 1. Pick a direction and a family, build `(HX, HZ)`

A **direction** is a concrete target: a track cell (locality class × weight class, e.g.
`unrestricted × weight-6`) plus a family/approach and a budget. If the user's direction is
vague, translate it: look at the board (`codes/*.json`, the site, `TRACKS.md`) for a **sparse
cell** or a **record to beat**, and aim there.

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
append_journal(decision, brief, path="research/candidates/escalation.jsonl")
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

`family` is a filterable Layer-2 tag, never ranked. You do **not** declare which tracks you
enter: the verifier computes primary-track membership (the weight and locality classes) from `H`
and the layout. To enter the `2d-local-*` tracks, give the code a layout — pass
`coordinates=[[x,y], ...]` or `[[x,y,z], ...]` (one per qubit) and `layers=`; `submit.py` fills the `locality` block
and computes the interaction radius, and the verifier derives the locality class from it.

## 5. Validate with the gate (do not skip)

Run `validate_candidate` on the packaged doc (see **The one rule** above). Keep only
`passed: true`. The verdict's `gates` are your evidence; its `labels` are what you show the
human. This — not the surrogate, not your own judgment — is what decides whether you have a find.

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
 The board has been wrong this way before (`[[882,18,30]]`→29, `[[684,12,81]]`→66,
`[[396,10,39]]`→37 — `audits/README.md`), and chasing an inflated d is how a campaign
ends with nothing.

So measure both numbers at one budget before spending anything on packaging:

```bash
uv run --frozen python research/audits/leader_audit.py pair \
    research/candidates/<n>-<k>-<d>.json --trials 2000000 --seeds 51 52 \
    --pair-depth 64 --witness-dir /tmp/pair
```

The peers are chosen automatically — every board entry with the same n, k and max check
weight and a lower claimed d — or name them with `--peer`. Both sides get the same trials,
seeds and `--pair-depth`: a number read on your candidate at a deeper budget than the peer
is an instrument artifact, not a distance difference. One of four decisions comes out:

| decision | meaning | do this next |
|---|---|---|
| `drop: ...` | your own claim came down at its own budget | drop the candidate; the ladder was right, the packaging would have been wrong |
| `redirect: ...` | the board peer came down | the submission is the peer's **distance revision** — a valid contribution on its own (`../CONTRIBUTING.md`) |
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

These need extra deps (`scipy`, `ldpc`): `uv run --with scipy --with ldpc python your_script.py`.
The constructors, surrogate, search, and packaging stay numpy-only.

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
  at matched depth (`leader_audit.py pair`) before you treat the gain as real.

## Field notes from past campaigns

Operational field experience lives in [`../fieldnotes/`](../fieldnotes/) —
PR-able entries rendered in the site's research log. The lessons that used to
be inlined here (trial-depth floors and the distance-inflation discipline,
lit-check timing, confirmation-budget planning, tooling landmines, and the
2026-06→07 open-directions snapshot) were ported there on 2026-07-23. Read
the entries touching your family before spending budget (step 0 of the
loop), and add a fieldnote when a campaign learns something the next one
should not have to re-learn.

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

- For each staged candidate, also draft its **research note** (`notes/TEMPLATE.md` format):
  the human will submit it beside the code, and your sweep counts, ladder traces (including
  collapses), and dead ends are exactly its required content — capture them while they are
  cheap to capture. Findings that are *not* attached to a candidate (blocked routes,
  calibration results) belong in a drafted `fieldnotes/` entry instead.
- Write each surviving candidate's **submission JSON + its full validator verdict** to a staging
  folder (e.g. `research/candidates/` or a scratch dir), and print a short ranked summary:
  `[[n,k,d]]`, cell, efficiency `kd²/n`, board-advancing?, and the honest labels.
- **Persist any new constructor code you wrote** and a brief decision journal, so the run is
  reproducible and a good `sample_<family>` can later graduate into `research/`.
- Respect the budget (time / iterations / until-one-find). Log progress. Stop and report — do
  not silently keep going.

## Module reference

| File | What it gives you |
|---|---|
| `kit/css.py` | `compute_k`, `verify_css`, and the re-exported GF(2) core (`rref`, `rank`, `kernel_basis`, `logical_basis`, ...) shared with the verifier |
| `kit/bb.py` | `build_bb`, `poly_matrix`, `KNOWN` (known BB codes to start from) |
| `kit/group_algebra.py` | `build_2bga` + group builders: `perm_group`, `cyclic_product`, `dihedral`, `metacyclic`, `sym`, `alt` |
| `kit/coset.py` | `build_coset` + `subgroup_closure`, `left_cosets`, `normalizer` |
| `kit/surrogate.py` | `distance_rand`, `lightest_logical` (witnesses), `mixed_volume` (k upper bound) |
| `kit/search.py` | `screen`, `pareto_frontier`, `update_leaderboard` (the funnel) + samplers: `sample_bb`, `sample_dihedral`, `sample_metacyclic`, `sample_kasai_affine` |
| `kit/escalation.py` | `rung_brief`, `apply_verdict`, `append_journal` — the rung-boundary escalation gate (step 3b): deterministic ladder facts + fenced judgment-model verdict; advisory only, never repo evidence |
| `kit/submit.py` | `make_submission`, `save_submission`, `validate` |
| `kit/distance.py` | `exact_distance` (MILP, `d=`), `decoder_distance` (BP+OSD) — needs the `research` extra |
| `kit/census_css.py` | exhaustive small CSS-code census up to qubit permutations and global X/Z swap; exact distance uses the trusted SAT certifier and needs the `research` extra |
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
