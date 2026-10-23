# The certification queue

`todo.json` lists every board entry whose distance is a witnessed upper bound
and no honored certificate, what certifying it would take, and the order the
work should go in (issue #4027). `certification_queue.py` writes it from
`codes/` and `certs/`; the `certification-queue` workflow regenerates it every
Monday on `main`, so a certificate that lands removes its entry and a distance
that changes re-lists the entry at the new value. Nothing in it is a distance
claim: every `d` stays an upper bound until a certificate says otherwise.

Who is in it is decided the way the site decides the `d=` tier: an entry is
exact only when `certs/<slug>.json` says `d_exact` and agrees with the entry's
current distance and side values (`site/build.py`, `cert_consistent`); every
other entry is here.

Per entry:

| field | meaning |
|---|---|
| `n`, `k`, `d`, `w`, `cells` | the shape and the primary-track cells it competes in |
| `record` | on a cell's Pareto frontier or the global one (`compute_records`, the star on the board) |
| `sides.X`, `sides.Z` | what `verify/certify.py` decides per side: `generators` (one MILP each, k per side), `lp_vars` (n + rank + 1) and `lp_constraints` (rank + 2) of each MILP, the rank being the side's kernel matrix's. A stabilizer entry has the single side `P` and no certifier |
| `peers` | the honored solver and proof_log certificates within 25% of its n and within 2 of its d: how many, and the median of their recorded seconds (worse side) |
| `band` | A: three or more peers, median under 600 s. B: a peer under 3,600 s, or n <= 400 and d <= 16 (what the October 2026 Perlmutter run closed at 2,400 s per solve). C: n <= 700 and d <= 24, beyond any peer but inside what the tier has reached (largest certified d is 19). D: n > 700 or d > 24, which nothing certified on main resembles. P: stabilizer, no certifier yet |
| `measured_shape` | when `research/cost/cost_table.json` exists, the nearest measured shape and how its certification run ended there (exact, MILP limit, wall cap) |
| `position` | rank under the rule below |

The rule, also in the file's `rule` field: records first, then band A to D with
P last, then cheapest first (the peers' median seconds, then n), then slug. A
cheap certificate on an entry no frontier needs buys less than a dear one on a
record, so value enters before cost. `next_ten` is the head of the queue, the
successor list for #3629-style work.

The peers' seconds come from certificates produced on different machines
(Perlmutter nodes and laptops) under different time limits, so a band is an
estimate from what has closed, not a promise. Band A entries are the ones
`verify/sat_certify.py --proof` should close in minutes; C and D are where
#3629's 28,800 s per solve runs sit and mostly time out.

Filing a certificate the queue produced follows #3666: the certifier's own
record, a `certs/proof_log_batch.jsonl` row when the proof path verified, and
a PR touching only `certs/`.

```
uv run python research/certs/certification_queue.py            # writes todo.json
uv run python research/certs/certification_queue.py --check    # exit 1 if the committed queue is stale
```
