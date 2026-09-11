# Initial CPU benchmark findings

The leading general-purpose candidates are the repository's packed C++ RIS and
`dist-m4ri`. QDistEvol and the existing circulant search each contribute useful
results on particular families. The evidence supports comparing combinations
under a fixed total budget before changing the production default.

This branch contains a 33-case corpus spanning 72–1,000 physical qubits,
204 reported method/case/seed runs, validated witness supports, pinned sources,
and a runnable benchmark. This is a pilot with one seed per configuration;
the full repeated-seed study has not been run.

## What was measured

The [main pilot](results/pilot32/REPORT.md) compares six methods on 32 inputs
with four workers and ten seconds per code, split equally between X and Z.
The [additional regression](results/regression4/REPORT.md) uses the same budget
on a public failed 690-qubit candidate. The
[one-worker diagnostic](results/one-worker/REPORT.md) repeats three methods on
two inputs to check resource control and throughput scaling.

| Implementation | Existing board targets recovered | All main-pilot targets recovered |
|---|---:|---:|
| Repository C++ RIS, eight-row pair search | 11/14 | 18/26 |
| Repository C++ RIS, pairs disabled | 11/14 | 18/26 |
| `dist-m4ri`, C with pthreads | 10/14 | 19/26 |
| QDistEvol, Python/Numba | 9/14 | 15/26 |
| Repository Python/NumPy RIS | 5/14 | 7/26 |

These are counts of inputs reached in this seed, not estimates of per-code
reliability. The all-target column includes paper and analytic targets; the
six fresh inputs initially have no target. Circulant search applies to only
four main-pilot inputs, so it has a separate denominator in the detailed report.

## Findings that affect the choice

* **Keep C++ RIS as the production baseline while evaluating `dist-m4ri`.**
  Both perform well across families. On the 975-qubit mitten example, C++
  reached weight 26 while `dist-m4ri` reached the paper target of 24. On the
  board's 700-qubit, six-logical-qubit example, C++ reached 32 while `dist-m4ri`
  delivered 34 within budget under the pilot's per-side stopping rules.
  Neither result establishes universal superiority.
* **Retain QDistEvol as a complementary candidate.** On the 432-qubit Tanner
  input it found a valid weight-32 logical; C++ reached 34 and `dist-m4ri` 33.
  On the 756-qubit bicycle input it reached 34 while both native general
  searches returned 36. Its current implementation was weaker on several
  large, high-rate examples. This compares available implementations: the
  public QDistEvol code uses NumPy/Numba byte arrays, whereas the native
  baselines pack GF(2) operations into machine words.
* **Include the existing circulant pass in the study.** It tightened the
  current bound in `codes/682-172-79.json` from **76 to 72**. On the added
  regression it found **48**, refuting the historical claim of 77, even
  though it did not recover the known weight-28 reference. The general
  methods missed both refutations in this seed. The restricted search can
  also be ineffective: its best on the 700-qubit, six-logical-qubit example
  was 200. High trial throughput alone is insufficient.
* **Keep pair search enabled for now.** Aggregate recovery tied the no-pairs
  control, but on the Tanner example it improved the observed bound from
  36 to 34 with little throughput difference.
* **Use NumPy as a portability/control baseline.** On the 975-qubit mitten
  input, measured rates were about 3,760 trials/s for C++, 5,510 for
  `dist-m4ri`, 149 for QDistEvol, and 60 for NumPy. Trials differ between
  methods; the decision metric remains useful logicals found per wall time.

Taking the union of separately budgeted runs is not a fair portfolio speedup.
A C++/M4RI/QDistEvol/circulant combination must share the same total time budget
as each competing configuration before its advantage can be quantified.

## Thread control

On the 432-qubit Tanner input, the one- versus four-worker diagnostics gave:

| Method | One worker, trials/s | Four workers, trials/s | Throughput ratio |
|---|---:|---:|---:|
| C++ RIS | 7,216 | 26,264 | 3.64× |
| `dist-m4ri` | 5,736 | 21,220 | 3.70× |
| QDistEvol | 714 | 2,774 | 3.89× |

Measured CPU/wall-time ratios were approximately one and four respectively.
QDistEvol uses independent processes/populations; this is not parallel fitness
evaluation inside a single evolving population. These short diagnostics show
that worker limits work, but do not establish how target-finding probability
scales with threads. The Apple M4 Pro host has heterogeneous cores and no
affinity control in this harness; see [build and hardware settings](results/hardware.json).

## Evidence, limitations, and next experiment

Each detailed report includes portable `results.jsonl`, the measured matrices,
and an archive of the exact instrumented sources. Every returned witness was
checked for zero syndrome and non-membership in the stabilizer rowspace using
the repository's GF(2) routines. These are upper-bound witnesses, not exact
distance certificates or new validated leaderboard submissions.

The main pilot's staging metadata was rechecked after fixing the kit's schema
path and supplying a nonempty benchmark author. This audit changed no matrices,
witnesses, or measured timings. Larger fixtures intentionally exceed the
current 700-qubit eligibility cap. The trusted verifier and its hash pin are
unchanged. The final adapter also uses the production circulant detector's
X-matrix decision for both sides; both detectors agreed on every pilot input.

`dist-m4ri` exports witnesses at process exit. Late exports are retained and
marked explicitly, with no credit before their observed arrival. This makes
the pilot conservative for that implementation, especially on full-budget
misses. Before definitive deadline comparisons, provide time for export within
the budget or instrument delivery of intermediate witnesses. Preparation,
imports/JIT, and validation are outside the reported warm search budget; this
is not an end-to-end gate speedup. Structural preparation was not separately
timed in the first pilot and is now recorded. Peak memory is not yet measured.

The pilot stopped each side at its own supplied witness weight. Those weights
were unequal on two board inputs (32/34 and 80/82), although overall recovery
was scored against their minimum. The final runner uses the same minimum
code-level target on both sides. It also preserves a smaller paper target
when the reference phase has only found a heavier witness; a looser validated
reference must not silently relax the published challenge. These timing-policy
changes require new measurements and are not retroactively credited to the pilot.

The [frozen reference corpus](results/reference-corpus/manifest.json) contains
validated X and Z witness targets for all 33 cases, including the fresh inputs.
It retains original source claims separately. The next comparison should use
held-out seeds 100–119, one and four workers, and 1/10/60-second budgets on the
intended CI CPU. Compare each native baseline, QDistEvol, and combinations with
equal total budgets; report per-code recovery rates and uncertainty. The
runner and report exporter support repeated seeds, with per-code Wilson
intervals in `SUCCESS_RATES.md`. A 33-case, four-method, 20-seed, 60-second run
alone permits about 44 hours of search before preparation and validation, so
the complete study needs a deliberate compute allocation.
