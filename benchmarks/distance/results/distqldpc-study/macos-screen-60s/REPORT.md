# DistQLDPC integration screen

Single active solver thread; upstream joint X/Z formulation. Preparation, input serialization, process startup and exit-time delivery count toward the total code budget. Independent witness validation and candidate saving happen after each run, before the next search.

Preparation retains the lightest individual logical-basis row on each side. It does not enumerate combinations, run a structural search, inject an incumbent, or pass reference witnesses to the solver. This is an integration screen, not the Linux external-refresh comparison. Numerical solver bounds are unverified claims; all reported witness weights are independently checked upper bounds.

| Code | Budget (s) | Preparation bound | Solver witness | Timely solver witness | Reported lower bound | Status |
|---|---:|---:|---:|---:|---:|---|
| board-144-12-12 | 60.0 | 12 | 12 | 12 | 12 | solver_optimal_claim |
| board-700-222-28 | 60.0 | 96 | — | — | 4 | timeout |
| regression-690-182 | 60.0 | 112 | — | — | 4 | timeout |

The solver's random policy is unchanged. Repeats use identical inputs and are not independent RIS seeds. On macOS, CPU affinity is unavailable; these timings must not be ranked against Linux measurements. Failed searches, late output, raw mixed Pauli operators, and candidate documents are retained.

No result here is a full candidate-gate pass or a portable proof certificate.
