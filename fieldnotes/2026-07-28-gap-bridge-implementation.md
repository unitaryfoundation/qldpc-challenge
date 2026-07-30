---
title: "GAP bridge implementation: smoke-tested, ready to launch Phase 1 and 2"
date: 2026-07-28
author: "@mathysrennela"
model: MiMo-V2.5
topics: [2bga, coset-2bga, gap-system, autoresearch, implementation, launch]
status: implementation
---

## What shipped

Three new files in `research/kit/`, all verified end-to-end:

| File | Lines | Purpose |
|------|-------|---------|
| `gap_bridge.py` | ~560 | GAP ↔ Python bridge via subprocess |
| `campaign_gap_2bga.py` | ~200 | Phase 1: systematic 2BGA enumeration |
| `campaign_gap_coset.py` | ~210 | Phase 2: coset code enumeration |

### gap_bridge.py

Core API:
- `all_groups_of_order(*orders)` — returns Cayley tables + metadata for every
  group of the given orders. Memoized to `research/candidates/_gap_cache/`.
- `gap_coset_candidates(None, min_nrm_q, order=N, index=I)` — subgroup lattice
  for group index I in GAP's AllSmallGroups(N), filtered by normalizer quotient.
- `conjugacy_class_supports(mul, weight)` — pure-Python fallback for structured
  supports (union of conjugacy classes). No GAP needed.

### Subprocess pitfalls solved (recorded in `/memories/repo/gap-bridge.md`)

1. **stdin hijack**: GAP reads stdin instead of the file argument when stdin is
   connected to the parent process. Fix: `stdin=subprocess.DEVNULL`.
2. **Alternate buffer**: GAP opens an interactive terminal buffer, causing
   subprocess to hang. Fix: `env["TERM"] = "dumb"`.
3. **StructuralDescription**: Not available in base GAP 4.15.1. Use
   `StructureDescription` instead.
4. **NilpotencyClassOfGroup**: Fails on non-nilpotent groups. Guard with
   `IsNilpotentGroup(G)`.
5. **Elements(G)**: Slow on pc groups. Use `AsList(G)` instead.
6. **JSON()**: Unreliable for records. Construct JSON manually with Print.
7. **Newlines in JSON**: GAP inserts newlines inside JSON objects (e.g. after
   `"index":`). Line-based parsing fails. Use `}{` splitting after stripping
   all whitespace.

### Coset candidates API change

The original plan passed Cayley tables to GAP for subgroup enumeration.
GAP cannot reconstruct groups from Cayley tables without the
`GroupFromCayleyTable` function (requires a package). The bridge now takes
`(order, index)` instead — GAP looks up the group directly from
`AllSmallGroups(order)[index]`, which avoids the package dependency entirely.

## Smoke test results

### Phase 1 (orders 60-66, 200 trials, ~20s)

46 codes with k>=4, d>=4. Top results:

| Code | Efficiency | Group | Support |
|------|-----------|-------|---------|
| [[120,8,12]] | 9.600 | C3×(C5:C4) | weight-5 random |
| [[120,16,8]] | 8.533 | C3×(C5:C4) | weight-5 random |
| [[120,16,8]] | 8.533 | C60 | weight-5 random |
| [[120,6,12]] | 7.200 | C5×(C3:C4) | weight-4 random |
| [[120,6,12]] | 7.200 | C15:C4 | weight-4 random |

Note: C3×(C5:C4) = order-120 metacyclic group the kit's existing
`sample_metacyclic` would miss (it parametrizes Z_n ×| Z_k, not direct
products of metacyclic). The GAP bridge found it automatically.

### Phase 2 (orders 12-20, 200 trials, ~30s)

Coset codes found on small groups, validating the subgroup lattice pipeline.
Best: [[32,12,4]] from (C4×C2):C2 and [[32,4,6]] from several groups.

## Launch plan

### Phase 1 command

```bash
uv run python research/kit/campaign_gap_2bga.py \
  --orders 60-120 --weights 4,5,6 \
  --random-per-group 20 --conj-per-group 10 \
  --trials 400 --min-k 4 --min-d 4
```

Estimated: ~50k candidates × 400 trials = 20M surrogate evaluations.
With gf2_fast: ~2h. Without: ~8-12h.

### Phase 2 command

```bash
uv run python research/kit/campaign_gap_coset.py \
  --orders 60-200 --weights 3,4,5 \
  --min-nrm-q 6 --random-per-pair 20 \
  --trials 400 --min-k 4 --min-d 4
```

Estimated: ~100k candidates × 400 trials = 40M surrogate evaluations.
With gf2_fast: ~4h. Without: ~16-24h.

### Post-screening: confirmation ladder (MANDATORY per fieldnote discipline)

For any candidate that looks board-worthy after screening:

1. Re-screen at 2k trials — if d dropped, discard.
2. Confirm at 8k, 60k, 1M trials — keep only if d is flat.
3. Package with `make_submission`, validate with `validate_candidate`.
4. Stage for human review — never commit to `codes/`.

### Validation command

```bash
uv run python research/kit/campaign_gap_2bga.py \
  --orders 60-120 --validate-top 10
```

## What to watch for

**Phase 1:**
- The conjugacy-class-invariant supports may produce different distance profiles
  than random supports. If they're consistently better, it validates the
  "structure beats volume" thesis from fieldnote 2026-07-14.
- Groups with large center (|Z(G)| ≥ order/4) deserve extra attention — they
  have more idempotent-rich algebra structure.

**Phase 2:**
- The |N_G(H)/H| ≥ 6 threshold is from the fieldnote record (coset records
  live at |N/H| = 30-84). Lower it to 4 if the ≥6 sweep is too sparse.
- Skip simple/almost-simple groups per fieldnote 2026-07-14 — they plateau at
  d=2 with small H. The bridge's `_is_simple_or_almost_simple` heuristic
  (trivial center + high derived length) handles this automatically.
- Odd-k is possible here: the coset construction with non-normal H can break
  the abelian parity constraint. Track odd-k finds separately.

## Compute budget

- Phase 1 screening: ~2h (with gf2_fast)
- Phase 2 screening: ~4h (with gf2_fast)
- Confirmation ladder (10-20 finalists): ~2h
- **Total: ~8h — fits in a single overnight run**
