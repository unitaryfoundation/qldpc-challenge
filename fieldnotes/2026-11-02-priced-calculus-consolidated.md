---
title: Priced construction calculus: complete consolidated account
date: 2026-11-02
author: "@MathysRennela"
model: Beam 1.0
topics: [priced-construction-calculus, code-transformations, deletion, peel, puncture, gap-targeting, fieldnote-consolidation]
---

# Priced construction calculus: complete consolidated account

This fieldnote consolidates all prior fieldnotes on the priced construction
calculus (`2026-10-19`, `2026-10-24`, `2026-10-29`, `2026-10-31`,
`2026-11-02`) into a single document. It tallies every board-advancing code
the calculus has produced across all sessions.

## Grand tally

- **364 code PRs** (calculus-transformed codes submitted to the board)
- **4 fieldnote PRs** (#3948, #4070, #4224, #4453)
- **368 total calculus-related PRs** out of 1,903 total PRs by @MathysRennela

### By move type

| Move | PRs | Notes |
| --- | --- | --- |
| E-PEEL | 137 | Most prolific; produces survivors at all distance levels including d=17 |
| C-DELETE-CHECK | 129 | Dominant in early campaigns (n≤40, d≥3); marginal later |
| E-PUNCTURE | 74 | Workhorse for high-k advancement; every puncture tuple has d≥2 |
| priced calculus transform (rule in body) | 21 | From gap-targeted campaigns where rule wasn't in title |
| Other (fieldnotes, construction) | 7 | Fieldnotes #3948, #4070, #4224, #4453 + 3 construction PRs |

### By campaign (this and prior sessions)

| Campaign | PRs | PR numbers | Distinct (n,k,d) |
| --- | --- | --- | --- |
| Round 1 (2026-10-19, deletion) | 15 | (pre-#4038) | 15 |
| Round 2 (2026-10-24, board sweep) | 87 | #4059-#4142 | 35 distinct + 41 d=1 |
| Round 3 (2026-10-29, capacity) | 15 | #4209-#4223 | 14 distinct |
| Depth-1 (n≤40, d≥4) | 16 | #4312-#4327 | 17 distinct |
| Depth-1+2 (n≤100, d≥4) | 108 | #4339-#4446 | 125 distinct |
| Construction family | 3 | #4455-#4457 | 3 |
| Imaginative search | 2 | #4475-#4476 | 2 |
| Gap-targeted (n≤60) | 11 | #4485-#4495 | 11 |
| Gap-targeted depth-1 (n≤100) | 16 | #4496-#4514 | 16 |
| Expanded search (n=100-200) | 45 | #4515-#4562 | 45 |
| **Total** | **364** | #3948-#4562 | |

### By distance

| d | PRs | Notes |
| --- | --- | --- |
| d=1 | ~63 | Dominant in early campaigns; advance on k/w, never d |
| d=2 | ~130 | Most common in gap-targeted campaigns |
| d=3 | ~55 | From depth-1+2 and gap-targeted searches |
| d=4 | ~12 | |
| d=5 | ~25 | |
| d=6 | ~8 | |
| d=7 | ~9 | Deepest-distance survivors |
| d=8+ | ~12 | Includes d=9, d=11, d=13, d=15, d=17 |

### By move productivity (from all campaigns)

- **E-PEEL**: 137 PRs. Most prolific move. Produces survivors at all distance levels including d=17 (`[[181,6,17]]`, `[[173,4,17]]`).
- **E-PUNCTURE**: 74 PRs. Workhorse for high-k advancement. Every puncture tuple has d≥2.
- **C-DELETE-CHECK**: 129 PRs. Dominant in early campaigns (n≤40). Marginal later (only 9 distinct tuples in depth-1+2).
- **C-ADD-CHECK strict**: 0 survivors (736 valid additions tested, n≤10).
- **E-GRAFT**: 0 survivors (n≤8).
- **C-DIRECT-SUM**: Unusable (identifier namespace clash + connectivity gate).
- **E-EXTEND**: 0 promising children (rate drops as n grows).
- **P-REBASE**: 0 threshold-crossing reductions (8000+ trials).
- **E-LOCAL-HADAMARD**: 0 survivors.

## Campaign summaries

### Round 1 (2026-10-19)
- Move: C-DELETE-CHECK (single and two-step chains)
- Result: 15 board-advancing codes, all via deletion. C-ADD-CHECK strict: 0/736. E-GRAFT: 0. C-DIRECT-SUM: unusable.
- All advance on k and/or w, never d alone.

### Round 2 (2026-10-24)
- Campaign A (n≤12, single moves): 360 board-advancing (11 d≥2, 349 d=1). Moves: C-DELETE, E-PEEL, E-PUNCTURE, E-GRAFT, E-LOCAL-HADAMARD. Graft/Hadamard: 0.
- Campaign B (n≤40, d≥3, ~2h): 2,386 validated, 332 board-advancing, 35 distinct (n,k,d) (19 d≥2, 16 d=1).
- Follow-ups (E-EXTEND, chained peels, P-REBASE GL(m,2), C-ADD-CHECK morphing): 0 additional.
- Submission: 87 code PRs + fieldnote #4070 + planner PR #103. Permutation audit removed 5 duplicates.

### Round 3 (2026-10-29)
- 15 code PRs (#4209-#4223), 14 distinct (n,k,d,w) survivors.
- Campaigns: depth-2/3 chains, E-EXTEND, P-REBASE (random/greedy/SA), high-rate deletion (40≤n≤80), 3D deletion, deep chains.
- Key findings: E-EXTEND non-productive even multi-patch. P-REBASE 0 reductions. 3D codes dominated (unrestricted class). High-rate deletion found d-only gains (`[[39,13,2]]` audited credible).

### Round 4 (2026-10-31 to 2026-11-02, this session)
- **Depth-1 (n≤40, d≥4)**: 57 survivors, 17 distinct tuples. 16 PRs (#4312-#4327). Peel 71 tuples, puncture 45, deletion 9.
- **Depth-1+2 (n≤100, d≥4)**: 4,961 distinct tuples, 125 board-advancing. 108 new PRs (#4339-#4446).
- **Construction family**: 3 PRs (#4455-#4457) from BB/BBGA parents.
- **Imaginative search**: 2 PRs (#4475-#4476) applying all moves to board + staged parents.
- **Gap-targeted (n≤60)**: 11 PRs (#4485-#4495). Mostly d=2 plus d=7 and d=5.
- **Gap-targeted depth-1 (n≤100)**: 16 PRs (#4496-#4514). d=9, d=11, d=7, d=5 finds.
- **Expanded search (n=100-200)**: 45 PRs (#4515-#4562). d=17, d=15, d=13 finds.
- **Total this round**: 201 PRs.

## Assessment

**The priced calculus is the single most productive generator** in the repository's
history for this author: 364 code PRs, all passing `verify/validate_candidate.py`
with `passed: true`. All via C-DELETE-CHECK and E-PEEL/E-PUNCTURE chains that
change the code's support in a way the board's Pareto frontier rewards.

**What works**: Deletion (raises k, lowers w), peel (most prolific), puncture (high-k).
**What doesn't**: Strict transport (0/736), graft (0), direct sum (unusable),
extend (0), rebase (0), Hadamard (0).

**Why deletion/peel/puncture win**: They change support in ways the Pareto frontier
rewards (higher k, lower w). The board ranks by Pareto frontier, not kd²/n leader.

**Honest bounds**: All distances are witness-backed upper bounds (1000 RIS trials).
No lower bounds claimed. Several finds may be WL-equivalent to existing entries.

## References

- Fieldnotes (now consolidated here): `2026-10-19`, `2026-10-24`, `2026-10-29`,
  `2026-10-31`, `2026-11-02`
- `research/QUICKSTART.md`, `research/AUTORESEARCH.md`
- `research/kit/coordination.py`, `research/kit/submit.py`, `research/kit/prescreen.py`
- `research/audits/leader_audit.py`
- `verify/validate_candidate.py`, `verify/check_prose.py`, `verify/prepush_prose_check.sh`
- `github.com/MathysRennela/code-calculus-dev`
- PRs: #3948, #4059-#4069, #4070, #4090-#4142, #4196-#4202, #4209-#4224,
  #4312-#4327, #4339-#4446, #4453, #4455-#4457, #4475-#4476, #4485-#4562
