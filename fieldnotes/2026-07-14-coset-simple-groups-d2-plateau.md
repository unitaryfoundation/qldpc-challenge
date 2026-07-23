---
title: Coset 2BGA on simple groups with small subgroups sits on a d=2 plateau
date: 2026-07-14
author: "@willzeng"
model: Claude Fable 5
topics: [coset-2bga, blocked-route, group-theory]
---

**Finding.** Coset 2BGA codes built from simple or almost-simple groups G
with a small non-normal subgroup H (C2/C3/C4) do not reach useful distance:
across 10 (G, H) pairs — PSL(2,7)/C2, PGL(2,7)/C4 and /C3, A6/C3 (two
classes), S6/S3, PSL(2,8)/C3, PSL(2,11)/C3, A6/C2, S6/C4, with
n ∈ {168, 224, 240, 336, 360, 440} — random screening (4,185 samples on
A6/C3 alone, ~730 k-filtered overall), simulated annealing (~75s/config),
and a 252-restart / ~75k-evaluation local search all topped out at **d = 6,
with d = 2 typical**, despite healthy k (up to 34).

**Contrast.** The record coset codes ([[168,20,14]], [[180,20,14]],
arXiv:2606.17268) live on *solvable metacyclic* groups where the normalizer
quotient is large (|N_G(H)/H| = 30–84). A large right-action class space
appears necessary for distance in this construction; simple groups with tiny
H give the right action almost nothing to act on. Consistent with this, the
follow-up sweep on C56⋊C6 / C2 (|W| = 84) immediately produced
[[336,20,21]] and [[336,12,26]].

**Sampler guards discovered en route** (worth hard-coding in any coset
sampler): odd |b| forces k = 0 (300/300 across four size combos);
b = the whole normalizer quotient is a k-inflating degeneracy that yields
k = 54–70 at d = 2 — screening on k·d²/n without a d floor will chase it.

**Boundary.** This blocks {simple/almost-simple G} × {|H| ≤ 4} at the stated
search depth (~10⁵ evaluations total). It says nothing about larger H in
simple groups, or about lifted/balanced-product constructions on the same
groups. Reopen with a genuinely different mechanism, not more of the same
sampling.

**Also closed (exhaustion, same campaign):** the n=180 coset optimum
[[180,20,14]] is locally optimal under all 1-element moves and all 447,859
2-element correlated moves — improving it needs a different construction,
not a better local search.
