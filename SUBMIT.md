# Submitting a code (agent quick reference)

The whole submission is one command. Everything else is optional.

## Happy path

```bash
./qldpc submit code.npz --authors @yourhandle --json
```

Dry runs and staging only: `--no-circuit --fast-trials 0` skips the circuit search and the accelerator tightening, so its witness comes from a shallow search. Do not file its output as a submission.

```bash
./qldpc submit code.npz --authors @yourhandle --no-circuit --fast-trials 0 --dry-run --json
```

## Performance notes

- First run on a fresh worktree loads the board (about five minutes on a laptop, about four seconds warm). The
  per-entry memo lives inside the checkout; `./qldpc targets`/`submit` print
  the measured time so you can tell warm from cold.
- A full checkout is ~8 GB (mostly `circuits/`). Use the sparse checkout in
  AGENTS.md; the pre-commit hook needs the full tree (`.github/`) to run the
  validator-integrity check.
- Machine mode: pass `--json`. Errors carry a `hint` with the exact rerun command.

`code.npz` holds `hx`, `hz` (dense 0/1 or scipy sparse). For stabilizer codes use key `s` (or `a`,`b`). The command computes n,k,d, finds the distance witness, runs the verifier, writes `codes/<n>-<k>-<d>.json`, drafts the PR body, and prints a JSON record on stdout (human prose on stderr).

Machine mode: always pass `--json`. Exit code 0 = success. On failure, `res.error` names the stage, the failed checks, and a `hint` with the exact rerun command; fix and rerun, do not parse prose.

## Useful flags (all optional)

- `--model "Claude Opus 4.8"` — exact model+version, or omit. Never write `"human"` unless a person did it.
- `--harness "OpenCode agent harness"` — tooling, separate from model.
- `--family bivariate-bicycle` — construction family tag.
- `--construction "..."` — how it was built.
- `--coords coords.npz --layers 2` — 2D layout (layers required with coords).
- `--note-file note.md` — research note staged as `notes/<slug>.md` (10 KiB cap). If omitted, the CLI warns that no note was given and ships none; submissions should always pass one.
- `--no-circuit` — skip the circuit tier (faster; code tier only).
- `--open-pr` — create branch, commit, push, open PR automatically.
- `--base-ref origin/main` — independent PRs from one checkout.
- `--slug 32-14-4-b` — suffixed slug when (n,k,d) collides with an existing entry.
- `--dry-run` — build + verify, write nothing; record carries full `doc`.

## Bulk submission

One command for a batch (issue #7449). It loads every candidate, drops the
duplicates inside the batch (the same code, or a probable permutation of one)
and the codes already on the board, runs each survivor through `submit` with
the shared flags, and with `--open-pr` files each one as its own PR from
`--base-ref` (default `origin/main`):

```bash
./qldpc submit-batch research/candidates/<run>/*.json --authors @yourhandle --open-pr --json --summary-file batch.json
```

- Code tier only by default (`--circuit` adds circuits); the accelerator pass runs at `submit`'s own depth. `--fast-trials 0` files shallow claims knowingly, and CI refutes shallow claims.
- A second code with the same (n, k, d, w) as one already filed in the batch is dropped as a `parameter-tie` (one PR per (n, k, d, w)); `--keep-parameter-ties` files it.
- `--against-open-prs` also dedups against the codes in open PRs (fetched with `gh`).
- `--note-dir DIR` passes `DIR/<candidate stem>.md` as the note when it exists.
- The record lists every candidate with a status: `filed`, `written`, `dry-run`, `duplicate`, `parameter-tie`, `refused`, `error`, or `not-run`. An `--open-pr` failure stops the batch, because the files it wrote are in the tree unfiled; finish that one by hand and re-run on the `not-run` ones. Exit 0 when every candidate was filed, written, or dropped as a duplicate.

## Before pushing

```bash
verify/prepush_prose_check.sh <body.md>
```

or the full sweep:

```bash
./qldpc preflight --body-file <body.md>
```

Both must exit 0. In a fork, add `upstream` first:
`git remote add upstream https://github.com/unitaryfoundation/qldpc-challenge.git && git fetch upstream`.

## Common failure modes

- **Paths in notes/PR body must resolve in the PR tree.** Never cite the gitignored staging directory, home-directory paths, or uncommitted files. Commit the script or describe the method.
- **The gitignored staging directory** can never be the audit trail.
- **d-only gain over an entry** (same n,k,w) needs `--peer-audit <file>` from `research/audits/leader_audit.py pair`.
- **Dominated code** is refused unless `--allow-non-frontier` (filed as a non-frontier record).
- **Revision** (changing an existing slug's d) must fold the old note forward (>=70% of body lines) or reclassify into `fieldnotes/`.
- **Family tag** must match `provenance.construction`. `verify/test_family_tag_consistency.py` checks the declared tag against the construction text, so a mismatch fails it.
- **One new code per PR.** No stray files under `research/` or directories under `repro/`.
- **No committed `.dem` files** — derived from `.stim`.
- **Code artifact is one file** `codes/<slug>.json`, never a directory.

## Minimal checklist before requesting review

1. `./qldpc submit ... --json` exits 0.
2. `./qldpc preflight --body-file <body.md>` exits 0.
3. PR body prompts replaced with real content; checklist boxes ticked only when true.
4. Note present at `notes/<slug>.md` (or deliberately omitted).

## Anti-patterns (do not do)

- Do not write your own distance/quality check; use the gate.
- Do not edit anything under `verify/` in a submission PR.
- Do not claim `"human"` for a model-produced code.
- Do not put a distance in the filename the JSON does not support.
- Do not open multiple PRs for the same `(n,k,d)`; run `research/kit/dedup_submissions.py` first, or let `./qldpc submit-batch` do the dedup.
