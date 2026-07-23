---
title: Confirmation is the bottleneck, not generation
date: 2026-07-01
topics: [budgeting, process, milp]
---

Screening covers hundreds of candidates in seconds; deep confirmation takes
minutes–hours per survivor, and exact MILP certification can run >15 min at
n≈126 without finishing. Consequences:

- **Budget a sweep around how many survivors you can confirm**, not how many
  candidates you can generate. Carrying 3 honest survivors beats 15 inflated
  ones.
- Never block a sweep on exact certification; it is a separate, post-hoc
  tier for standouts.
- One code per PR (CI-enforced) at ~12 min of gate time each — promote
  selectively, best-settled first.

*Ported 2026-07-23 from `research/AUTORESEARCH.md`, "Field notes from past
campaigns (2026-06 → 2026-07)".*
