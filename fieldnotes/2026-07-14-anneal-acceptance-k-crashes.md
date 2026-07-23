---
title: The 0.1%-acceptance annealing problem was never temperature — it is k-destroying moves
date: 2026-07-14
author: "@willzeng"
model: Claude Fable 5
topics: [annealing, search-tuning, 2bga]
---

**Finding.** Simulated annealing over 2BGA support sets was historically run
at ~0.1% acceptance and written off as "too cold." Instrumenting the move
loop shows the real cause: **60–80% of single-support mutations destroy k
entirely** (k → 0 or below the target floor), and a k=0 candidate scores so
badly that Metropolis rejects it at any reasonable temperature. Temperature
was never the knob.

**Fix.** Reject k-crashing moves *before* the Metropolis step (cheap: k via
gf2 rank on the mutated supports), and tune temperature only over k-viable
moves. Among k-viable moves, acceptance at T = 1–2 is ~50%; production runs
at T = 1.5 with cooling then actually anneal. On the metacyclic 2BGA family
this lifted a screened [[288,8,18]] seed to the board's [[288,16,16]]
(weight-6 cell best at the time), and [[360,10,40]] → [[360,18,38]] at
screen depth.

**Numbers.** Tuning runs: order-100–180 metacyclic/dicyclic groups, 4,700
random screens + ~2,500 anneal evaluations; acceptance measured 5.7–12.1%
across configs after the fix (vs ~0.1% before). A separate coset-2BGA
campaign reproduced the pattern: raising T_HI 1.2 → 1.8 helped only after
k-crash pre-rejection was in place.

**Boundary.** Measured on 2BGA/coset-2BGA support mutations. Any family
whose moves can silently zero k (most two-block algebraic constructions)
likely behaves the same; families with k fixed by construction (e.g.
designed-divisor GB, where k = 2·deg g is invariant under the move set) do
not need the pre-rejection and can spend the temperature budget on d.
