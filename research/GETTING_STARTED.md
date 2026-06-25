# Getting started: constructing a code

This directory is a **starter kit for building qLDPC codes** to submit to the
leaderboard. The rest of the repo (`verify/`, `schema/`, `codes/`, `site/`)
*checks and ranks* codes; this is the missing front half — actually
*constructing* one, *estimating its distance*, and *packaging* a valid
submission. It is written so that a newcomer (or an LLM doing the work) can go
from nothing to a verifiable PR in one sitting.

Everything here is **pure numpy** (no extra dependencies beyond what the
verifier already needs) and sits directly on top of the verifier's own GF(2)
core, so what you read here is exactly what the board will record.

## The loop

```
  pick a family ─▶ build (HX,HZ) ─▶ estimate distance ─▶ package ─▶ verify ─▶ PR
     bb.py           construct()      surrogate.py       submit.py   verify/   codes/
   group_algebra.py                 (witness comes free)
   coset.py
                       │                                    ▲
            sweep a family with        confirm the distance (exact MILP or
            search.py (screen→rank)    decoder) with distance.py before claiming
```

Two worked examples, each runs the real verifier in-process at the end:

```
uv run python research/recipes/01_build_and_submit_bb.py   # one code, end to end
uv run python research/recipes/02_search_a_family.py       # sweep a family, take the best
```

## 1. Pick a family and build `(HX, HZ)`

Every constructor returns two parity-check matrices `HX, HZ` (numpy int arrays,
shape `(num_checks, n)`) for a CSS code. Pick by the track you're aiming at
(see `../TRACKS.md`):

Check weight is not a track — it is the `w` property (filtered by the board's
weight slider), shown below as the typical check weight each family produces.

| Module | Family | Track / weight | CSS holds because |
|---|---|---|---|
| `bb.py` | bivariate bicycle on a torus Z_l × Z_m (the "gross code" family) | `bivariate bicycle (periodic)`, w 6 | abelian circulants commute |
| `group_algebra.py` | two-block group-algebra (2BGA) on **any** finite group | `generalized bicycle`, w 6 | left/right multiplication commute |
| `coset.py` | coset 2BGA on G/H (record efficiencies; non-normal H) | no track, w 8 | left action commutes with right action by the normalizer |

`bb.py` is the place to start — it's the simplest and any choice of monomials is
a valid code. `group_algebra.py` generalizes it to non-abelian groups (which can
reach odd `k`); `coset.py` generalizes further to the highest known efficiencies.

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

To make a **new** code, change the monomials / group / supports. A code is only
*interesting* if it advances a track's Pareto frontier over (n, k, d) — see
`../CONTRIBUTING.md`.

## 2. Estimate the distance (and get a witness for free)

Distance is the hard part: computing it exactly is NP-hard, so the board uses a
**trustless witness** instead — you attach an explicit low-weight logical
operator and the verifier confirms it, certifying `d <= value`. `surrogate.py`
finds that witness for you:

```python
from surrogate import distance_rand, lightest_logical
d = distance_rand(HX, HZ, trials=600)        # an UPPER BOUND on min(dX, dZ)
wx, x_witness = lightest_logical(HX, HZ)     # lightest X-logical: (weight, support)
wz, z_witness = lightest_logical(HZ, HX)     # lightest Z-logical
```

**Read this carefully — it's the one place honesty matters most:**

- `distance_rand` returns an **upper bound**. It found *a* logical of that
  weight, so `d <= value`; it is Monte Carlo, **not a proof**.
- To gain confidence, **raise `trials` until the value stops dropping** (e.g.
  `distance_rand(.., trials=t) == distance_rand(.., trials=2*t)`). Then treat it
  as a solid upper bound.
- The matching submission confidence is therefore `"upper_bound"`. An `"exact"`
  claim is a *separate, server-certified tier* (`../verify/certify.py`) — don't
  mark `exact` unless you mean to earn it.
- `mixed_volume(S_f, S_g)` gives a fast, matrix-free **upper bound on k** for
  bivariate constructions — use it to screen candidate exponent sets before you
  ever build a matrix.

## 2b. Search a family (autoresearch)

Building one code is step one; *discovering* a good one means sweeping a family.
`search.py` is a generic funnel: generate candidates → screen each cheaply →
rank by efficiency and Pareto frontier.

```python
from search import screen, pareto_frontier, sample_bb, update_leaderboard
records = screen(sample_bb(400, seed=7), min_k=4, min_d=4, trials=250)
records[:5]                       # best by k*d^2/n (the board's headline metric)
pareto_frontier(records)          # the non-dominated codes over (n, k, d)
update_leaderboard("board.json", records)   # merge + persist, so a sweep can resume
```

