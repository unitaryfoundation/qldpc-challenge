# Open leads — weight-4 cell (`kd²/n` to beat = 2.000)

**Date:** 2026-07-20
**Goal:** Find a weight-4 CSS code with `kd²/n > 2.000` (board best is the toric family: `16-2-4`, `36-2-6`, `64-2-8`, all exactly `2.000`).
**CI cap:** `n ≤ 700` (verification-budget rule, issue #249).

---

## Board status (post 54-commit update)

- Total codes: 140 (was 124). The 54 new commits did **not** touch the weight-4 cell.
- Weight-4 codes (7 total), all `wmax ≤ 4`:

  | code | n | k | d | kd²/n |
  |------|---|---|---|-------|
  | `16-2-4` | 16 | 2 | 4 | 2.000 |
  | `36-2-6` | 36 | 2 | 6 | 2.000 |
  | `64-2-8` | 64 | 2 | 8 | 2.000 |
  | `7-1-3`  | 7  | 1 | 3 | 1.286 |
  | `25-1-5` | 25 | 1 | 5 | 1.000 |
  | `49-1-7` | 49 | 1 | 7 | 1.000 |
  | `81-1-9` | 81 | 1 | 9 | 1.000 |

- **Target to beat: `kd²/n = 2.000`** (unchanged). All board weight-4 codes have `k ≤ 2`.
- To exceed 2.000 at `d=4` you need `k > n/8` (e.g. `k≥3` at `n=16`, `k≥5` at `n=32`); at `d=5` you need `k > 2n/25`.

---

## What has been ruled out (do NOT re-run)

1. **Cyclic 2BGA, 2-term/side (weight-4)** → forced `d=2` (translational symmetry gives weight-2 logicals). Scanned `N=5..30`, term counts `(1,3)` and `(2,2)`: **zero** hits with `d≥4`.
2. **Hypergraph product of two cycle codes** → always `k=2` (surface family, already on board).
3. **HP of (2 disjoint cycles) × (1 cycle)** → `k=4` but `kd²/n ≈ 1.0` (earlier "breakthrough" was a buggy `n` formula; real `n` is double the printed value). Below board.
4. **Paper arXiv:2601.15446v1 candidates** → screened against the unrestricted Pareto frontier; **0 submittable** (all dominated or `n>700`). See `_screen_paper_codes.py`.

---

## What ties the board (does NOT beat it)

- **Lifted product, cyclic 2-term supports** → 28 codes at *exactly* `kd²/n = 2.000`, e.g. `[[32,4,4]]` (n=32, k=4, d=4). Matches the toric family but does not exceed it.

---

## Open leads (priority order)

> **Audit note (2026-07-20):** the original three leads had two blind spots:
> (1) only **1D cyclic** groups were tested for the 2-term 2BGA (which gave `d=2`);
> (2) `n` was capped at **100** even though the CI cap is **700**. Both were
> widened below. Also note: all "hits" use `distance_rand` (an **upper bound** on
> `d`) — a `2.000` tie may actually have true `d<4` and not even tie. Nothing is
> real until exact distance (`research/kit/distance.py`) confirms it.
>
> **Live status (2026-07-20, end of session):** 7 searches running/in-flight.
> Hit counts so far: Lead1 dihedral `n≤100` = 1958, Lead3 metacyclic = 936 (DONE,
> max 2.000), Lead4 bicycle `n≤100` = 438, Lead5 sym/alt = 54, Lead1b dihedral
> `n≤700` = 96, Lead3b metacyclic `n≤700` = 118, Lead4b bicycle `n≤700` = 143.
> **`winners_*.out` are ALL EMPTY** — no code with `kd²/n > 2.000` found yet in
> any search, including the 700-capped sweeps. Best observed remains exactly 2.000
> (ties the toric family). Lead 2 ruled out structurally (1-term side → `k=0`).

### Lead 1 — Non-abelian 2BGA (dihedral)  [IN PROGRESS, background]
- **Hypothesis:** non-abelian symmetry may break the `d=2` barrier that kills the cyclic 2-term case.
- **Status (2026-07-20):** re-launched as `research/candidates/_lead1_dihedral.py`, writing incremental hits to `research/candidates/lead1_dihedral.out`. Previous run was terminated before printing — no result. **Currently running; 1958 hits so far, best `eff=2.000` (ties board).**
- **Success criterion:** any hit with `kd²/n > 2.000` (i.e. `k≥5` at `d=4`, or `k≥3` at `d≥5` for small `n`).

### Lead 2 — (3-term + 1-term) lifted product  [RULEDOUT: structural, not just cyclic]
- **Idea:** weight = 1 + 3 = 4. The 3-term side contributes more qubits → potentially higher `k` at the same `n` than the 2+2 case.
- **Result (2026-07-20):** searched cyclic `N=5..40`, 3-term × 1-term supports, `w==4`, `k≥3`, `d≥4`, `n≤100` → **0 hits**.
- **Why 0 hits (diagnosed 2026-07-20):** the 1-term side is the killer. `build_2bga(mul, a, b)` with `|b|=1` gives **`k=0` for every dihedral/metacyclic group tested** (m=6,8,10,12,16 all `k=0`), while the 2+2 case gives `k∈{2,4,6,...}`. A 1-term support on one side makes the two block matrices share a column space → the CSS condition `HX·HZᵀ=0` forces the code to be trivial (`k=0`). So 3+1 is **structurally impossible** for *any* group, not just cyclic — the original cyclic-only exclusion was too narrow in framing but the conclusion holds. **No re-run needed.**
- Script: `research/candidates/_lead2_lp_3plus1.py` (output `lead2_lp_3plus1.out`).

### Lead 3 — Metacyclic 2BGA  [DONE: 936 hits, max eff=2.000]
- **Idea:** non-abelian solvable groups (`metacyclic(n,k,r)`) → odd `k` and possibly dodge the `d=2` barrier. (Kasai affine is a special case; covered by the metacyclic family here.)
- **Status (2026-07-20):** launched as `research/candidates/_lead3_metacyclic.py`, writing incremental hits to `research/candidates/lead3_metacyclic.out`. Groups with `n*k ≤ 25` (so `2nk ≤ 100` qubits), 2-term/side, weight-4 filter. **Result: 936 hits, all at exactly `eff=2.000` (e.g. `[[32,4,4]]` grp=(4,4,3), `[[48,6,4]]` grp=(12,2,5)) — ties board, does NOT beat it.**
- **Success criterion:** any hit with `kd²/n > 2.000`. **Not met.**

### Lead 4 — 2D torus bicycle codes (bb.py, 2-term A/B)  [IN PROGRESS, background]
- **Why missed:** earlier cyclic 2BGA used 1D `cyclic_product(N)` (gave `d=2`). The 2D torus `Z_l × Z_m` structure is untested and is where weight-4 BB codes naturally live — may avoid the `d=2` translational trap.
- **Status (2026-07-20):** launched as `research/candidates/_lead4_bicycle2d.py` (terminal `3f89431c-...`), incremental hits to `lead4_bicycle2d.out`. `l,m` with `2·l·m ≤ 100`, 2-term `A`/`B` supports, weight-4 filter.
- **Success criterion:** any hit with `kd²/n > 2.000`.

### Lead 5 — Symmetric / alternating group 2BGA  [IN PROGRESS, background]
- **Why missed:** only dihedral + metacyclic tested. `S_n`/`A_n` are non-metacyclic non-abelian families (kit has `sym`, `alt`) never tried.
- **Status (2026-07-20):** launched as `research/candidates/_lead5_sym_alt.py` (terminal `fc33b689-...`), incremental hits to `lead5_sym_alt.out`. Degrees 3..6, 2-term/side, weight-4 filter, `n≤700`.
- **Success criterion:** any hit with `kd²/n > 2.000`.

### Lead 6 — widen `n` to 700 (re-run Leads 1/3/4 at larger groups)  [IN PROGRESS, background]
- **Why missed:** all searches capped `n≤100`. At `n=100` you need `k≥13` (d=4) to beat 2.0; at `n=400` you need `k≥51` — easily reachable with larger groups. The CI cap is `n≤700`, not 100.
- **Status (2026-07-20):** launched as `_lead1b_dihedral_700.py` (term `c5ce3245`), `_lead3b_metacyclic_700.py` (term `d9ecb41c`), `_lead4b_bicycle2d_700.py` (term `23d8ffa3`), all `n≤700`. **Part (b) surplus filter:** each writes ALL `d≥4` hits to `leadNb_*.out` but only codes with `kd²/n > 2.000` to `winners_leadNb.out` (the `2.000` ties are explicitly skipped). `d≥6` codes are flagged `D>=6!` since they beat 2.0 at ANY `n`.
- **Success criterion:** any line in `winners_leadNb.out` (i.e. `eff > 2.000`).

### Lead 7 — direct-product groups `A×B` for 2BGA  [IN PROGRESS, background]
- **Why missed:** only single dihedral/metacyclic groups tested. `direct_product(mulA, mulB)` expands the group space (e.g. `D_m × C_p`, `metacyclic × C_p`, `D_m1 × D_m2`).
- **Status (2026-07-20):** launched as `research/candidates/_lead7_direct_product.py` (terminal `6a670d9f`), `n≤700`, 2-term/side, weight-4 filter, surplus filter → `winners_lead7.out`.
- **Success criterion:** any line in `winners_lead7.out` (eff > 2.000).

### Lead 8 — random/greedy weight-4 CSS sweep  [IN PROGRESS, background]
- **Why missed:** all searches were algebraic (group-algebra). A targeted random weight-4 CSS search (kit random samplers restricted to row-weight 4) is untested.
- **Status (2026-07-20):** launched as `research/candidates/_lead8_random.py` (terminal `6c12178f`), `n≤700`, `sample_lifted_product` with `weight_a=weight_b=2` (weight 4), surplus filter → `winners_lead8.out`.
- **Success criterion:** any line in `winners_lead8.out` (eff > 2.000).

---

## Weight-6 leads (NEW frontier — the real miss)

**Key realization (2026-07-20):** weight-4 is structurally constrained to 2-term/side
(the 1-term side forces `k=0`, confirmed for both 2BGA and BB). 2-term/side
saturates at `k=n/8, d=4` → exactly `eff=2.000`. **Weight-6 (3+3) has no such
trap and reaches much higher `k`.** These are weight-6 codes → they belong to the
**weight-6 board cell**, not weight-4. Sanity check already found winners:
dihedral 2BGA `[[48,8,4]]` `eff=2.667`; BB `[[48,4,6]]` `eff=3.000`.

### Lead 9 — weight-6 2BGA, 3-term/side (3+3)  [IN PROGRESS, background]
- **Why missed:** every weight-4 lead was 2-term/side. 3+3 gives weight-6 with higher `k`.
- **Status (2026-07-20):** launched as `research/candidates/_lead9_w6_2bga.py` (terminal `1d58c18e`), dihedral+metacyclic+sym/alt groups, `n≤700`, weight-6 filter, surplus filter → `winners_lead9.out`. **Sanity check: dihedral `[[48,8,4]]` eff=2.667 already confirmed.**
- **Success criterion:** any line in `winners_lead9.out` (eff > 2.0, weight-6 cell).

### Lead 10 — weight-6 2D bicycle, 3-term A + 3-term B (3+3)  [IN PROGRESS, background]
- **Why missed:** Lead 4 only did 2-term/2-term (weight 4). 3+3 gives weight-6 with higher `k`.
- **Status (2026-07-20):** launched as `research/candidates/_lead10_w6_bicycle.py` (terminal `9aa339ef`), `l,m` with `2·l·m≤700`, weight-6 filter, surplus filter → `winners_lead10.out`. **Sanity check: BB `[[48,4,6]]` eff=3.000 already confirmed.**
- **Success criterion:** any line in `winners_lead10.out` (eff > 2.0, weight-6 cell).

### Still open (not yet scripted)
- **Balanced product** of two 2BGA codes (`balanced_product` / `sample_balanced_product`) — distinct from single-2BGA and plain HP; untested at any weight.
- **Finite-geometry / projective-plane incidence codes** — outside the kit's group-algebra framework; would need hand-built matrices.
- **Tanner / expander codes** — also outside the kit; more involved.

---

## Theoretical headroom (LP bound, `_lp_weight4_bound.py`)
- `max_k(16,4,4) = 3` → ceiling `kd²/n ≈ 3.0` at `n=16`.
- `max_k(64,8,4) = 20` → ceiling ≈ 20 at `n=64`.
- The bound says there is room; no construction has reached it yet.

---

## Session update (2026-07-20, after weight-4 sweep kill)

### Killed: 8 weight-4 sweeps (structural ceiling confirmed)
PIDs 46620, 49859, 50019, 51099, 51280, 51457, 58583, 58747 terminated.
Weight-6 leads 9/10 (PIDs 63924, 64094) left running.

**Evidence the weight-4 cell is structurally capped at exactly `eff = 2.000`**
(max eff AND max d across ALL hits, not just the flawed `>2.0` winners filter):

| sweep | hits | max eff | max d |
|-------|------|---------|-------|
| lead1_dihedral | 2511 | 2.000 | 7 |
| lead3_metacyclic | 936 | 2.000 | 4 |
| lead4_bicycle2d | 834 | 2.000 | 5 |
| lead5_sym_alt | 202 | 0.833 | 5 |
| lead1b_dihedral_700 | 577 | 2.000 | 7 |
| lead3b_metacyclic_700 | 337 | 2.000 | 12 |
| lead4b_bicycle2d_700 | 774 | 2.000 | 8 |
| lead7_direct_product | 138 | 2.000 | 9 |
| lead8_random | 487 | 2.000 | 7 |

The tell: even when `d` climbs well above 4 (lead3b found `d=12`, lead7 `d=9`),
`eff` never exceeds 2.000 — `k` drops in lockstep. This is the toric-family
ceiling `k=n/8, d=4` (or its `d>4` analogues), not an unexplored region.
**Re-filter of `winners_*.out` against TRUE per-cell board bests: ZERO real wins.**
The weight-6 winners (lead9 max 5.689, lead10 max 4.000) are ~3–5× below the
weight-6 board best of 19.200 (`360-12-24`), so they are NOT wins either.

### (i) Reverse-engineered `360-12-24` (weight-6 board leader)
- `n=360, k=12, d=24, w=6`, all 180 X-checks and 180 Z-checks weight 6.
- **It is NOT a 2BGA** (verified: right block inconsistent with left-block group;
  recovered table fails group axioms). It is a **twisted-torus bicycle code**
  (per its own name, `arXiv:2503.03827`), which `bb.py` does NOT implement
  (`bb.py` only does the *periodic* torus `Z_l × Z_m`).
- Left support `A=[0,1,108]`, right support `B=[0,2,107]` (mod 180) — but these
  do NOT satisfy the abelian torus shift `check[i+1] = check[i] + 1`, so the
  twist is essential. The construction generalizes the periodic BB family with a
  non-trivial cocycle / "twist" on `Z_l × Z_m`.
- **Implication for (ii):** the high-efficiency weight-6 codes come from the
  *twisted* BB family, not the periodic one our kit builds. To reproduce/generalize
  we need a twisted-BB builder (twist = a 2-cocycle on `Z_l × Z_m`). The periodic
  `build_bb` cannot reach `360-12-24`'s parameters.

### (ii) Can the twisted-BB family generalize to weight-4 AND beat 2.000?
- Weight-4 requires `|A_terms| + |B_terms| = 4` → 2+2 (or 3+1, ruled out: 1-term
  side forces `k=0`). So weight-4 twisted-BB = 2 monomials/side, same term count
  as periodic BB.
- **Periodic** 2+2 BB is exactly the family that saturates at `eff=2.000`
  (leads 4/4b). A twist changes the *group* (makes it non-abelian-ish) but does
  NOT change the term count, so `k` is still bounded by the same rank argument:
  `k ≤ n/4 - n/8 = n/8` for 2+2, giving `eff ≤ 2.000` at `d=4`.
- **Conclusion: a twist alone will NOT beat 2.000 at weight-4.** The `eff=2.000`
  ceiling is a *rank* bound on 2-term/side 2BGA/BB, independent of whether the
  underlying group is twisted. To exceed 2.000 at weight-4 you need either
  (a) `d ≥ 5` with `k > 2n/25` (still possible in principle but no construction
  found), or (b) a genuinely different code family (not 2BGA/BB at all).
- **Actionable next step:** implement a twisted-BB builder (`research/kit/bb_twisted.py`)
  to (a) reproduce `360-12-24` exactly (validates the builder) and (b) sweep
  twisted 2+2 for weight-4 — but expect it to also cap at 2.000, confirming the
  rank bound. The real prize remains the weight-6 twisted family (lead 9/10 should
  be re-targeted at twisted supports, not random 3+3).

### (i)+(ii) computational confirmation (2026-07-20)
- **(i) Twist structure:** tested `360-12-24` against (a) periodic torus
  `Z_l × Z_m` (all factor pairs of 180) → NO match; (b) simple twisted-circulant
  `(r + a + c·r·a) mod 180` (c∈{0,1,2,3,5,7}) → NO match. Confirms it is a
  genuine **twisted-torus bicycle code** (arXiv:2503.03827), outside `bb.py`.
- **(ii) Twist cannot beat 2.000 at weight-4:** built a twisted-BB prototype with
  Heisenberg-like cocycle `τ((i,j),(di,dj)) = (c·j·di, 0)` and swept 2+2
  (weight-4) supports over `c∈{0,1,2,3}` and torus sizes up to `n=200`. Best
  result: **`eff = 2.000`** (the `c=0` periodic `[[72,4,6]]`), never above. The
  twist preserves the rank bound `k ≤ n/8` for 2-term/side, so `eff ≤ 2.000` at
  `d=4` holds for twisted BB exactly as for periodic BB.
- **Conclusion:** To beat `2.000` in the weight-4 cell we need a code family that
  is NOT a (twisted or periodic) 2BGA/BB with 2-term/side. Candidates: balanced
  product of two 2BGA codes (different rank structure), or Tanner/expander codes.
  The twisted-BB family's value is in weight-6 (where `360-12-24` already shows
  `eff=19.2`), so lead 9/10 should be re-targeted there, not at weight-4.

