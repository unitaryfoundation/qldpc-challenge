---

title: Spectral BB screening: four campaigns from arXiv:2608.27565

date: 2026-08-31

author: "@mathysrennela"

model: GLM 5.3 Flash (Zed agent)

topics: [bivariate-bicycle, spectral-screening, calibration, campaign-plan]

---

# Spectral BB screening: four campaigns from arXiv:2608.27565

- **Status:** plan + same-day kickstart results (all four campaigns started;
  instrument validated, first data recorded).
- **Source:** arXiv:2608.27565 (Sabo, Can, Marquis, "Spectral Theory of
  Semisimple Bivariate Bicycle Codes").

## What the paper gives the loop

The paper decomposes the BB ring `R = F2[x,y]/(x^l-1, y^m-1)` (semisimple
case: `l`, `m` both odd) into finite-field components indexed by 2-Frobenius
orbits of the root grid `Z_l x Z_m`. Three results are directly actionable:

1. **Exact dimension** (Thm 81): `k = 2|T|` where `T = Z_a ∩ Z_b` is the
   common-zero region of the check polynomials on the root grid. Matrix-free,
   exact — strictly stronger than the kit's `mixed_volume` k *upper bound*.
2. **Colon-ideal distance floor** (Thm 88/91, conservative strip form of
   Remark 92): `d >= min{E_a, E_b, N_a,b}` where each term is a minimum
   distance of a *classical* 2D cyclic code defined by a zero-region
   (`ann<a> = C(U_ba ∪ F)`, `<b:a> = C(U_ba)`, `<a:b> = C(U_ab)`), each
   lower-bounded by 2D BCH strips (Thm 58): a run of `δ-1` consecutive full
   zero columns/rows proves `d >= δ` (one-sided) or `δx·δy` (two-sided).
   Proven, deterministic, no search. The uncoupled regions `U_ab`, `U_ba`
   carry the mixed-block logicals that per-block bounds miss.
3. **Cover dimension law** (Thm 126): for any odd cover `(l,m) -> (s·l, s·m)`
   with the same polynomial supports, `k_h = k + 2|ΔZ|` where `ΔZ` counts new
   common roots — the whole lift ladder's `k` sequence is predictable before
   building anything.

**Honest boundary:** all of this is the *semisimple* (odd-grid) case. The
6x6 gross code and most Bravyi-et-al records live on even grids
(repeated-root ring) and are out of scope; matrix rank still works there.
And every number here is a *pruning* instrument: the lower bound proves a
candidate is dead, never that it is good; the board still certifies via
witnesses (`d <=`) and the gate.

## The four campaigns (sequenced)

**A — Exact-k funnel upgrade.** Add two pre-stages to the BB screen: exact
spectral `k`, then the colon-ideal floor; run the expensive witness search
only on survivors. Deliverable: funnel counts + a calibration set of
`(d_lower proven, d_upper witnessed)` pairs on survivors, which measures how
tight the floor is on weight-3 trinomials. Instrument: `research/kit/spectral.py`.

**C — Lift ladder with predicted k.** Take strong odd-grid bases, enumerate
odd covers `s ∈ {3,5,7}`, predict `k_h` exactly, witness-search only the
lifts whose predicted `(n, k)` lands near a Pareto frontier. Converts lift
exploration into a shortlist problem.

**B — Region-designed census.** Before building the paper's suggested
"sweep by grouping orbits" sampler, run a census: which region signatures
`(|T|, |U_ab|, |U_ba|, |F|)` are reachable by weight-3 checks, and how does
`|U|` spread correlate with the proven floor? Feeds the real sampler.

**D — Dense-to-sparse via units.** Thm 140: unit multiples `(u·a, w·b)`
preserve `k` and all colon-ideal floors. In the semisimple ring, `u` is a
unit iff its zero set is empty — checkable with the same spectral machinery.
First experiment: can random unit multiples reduce check weight while
keeping the floor? If yes, prescribed-BCH constructions (proven floors,
dense checks) become a route to weight-bounded codes with `d=` potential.

## Kickstart results (2026-08-31)

**Instrument.** `research/kit/spectral.py` implements exact spectral k,
the strip-form colon floor, and cover prediction for odd grids (GF(2^e)
root-grid evaluation, e <= 20, primitive polynomials verified at use).
Validation: exact k matched matrix rank on 60/60 random odd-grid codes and
on the board's [[90,8,10]]; the floor never exceeded the witnessed upper
bound (20/20); the cover law matched built covers at s = 3, 5.

**Campaign A** (exact-k screen, 4000 random
weight-3 candidates, 7 odd grids; per-candidate logs and the staged
submission live in local gitignored staging output and are not evidence --
the numbers below are the record):

- Spectral exact-k costs 0.11-0.16 ms/candidate vs 7.6-14 ms for
  build+rank: **50-120x cheaper**, and it is exact where `mixed_volume`
  is only an upper bound.
- Funnel: 191/4000 pass exact k >= 8; 38 reach witnessed d >= 6; three
  standouts passed the validation gate. Deep re-verification (the CLI's
  2M-trial pass) tightened every one: the survivors collapsed to
  [[450,8,26]] (twice -- two distinct codes, same claim) and [[450,8,24]]
  (dominated by the board's [[330,8,24]]). Exactly one board-advancing
  submission: [[450,8,26]] on Z_15 x Z_15, kd^2/n = 12.0, witness-backed
  upper bound. Lesson: screening bounds inflated 26-36% across the board;
  the exact-k screen is the keeper, the deep pass is non-negotiable.
- Calibration (40 stage-1 codes, floor vs witnessed upper): floor median
  2, upper median 15, gap median 13, max 34; floor within 2 of upper in
  only 2/40. **The conservative strip floor is too weak to prune random
  weight-3 codes** -- it is a kill-criterion only for candidates whose
  target distance is tiny, not a ranking signal. The exact-k stage is the
  valuable one.

**Campaign C** (lift covers): covers of
[[90,8,10]] are **dimension-static** (k stays 8 at s = 3, 5, 7 -- Cor 127's
equality case: the base lattice relations are already absorbed). The law
matched built covers exactly. Consequence: lifts of these bases grow n and
d at fixed k -- the Kasai-style high-n regime, not a rate play. The s = 5
cover reaches kd^2/n ~ 84 on a 200-trial upper bound at n = 2250, but
n = 2250 is far above the board's n <= 700 submission cap, so no cover of
this base is submittable (even s = 3 gives n = 810). The lift ladder is
only actionable if a base with n <= 700/s^2 exists; closed for now.

**Campaign B** (region census, 20000
samples): 80% of random weight-3 odd-grid codes have k = 0 (empty common-
zero region); k >= 8 in only 4.3%; 854 distinct region signatures; the
proven floor is 2 for 98% of samples and **uncorrelated** with uncoupled
mass (corr = -0.005). Design consequence: the region-designed sampler must
*construct* zero sets with structured strips (BCH-style), not sample
random checks and hope -- random regions almost never carry distance
certificates.

**Campaign D** (unit search): Thm 140
verified empirically (k preserved in 600/600 unit-multiple products). But
**random units never sparsify**: over 300 unit pairs per base, zero
lighter representatives (sparse [[90,8,10]]: min weight 12 vs 6; dense
(15,15) pair: min 38 vs 16). Units only inflate weight. Operational note:
units must have odd weight (even-weight polynomials vanish at (1,1)).
Sparsification of prescribed-BCH codes, if possible at all, needs units
*tailored* to cancel support -- random search is dead as an approach.

**Where this leaves the campaigns.** A's exact-k stage is a keeper and
should graduate into `research/kit/search.py` screening; the floor stage
needs the structured-region construction of B to have teeth. C is worth
one deep-confirmation run on the [[2250,8]] cover if the high-n regime is
the target. D closes its random-search branch; reopen only with a
structured-unit mechanism.

## Adjacent negative: weight-6 planar BB reproduces the surface code, not the frontier (2026-08-26)

Run alongside these campaigns: swept trinomial planar-BB families
`f = 1 + x^a y^b`, `g = 1 + y + x^c y^d` for small (a, b, c, d), screened
with `corner_detector.detect` (growing-distance = w_bdd None), built
survivors with `boundary_engine.build_planar`, measured (n, k, d) via the
kit. Only 3 growing-distance families in the sweep range, all
surface-code-like:

| family | 8x8 | 10x10 | 12x12 | 14x14 |
|---|---|---|---|---|
| (1,1,1,1) | n=128 k=2 d<=8 | n=200 k=2 d<=10 | n=288 k=2 d<=12 | n=392 k=2 d<=14 |
| (2,0,2,1) | n=120 k=2 d<=5 | n=190 k=2 d<=6 | — | — |
| (3,0,3,1) | n=120 k=3 d<=3 | n=190 k=3 d<=5 | — | — |

The best family has d = L, n = 2L^2, k = 2 → kd²/n = 1.0 exactly (surface-
code rate) at weight-6 with r ≈ 2.2 (r⁴ ≈ 24) → g ≈ 0.17, far below the
g-frontier. Local weight-<=6 checks on a 2D grid cannot beat the surface
code's geometric efficiency — the same structural ceiling that ended the
punctured-RSC campaign. The g > 1 frontier ([[101,5,5]], [[197,5,7]])
remained hand-designed and unbeaten by any search grammar tried through
this campaign; the routes that eventually beat it are the SAT and
multiband lines recorded in the 2026-09-18 consolidated campaign note.

## Consolidation record

Absorbs (not committed; content merged here): the 2026-08-26
weight6-planar-not-frontier note, in the section above.

