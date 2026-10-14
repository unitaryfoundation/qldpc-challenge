---
title: "Concatenating onto the non-CSS board: what arXiv:2610.04694 does and does not give a qubit board"
date: 2026-10-13
author: "@MathysRennela"
model: "Mimo-V2.6-Flash (opencode agent harness)"
topics: [stabilizer-board, concatenation, non-css, negative-results, phase-space]
related:
  - 2026-09-28-symplectic-doubling-and-halving.md
  - 2026-10-08-literature-harvest-campaign-method.md
---

## Summary

*Stabilizer codes over general phase spaces* (Chakraborty and Albert,
arXiv:2610.04694) is a theory paper: its codes live on
`M = R^p x Z^q x Z_c`, the oscillator and rotor factors have no finite Hilbert
dimension, and this board's verifier recomputes `k` over `GF(2)`. Two-thirds of
the session's work was therefore a *negative*, and it is written down below so
the next reader does not repeat it. One reading in it did pay: the paper says
its examples are all "a stabilizer code concatenated with a GKP code", and
swapping the GKP inner code for a **small non-CSS stabilizer code** produces
ordinary qubit codes that land on the non-CSS board, where the frontier is far
thinner than on the CSS board.

One such product, [[512,54,24]] with check weight 32, passed the trusted gate
(`passed: true`, `board_advancing: true`, empty `dominator_slugs`, and a fresh
refutation search that found nothing lighter); it is staged for a human to
review, and the campaign ledger records the
parameters, seeds and where each survivor sits. Five candidates were measured;
one was refused by the schema outright, which is the most useful thing this
campaign found. All distances here are witness-backed upper bounds.

## The paper, and why most of it is not submittable here

The paper's contribution is a common language (stabilizer lattices in phase
space, symplectic duals, Clifford-Gaussian gates from lattice symplectries,
weight enumerators) with qudit, oscillator and rotor codes as special cases.
Its one finite-looking example, the hybrid Golay code, couples twelve
oscillators to twelve qubits and encodes *one* logical qubit; qubitizing it is
not even well defined, since an order-4 qudit shift is not a qubit Pauli and no
homomorphism sends one to the other. The `arxiv_watch` screen had already filed
this paper as `background` (2026-10-11), and that was the right call.

## Dead end 1: the finite reading of "integer lift" collapses to F_2

The most quotable finite statement is Sec. II.4.1: *to construct a mixed-qudit
stabilizer code, choose a full-rank integer lattice with integral symplectic
Gram matrix and reduce it modulo the local dimensions; every such subgroup
arises this way*. With all `c_i = 2` this parametrizes binary stabilizer codes,
and the tempting move is to build one out of ring-valued data -- a
`Z_4`-valued bivariate bicycle, say -- and reduce mod 2.

It adds nothing. The mod-2 image of the lattice is the span of the mod-2 images
of the chosen generators, so a `Z_4`-valued check matrix reduces to the `F_2`
check matrix with the same supports: a `Z_4` bicycle with monomials `A, B` and
`A B^T + B A^T = 0 (mod 4)` reduces to the `F_2` bicycle on the same monomials,
since `mod 4` implies `mod 2`. The lattice parametrization is a repackaging of
`k = n - rank` and of the symplectic dual, not a larger search space. The only
way to leave the binary world and come back is a genuinely quaternary object
whose *reduction* has mixed X/Z supports, which is just a non-CSS binary code
again -- so one ends up searching binary stabilizer codes directly.

