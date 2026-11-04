# Beat the Surface Code

This page documents the campaign launched by issue #4601: discover, verify, and
benchmark codes that outperform the surface code in finite-size resource
efficiency, while keeping the surface code as a reference benchmark rather than
a restriction on participating families.

## Three notions of beating the surface code

1. **Structural advantage**: better code parameters or encoding overhead.
2. **Operational advantage**: better logical memory performance under comparable noise.
3. **Architectural advantage**: lower total resource requirements for fault-tolerant computation.

A code that wins on only one of these is not automatically superior overall.

## Primary operational comparison

```
N_candidate < N_surface
subject to k_candidate = k_surface
           pL_candidate <= pL_target
```

`N` includes syndrome ancillas, not just data qubits. Spacetime volume and decoder
latency are independent competitive metrics. No weighted aggregate score is used.

## Surface-code baselines

| k target | Baseline slug(s) | Description |
|---|---|---|
| 1 | `25-1-5`, `49-1-7`, `81-1-9`, `169-1-13` | Rotated surface codes |
| 5 | `101-5-5`, `197-5-7` | Dense-packed surface codes |
| 25 | `598-25-4` | Holey rotated surface code |
| 100 | `957-105-4` | Holey rotated surface code (k=105) |
| Hyperbolic | `330-68-6`, `546-236-4` | Hyperbolic surface codes |

For k values without a single-code baseline, the baseline is k independent rotated
surface-code patches at the target distance, with total n = k * d^2.

## Initial campaigns

- `research/campaigns/beat-surface-k10-w4-2d/`
- `research/campaigns/beat-surface-k25-w6-2d/`
- `research/campaigns/beat-surface-k50-w8-unrestricted/`
- `research/campaigns/beat-surface-k100-w8-unrestricted/`

Run one with:

```
python research/cyclic_gb.py --campaign research/campaigns/beat-surface-k10-w4-2d/campaign.json
```

(or any sweep script that accepts `--campaign`).

## Tiers

- Tier A — Code discovery (current board submissions).
- Tier B — Memory benchmarking (circuit tier + LER).
- Tier C — Fault-tolerant architecture (forward-looking).

## Evidence standards

Preserve the distinction between proven mathematical results, certified exact
distances, certified lower bounds, heuristic estimates, numerical simulations,
and experimental demonstrations. A submission must never be presented as
experimentally demonstrated if it is only numerically simulated.