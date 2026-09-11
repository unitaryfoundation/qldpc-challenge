# CPU distance-search study (#1016)

The decision is which CPU search, or combination of searches, should serve the
repository's distance refutation gate. Finding a light nontrivial logical is the
success criterion. Failure to find one is never an exact-distance certificate.

See [initial results and recommendations](RESULTS.md) for the completed
33-case pilot and one-worker diagnostics. The full repeated-seed study remains
to be run; a frozen reference corpus is included under `results/reference-corpus`.

## Comparisons

* The current C++ RIS, with its normal eight-row pair search.
* The same C++ kernel with pairs disabled, separating pair-search benefit from
  implementation speed.
* The current multithreaded `dist-m4ri` random-window search.
* QDistEvol: independent evolutionary populations sharing a fixed CPU budget.
* The verifier's NumPy RIS, as a completeness and portability baseline.
* The current C++ circulant-block search, on matrices that it recognizes.

No verifier, gate, eligibility limit, or distance algorithm is changed by this
study. Benchmark adapters may expose existing native primitives and observe
intermediate results; any such difference from the public entry point is
reported with the results.

## Corpus and selection

The 33-case corpus combines the cases in issue #1016 with small controls, difficult
current submissions, published quantum Tanner and bicycle examples, and fresh
fixed-seed constructions. It includes both non-abelian families behind the four
large reference bars: ZSZ-LP and mitten. Those families both have rate 1/5, so
larger low-rate bicycle/toric and fresh hypergraph-product cases are included too.

Fresh examples are selected without running a distance search. Their random
seeds, constructors, and parameters are fixed before comparing methods. The
corpus records matrix hashes, dimensions, GF(2) ranks, check weights, provenance,
and reference-witness status. A paper's distance label is initially an
unverified target, not a validated answer. Toric examples are scaling
controls, not evidence of typical qLDPC search difficulty.

The staged 666-qubit example in the issue is excluded until its matrices are
public and the discrepancy between its claimed witness weight and support list
is resolved. This exclusion is recorded rather than replaced by a guessed code.
The public failed 690-qubit candidate in `notes/682-172-79.md` supplies a separate
regression: its historical claim was 77 and the note retains a weight-28 logical.

## Resource and timing contract

The primary comparison uses four CPU workers total, including subprocesses and
nested native pools. A one-worker comparison separates algorithm differences
from scaling. Methods run sequentially on the same host; different methods do
not compete for CPU. BLAS, OpenMP, and Numba internal pools are limited to one
thread unless explicitly allocated as the method's workers. Where supported,
CPU affinity is fixed and recorded. On heterogeneous CPUs the lack of an
equivalent core allocation must be reported.

Each code gets an equal time allocation for X and Z search. Report per-side
results as well as the minimum over both sides. Imports/JIT and process startup,
matrix/logical-basis preparation, search, and witness validation/persistence are
measured separately. The end-to-end cost includes all applicable stages; warm
search throughput is also useful but must not be labeled end-to-end latency.
An observation arriving after a deadline does not count as success by that
deadline. Batch boundaries can conservatively delay observation of a witness;
report that granularity and any overrun.

Both sides use the same code-level stopping target: the minimum of supplied
witness weights, paper targets, and analytic targets. A newly frozen witness
does not relax a smaller paper target. Reference recovery and paper-target
recovery remain distinguishable in the output.

QDistEvol's generations must remain intact within each worker. Four independent
populations are explicitly different from parallel evaluation of one population.
Keep population and mutation settings fixed across comparisons. Random seeds
are recorded, but identical seed integers do not imply identical random trials
across implementations or thread counts.

## Outcomes

1. For a held-out, validated reference witness of weight w, measure the fraction
   of runs independently returning a valid logical of weight at most w. This is
   equivalent to refuting a hypothetical claim greater than w; it does not
   require knowing the exact distance.
2. Separately measure actual refutations of the submission's current claim.
3. Record best weight, time to target, completed trials, wall and CPU time,
   preparation cost, and deadline overshoot. Derive trials/second from those
   records. Per-run peak memory measurement remains follow-up work.
4. Report each code/family/size band; do not hide failures behind one aggregate
   speedup. Give binomial uncertainty for repeated-seed success rates and retain
   timed-out runs as censored observations.

Reference witnesses are used only for scoring and validation, never as initial
search candidates. Comparisons use a frozen reference set. New lighter
witnesses are retained and reported separately rather than silently changing
the target during the experiment. Where no reference witness has yet been
validated, report bounds and throughput without claiming a success rate against
ground truth.