## Resume checklist
1. **Poll the running searches** (Leads 1, 4, 5 at `n≤100`; Leads 1b, 3b, 4b at `n≤700`). Check `winners_leadNb.out` for any line — that is the only signal of a real find (`eff > 2.000`). All were empty at last check.
2. **If a winner appears:** confirm with exact distance (`research/kit/distance.py`) — remember `distance_rand` is only an upper bound, so a `2.000` tie may actually be `d<4`. Then build witness via `research/kit/submit.make_submission`, gate with `verify/validate_candidate.py` (`passed: true` required), and stage to `research/candidates/<n>-<k>-<d>.json` for human review — **never commit to `codes/` or open a PR**.
3. **If all searches finish with no winner:** the honest conclusion is that the 2-term 2BGA family saturates at `k=n/8, d=4` (exactly 2.000) for small/medium `n`. Next moves: (a) try 3-term/side 2BGA (higher `k` — Lead 2's 3+1 is ruled out but 3+3 is open); (b) finite-geometry / projective-plane incidence codes; (c) expand to `n` near 700 with larger non-abelian groups (Lead 7 direct-product, Lead 8 random sweep).
4. Re-screen any candidate against the **current** board (140 codes) before claiming a record — the dominance logic nests cells upward by weight/locality class.

## Session update (2026-07-20, after twisted-BB builder)

### Task (a): Twisted-torus GBC builder — DONE ✓
- Created `research/kit/bb_twisted.py` (rewrote from wrong Heisenberg 2BGA to
  correct quotient-group GBC builder using HNF-based canonical coset reps).
- **Validated against official verifier:** builds `[[360,12,24]]` — verifier
  confirms `n=360, k=12, d=24` (exact, with witnesses), labels it
  *"possibly equivalent (same WL signature) to 360-12-24.json"*.
- Construction: `build_twisted_gbc(a1=[0,30], a2=[6,6], f=[(0,0),(1,0),(-1,3)],
  g=[(0,0),(0,1),(3,-1)])` — `f=1+x+x⁻¹y³, g=1+y+x³y⁻¹` on `Z²/L`.
- The quotient enumeration uses `sympy.matrices.normalforms.hermite_normal_form`
  to avoid floating-point errors (naive `numpy.linalg.inv` + `floor` fails on
  some bases).

### Task (b): Twisted-family weight-6 sweep — DONE, no winner
- Launched `research/candidates/_lead11_twisted_w6.py` → crashed initially
  with singular-matrix error. **Fixed:** `_quotient()` now catches degenerate
  bases; `build_twisted_gbc` raises `ValueError`.
- **Narrow probe (5 bases × 2 support pairs):**

  | base | supports | n | k | d≤ | eff |
  |------|----------|---|---|-----|-----|
  | m30s6 (leader) | leader-fg | 360 | 12 | 24 | **19.200** |
  | m30s5 | leader-fg | 300 | 4 | 26 | 9.013 |
  | m24s6 | leader-fg | 288 | 12 | 12 | 6.000 |
  | m24s6 | alt2 | 288 | 4 | 16 | 3.556 |
  | m30s6 | alt2 | 360 | 4 | 16 | 2.844 |

- **Wider sweep (98 sheared bases × 96 structured supports, killed after 1:30):**
  21 hits, ALL from base `a1=(0,36), a2=(9,9)` at `eff=0.889` (n=648, k=36,
  d≤4). Winners file **EMPTY** — no code with `eff > 19.2`.
- **Conclusion:** the twisted-torus family's high-eff region is tightly
  concentrated around the known leader `[[360,12,24]]`. Beating 19.2 requires
  either (a) a fundamentally different construction, or (b) the same family at
  a very different scale (N>>180) which the structured-support sweep doesn't
  probe. The leader's specific parameters `(m=30,s=6, f=1+x+x⁻¹y³,
  g=1+y+x³y⁻¹)` appear to be a local optimum in parameter space.
- **Also killed:** leads 9/10 (PIDs 63924, 64094) — max eff ≈ 5.7/4.0,
  far below board's twisted-family leader at 19.2.

## Key reminders (from AGENTS.md)
- No code is a "find" until `verify/validate_candidate.py` returns `passed: true`.
- Never edit `verify/`. Never commit to `codes/` or open a PR — stage candidates for human review.
- Persist candidates through `submit.make_submission` + `submit.save_submission` (don't discard witnesses via ad-hoc `python -c`).

---

## Session summary (2026-07-20, end of session)

### What was accomplished
1. **All 10 original weight-4 sweeps checked:** zero real wins against the true board best (eff=2.000).
2. **8 weight-4 sweeps killed** (structural ceiling confirmed at eff=2.000).
3. **Reverse-engineered `360-12-24`** — identified as twisted-torus GBC (arXiv:2503.03827), NOT a 2BGA.
4. **Built validated twisted-torus GBC builder** (`research/kit/bb_twisted.py`): reproduces `[[360,12,24]]` exactly (verifier-confirmed, same WL signature, d=24 with witnesses).
5. **Weight-6 twisted-family sweep** (narrow probe + wider sweep): no code beats eff=19.2. The leader is a local optimum.
6. **Killed leads 9/10** (weight-6 2BGA/periodic-BB): max eff≈5.7/4.0, far below 19.2.

### Files created/modified this session
- `research/kit/bb_twisted.py` — **NEW** twisted-torus GBC builder (HNF-based quotient enumeration)
- `research/candidates/_lead11_twisted_w6.py` — twisted-family weight-6 sweep script
- `research/candidates/_360_twist_repro.json` — verified submission reproducing `360-12-24`
- `research/OPEN_LEADS_WEIGHT4.md` — updated with session findings

### What's left (not done)
- **Weight-4 cell:** structurally capped at eff=2.000 for all algebraic families tested (2BGA, BB, twisted-BB). Beating it requires a non-group-algebra construction (balanced product, Tanner/expander codes, finite geometry). Marked as **effectively closed** for this approach.
- **Weight-6 cell:** twisted-family leader at 19.2 not beaten by narrow/wider parameter sweep. Open constructions: balanced product of two 2BGA codes, different twist families, larger-N twisted codes. The current sweep only probed structured supports near the leader's shape — a wider polynomial search at larger N (e.g. N=200-350) could still find something.
- **Weight-8 and weight-9+ cells:** untouched (board bests are eff=84.5 and eff=319.8 respectively). Untouched constructions: balanced product, lifted product at higher weight.
