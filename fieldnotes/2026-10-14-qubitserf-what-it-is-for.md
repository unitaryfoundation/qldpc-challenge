---
title: "Qubitserf: a fast exact-distance screen, not a certifier — and the claim that made it look like one was wrong"
date: 2026-10-14
author: "@MathysRennela"
model: "Mimo-V2.6-Flash (opencode agent harness)"
topics: [calibration, negative-result, exact-distance, trust, css-codes]
related:
  - 2026-07-01-confirmation-is-the-bottleneck.md
  - 2026-09-20-screening-traps-at-n-900.md
  - 2026-09-22-frontier-truth-gpu-audit.md
---

## Summary

[Qubitserf](https://github.com/Quantinuum/Qubitserf) (Quantinuum, MIT, C++ core
with a ctypes front end) computes **exact** code distance — not a Monte-Carlo
bound — and does it fast enough to change how a sweep is run. It is a *screen*,
not a *certifier*, and the difference is the whole note: the board's certificates
come from `verify/`, and a number produced outside it is evidence, not a
certificate.

Most of the session was spent on a wrong idea worth recording. It was assumed
that handing the repo's SAT certifier a tight bound from connected cluster would
make that solve cheaper, which justified a two-stage
`verify_with_cc` pipeline. It does not, and the pipeline earns nothing. The
measurements that killed it are below, because the argument sounds right and the
next agent will make it again.

## Building it

```
git clone https://github.com/Quantinuum/Qubitserf && cd Qubitserf
./build.sh                      # needs CMake >= 3.20, C++17; no GPU required
PYTHONPATH=python ...           # or QUBITSERF_PYTHON=/path/to/Qubitserf/python
```

A C extension never yields to `SIGALRM`, so a timeout must be a real process
kill — `fork` in the parent, `terminate()` past the budget. A
`multiprocessing.Pool` worker is daemonic and cannot fork a child, so under
`search.screen(workers=N)` that path has to fall back to `subprocess`, which
sidesteps the daemon flag and still kills.

**Do not install the GPU backends for this board.** On sparse qLDPC codes the
CPU connected-cluster engine beats GPU Brouwer–Zimmermann by orders of
magnitude, per the project's own benchmarks. CUDA/Metal is for dense codes.

## Method choice: `cc`, always

| `method=` | what it is | verdict here |
|---|---|---|
| `"cc"` | connected cluster; exploits low-weight stabilizers | **the one to use** |
| `"bz"` | Brouwer–Zimmermann; enumerates codeword classes, GPU-capable | dense codes only; **not reproducible** — stalled past 90 s on `[[144,12,12]]` where its docs claim 3.87 s |
| `"mitm"` | meet-in-the-middle | independent cross-check, **small n only** |

On `mitm`: it is a genuinely independent algorithm, so it is the better
cross-check of the three — but it is `2^(n/2)` and **segfaults around n=120**.
Usable to roughly n≤100, which is a thin slice of this board. Measured on
`n=80`: 113x slower than `cc`.

Note the project is 21 commits, no tagged release, single author, and its
committed benchmark tables predate a cap removal its own CHANGELOG describes.
Treat its published timings as aspirational until measured locally.

## What it does well (measured, 2026-10-14, 8-core CPU box)

```
gross [[144,12,12]]   cc -> 12 in 1.3s     (which=x 0.69s, which=z 0.72s)
steane 3 / shor 3 / toric(10) 10 / surface(6) 6  -- all correct
median across 279 board codes: 0.08s        max 199.7s
```

**Cross-validation is the strong part.** Against the board's own certifiers
(scipy/HiGHS MILP in two configurations, CryptoMiniSat in two), on entries that
already carried committed certificates:

```
d=2..10   20/20 agree at every single band
d=11      14/14      d=12  12/12      d=13  4/4      d=14  1/1
total     211/211, zero disagreements, zero anomalies in 416 entries
```

`k` recomputed with `verify/gf2.py` matched the claimed `k` on every entry.

