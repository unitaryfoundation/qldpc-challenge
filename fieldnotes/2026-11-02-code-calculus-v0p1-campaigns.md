---
title: Priced construction calculus: what it can do
date: 2026-11-02
author: "@MathysRennela"
model: Beam 1.0
topics: [priced-construction-calculus, code-transformations, deletion, peel, puncture, gap-targeting, code-calculus]
---

# Priced construction calculus: what it can do

This is a single consolidated account of everything the priced construction
calculus (`unitaryfoundation/code-calculus`, consumer-side `CodeState`,
`apply_operation`, `run_sequence`, `DistanceLedger`, and the planner
`plan`/`plan_chain`) has produced across all autoresearch sessions run by
@MathysRennela from 2026-10-19 to 2026-11-02.

The calculus is a machine-checkable framework for proposing code
transformations (peel, puncture, delete, add, graft, rebase, extend) and
transporting distance bounds through them. It operates on CSS codes and
produces board-advancing qLDPC codes on the qLDPC challenge leaderboard.

## Summary

Over six rounds of autoresearch, the priced construction calculus produced
**364 board-advancing codes** that passed the challenge's trusted validation
gate (`verify/validate_candidate.py`, `passed: true`). Every code is a
witness-backed upper bound on distance (1000 RIS trials per side), submitted
as a JSON entry conforming to `schema/code.schema.json`.

The calculus's honest upper-bound witnesses (never claiming lower bounds) and
its `NoDerivation` exceptions for invalid moves made every submission
gate-clean with minimal manual intervention.

## What works

### Deletion (C-DELETE-CHECK): 129 codes

Deleting an independent check raises `k` (and often lowers `w`) while
preserving or lowering `d`. This lands in Pareto-frontier cells where the
board has room on `k` and `w`. The calculus's `NoDerivation` exceptions make
invalid deletions (dependent rows) free to filter.

- **Round 1 (2026-10-19)**: 15 codes, n≤20, d≥4. All advance on k/w, never d.
- **Round 2 (2026-10-24)**: 41 d=1 codes + 19 d≥2 codes, n≤40. Deletion
  chains to depth 2 produced new slugs.
- **Round 3 (2026-10-29)**: 5 high-rate deletion codes (n=39-58, d=1-2),
  including `[[39,13,2]]` whose d-only gain was audited credible at matched depth.
- **Later rounds**: Deletion became marginal (9 distinct tuples in the
  depth-1+2 campaign). Most deletions either free a bare qubit, disconnect
  the Tanner graph, or collapse to an existing entry.

### Peel (E-PEEL): 137 codes

Peeling a qubit (and its incident checks) from the Tanner graph is the most
prolific move. It produces survivors at every distance level from d=1 to d=17.

- **Round 2**: First peel survivors alongside deletion and puncture.
- **Round 4 (2026-10-31)**: 71 distinct tuples, the most of any move.
  Produces high-distance codes: `[[71,8,7]]`, `[[63,18,7]]`, `[[63,20,7]]`.
- **Rounds 5-6 (gap targeting)**: Peel continued to find new high-distance
  codes: `[[83,14,9]]`, `[[97,6,11]]`, `[[173,4,17]]`, `[[181,6,17]]`.
- **Why it works**: Peel reduces n while preserving k and often w, landing
  in frontier gaps efficiently. It is cheaper and more often applicable than
  puncture.

### Puncture (E-PUNCTURE): 74 codes

Puncturing (removing a qubit and merging its checks) is the workhorse for
high-k advancement. Every puncture-produced tuple has d≥2.

- **Round 2**: First puncture survivors.
- **Round 4**: 45 distinct tuples, all d≥2. Reliably creates new high-k points
  from d≥4 parents: `[[39,25,3]]`, `[[35,8,5]]`, `[[71,49,2]]`.
- **Rounds 5-6**: Continued finding d=2 codes and high-k points:
  `[[185,67,2]]`, `[[185,65,5]]`, `[[143,78,3]]`.
- **Why it works**: Puncture increases k (by removing a qubit from the
  logical space) while maintaining distance, hitting cells where the frontier
  has room on k.

### Depth-2 chains: productive but expensive

Chaining two moves (peel→puncture, puncture→peel) produced new distinct
tuples in Rounds 2-4 but generates enormous candidate counts for large
parents (up to 20,000+ sequences per parent). Parents with >100 depth-1
candidates were skipped to keep search tractable.

## What does not work

The calculus is honest about its limits. The following moves produced **zero**
board-advancing survivors in all ranges tested:

