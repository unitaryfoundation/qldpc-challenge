# DistQLDPC integration study

This adds an independent native MaxSAT candidate to the CPU distance study.
It targets macOS and Linux; the Linux build and execution still need validation.
The completed Mac screen establishes build,
witness-export and timeout behavior. Performance rankings against the current
RIS implementations require runs on the same Linux host and core allocation.

Upstream is [guluchen/DistQLDPC](https://github.com/guluchen/DistQLDPC), pinned to
`c01fa93eb5e1e62948e4861e2c164a6b64fe88eb` in `source.json`. The associated paper is
[SAT, MaxSAT, and SMT for QLDPC Distance Computation](https://arxiv.org/abs/2606.12445).
The upstream application is GPL-3.0-or-later and its MaxCDCL engine is MIT licensed.
The observation header retains that attribution; no upstream sources are vendored.

## Build and run

Use the existing benchmark Python environment and native preparation extension
described in `benchmarks/distance/README.md`. The additional solver requires
a C++ compiler, make, patch, git and zlib. Building needs network access only
to obtain the pinned public source. It installs no system packages.

```sh
.venv-benchmark/bin/python benchmarks/distance/bootstrap_distqldpc.py
.venv-benchmark/bin/python -m pytest -q benchmarks/distance/test_distqldpc.py
.venv-benchmark/bin/python benchmarks/distance/study_distqldpc.py \
  --output benchmarks/distance/runs/distqldpc-screen --seconds 10
```

The bootstrap extracts the exact commit into a new build directory, normalizes
the engine's CRLF line endings, and applies `upstream.patch`. It preserves the
cached checkout. To rebuild, supply a fresh `--build-directory`. The build record
contains source, patch, observer and binary hashes, compiler version and flags.
C++98 is explicit because modern Clang rejects the upstream legacy adjacent
format-string macros in its default language mode. Both platforms use `-O3`.
The four parallel **build** jobs are separate from the single **search** thread.

On Linux, after other timed jobs finish, constrain the whole process tree to one
available CPU with `--cpu 0` (or another available CPU). macOS cannot provide
equivalent CPU affinity; the report records that limitation. Numerical library
pools are restricted to one thread. The solver is sequential; its extra parent
process only watches the deadline and receives progress.

## Observation patch

The patch adds a virtual callback at the existing improving-incumbent hook.
`observer.h` copies current assignments and reconstructs variables eliminated by
SimpSolver, following its reverse elimination record. It writes a complete JSON
record containing both Pauli components and the solver cost, then calls `fsync`.
It does not change assignments, elimination, branching, restart policy, incumbent
selection, cardinality encoding, or the objective. Export cost is charged.

Two interface changes support the harness: fractional wall-clock timeouts and
`-witness-file=PATH`. Unexpected child failures, including failed witness writes,
are propagated rather than presented as ordinary search timeouts. The wrapper
also has a process-group watchdog so a stalled child cannot continue searching
after its launcher is killed. A watchdog kill makes descendant CPU accounting
incomplete, which is flagged in the result.

The full mixed Pauli operator is retained. The trusted GF(2) predicates check its
syndrome and nontriviality and identify its nontrivial pure X/Z components. Those
components are valid CSS logicals and cannot outweigh their union. Each is saved
through `research/kit/submit.py`, with a durable copy in the run artifacts. The
only submission-schema exemption is the existing n>700 benchmark-fixture cap.
Failure to save stops the run. Numeric upper bounds without exported witnesses
never count as successful witness recovery.

## Timing and scope

`--seconds` is the **total per-code** budget. The upstream solver searches the
joint X/Z problem; it receives one total budget, not a full budget per side.
Native logical-basis preparation, input serialization, process startup and
exit-time delivery are charged. Imports, matrix loading, independent validation
and candidate packaging are excluded and run serially outside search timing.

The preparation fallback is the lightest individual logical-basis row per side.
It is reported separately from solver discoveries and is not passed into the
solver as an incumbent. This differs from the Linux external-refresh protocol,
whose common initialization also enumerates combinations. The standalone Mac
screen must not be merged directly into that ranking.

The adapter's `run_solver(hx, hz, logicals, directory, seconds)` accepts prepared
bases from another harness. `logicals['X']` means Z-type logicals that detect X
errors, matching the existing verifier convention. For Linux integration:

1. Reuse the frozen matrices, native preparation, initialization and validation.
2. Charge shared preparation to the same total code budget and pass the remaining
   time to this joint solver. Explicitly distinguish its joint allocation from
   the existing equal X/Z half-budget policy.
3. Retain the common initialization as an output fallback for every method.
   Feeding a known incumbent into MaxSAT is a separate experiment.
4. Archive this adapter, compiler flags and upstream pin alongside that run.
5. Compare delivered logical weights first. Study exact-solving coverage on a
   separate smaller corpus and longer budgets if justified.

All exports are scored at conservative CLI-exit delivery time. No internal
time-to-target is inferred; late exports are preserved without deadline credit.
The wrapper reserves 100 ms for the parent polling loop and process-exit delivery.
The native random policy is unchanged, so repeated identical inputs are not
independent randomized RIS trials. The solver begins by testing low weight caps;
it can spend the whole budget raising a lower bound without finding a witness.

Reported lower bounds and optimality are **solver claims**, not independently
replayed proof certificates. A checked witness is an upper bound. This harness
does not modify the trusted verifier, certify a leaderboard entry, or change the
code-size cap. The production validation gate remains unchanged.

## Audit and portable evidence

```sh
.venv-benchmark/bin/python benchmarks/distance/audit_distqldpc.py \
  benchmarks/distance/runs/distqldpc-screen --pack
```

The audit checks file hashes, matrix identity, exact raw-export preservation,
both CSS witness conditions, and equality between saved candidate witnesses and
the solver's returned supports. `raw.tar.gz` carries the complete raw directories
and source snapshot. The same audit works from a Git checkout containing only
the summaries and archive, without extracting files into the worktree.

The completed Mac results and Linux follow-up recommendation are in
`benchmarks/distance/results/distqldpc-study/README.md`.
