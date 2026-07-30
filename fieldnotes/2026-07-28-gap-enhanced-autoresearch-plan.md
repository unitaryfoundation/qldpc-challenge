---
title: "GAP-enhanced autoresearch: systematic group enumeration for 2BGA and coset code construction"
date: 2026-07-28
author: "@mathysrennela"
model: MiMo-V2.5
topics: [2bga, coset-2bga, group-theory, gap-system, autoresearch, plan]
status: implemented  # see 2026-07-28-gap-bridge-implementation.md
---

## Motivation

The current research kit constructs codes from 5 hand-coded group families:
cyclic products (abelian BB), dihedral, metacyclic, symmetric, and
alternating. GAP (Groups, Algorithms, Programming) is a computational
discrete algebra system that catalogues all finite groups up to order 2000
(~49 million groups). The gap between what the kit can build and what exists
is the design-space bottleneck: the fieldnote record shows that **structure
beats sampling volume** (designed-divisor on cyclic groups produced
[[126,18,14]], [[210,24,20]], [[258,32,22]] from 13k candidates; 85k random
samples across 15 nonabelian groups produced nothing board-advancing). GAP's
value is not "more random groups" — it is **systematic enumeration with
structural filtering**.

## What GAP provides that the kit lacks

**Group catalog.** AllSmallGroups(n) returns every group of order n, up to
isomorphism. The kit currently has ~5 families; for order 60 alone GAP
returns 13 distinct groups (of which the kit covers 3).

**Subgroup lattice.** ConjugacyClassesSubgroups(G) returns the full
subgroup lattice. The coset construction (coset.py) requires a subgroup H
and its normalizer N_G(H). Currently H is chosen by hand. GAP enumerates
all subgroups and ranks them by |N_G(H)/H| — the quantity the fieldnote
record identifies as the key driver of distance in coset codes.

**Conjugacy classes.** ConjugacyClasses(G) partitions G into natural
conjugacy classes. Supports that are unions of conjugacy classes are
invariant under inner automorphisms — a symmetry that may correlate with
good distance. The kit currently picks supports randomly.

