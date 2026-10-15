# research/

The starter kit and everything built on it. `AUTORESEARCH.md` is the manual
and `QUICKSTART.md` the short version; this file is the map of the directory,
so that two scripts that look alike are not picked by name (issue #3383).

## Directories

| Directory | What is there | Read |
|---|---|---|
| `kit/` | the toolkit: constructors, surrogate, search funnel, packaging, coordination | the module reference in `AUTORESEARCH.md` |
| `local2d/` | open-boundary planar (2D-local) builders, layout search, distance-scaling theory | `local2d/README.md` |
| `audits/` | re-measure and compare what is on the board | `audits/README.md` |
| `campaigns/` | bounded, reproducible search tasks and their committed records | `campaigns/README.md` |
| `evidence/` | per-entry evidence bundles with their own scripts | the `README.md` in each bundle |
| `geometric_grafts/` | the affine-checkerboard contraction campaign and its reproduce scripts | the docstrings; `geometric_grafts/campaign.py` is the entry point |
| `literature/` | the literature harvest | `literature/README.md` |
| `provenance/` | the literature-novelty checker and `derived.json` | `provenance/README.md` |
| `candidates/`, `out/`, `runs/` | gitignored working output: staging, run output, run logs | never cite them as evidence |

## Top-level scripts

Status: **canonical** is the one to use; **base** is extended or superseded by
another script and is kept for the narrower question it still answers;
**rebuild** reproduces one board entry from its parameters and searches
nothing; **audit** re-prices or triages what already exists.

| Script | Status | What it does |
|---|---|---|
| `cyclic_gb.py` | canonical | cyclic generalized-bicycle search stack over Z_m: designed-divisor construction plus the staged distance ladder |
| `local_sat.py` | canonical | 2D-local SAT search: every check is anchored at a lattice site and acts within a radius, so each find carries a layout and a geometric-efficiency score |
| `sat_rungs.py` | canonical | runs one rung of the 2D-local SAT ladder on `local_sat.py` and records how it ended (issue #2703) |
| `sat_search.py` | base | the unconstrained SAT formulation `local_sat.py` extends; its finds carry no layout and cannot enter the 2D-local tracks |
| `build_halved_pp.py` | canonical | symplectic-halved CPM pair-partition codes (arXiv:2609.30069) |
| `multiband_surface.py` | canonical | the general multi-band dense-packed surface family; `build_dense_surface.py` is one fixed point of it |
| `apm_kasai.py` | canonical | Kasai affine-permutation CSS family (arXiv:2504.17790) at board-admissible blocklengths |
| `kasai_affine_sweep.py` | canonical | sweep of `sample_kasai_affine` over the n = 630-682 band only that sampler reaches, staged with the refine pass a coarse reading needs |
| `quadcycle4d.py` | canonical | quadcycle codes, the 4D multi-cyclic family of arXiv:2610.10731 |
| `quadricycle.py` | canonical | quadricycle codes, rank-4 periodic generalized bicycles |
| `spc_product.py` | canonical | single-parity-check D-fold product codes, including the [[512,174,8]] instance |
| `hyperbolic_psl.py` | canonical | self-dual PSL(2,q) hyperbolic surface codes of arXiv:2610.10948, rebuilt from the construction |
| `ub_sweep.py` | canonical | univariate bicycle sweep, the Table I rows of arXiv:2605.14173 |
| `multi_yoke_light_basis.py` | canonical | decides whether a multi-yoked chain-code check matrix has a basis under the board's weight cap |
| `oneshot_count.py` | canonical | size and rank of the one-shot level map of arXiv:2610.02137 on real bases |
| `bb_table1.py` | base | transcription of the ten BB codes of arXiv:2407.03973 Table 1, which pins the BB convention; build BB codes with `kit/bb.py` |
| `build_128_20_14.py` | rebuild | the [[128,20,14]] 2BGA entry from its group and supports |
| `build_254_14_16.py` | rebuild | the [[254,14,16]] generalized-bicycle entry from its trinomial supports |
| `build_96_8_12_2bga.py` | rebuild | the [[96,8,12]] 2BGA code on D_4 x Z_6 from the paper's supports |
| `build_dense_surface.py` | rebuild | the dense-packed surface entries ([[101,5,5]] and its larger sizes) as (HX, HZ, coords) |
| `foldbound.py` | audit | distance upper bound by folding a code onto a symmetric subspace; a refuter, not a layout tool |
| `annihilator_sweep.py` | audit | the annihilator attack over the board's uncertified block-shaped entries (issue #2706) |
| `board_bar.py` | audit | the smallest undominated d for a candidate (n, k, w), read off the board before any distance search |
| `does_it_advance.py` | audit | mirror of the gate's novelty block: would this candidate beat the board, and on which axes, before paying for the gate |
| `derive_provenance.py` | audit | literature-versus-discovered provenance for every entry from the isomorphism check (issue #1279) |
| `arxiv_watch.py` | audit | arXiv triage for papers that may carry a board-relevant code; claims, never distances |
| `circuit_autogen.py` | canonical | memory-circuit generation behind `qldpc submit` (issue #1848) |
| `circuit_backfill.py` | canonical | the same circuit path over board entries that have no circuit tier (issue #1026) |
| `circuit_seed.py` | rebuild | the circuit-tier seed artifact for a rotated-surface-code entry (RFC 0001 Phase A) |

## Easily confused

- `local_sat.py` and `sat_search.py`: the second is the base the first extends.
  Without the locality constraint a find has no layout, so the 2D-local tracks
  cannot score it, and the search spends its budget on records that are
  worthless on arrival. Start from `local_sat.py`.
- `foldbound.py` and `local2d/fold_layout.py`: both "fold". The first folds a
  code onto an orbit-constant subspace to find a lighter logical, a distance
  upper bound. The second folds a periodic code into the plane to minimize its
  interaction radius, a layout. Opposite purposes, different subtrees.
- `kit/bb.py`, `bb_table1.py`, and `[[128,14,12]]`: `kit/bb.py` is the BB
  builder the manual and the tests use. `bb_table1.py` re-derives the paper's
  table to pin the convention and is not a second builder. The gross code
  [[144,12,12]] and [[128,14,12]] are already on the board, and the gate rejects
  a re-derivation of either as a duplicate.

Scratch scripts are `_`-prefixed and gitignored. A new top-level script
belongs in the table above; `test_research_readme.py` checks that it is.
