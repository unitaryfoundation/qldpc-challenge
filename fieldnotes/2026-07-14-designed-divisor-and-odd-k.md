---
title: "Two constructive mechanisms: designed-divisor GB (k by construction) and the odd-k parity rule"
date: 2026-07-14
author: "@willzeng"
model: Claude Fable 5
topics: [gb-codes, constructions, odd-k, mechanism]
---

Two mechanisms from the 2026-07-14 campaign that turn blind sweeps into
directed ones. Both are positive results, recorded here because the
*mechanism* is the transferable part, beyond any single code.

**1. Designed-divisor GB: fix k first, spend the search on d.** For a cyclic
GB code on Z_N, choosing both generator polynomials as multiples of a common
divisor g(x) | x^N − 1 guarantees k = 2·deg g by construction. The search
then reduces to enumerating (e.g. meet-in-the-middle) weight-w multiples of
g, ranking purely on surrogate distance — no compute wasted on k-collapsed
candidates, and no k/d misalignment. One 13,200-candidate sweep over
N = 63–147 at support-5 produced [[126,18,14]], [[210,24,20]], and
[[258,32,22]] (then a 4× cell-efficiency record). For contrast, 85,828
random support-5 samples over 15 nonabelian groups produced nothing
board-advancing: **structure beat sampling volume by orders of magnitude.**
The subsequently-submitted [[390,82,·]] family shows the same trick scaling
further (Z_195, larger divisors, higher weight).

**2. When is odd k possible?** Verified identity (400-sample spot check) for
2BGA with supports a, b on group G:
k = 2|G| − rank[L(a)|R(b)] − rank[L(a⁻¹)|R(b⁻¹)], so **odd k requires the
inversion a → a⁻¹, b → b⁻¹ to flip a rank parity.** Consequences, all
confirmed empirically: abelian groups never give odd k; inverse-closed
supports never do (0/1,342 odd-k finds violated this); an even-size support
appears required — support-3 × support-3 gave 0 odd-k in 27,000 samples, so
**the weight-6 cell is closed to odd k** for this construction. Group
structure gates the rate: PSL(2,7) ~29% of samples odd-k, S5 ~15%,
SL(2,5) 0.4% (central Z2 hurts), solvable metacyclic 0% (0/24,000).
Odd-k codes occupy Pareto slots abelian constructions cannot reach
(e.g. [[240,15,15]] at w8), but odd k is not itself a board axis — check
domination before spending confirmation compute.

**Boundary.** Both mechanisms are stated for two-block group-algebra
constructions over GF(2). The parity rule's "even support size required" is
empirical (27k samples), not proved.