The full study uses 20 seeds and 1/10/60-second checkpoints, with longer runs on
unresolved cases. A shorter pilot first validates adapters, persistence,
deadline behavior, and estimated cost. Pilot results cannot establish a
population-wide missed-refutation rate or justify raising the code-size cap.

## Evidence and reproducibility

Pin source revisions and dependencies. Preserve raw run records and every
returned improving witness before scoring. Validate witnesses using the
repository's existing GF(2) routines; package retained candidates through
`research/kit/submit.py`. A failed witness save is a hard error. Raw benchmark
evidence is stored separately from candidate staging so it can accompany a
reviewable report. There are no automatic leaderboard submissions.

Inputs above the current 700-qubit cap are deliberately ineligible benchmark
fixtures. Their retained candidate documents are allowed only that specific
schema violation; malformed metadata and all invalid logicals are hard errors.
Witness validation in this harness is not a pass through the full candidate gate.

Sources:

* https://github.com/unitaryfoundation/qldpc-challenge/issues/1016
* https://arxiv.org/abs/2603.22532 (RIS/QDistEvol benchmarks)
* https://github.com/QEC-pages/dist-m4ri
* https://github.com/m-webster/codeDistancePYPI
* https://arxiv.org/abs/2607.27644 (ZSZ-LP)
* https://github.com/a7b/yarn (mitten matrices)

## Running the study

From the repository root, prepare an isolated Python 3.12 environment:

```sh
uv venv --python 3.12 .venv-benchmark
uv pip install --python .venv-benchmark/bin/python -r benchmarks/distance/requirements.txt
.venv-benchmark/bin/python benchmarks/distance/bootstrap.py
.venv-benchmark/bin/python benchmarks/distance/corpus.py
.venv-benchmark/bin/python -m pytest -q benchmarks/distance/test_benchmark.py
```

The bootstrap downloads pinned public sources and compiles them under the
benchmark cache. It does not install system libraries or change the production
environment. The corpus step performs structure/reference checks, without a
distance search or screening fresh inputs by distance.

Run a small target-recovery pilot, then export portable evidence:

```sh
.venv-benchmark/bin/python benchmarks/distance/run.py \
  --m4ri benchmarks/distance/cache/deps/dist-m4ri/src/dist_m4ri \
  --output benchmarks/distance/runs/pilot \
  --methods cpp cpp-no-pairs m4ri qdistevol numpy cpp-circulant \
  --threads 4 --seconds 10 --seeds 1 --seed-start 11
.venv-benchmark/bin/python benchmarks/distance/report.py \
  benchmarks/distance/runs/pilot benchmarks/distance/results/pilot
```

`--seconds` is the total per-code search budget; half goes to each side.
`--no-target-stop` instead spends the full budget looking for tighter bounds.
Use `--cases` to select manifest IDs and `--seed-start` to reserve independent
evaluation seeds. On Linux, `--cpus` fixes the affinity inherited by workers;
choose one physical core per worker and avoid SMT siblings. Four processes each
running one native thread count as four workers, not sixteen.

After a reference phase, freeze witnesses into a new corpus and reserve fresh
seeds for evaluation. Late witnesses can improve the reference set even though
they did not count as timely successes in the original run:

```sh
.venv-benchmark/bin/python benchmarks/distance/freeze_references.py \
  --corpus benchmarks/distance/cache/corpus \
  --runs benchmarks/distance/runs/pilot \
  --output benchmarks/distance/cache/evaluation-corpus
.venv-benchmark/bin/python benchmarks/distance/run.py \
  --corpus benchmarks/distance/cache/evaluation-corpus \
  --m4ri benchmarks/distance/cache/deps/dist-m4ri/src/dist_m4ri \
  --output benchmarks/distance/runs/evaluation-4-workers \
  --methods cpp m4ri qdistevol cpp-circulant \
  --threads 4 --seconds 60 --seeds 20 --seed-start 100
```

Run the same frozen corpus with `--threads 1` for the scaling comparison.
The included `results/reference-corpus` can also be supplied directly to
`--corpus`, using held-out seeds. Repeat the command at `--seconds 1` and
`--seconds 10` for the shorter budget comparisons.
The commands above start substantial local computation; choose a host and time
budget appropriate to the study. They do not schedule unattended background jobs.

The initial local pilot uses Apple M4 Pro hardware (10 performance and 4
efficiency cores, 48 GiB RAM). macOS does not expose Linux-style affinity through
this harness, so core equivalence is uncontrolled. Its M4RI library uses the
release's default `-O2`; dist-m4ri and the repository kernel use `-O3`. The
reproducible bootstrap uses `-O3` for both the library and executable. Record
these build settings with any comparison; repeat on the intended CI CPU before
making a production performance claim.
