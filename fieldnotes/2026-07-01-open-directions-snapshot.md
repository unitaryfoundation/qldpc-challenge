---
title: "Open directions that produced the early wins (snapshot, 2026-06 → 2026-07)"
date: 2026-07-01
topics: [directions, 2bga, weight-9plus, 2d-local, annealing]
---

A historical snapshot of the directions that produced the first months'
wins, preserved as recorded; several have since been executed or superseded
(noted inline). Treat as a map of *where wins came from*, not a current
to-do list — check the research log for what has landed since.

- **Nonabelian 2BGA beyond n=200** — outside the exhaustive enumeration, so
  novelty is real. S5 gave odd-k [[240,13,15]] (odd k is unreachable by
  abelian BB — a niche only nonabelian constructions can enter); PSL(2,7)
  gave [[336,20,20]], then a board-best efficiency. Untried neighbors at the
  time: PSL(2,8), PSL(2,11), SL(2,7), other simple/Hurwitz groups.
  *(Since executed: the 2026-07-14 campaign swept SL(2,7) and PSL(2,8);
  see those submission notes. For coset variants, simple groups with small
  subgroups are a blocked route — see the d=2 plateau fieldnote.)*
- **The weight-9plus cell is thin.** Support-5 2BGA opens it; apply the
  1M-trial floor from the start (this family is the worst inflater).
  *(Since executed: designed-divisor GB filled the cell — [[126,18,14]],
  [[210,24,20]], [[258,32,22]], and the later [[390,82,·]] family.)*
- **2D-local grafts:** codes dominated on the unrestricted board still set
  locality records ([[216,15,11]] is a bilayer k-record only because of its
  layout). Seeded, deterministic graft replay gives bit-exact provenance for
  a checkpointed matrix. *(Still open.)*
- **Re-mining old low-trial sweep artifacts at honest trial counts** is
  cheap and productive. *(Still open.)*
- **Annealing (screen-then-confirm) beats blind sampling** once a fertile
  group is chosen — but tune acceptance first (T_HI=2.0 ran at ~0.1%
  acceptance, far too cold). *(Since diagnosed: the acceptance problem was
  k-destroying moves, not temperature — see the 2026-07-14 annealing
  fieldnote.)*

*Ported 2026-07-23 from `research/AUTORESEARCH.md`, "Field notes from past
campaigns (2026-06 → 2026-07)".*
