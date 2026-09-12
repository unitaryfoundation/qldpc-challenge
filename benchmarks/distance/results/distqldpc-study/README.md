# DistQLDPC Mac integration screen

The native solver is buildable on Apple Silicon with Clang in C++98 mode. The
adapter exports and validates its improving Pauli assignments, preserves their
nontrivial CSS components through the research kit, and enforces a single active
solver thread. The Linux build and matched performance comparison remain to run.

## Results

The corrected nine-case, 10-second screen found these solver-generated witnesses:

| Case | Solver witness | Solver-reported lower bound | Result |
|---|---:|---:|---|
| Board-72 | 6 | 6 | Reported optimum in approximately 0.09 seconds |
| Board-144 | 12 | 8 | Timed out with a validated weight-12 witness |
| Board-700, Board-682, regression-690 | None | 2 | Timed out without an incumbent |
| Tanner-432 | None | 4 | Timed out without an incumbent |
| Mitten-975 | None | 2 | Timed out without an incumbent |
| Toric-1000 | None | 8 | Timed out without an incumbent |
| Bicycle-960 | None | 4 | Timed out without an incumbent |

A targeted 60-second follow-up gave:

| Case | Solver witness | Solver-reported lower bound | Elapsed including preparation |
|---|---:|---:|---:|
| Board-144 | 12 | 12 | 19.655 seconds; reported optimum |
| Board-700 | None | 4 | 59.911 seconds |
| Regression-690 | None | 4 | 59.956 seconds |

Every corrected run delivered within its budget. For runs exceeding one second,
recorded CPU time was approximately 99.4–100% of elapsed time. The small control
has more visible startup/exit overhead. CPU accounting includes the solver's
waited-for descendants. The solver's watchdog parent is not an additional search
worker. macOS provides no equivalent affinity control to the Linux protocol;
these development-screen timings are not a cross-host performance ranking.

The solver cost and both Pauli components were retained. The GF(2) witness checks
passed. Reported lower bounds and optimality are solver claims; this work does
not supply independently replayable proof certificates or full candidate-gate
passes. The preparation fallback is reported separately from solver discoveries.

## Interpretation and Linux follow-up

The default upstream search begins by ruling out low weights. On the difficult
large examples, the 60-second runs were still excluding low-weight regions and
had not found a feasible logical. This makes this configuration a weak candidate
for replacing short-budget RIS witness search. It does not establish that other
SAT encodings, logical bases, or search schedules would behave the same way.

The 144-qubit result is a useful certification signal. Confirm it on the Linux
host alongside the repository's existing native-backed SAT/MILP certifiers, using
the same witnessed bound and total CPU budget. A longer exact-solving study should
begin with smaller overlapping cases rather than only the hard 700–1000-qubit
search corpus.

For witness-search evaluation, the existing Linux harness can call
`run_solver` in `benchmarks/distance/distqldpc_adapter.py` with its prepared bases
and remaining **total code** budget. Keep the joint X/Z allocation explicit and
retain the shared initialization outside the solver. A seeded-incumbent hybrid,
per-sector formulation, or changed starting weight is a separate experiment.
No such algorithm change was made in this screen. The completed results do not
justify a larger hybrid benchmark on this Mac before a Linux confirmation.

## Artifacts and checks

- `macos-screen-10s/`: corrected short screen, nine configurations, three raw
  Pauli exports, twelve retained candidate documents, zero late configurations.
- `macos-screen-60s/`: targeted follow-up, three configurations, two raw Pauli
  exports, five retained candidate documents, zero late configurations.
- `macos-10s/`: initial delivery diagnostic. A 25 ms exit reservation led to eight
  late configurations by approximately 1–28 ms. They received no deadline credit.
  All evidence remains preserved; the corrected adapter reserves 100 ms.

All three artifact audits passed, covering 21 configurations, eight raw Pauli
exports and 29 candidate documents, including the delivery diagnostic. Each
directory has its exact runtime source snapshot and executable hash. Final
test/audit additions after a run do not change that run's archived sources.

The current adapter and existing benchmark tests pass: **31 tests**. Checks cover
eliminated-variable reconstruction on relabeled Steane codes, asymmetric X/Z
distances, mixed Pauli projection, invalid exports, late and killed processes,
failed saves, contradicted optimality claims and errors without witnesses.
The trusted verifier matches all 27 pinned files.

The candidate documents and full raw inputs/outputs are compressed in each
directory's `raw.tar.gz`; summaries and hash manifests are uncompressed. The
three raw archives total less than 1 MB. Build and reproduction instructions
are in `benchmarks/distance/distqldpc/README.md`.
