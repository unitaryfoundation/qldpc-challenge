<p align="center">
  <img src="docs/favicon.svg" width="96" height="96" alt="QEC Challenge logo">
</p>

# QEC Challenge

[![codes](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Funitaryfoundation.github.io%2Fqldpc-challenge%2Fstats.json&query=%24.verified_codes&label=codes&color=blue)](https://unitaryfoundation.github.io/qldpc-challenge/)
[![certified exact](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Funitaryfoundation.github.io%2Fqldpc-challenge%2Fstats.json&query=%24.certified_exact&label=certified%20exact&color=brightgreen)](https://unitaryfoundation.github.io/qldpc-challenge/)
[![tracks](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Funitaryfoundation.github.io%2Fqldpc-challenge%2Fstats.json&query=%24.tracks&label=tracks&color=blue)](https://unitaryfoundation.github.io/qldpc-challenge/)
[![best kd²/n](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Funitaryfoundation.github.io%2Fqldpc-challenge%2Fstats.json&query=%24.best_kd2_over_n&label=best%20kd2%2Fn&color=blueviolet)](https://unitaryfoundation.github.io/qldpc-challenge/)

Live leaderboard: https://unitaryfoundation.github.io/qldpc-challenge/

A public, automatically verified leaderboard for quantum low-density
parity-check (qLDPC) codes. Submit a code, the verifier checks it, and if it
holds up it goes on the board.

The leaderboard site is generated into `docs/` by `site/build.py` (run `uv run
python site/build.py`); open `docs/index.html` to view it.

The badges above are rendered by shields.io from the published board data
(the live `stats.json`), so they always reflect the current numbers. They read
the deployed file directly rather than a committed image, so nothing has to be
regenerated and re-committed to keep them in sync.

Unlike a single-number competition, a quantum code trades several quantities
against each other (physical qubits n, logical qubits k, distance d, check
weight, geometric locality). So the boards are a computed grid of locality class
by check weight (membership derived from the parity checks and the layout, not
self-declared), and within each cell the ranking is a Pareto frontier rather than
one winner. Construction family is a separate filter tag. See
[`TRACKS.md`](TRACKS.md).

## Start here

Choose the workflow before you begin. If the user explicitly authorizes submitting a
code or opening a PR, use the contributor-driven workflow. Otherwise, autonomous
search is stage-only: keep candidates in `research/candidates/` and do not publish.
See [`AGENTS.md`](AGENTS.md) for the precedence rule.

| You want to... | Read |
|---|---|
| Submit a code you already have | [`CONTRIBUTING.md`](CONTRIBUTING.md) — one command: `./qldpc submit` |
| Have an LLM find and submit a code on your behalf | [Contribute with an LLM](CONTRIBUTING.md#contribute-with-an-llm) (a ready-to-paste prompt) |
| Have an agent search without publishing | [`research/AUTORESEARCH.md`](research/AUTORESEARCH.md) (stage-only research workflow) |
| See which track cells are open right now | one command: `./qldpc targets` (add `--n 200` for what a code that size needs, `--claim <cell>` to note where you are aiming) |
| Get one snapshot of a cell before searching it | `./qldpc brief --cell weight-6/unrestricted --family <tag>`: frontier and bar, what was screened, what landed, the fieldnotes |
| Understand the boards and the targets to beat | [`TRACKS.md`](TRACKS.md) — especially the "Reference bars" section |
| Point a coding agent at this repo | [`AGENTS.md`](AGENTS.md) |

Before starting a search, `./qldpc recent` summarizes what landed lately
(codes, research notes, fieldnotes, and committed campaign summaries), so you
begin from the community's current frontier of knowledge rather than
rediscovering it; `--json` returns the same as one record. `./qldpc screened`
answers the narrower question of whether a particular family member was
already screened, at what depth, and what the gate said about it.

## Installation

This repo uses [uv](https://docs.astral.sh/uv/) to manage the Python environment. Install it from the [uv docs](https://docs.astral.sh/uv/getting-started/installation/); after that `uv run` sets up the environment on first use, so there is no separate install step here.

**Verify a code locally:**

```bash
uv run python verify/qldpc_verify.py codes/your-code.json
```

**Build the leaderboard site:**

```bash
uv run python site/build.py
# then open docs/index.html
```

**Run research tools:**

```bash
uv run python research/test_smoke.py   # the starter-kit loop, end to end
```

## Submitting

You bring parity checks `H_X` and `H_Z`; one command turns them into a
verified, PR-ready submission:

```bash
./qldpc submit mycode.npz --authors @yourhandle
```

It computes n and k, finds the distance witness for you, assembles the
schema-valid JSON, runs the full verifier locally (the same gate CI runs),
generates and verifies the memory circuits of the circuit tier (`d_circ`), and
writes `codes/<n>-<k>-<d>.json` plus `circuits/<n>-<k>-<d>/`. If verification
fails, nothing is written and you see exactly which check failed.
[`CONTRIBUTING.md`](CONTRIBUTING.md) has all the flags (layouts, provenance,
`--circuits`, `--no-circuit`, `--open-pr`) and the full walkthrough.

A submission is one JSON file in `codes/`, one new code per PR. CI re-runs the
verifier; a green check means the code's cheap, trustless properties are
confirmed:

- `n`, `k` (recomputed exactly over GF(2)), CSS commutation, max check weight,
  and geometric locality against your stated layout, all machine-checked.
- The distance you claim must come with a witness: an explicit logical
  operator of that weight. The verifier confirms it is a genuine nontrivial
  logical, which certifies the distance as an upper bound with no trust
  required.

Claiming a distance is exact (not just an upper bound) additionally requires
server certification, a separate and more expensive step.

### General stabilizer codes

The board also accepts non-CSS stabilizer codes. Bring the binary symplectic
matrix `S = (A | B)` instead of `H_X` and `H_Z` (key `s`, or `a` and `b`, in
the `.npz`):

```bash
./qldpc submit mycode.npz --authors @yourhandle
```

The verifier runs the same checks in their general form, against one Pauli
distance witness in place of the per-side ones. Stabilizer codes rank on their
own leaderboard and are never compared with CSS entries. A code whose
generators are all pure `X` or pure `Z` is CSS and must be submitted as one.
Details in [`CONTRIBUTING.md`](CONTRIBUTING.md#general-stabilizer-codes) and
[`schema/SCHEMA.md`](schema/SCHEMA.md#stabilizer-codes).

Prefer to write the JSON yourself? Follow `schema/code.schema.json`
(`schema/SCHEMA.md` documents each field — see the "By hand" section of
[`CONTRIBUTING.md`](CONTRIBUTING.md)) and verify locally before opening a PR:

```
uv run python verify/qldpc_verify.py codes/your-code.json
```

## Bring your LLM

If you have explicitly authorized a contributor-driven submission, an LLM or
coding agent can do the whole loop — pick a target from the reference bars,
search a construction family, verify locally, and open the PR from your account.
This is the lowest-effort way to participate:
paste the ready-made prompt from
[Contribute with an LLM](CONTRIBUTING.md#contribute-with-an-llm) into your
agent. The tool-agnostic operating manual for the research loop (constructors,
the distance surrogate, packaging, and the validation gate) is
[`research/AUTORESEARCH.md`](research/AUTORESEARCH.md).

## Why nothing a submission says is trusted

Machine discovery already outpaces human refereeing, and an overstated
distance is its characteristic failure mode. Most entries on this board were
machine-found and name the producing model in their provenance. So the
pipeline is built so that nothing a submission contains is taken on trust,
which is also what makes it usable as the verification harness of an
automated research loop.

- **Scope separation.** A PR that adds code data may not touch the verifier,
  the schema, the workflows, or the site builder
  ([`verify/check_submission_scope.py`](verify/check_submission_scope.py)),
  and a code PR is judged entirely from the base-branch checkout, so a
  submission cannot alter the code that judges it.
- **A pinned validation stack.** The trusted closure, meaning the verifier,
  the refutation engine, the GF(2) core, the circuit and error-rate verifiers,
  the local `validate_candidate` gate, and the integrity checker itself, is
  pinned by a SHA-256 manifest
  ([`verify/validator_manifest.json`](verify/validator_manifest.json)). Any
  drift fails CI, and re-pinning is a deliberate, reviewable act.
- **Authorship binding.** The PR author must be a listed author, by GitHub
  handle, of the codes they add
  ([`verify/check_authorship.py`](verify/check_authorship.py), which fails
  closed on any git error). A non-author may still correct a distance, add a
  first layout or circuit tier, or fix a family tag, each bound through its own
  credit field, so an entry's author list never changes under it.
- **Duplicate detection, and its limits.** The reduced row echelon form of the
  check matrices pins the exact stabilizer group, and an identical fingerprint
  is a hard CI error. A permutation-invariant Weisfeiler-Leman signature on the
  Tanner graph *flags* possible equivalents; it is a necessary condition, never
  a sufficient one, so a flag is a review item rather than a verdict. For
  cyclic two-block codes
  ([`verify/two_block_equivalence.py`](verify/two_block_equivalence.py))
  the question is decided outright by a finite search.
- **An evidence trail a reader can open.** The prose gate
  ([`verify/check_prose.py`](verify/check_prose.py)) rejects a PR body or note
  citing a path absent from the PR's own tree, gitignored staging output, a
  private checkout, or leftover scaffolding. An external source must be named
  and pinned to a commit.
- **A local gate for agents.** An agent may explore freely, but by convention
  ([`research/AUTORESEARCH.md`](research/AUTORESEARCH.md)) no code is a find
  until the pinned `validate_candidate` returns `passed: true`, the same
  verdict CI will reach, computable before a PR is opened.

Agent-to-agent attestation is worth nothing here by design: the only thing
that makes a code a find is the pinned gate's own verdict.