**Reach:** n=7 to n=937, and `d≤12` in practice. `d=13` got 1 of 33 candidates,
`d=14` got 3 of 69, and every `d≥16` code timed out at 280 s — including `k=2`
ones such as `[[112,2,16]]`, `[[134,2,18]]` and `[[164,2,20]]`.

## What it does NOT do

**1. It cannot certify.** `verify/check_certs.py` defines `solver` level as
"a solver said UNSAT or optimal. No artifact a third party can act on" — which
is what a Qubitserf verdict *is*, and the same level the board's existing
certificates carry. But `certs/` is board data and `verify/` is the trust
anchor; a maintainer decides what lands. An exact number from an external
engine is corroboration, never a certificate.

**2. A tight bound does not make the repo's SAT cheaper.** This was the claim
that justified a two-stage pipeline, and it is false:

```
entry            k   sat @ distance_rand bound   sat @ cc's bound
[[7,1,3]]        1              1.1s                     1.2s
[[126,6,9]]      6             39.0s                    36.8s
[[250,40,8]]    40             89.4s                    90.2s
[[330,68,7]]    68            237.5s                   239.0s
```

Within 2% every time. SAT's cost is intrinsic to the entry — a solve per
logical generator per side — and asking "is anything lighter than 8?" is the
same hard problem whoever supplies the 8.

**3. `distance_rand` did not inflate.** 4/4 entries returned the true distance
at `trials=4000`, so there was never a loose bound for stage 1 to tighten. The
surrogate's inflation failure mode is real but it does not fire at this budget
on this board.

So a `verify_with_cc` two-stage wrapper was built, tested, and is **not worth
submitting**: the identical certificate arrives in the identical time from
`sat_exact_distance` alone. The wrapper survives in `research/kit/distance.py`
for whoever wants to disagree with the measurement.

## Cost drivers — budget before spending

Driven by **`d` and `k`**, not by `n` or check weight. This is the mistake that
cost the most time here:

```
w=28 at d<=14                     instant (<0.05s)
w=16 at d<=14                     ~0.6s
n=92, k=4, w=8, d=13              ~92s
n=92, k=4, w=8, d=16              never (timed out at 280s)
k=2 at d=16/18/20                 never (timed out at 280s)
```

The distribution is bimodal, not smooth: most codes are milliseconds and a
tail needs minutes. The knee, over 279 solved entries:

```
  0->1s     +160 certs for   37s of compute  (0.2 s/cert)
  3->10s     +34 certs for  200s            (5.9 s/cert)
 10->30s     +19 certs for  311s           (16.4 s/cert)   <- KNEE
 30->60s     +13 certs for  577s           (44.4 s/cert)
150->200s    +10 certs for 1732s          (173.2 s/cert)
```

**A 30 s cap captures 84% of the output for 11% of the compute.** Run the sweep
cheap; escalate only for entries that already matter.

## How to use it

As a `search.screen` backend, which is what the hook in
`research/kit/search.py` is for:

```python
from distance import qubitserf_screen
from search import screen

screen(candidates, distance=qubitserf_screen, distance_kwargs={"tlim": 30})
```

`qubitserf_screen` is signature-compatible with `surrogate.distance_rand` and
returns `float("inf")` when a code does not finish, which drops the candidate —
the same thing the surrogate does when it finds no logical. That makes it a
drop-in replacement for *ranking* a generated family, where it replaces an
upper bound with an exact value and therefore cannot rank a code above a
lighter logical it failed to find.

Use it to decide **which of a large generated family is worth building and
submitting**. Do not use it to certify, and never let a returned integer
populate `confidence: "exact"`.

## What it does not replace

`verify/refute_board.py` already sweeps the board weekly with a fresh random
seed looking for over-claims, so an independent second opinion on existing
entries is corroboration rather than new coverage. `escalation.exact_first`
already encodes "try a cheap exact check before spending a deep ladder" —
bounded to `n<=90, d<=8` because it calls `verify/certify.py` directly. Raising
those caps is a maintainer's decision about a policy module, not an agent's.
