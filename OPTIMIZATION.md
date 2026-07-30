# CI Pipeline Optimization Guide

This document analyses the CI gate (`verify.yml`) and identifies opportunities
to reduce wall-clock time. Changes are grouped by difficulty and expected impact.

---

## Current Pipeline (PR gate, `verify.yml`)

| Step | ~Time | Notes |
|------|-------|-------|
| Checkout ×2 (`submitted` + `trusted`) | ~10 s | Both use `fetch-depth: 0` |
| `make fast` ×2 (C++ `gf2_fast` build) | ~15–30 s | `continue-on-error`; falls back to pure Python on failure |
| Changed-file detection (`git diff`) | <1 s | |
| `check_submission_scope.py` | <1 s | Trust-boundary enforcement |
| `check_validator_integrity.py` | <1 s | SHA-256 manifest check |
| `run_tests.py` (6 test files) | ~30–60 s | **Sequential subprocesses** |
| `verify_all.py` (137 submissions) | ~15–70 s | **Sequential for-loop** |
| `gate_changed.py` (RIS refutation) | ~2–10 min/code | **Sequential per code; dominant cost** |
| `check_authorship.py` | <1 s | |

Total for a typical single-code PR: **~3–11 minutes**.
Total for a codes-only PR (skips tests): **~2.5–10 minutes**.

---

## 1. Parallelize `verify_all.py` (easy, ~30 s saved)

### Problem

`verify_all.py` processes 137 submissions in a sequential `for` loop. Each call
to `verify(doc)` runs schema validation, GF(2) matrix construction, CSS
commutation checks, rank/rref, witness validation, and WL hashing — taking
~0.1–0.5 s per code. Total wall time: ~15–70 s.

### Fix

Use `concurrent.futures.ProcessPoolExecutor` to run `verify(doc)` across all
submissions in parallel. The work is embarrassingly parallel — no shared state
between codes.

```python
from concurrent.futures import ProcessPoolExecutor, as_completed

def _verify_one(path):
    """Run structural checks on a single submission. Designed for ProcessPool."""
    with open(path) as f:
        doc = json.load(f)
    rep = verify(doc)
    return path, rep

with ProcessPoolExecutor(max_workers=4) as pool:
    futures = {pool.submit(_verify_one, p): p for p in paths}
    for future in as_completed(futures):
        path, rep = future.result()
        # ... accumulate results
```

The duplicate-detection pass (WL signature + fingerprint grouping) remains
serial after the parallel map — it just aggregates already-computed results.

### Risk

None. The `verify()` function is a pure computation with no I/O side effects
beyond reading the JSON (which is done before dispatch). Pickling the result
dict across processes is trivial.

---

## 2. Parallelize `run_tests.py` (easy, ~40 s saved)

### Problem

`run_tests.py` discovers test files by glob (`verify/test_*.py`,
`research/test_*.py`) and runs each as a separate `subprocess.run()`
sequentially. There are currently 6 tests, each independent.

### Fix

Launch all test subprocesses concurrently and collect exit codes:

```python
procs = []
for t in tests:
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, t)], cwd=ROOT)
    procs.append((t, p))

failed = []
for t, p in procs:
    rc = p.wait()
    if rc != 0:
        failed.append(t)
```

A wall-clock reduction from ~60 s to ~20 s is expected, since the slowest
test (`test_heuristic_distance.py`) dominates and the others finish well
before it.

### Alternative

Switch the entire test suite to `pytest` with `pytest-xdist` (`-n auto`)
for automatic parallel discovery. This is a larger refactor but gives better
reporting.

### Risk

Low. Tests write to stdout/stderr independently. If any test mutates shared
files (e.g. fixture JSONs), they'd race — but current tests are read-only on
shared state.

---

## 3. Parallelize `gate_changed.py` across changed codes (medium effort)

### Problem

