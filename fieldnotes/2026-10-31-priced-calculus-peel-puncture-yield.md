---
title: Priced construction calculus: peel and puncture carry the board-advancing yield
date: 2026-11-01
author: "@MathysRennela"
model: Beam 1.0
topics: [priced-construction-calculus, code-transformations, deletion, peel, puncture]
---

## Finding

Two campaigns of the priced construction calculus over connected CSS parents.

**Campaign 1** (depth-1, `n <= 40`, `d >= 4`): 57 board-advancing
survivors across 17 distinct `(n, k, d, w)` tuples. 16 submitted as PRs
#4312-#4327 (the `[[11,3,3]]` candidate is an exact duplicate of an
existing board entry and was dropped).

**Campaign 2** (depth-1 + depth-2, `n <= 100`, `d >= 4`): 4,961 distinct
`(n, k, d, w)` tuples enumerated, of which 125 had board-advancing
survivors. After excluding the 16 already submitted and one exact duplicate,
108 new distinct tuples were submitted as PRs #4339-#4446.

In total, **124 PRs** were submitted from this campaign family.

Rule breakdown across all 125 distinct board-advancing tuples:

| Move | Distinct tuples |
| --- | --- |
| E-PEEL | 71 |
| E-PUNCTURE | 45 |
| C-DELETE-CHECK | 9 |

Distance distribution: d=2 (32), d=3 (39), d=4 (12), d=5 (25),
d=6 (8), d=7 (9). The d=7 finds (`[[71,8,7]]`, `[[63,18,7]]`,
`[[63,20,7]]`, etc.) are the deepest-distance survivors.

For the first time in this campaign family, peel and puncture are the
dominant productive moves rather than deletion. Peel produced the most
distinct tuples (71), followed by puncture (45). Deletion found only 9.

## Assessment of the calculus

- **Puncture is the workhorse for high-k advancement.** It reliably creates
  new high-`k` points from d >= 4 parents (e.g. `[[39,25,3]]`,
  `[[35,8,5]]`, `[[71,49,2]]`). Every puncture tuple has d >= 2.
- **Peel is the most prolific move** overall (71 distinct tuples), producing
  survivors across all distance levels including d=7. It is cheaper and more
  often applicable than puncture.
- **Deletion is marginal in this regime** (9 tuples). Most deletions either
  free a bare qubit, disconnect the Tanner graph, or collapse to an existing
  entry.
- **Depth-2 chains** (peel->puncture, puncture->peel) are productive but
  generate enormous candidate counts for large parents (n >= 70, up to
  20,000+ sequences per parent), requiring per-parent timeouts (120s).
  Parents with >100 depth-1 candidates were skipped to keep the search
  tractable.
- **The calculus is efficient at producing board-advancing CSS codes** when
  restricted to peel/puncture on connected d >= 4 parents: 125
  board-advancing survivors, all validated with `passed: true`.
- **Limits:** all distances are witness-backed upper bounds (1000 RIS trials
  per side); several finds are possibly WL-equivalent to existing entries
  and need matched-depth follow-up. No graft/Hadamard/rebase/extend gains
  were sought in this run.

## Suggested next steps

1. Matched-depth `leader_audit.py pair` audits for the possibly-equivalent
   tuples before merging.
2. Deeper witness search on the d = 2 survivors to settle whether any reach
   d = 3.
3. Explore n <= 100, d >= 5 parents with depth-2 chains, skipping parents
   that generate excessive candidate counts.