Two related routes are closed for the same reason. A symplectic shear applied
to a CSS code is a block Clifford, so its image is a declared relabel
(`provenance.clifford_relabel_of`, issue #2802) and not a construction result.
And the paper's own criterion for intrinsic non-decomposability is *torsion* of
the stabilizer lattice, which needs a local dimension of at least 4: a binary
`D` is an `F_2` vector space and has none.

## Dead end 2: the check weight is set by the heaviest logical, not the distance

Concatenating an outer code with an inner one imposes the outer code on *all*
`k_in` logical layers of every block, so the builder needs a full symplectic
basis of the inner logical space, not one pair -- the version that imposed a
single layer gave `k = n_out(k_in - 1) + k_out` instead of `k_in k_out`, which
is what the first build caught. Then:

    n = n_in n_out,  k = k_in k_out,  d >= d_in d_out,
    check weight = max(w_in, w_out * max_j wt(L_j))

The weight is set by the **heaviest** basis vector `beta`, while the witnessable
distance is set by the **lightest** vector in the X- (or Z-) subspace. Measured
over the board's non-CSS entries with `n <= 40`, `beta` is usually well above
the distance: `[[36,4,8]]` needs basis vectors of weight 9, `[[36,6,6]]` of
weight 24, `[[12,4,4]]` of weight 6 against a distance of 4. Only a handful of
inners have a uniformly light basis -- `[[8,3,3]]` (`beta` 4, `d` 3),
`[[8,2,3]]` (`beta` 3, `d` 3), `[[12,4,4]]` (`beta` 6, `d` 4) -- and those are
what the surviving candidates use.

The metric that makes this work is Pauli weight: a `Y` counts once. Scoring the
basis by `|X| + |Z|` instead over-weights `Y`-heavy logicals, which is how the
first packaged claim of `d <= 32` on `[[512,54,*]]` was produced when the
witness is really 24. **Score stabilizer logicals with `|X union Z|`.**

## Dead end 3: a hard cap on check weight, and it binds

`schema/code.schema.json` allows at most 32 qubits per generator
(`$defs/generatorList/items/properties/X` and `/Z`, and the same
`maxItems: 32` on a CSS support list), so `w > 32` is not a low-ranked
candidate but a schema violation. `[[496,30,36]]` (inner `8-3-3`, outer
`62-10-9`) was refused at `checks/S/310/Z ... is too long` and cannot be filed
at any rank -- it is also the second-best `kd^2/n` this campaign produced. That
cap is exactly where every non-CSS entry on the board stops, and the binding
rule for this family is `beta * w_out <= 32` alongside `n_in n_out <= 700`.

## What passed the gate

All three staged candidates ran the trusted gate and all three passed:
`passed: true`, `verify.ok: true`, `refute.refuted: false` with the detail
"no lighter logical in 8000 RIS trials" (seeds 124356530, 909393092 and
317404972), no exact or WL-equivalent board duplicate, and
`novelty.board_advancing: true` with an empty `dominated_by` in the
`weight-9plus / unrestricted` stabilizer cell.

- **[[512,54,24]]**, check weight 32, `kd^2/n` 60.75: the CSS board entry
  [[64,18,8]] as outer with the non-CSS [[8,3,3]] as inner.
- **[[576,42,24]]**, `w` 32, `kd^2/n` 42.0: [[72,14,8]] outer, same inner.
- **[[672,28,30]]**, `w` 24, `kd^2/n` 37.5: [[84,14,10]] outer with the
  non-CSS [[8,2,3]] inner.

In each the witness is the outer's own witness lifted through a weight-3
logical of the inner code, which the verifier confirms is a genuine nontrivial
logical, and in each that weight equals the concatenation bound
`d_in d_out`, so the claim is witnessed *and* argued rather than merely
exhibited -- subject, as always, to the parents' own `d<=` claims.

They are staged for a human to review, unadjudicated beyond the gate. They are
kept because each costs nothing to hold and one may outlive a refutation of a
parent's distance; the campaign ledger holds the per-candidate verdicts behind
this note.

| inner x outer | product | `w` | `kd^2/n` | claim | gate |
|---|---|---|---|---|---|
| `8-3-3` x `64-18-8` | [[512,54,24]] | 32 | 60.75 | d <= 24 = bound `3*8` | passed |
| `8-3-3` x `72-14-8` | [[576,42,24]] | 32 | 42.0 | d <= 24 = bound `3*8` | passed |
| `8-2-3` x `84-14-10` | [[672,28,30]] | 24 | 37.5 | d <= 30 = bound `3*10` | passed |
| `8-3-3` x `56-12-8` | [[448,36,24]] | 32 | 46.3 | d <= 24 = bound `3*8` | built, not staged |
| `8-3-3` x `62-10-9` | [[496,30,36]] | 36 | 78.4 | **refused** | `maxItems: 32` |


## The negative that matters more than the win

Every non-CSS entry on the board carries `d <=`, because `verify/certify.py`
does not minimize a Pauli weight yet. That makes *any* construction inherited
from two upper bounds -- and this one is inherited twice -- soft in a way the
CSS side is not: RIS over the product's normalizer found a logical of weight 26
where the constructed witness was 32, i.e. the parents' distances do not
compose the way their witnesses suggest. Measuring the product is not optional,
and the claim must be the lightest thing anyone can construct, not the lightest
thing the builder happened to build.

## Reopen conditions

This route is bounded by `beta * w_out <= 32` and by the board's small
non-CSS codes as inner codes. Reopen it with either of: an inner code with a
large `k_in` and a uniformly weight-`d_in` symplectic basis (nobody on the board
has one -- the measured `beta` never sits at `d_in` for `k_in >= 3` except
`[[8,3,3]]`, and there at 4 against 3); or a truncated product in the style of
[[910,12,36]] / arXiv:2609.37231, which drops qubits instead of scaling `n` by
`n_in` and might reach a low-weight cell. Stop a variant if `beta * w_out > 32`
before `n` is interesting, which is where most of them stop.

## Provenance

Campaign run under model Mimo-V2.6-Flash, opencode harness, requested by the
maintainer. Four purpose-built scripts carried the session, none committed to
this repository: a concatenation builder, a packaging script that lifts the
outer's witnesses through the lightest inner subspace vectors, a product search
run first with the wrong weight model and then with the measured one, and an
RIS pass over the normalizer. The five measured candidates and their seeds are
recorded in the campaign ledger; the builders were session-local scratch and are
available from the author on request. Every distance here is
a witness-backed upper bound; nothing is certified exact.
