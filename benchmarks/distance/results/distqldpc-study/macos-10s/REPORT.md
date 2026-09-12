# DistQLDPC integration screen

Single active solver thread; upstream joint X/Z formulation. Preparation, input serialization, process startup and exit-time delivery count toward the total code budget. Independent witness validation and candidate saving happen after each run, before the next search.

Preparation retains the lightest individual logical-basis row on each side. It does not enumerate combinations, run a structural search, inject an incumbent, or pass reference witnesses to the solver. This is an integration screen, not the Linux external-refresh comparison. Numerical solver bounds are unverified claims; all reported witness weights are independently checked upper bounds.

| Code | Budget (s) | Preparation bound | Solver witness | Timely solver witness | Reported lower bound | Status |
|---|---:|---:|---:|---:|---:|---|
| board-72-12-6 | 10 | 6 | 6 | 6 | 6 | solver_optimal_claim |
| board-144-12-12 | 10 | 12 | 12 | — | 8 | timeout |
| board-700-222-28 | 10 | 96 | — | — | 2 | timeout |
| board-682-172-79 | 10 | 116 | — | — | 2 | timeout |
| regression-690-182 | 10 | 112 | — | — | 2 | timeout |
| tanner-432_8_33 | 10 | 36 | — | — | 4 | timeout |
| mitten-975-195 | 10 | 86 | — | — | 2 | timeout |
| toric-1000 | 10 | 20 | — | — | 8 | timeout |
| fresh-bb-960 | 10 | 60 | — | — | 4 | timeout |

The solver's random policy is unchanged. Repeats use identical inputs and are not independent RIS seeds. On macOS, CPU affinity is unavailable; these timings must not be ranked against Linux measurements. Failed searches, late output, raw mixed Pauli operators, and candidate documents are retained.

No result here is a full candidate-gate pass or a portable proof certificate.