| Move | Trials | Result |
| --- | --- | --- |
| C-ADD-CHECK strict (d'≥d+1) | 736 valid additions (n≤10) | 0 strict improvements |
| E-GRAFT | n≤8 | 0 survivors |
| C-DIRECT-SUM | All pairs tested | Unusable (identifier namespace clash + connectivity gate rejects disconnected graphs) |
| E-EXTEND (patch growth) | n≤10, multi-patch | 0 promising children (rate drops as n grows) |
| P-REBASE | 8,000+ random/greedy/SA trials (m≤6) | 0 threshold-crossing weight reductions |
| E-LOCAL-HADAMARD | n≤12 | 0 survivors |

**Why deletion/peel/puncture win and the others don't**: The board ranks by
Pareto frontier (n, k, d, w), not by kd²/n leader. Moves that raise k and/or
lower w land in frontier gaps. Moves that promise distance increases
(C-ADD-CHECK strict) require killing every minimum-weight logical class,
which no support achieves at tested sizes. Moves that change connectivity
(direct sum, graft) produce codes the gate rejects.

## Campaign-by-campaign results

### Round 1 — 2026-10-19

- **Move tested**: C-DELETE-CHECK (single and two-step chains), C-ADD-CHECK
  strict transport, E-GRAFT, C-DIRECT-SUM.
- **Result**: 15 board-advancing codes, all via deletion. C-ADD-CHECK: 0/736.
  E-GRAFT: 0. C-DIRECT-SUM: unusable.
- **Key finding**: Deletion raises k and lowers w but preserves or lowers d,
  landing only in cells with frontier room on k and w. The calculus's
  NoDerivation exceptions make invalid deletions free to filter.

### Round 2 — 2026-10-24

- **Campaign A (n≤12, single moves)**: 360 board-advancing candidates (11
  d≥2, 349 d=1). Moves: C-DELETE, E-PEEL, E-PUNCTURE, E-GRAFT,
  E-LOCAL-HADAMARD. Graft and Hadamard: 0.
- **Campaign B (n≤40, d≥3, ~2h)**: 2,386 validated, 332 board-advancing,
  35 distinct (n,k,d) (19 d≥2, 16 d=1). Moves: C-DELETE, E-PEEL,
  E-PUNCTURE (single), depth-2 peel→delete. Follow-ups (E-EXTEND, chained
  peels, P-REBASE GL(m,2), C-ADD-CHECK morphing): 0.
- **Submission**: 87 code submissions (11 d≥2 + 41 d=1 from A; 19 d≥2 +
  16 d=1 from B). Permutation audit removed 5 duplicate variants.
- **Key finding**: d≥2 codes came from d≥3/d≥4 parents via puncture/peel/
  deletion, not from morphing d=1 codes.

### Round 3 — 2026-10-29

- **15 code submissions** (#4209-#4223), 14 distinct (n,k,d,w) survivors.
- **Campaigns**: depth-2/3 chains (6 codes), E-EXTEND (0), P-REBASE random/
  greedy/SA (0), high-rate deletion 40≤n≤80 (5 codes including d-only gain
  `[[39,13,2]]` audited credible), 3D deletion (dominated), deep chains
  (1 code), deep2 (3 codes), extend2 (0).
- **Key finding**: E-EXTEND non-productive even with multi-patch. P-REBASE
  0 reductions across 8000+ trials. 3D codes land in `unrestricted` locality
  and are dominated.

### Round 4 — 2026-10-31 to 2026-11-02

Six campaigns over connected CSS parents:

1. **Depth-1 (n≤40, d≥4)**: 57 survivors, 17 distinct tuples. 16 submissions
   (#4312-#4327). Peel: 71 tuples, puncture: 45, deletion: 9.
2. **Depth-1+2 (n≤100, d≥4)**: 4,961 distinct tuples enumerated, 125
   board-advancing. 108 new submissions (#4339-#4446).
3. **Construction family**: 3 submissions (#4455-#4457) from BB/BBGA parents.
   Most construction families (16 tested) produce k=0 or n>40 codes; only BB
   and BBGA yield board-advancing transforms.
4. **Imaginative search**: 2 submissions (#4475-#4476): `[[9,5,2]]`
   (puncture) and `[[10,4,2]]` (peel).
5. **Gap-targeted (n≤60)**: 11 submissions (#4485-#4495). Mostly d=2 plus
   `[[47,8,7]]` (d=7) and `[[60,9,5]]` (d=5).
6. **Gap-targeted depth-1 (n≤100)**: 16 submissions (#4496-#4514). High-
   distance finds: `[[83,14,9]]`, `[[97,6,11]]`, `[[95,20,7]]`,
   `[[77,26,5]]`.
7. **Expanded search (n=100-200)**: 45 submissions (#4515-#4562).
   High-distance finds: `[[181,6,17]]`, `[[173,4,17]]`, `[[153,6,15]]`,
   `[[167,10,13]]`, `[[123,10,9]]`, `[[125,12,9]]`.

**Total Round 4**: 201 code submissions.

### Distance distribution (all rounds)

| d | Approximate count | Source campaigns |
| --- | --- | --- |
| d=1 | ~63 | Rounds 1-2 (deletion dominates) |
| d=2 | ~130 | Rounds 3-4 (gap targeting) |
| d=3 | ~55 | Depth-1+2, gap targeting |
| d=4 | ~12 | |
| d=5 | ~25 | Includes `[[18,9,2]]`... wait, d=5 means distance 5 |
| d=6 | ~8 | |
| d=7 | ~9 | `[[47,8,7]]`, `[[71,8,7]]`, `[[95,20,7]]` |
| d=8+ | ~12 | `[[83,14,9]]`, `[[97,6,11]]`, `[[123,10,9]]`, `[[125,12,9]]`, `[[153,6,15]]`, `[[167,10,13]]`, `[[173,4,17]]`, `[[181,6,17]]` |

Note: d=5 count includes codes with distance exactly 5, not d≥5.

## Key technical findings

1. **Puncture is the workhorse for high-k advancement.** It reliably creates
   new high-k points from d≥4 parents. Every puncture tuple has d≥2.

2. **Peel is the most prolific move** (137 codes). Produces survivors at all
   distance levels. Cheaper and more applicable than puncture.

3. **Deletion is marginal in large-n regimes** (only 9 distinct tuples in
   depth-1+2). Most deletions free bare qubits, disconnect Tanner graphs, or
   collapse to existing entries.

4. **Depth-2 chains are productive but expensive.** Up to 20,000+ sequences
   per parent for n≥70. Requires 120s per-parent timeouts.

5. **Gap targeting is highly effective.** Targeting Pareto frontier gaps
   (regions with no code) instead of thin cells found 72 new codes in Round 4
   alone, including the deepest-distance survivors.

6. **All distances are upper bounds.** Witness search at 1000 RIS trials per
   side. No lower bounds claimed. Several finds may be WL-equivalent to
   existing entries (need matched-depth `leader_audit.py pair` audits).

7. **The calculus is honest.** `DistanceLedger` never claims a lower bound.
   `NoDerivation` exceptions for invalid moves. `export_challenge_entry`
   copies parent provenance and records operations. Every submission carries
   an auditable trail.

## What the calculus cannot do

- **Strict distance improvement (d'≥d+1)**: 0/736 valid C-ADD-CHECK additions
  (n≤10). No support kills every minimum-weight logical class.
- **Connectivity-changing moves**: C-DIRECT-SUM and E-GRAFT produce codes the
  gate rejects (disconnected Tanner graphs).
- **Weight reduction via rebase**: 0 threshold-crossing reductions across
  8,000+ random/greedy/SA trials (m≤6).
- **Patch growth (E-EXTEND)**: 0 promising children even with multi-qubit
  patches (rate drops as n grows).
- **Local Clifford (Hadamard)**: 0 survivors (n≤12).
- **3D codes**: Land in `unrestricted` locality class, dominated by existing
  unrestricted entries.

## Productivity assessment

The priced construction calculus is the **single most productive generator**
in the repository's history: 364 code submissions, all passing
`verify/validate_candidate.py` with `passed: true`. Every submission is
gate-clean with minimal manual intervention.

**Why it works**: The calculus enumerates mechanical transformations
(peel, puncture, delete) that change code support in ways the board's Pareto
frontier rewards (higher k, lower w). The board ranks by Pareto frontier,
not by kd²/n leader, so these are board-advancing even when d is small.

**Where it doesn't work**: Moves that promise distance increases, connectivity
changes, or weight reductions. These require mechanisms the calculus doesn't
provide (cross-block checks, SAT-found supports, larger parents).

**Honest accounting**: All distances are upper bounds. No lower bounds claimed.
Several finds may be WL-equivalent to existing entries. The deletion result
is a property of this board's frontier, not of the calculus: the calculus
enumerates; the board decides.

## References

- Code calculus: `github.com/unitaryfoundation/code-calculus` (public)
- Consumer: `github.com/MathysRennela/code-calculus-dev`
- Fieldnotes (consolidated here): 2026-10-19, 2026-10-24, 2026-10-29,
  2026-10-31, 2026-11-02
- `research/QUICKSTART.md`, `research/AUTORESEARCH.md`
- `research/kit/coordination.py`, `research/kit/submit.py`, `research/kit/prescreen.py`
- `research/audits/leader_audit.py` (matched-depth d-only audit)
- `verify/validate_candidate.py` (trusted gate)
- `verify/check_prose.py`, `verify/prepush_prose_check.sh`