**Structural invariants.** AbelianInvariants, DerivedSeries,
NilpotencyClass, Centre, FrattiniSubgroup — these partition the design
space into coarse families and enable targeted search (e.g. "only solvable
groups with large center" or "nilpotency class exactly 2").

**Isomorphism testing.** IsomorphismGroups detects structurally equivalent
codes from different group presentations. The kit's RREF fingerprint
detects identical stabilizer groups but not isomorphic codes — two
presentations of the same group can produce the same code via different
supports, wasting surrogate evaluations.

## Architecture: GAP ↔ Python bridge

Integration via subprocess: Python writes a GAP script to a temp file, calls
`gap -q`, parses JSON output. GAP startup is ~0.3-1s; amortize by batching
entire group orders in one script. No Python bindings required.

New file: `research/kit/gap_bridge.py`

Key functions:
- `all_groups_of_order(n)` — returns list of Cayley tables + metadata
  (structure description, abelian flag, center size, derived order, etc.)
- `gap_coset_candidates(G, min_nrm_quotient)` — for a given G, find all
  subgroups H with |N_G(H)/H| >= threshold
- `conjugacy_class_supports(mul, weight)` — generate supports that are
  unions of conjugacy classes

Caching: group catalogs for each order are memoized to disk (JSON) so
repeated sweeps don't re-enumerate.

## Campaign plan

### Phase 1: Exhaustive group enumeration (orders 60-120)

**Target:** unrestricted x weight-6 and unrestricted x weight-8 boards at
n = 120-240.

**Method:** For each non-abelian group of order 60-120, build 2BGA codes
with:
- Random supports of weight 4 and 5 (baseline)
- Conjugacy-class-invariant supports (structured)

**Budget:** ~50k candidates screened at 400 trials each (~2h with gf2_fast).

**Why this range:** n = 2N, so order 60-120 gives n = 120-240 — the sweet
spot where verification is tractable and the board is competitive. Below 60
the design space is small (few groups); above 200 the inflation/trial-depth
problem from the large-n calibration fieldnote kicks in.

### Phase 2: Coset codes with GAP subgroup lattices (orders 60-200)

**Target:** unrestricted x weight-8 board at n = 120-400.

**Method:** For each group G, enumerate all subgroups H with
|N_G(H)/H| >= 6 (the threshold identified in the fieldnote record: the
coset records [[168,20,14]], [[180,20,14]], [[336,20,21]] live on groups
with |N_G(H)/H| = 30-84). Build coset codes for each (G, H) pair.

**Blocked route:** Simple/almost-simple groups with small H — the fieldnote
record shows these plateau at d=2. Skip them. Focus on solvable groups
with large normalizer quotients.

**Budget:** ~100k candidates at 400 trials each (~4h).

**Key difference from current kit:** The kit's coset.py requires manual
(G, H) selection. GAP computes the full subgroup lattice, so this is
systematic rather than ad-hoc.

### Phase 3: Designed-divisor for non-abelian groups (targeted)

**Target:** Sparse cells where designed-divisor on cyclic groups has not
yet been applied — specifically odd-k cells and weight-8 cells at n = 120-300.

**Method:** For non-abelian groups, use GAP's structural invariants to
identify which group algebras admit controlled k. The abelianization
G/[G,G] constrains the rank of L(a) and R(b), and central idempotents
(identified via CharacterTable) decompose the algebra into blocks. Choose
supports within a controlled block to guarantee k by construction.

This extends the designed-divisor trick (fieldnote 2026-07-14) from cyclic
groups to arbitrary finite groups.

**Budget:** ~20k candidates at 1k trials initial, 50 finalists at 1M
confirmation.

### Confirmation protocol (all phases)

All candidates pass through the standard ladder:
- Screen at 400 trials (surrogate upper bound)
- Ladder-confirm survivors: 2k -> 8k -> 60k -> 1M trials
- Keep only values flat across the ladder (fieldnote discipline)
- Package with make_submission, validate with validate_candidate
- Stage for human review — never commit to codes/

## Expected output

**unrestricted x weight-6:** Fill the n = 120-240 range with non-abelian
2BGA codes (currently sparse — only a few metacyclic/dihedral entries).

**unrestricted x weight-8:** Coset codes at n = 120-300 with GAP-optimized
(G, H) pairs (currently only 5 coset entries on the board).

**Odd-k codes:** Non-abelian groups with even-size supports (the parity
rule from fieldnote 2026-07-14) at n = 120-300 — a niche abelian BB
cannot enter.

Realistic target: 5-15 new board entries advancing Pareto frontiers in 1-2
cells.

## Risks and mitigations

**GAP not installed.** Provide brew install gap / conda instructions in
gap_bridge.py. Graceful fallback: if GAP unavailable, fall back to existing
random samplers with a warning.

**Large groups slow.** Cap at order <= 200 (n <= 400). Larger n has the
inflation/trial-depth problem from the large-n calibration fieldnote.

**Simple groups blocked.** Skip simple/almost-simple groups with small H.
Focus on solvable groups with large normalizer quotients.

**Duplicate codes across groups.** Use RREF fingerprint for intra-sweep
dedup. Use GAP's IsomorphismGroups for cross-group isomorphism detection
(expensive; only on finalists).

## Compute estimate

- Phase 1: ~50k candidates x 400 trials = 20M surrogate evaluations (~2h)
- Phase 2: ~100k candidates x 400 trials = 40M surrogate evaluations (~4h)
- Phase 3: ~20k x 1k + 50 x 1M confirmation (~6h)
- Total: ~12h screening + confirmation

With gf2_fast extension (make fast, ~30-170x over pure Python), this is
a single overnight run.