`screen` consumes any iterable of `(spec, HX, HZ)` triples, where `spec` is a
JSON-serializable description of how the code was built — so you can point it at
**your own generator** for any family. `sample_bb` is a ready-made one; a 2BGA or
coset sampler over `group_algebra` / `coset` has the same shape. Because the
screening distance is the surrogate *upper bound*, `screen` ranks **candidates** —
confirm the winners before claiming anything (next).

## 3. Package a submission

`submit.py` turns `(HX, HZ)` plus a little provenance into a schema-valid
submission. It recomputes n/k, asserts CSS, extracts the witnesses, and
**pre-checks each witness against the verifier's own criteria**, so the document
it returns is built to pass:

```python
from submit import make_submission, save_submission
doc = make_submission(
    HX, HZ,
    name="[[72,12,6]] my BB code",
    construction="Bivariate bicycle on Z_6 x Z_6, A = x^3+y+y^2, B = y^3+x+x^2.",
    authors=["your-handle"],
    tracks=["bivariate bicycle (periodic)"],
    references=["arXiv:2308.07915"],
    confidence="upper_bound",
)
save_submission(doc, "codes/my-72-12-6.json")
```

For the `2d-local-*` tracks, also pass `coordinates=[[x,y], ...]` (one per qubit)
and `layers=`; `submit.py` fills the `locality` block and computes the true
interaction radius for you.

## 3b. Confirm the distance (optional but recommended)

The surrogate gives an *upper bound*. To go further, `distance.py` confirms a
raw `(HX, HZ)` two ways by reusing the repo's own server-side certifiers — no
need to hand-write a submission first:

```python
from distance import exact_distance, decoder_distance
exact_distance(HX, HZ, tlim=600)       # scipy MILP: proves d= exact, per side
decoder_distance(HX, HZ, trials=200000)  # BP+OSD: independent upper-bound evidence
```

- `exact_distance` wraps `verify/certify.py` (the `d=` tier): it proves no
  lighter logical exists. A `d_exact: True` result means you can legitimately
  pursue an `"exact"` submission (a maintainer re-runs the same certifier).
- `decoder_distance` wraps `decode/distance.py`: a *different* mechanism (a
  decoder's mistakes), so agreement with the surrogate is real corroboration.

These need extra dependencies (`scipy`, `ldpc`) — install the `research` extra,
or run on demand: `uv run --with scipy --with ldpc python your_script.py`. The
constructors, surrogate, search, and packaging stay numpy-only.

## 4. Verify, then open a PR

```
uv run python verify/qldpc_verify.py codes/my-72-12-6.json
```

Exit 0 with an `earned_distance` block means it will pass CI. Then open a PR
adding your file under `codes/` (see `../CONTRIBUTING.md`).

## Module reference

| File | What it gives you |
|---|---|
| `css.py` | `compute_k`, `verify_css`, and the re-exported GF(2) core (`rref`, `rank`, `kernel_basis`, `logical_basis`, ...) shared with the verifier |
| `bb.py` | `build_bb`, `poly_matrix`, `KNOWN` (known BB codes to start from) |
| `group_algebra.py` | `build_2bga` + group builders: `perm_group`, `cyclic_product`, `dihedral`, `metacyclic`, `sym`, `alt` |
| `coset.py` | `build_coset` + `subgroup_closure`, `left_cosets`, `normalizer` |
| `surrogate.py` | `distance_rand`, `lightest_logical` (witnesses), `mixed_volume` (k upper bound) |
| `search.py` | `screen`, `pareto_frontier`, `sample_bb`, `update_leaderboard` (the search funnel) |
| `distance.py` | `exact_distance` (MILP, `d=`), `decoder_distance` (BP+OSD) — needs the `research` extra |
| `submit.py` | `make_submission`, `save_submission`, `validate` |
| `recipes/` | runnable end-to-end examples (01: one code; 02: search a family) |

Each module is runnable on its own (`uv run python research/<module>.py`) and
prints a small self-test / demo.

## What's here

- Constructors (`bb`, `group_algebra`, `coset`), the distance/k surrogate
  (`surrogate`), the search funnel (`search`), and submission packaging
  (`submit`) — all numpy-only.
- Distance confirmation (`distance`: exact MILP `d=` and decoder corroboration),
  which reuses the repo's existing certifiers and lives behind the optional
  `research` extra so the core stays numpy-only.

This covers the periodic / group-algebra / coset families and the weight- and
bivariate-bicycle tracks. The specialized open-boundary planar engine for the
`2d-local-bilayer` track is intentionally out of scope here.