When a PR changes multiple code submissions, `gate_changed.py` runs the full
RIS refutation pipeline on each one sequentially. Each code takes 2–10 min
depending on `n` and whether it's a record-advancing claim. Two codes = ~6–20
min wall time.

### Fix

Refactor the `for f in files:` loop in `main()` into a parallel map. Each
code's refutation is fully independent (own seed, own budget, own RIS run).
Use `ProcessPoolExecutor` or `multiprocessing.Pool`:

```python
def _refute_one(args):
    """Refute a single code. Designed for ProcessPool."""
    path, code_root, seed, records, fast = args
    doc = json.load(open(path))
    # ... full refutation logic ...
    return path, result

with ProcessPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(_refute_one, work_items))
```

The `FAST_THREADS=4` C++ thread count should be lowered if running multiple
codes in parallel (e.g. `FAST_THREADS=2` with 2 workers, or dynamically
allocated).

### Risk

Medium. The C++ accelerator uses OpenMP threads; running multiple codes each
spawning 4 threads could oversubscribe. Cap total threads:
`FAST_THREADS = max(2, os.cpu_count() // max_workers)`.

---

## 4. Parallelize `refute_board.py` weekly cron (medium effort, high impact)

### Problem

The weekly board refutation runs `H.refute_check(doc, seed=...)` on every
coded submission sequentially. With ~136 codes at ~10–90 s each, this takes
~30–60 minutes.

### Fix

`certify_all.py` already demonstrates the pattern — use
`ProcessPoolExecutor(max_workers=4)`:

```python
from concurrent.futures import ProcessPoolExecutor

def _refute_one(args):
    path, seed = args
    rel = os.path.relpath(path, ROOT)
    doc = json.load(open(path))
    # ... refute_check logic ...
    return rel, result

with ProcessPoolExecutor(max_workers=4) as pool:
    results = list(pool.map(_refute_one, work_items))
```

Expected: ~30–60 min → ~10–15 min with 4 workers.

### Risk

Low. Same read-only pattern as `verify_all.py`. The per-file seed derivation
(`(seed + sha256(rel)) % 2**31`) is deterministic and doesn't depend on
processing order.

---

## 5. Cache `uv` dependencies (easy, ~15–30 s saved)

### Problem

Every CI run installs dependencies from `uv.lock` via `uv run --frozen`.
While `--frozen` skips resolution, the actual package installation (especially
compiled packages like `ldpc` and `numpy`) takes ~10–20 s on a cold cache.

### Fix

Use GitHub Actions' `actions/cache` to persist the `uv` cache directory:

```yaml
- uses: actions/cache@v4
  with:
    path: ~/.cache/uv
    key: uv-${{ runner.os }}-${{ hashFiles('uv.lock') }}
    restore-keys: uv-${{ runner.os }}-
```

Or use `astral-sh/setup-uv@v5`'s built-in caching:

```yaml
- uses: astral-sh/setup-uv@v5
  with:
    enable-cache: true
    cache-dependency-glob: uv.lock
```

### Risk

None. `uv` cache is safe to share across runs; `--frozen` still enforces the
exact lockfile.

---

## 6. Make `gf2_fast` build reliable (medium effort, ~2–4 min saved per record code)

### Problem

The C++ `gf2_fast` accelerator is built with `continue-on-error: true`. When
the build fails, the gate silently falls back to 3 Python RIS seeds instead of
1 Python seed + the C++ fast pass. This means record-advancing codes get
~3× less refutation depth (~2–4 min more Python time per code).

### Fix

- Pin the build dependencies (compiler version, pybind11) in `pyproject.toml`
  or a CI-specific step.
- Add a build-test step that imports `gf2_fast` and runs a trivial assertion
  before proceeding.
- Consider pre-building and caching the `.so` artifact (keyed on the C++ source
  hash + Python version).

### Risk

Low. The gate already degrades gracefully; this just makes the fast path
reliable.

---

## 7. Skip tests on push to `main` (trivial, ~60 s saved)

### Problem

