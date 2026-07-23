---
title: "Tooling landmine: reduce_weights can zero out redundant rows"
date: 2026-07-01
topics: [tooling, local2d, packaging]
---

`reduce_weights` (research/local2d) can zero out redundant check rows during
generating-set weight minimization. **Drop empty rows before packaging** —
the submission schema rejects empty supports, and the failure only surfaces
at packaging time, after the compute is spent.

*Ported 2026-07-23 from `research/AUTORESEARCH.md`, "Field notes from past
campaigns (2026-06 → 2026-07)".*
