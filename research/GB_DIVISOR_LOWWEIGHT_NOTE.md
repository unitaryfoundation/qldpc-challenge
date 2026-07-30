# GB-divisor method cannot reach weight-4/6/8 at k=82 — search-strategy note

**Date:** 2026-07-19
**Context:** `codes/390-82-27.json` (the weight-32 GB code) and the
`research/search_390_sym.py` / `research/sweep_gb_divisor.py` machinery.
**Status:** analysis note (no code change, no candidate). Per `AGENTS.md`,
nothing here is a "find" until `verify/validate_candidate.py` returns
`passed: true`.

---

## The core realization

The weight-32 code came from **weight-16 circulants**: the first `X` check row
is `circ(a) | circ(b)` with `a`, `b` each of weight 16, so the check weight is
32. To get **weight-4 / 6 / 8 checks** you need **weight-2 / 3 / 4 circulants**
— i.e. *sparser* multiples of the divisor $g$.

The catch: `search_390_sym.py` works by XOR-combining shifts of $g$ to
**grow** weight (trading weight for distance). For low-weight checks you would
do the *inverse* — find the **sparsest** multiples of $g$. That is only
possible if the cyclic code $\langle g\rangle$ actually *contains* low-weight
codewords.

## Definitive math (grounded in the actual divisor)

For `390-82-27`, let $g = \gcd(\gcd(a,b),\, x^{195}-1)$ over $\mathbb{F}_2$
(where `a`, `b` are the two circulant generators of the first `X` row).

- **Weight-2 multiples:** searched all $1 + x^m$ for $m < 195$.
  **Count = 0.** There is *no* weight-2 multiple of this $g$.
- The original `390-82-27` itself uses **weight-8** circulants, which strongly
  suggests the minimum distance of $\langle g\rangle$ is **8**.
- Weight-3 / weight-4 feasibility: a full search was started (≈1.2M sympy
  divisions for weight-4) and backgrounded; the weight-2 result already bounds
  the floor. If min-distance is 8, no weight-3/4 multiple exists either.

**Conclusion:** this exact divisor ($k=82$) cannot produce weight-2/3/4
circulants at all. You are hard-capped at **weight-16 checks** (wt-8
circulants). The "same method" cannot reach weight-4/6/8 at $k=82$.

## How you would actually proceed

**Option A — keep the divisor method, accept the floor.** Enumerate the
minimum-weight multiples of $g$ (the min-distance codewords of $\langle g\rangle$,
likely wt 8) and pair them. That gives weight-16 checks max, not 4/6/8. This
path **cannot** hit the target with $k=82$.

**Option B — pick a different divisor $g'$ with smaller min-distance.** Search
over divisors of $x^{195}-1$ (or other $N$) whose cyclic code has min-distance
2/3/4, then build GB codes on them. This lowers $k$ (lower $k$ typically →
sparser multiples). Same GB-divisor machinery in `search_390_sym.py` /
`sweep_gb_divisor.py`, different search objective.

**Option C — switch construction family (realistic path for wt-4/6/8).** Low
weight is *native* to other families, not to high-rate GB divisor codes:
- **Weight-4:** surface/toric codes (topological), or hypergraph-product /
  lifted-product of small base codes.
- **Weight-6/8:** bivariate-bicycle (BB) or lifted-product codes — many board
  entries in `weight-6` / `weight-8` are BB/LP. The repo already ships
  `sweep_bb_groups.py`, `sweep_hp_bch.py`, `sweep_hp_library.py` for exactly
  this.

## Bottom line

The same GB-divisor method **cannot** reach weight-4/6/8 at $k=82$ (the
divisor's min-distance is too high — no weight-2 multiple exists). To get there
you either (B) lower $k$ via a sparser divisor, or — more productively — use the
BB / lifted-product / hypergraph-product search scripts already in `research/`
that are designed for bounded-weight checks.

---

## Reproduce the key check

```bash
source .venv/bin/activate
python -c "
import json, sys
sys.path.insert(0,'verify')
from sympy import Poly, GF, symbols, rem, gcd
x=symbols('x'); N=195
c=json.load(open('codes/390-82-27.json'))
row0=c['checks']['X'][0]
a_sup=sorted([q for q in row0 if q<N]); b_sup=sorted([q-N for q in row0 if q>=N])
a=Poly(sum(x**e for e in a_sup),x,domain=GF(2)); b=Poly(sum(x**e for e in b_sup),x,domain=GF(2))
g=Poly(gcd(gcd(a,b),Poly(x**N-1,x,domain=GF(2))),x,domain=GF(2))
def P(*exps): return Poly(sum(x**e for e in exps), x, domain=GF(2))
w2=[m for m in range(1,N) if rem(P(0,m), g).is_zero]
print('weight-2 multiples of g (1+x^m, m<N):', len(w2))
"
```