After a PR passes CI and merges, the push to `main` re-runs the entire
`verify.yml` workflow including all tests. Since the PR already validated
the code, this is redundant.

### Fix

Add a condition to skip `run_tests.py` on push events:

```yaml
- name: self-tests
  if: github.event_name == 'pull_request' && steps.changes.outputs.only_codes != 'true'
  working-directory: submitted
  run: uv run --frozen python run_tests.py
```

The `verify_all.py` and `gate_changed.py` steps should still run on `main`
pushes to catch anything the PR gate missed (e.g. merge conflicts that break
JSON).

### Risk

Low. The only scenario where a `main` push could introduce a test failure that
a PR didn't catch is if `run_tests.py` or the test files themselves were
modified in the same PR — but the workflow's `paths` filter already ensures
those PRs run tests.

---

## 8. Shallow-clone the `trusted` tree (trivial, ~5–10 s saved)

### Problem

Both checkouts use `fetch-depth: 0` (full git history). The `trusted` tree
is only needed to run the verifier code from the base branch — it never needs
history for diffs or log analysis.

### Fix

```yaml
- name: check out trusted verifier tree (base branch)
  if: github.event_name == 'pull_request'
  uses: actions/checkout@v4
  with:
    ref: ${{ github.base_ref }}
    fetch-depth: 1          # <-- only needs contents, not history
    path: trusted
```

Keep `fetch-depth: 0` on `submitted` — the diff computation needs full
history.

### Risk

None. The trusted tree is only used to execute `verify/` and `run_tests.py`.

---

## 9. Deduplicate checkout on `main` pushes (trivial, ~5 s saved)

### Problem

On pushes to `main`, both `submitted` and `trusted` are checked out to the
same ref, producing two identical copies of the repo.

### Fix

When `github.event_name != 'pull_request'`, use a single checkout and
symlink or alias:

```yaml
- name: check out submitted tree
  uses: actions/checkout@v4
  with:
    fetch-depth: 0
    path: submitted

- name: symlink trusted tree (same ref on push)
  if: github.event_name != 'pull_request'
  run: ln -s submitted trusted
```

Then adjust the `working-directory` in later steps to use `submitted` when
`trusted` was the same tree.

### Risk

Low. The `trusted` path is only referenced by name in `working-directory`;
the symlink makes it transparent.

---

## 10. Shared verification cache between `verify_all.py` and `gate_changed.py`

### Problem

Both `verify_all.py` and `gate_changed.py` call `verify(doc)` for structural
checks on the same submissions (verify_all checks everything; gate_changed
re-checks changed codes for the submission scope). The `lru_cache` on `verify`
doesn't help because they run as separate processes.

### Fix

Write a JSON cache of `{path: {ok, signature, fingerprint, ...}}` to a temp
file after `verify_all.py` completes. `gate_changed.py` loads it and skips
re-running structural checks on codes that already passed.

### Risk

Low. The cache is a pure function of the JSON content (the hash is already
computed). Stale entries are caught by the hash comparison.

---

## Summary: Estimated Savings

| Change | Effort | Wall-clock saved |
|--------|--------|-----------------|
| Parallelize `verify_all.py` | Low | ~30 s |
| Parallelize `run_tests.py` | Low | ~40 s |
| Cache `uv` dependencies | Low | ~15–30 s |
| Shallow-clone `trusted` | Trivial | ~5–10 s |
| Skip tests on `main` push | Trivial | ~60 s |
| Deduplicate checkout on push | Trivial | ~5 s |
| Parallelize `gate_changed.py` per-code | Medium | Variable (saves minutes for multi-code PRs) |
| Parallelize `refute_board.py` weekly | Medium | ~30–45 min |
| Fix `gf2_fast` build reliability | Medium | ~2–4 min per record code |
| Shared verification cache | Medium | ~10–20 s |

**Combined easy wins (items 1–6):** ~2–3 minutes off every PR run.
**All items:** transformative for the weekly board refutation and significant
for the PR gate.
