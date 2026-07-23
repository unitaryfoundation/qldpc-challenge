# autoresearch: find new qLDPC codes for a direction

Tool-agnostic guide for an LLM (or any agent, or a human newcomer) doing autoresearch on the
qLDPC challenge. Point your model at this file — nothing here is specific to any one agent
tool. It is both the **operating manual for the research loop** and the **reference for the
`research/` starter kit**: constructing a code, estimating its distance, and packaging a
verifiable submission.

Everything in `research/` is **pure numpy** (no deps beyond what the verifier needs) and sits
directly on the verifier's own GF(2) core, so what you build here is exactly what the board
records. Your job: given a research direction, construct and search qLDPC codes and surface
**verified, genuinely-new candidates** for human review. You may write and run any code you
like — but you do **not** get to decide whether a code is good. A trusted gate does.

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
pareto_frontier(records)          # the non-dominated codes over (n, k, d)
update_leaderboard("board.json", records)   # merge + persist, so a sweep can resume
```

`screen` consumes any iterable of `(spec, HX, HZ)` triples, where `spec` is a JSON-serializable
description of how the code was built — so you can point it at **your own generator** for any
family. `sample_bb` is a ready-made one; a 2BGA or coset sampler over `group_algebra` / `coset`
has the same shape. Because the screening distance is the surrogate *upper bound*, `screen`
ranks **candidates** — validate the winners before claiming anything (next).

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
`coordinates=[[x,y], ...]` (one per qubit) and `layers=`; `submit.py` fills the `locality` block
and computes the interaction radius, and the verifier derives the locality class from it.

## 5. Validate with the gate (do not skip)

Run `validate_candidate` on the packaged doc (see **The one rule** above). Keep only
`passed: true`. The verdict's `gates` are your evidence; its `labels` are what you show the
human. This — not the surrogate, not your own judgment — is what decides whether you have a find.

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
  (and opens any PR — see `../CONTRIBUTING.md`).

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
| `kit/submit.py` | `make_submission`, `save_submission`, `validate` |
| `kit/distance.py` | `exact_distance` (MILP, `d=`), `decoder_distance` (BP+OSD) — needs the `research` extra |
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
