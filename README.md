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

| You want to... | Read |
|---|---|
| Submit a code you already have | [`CONTRIBUTING.md`](CONTRIBUTING.md) — one command: `./qldpc submit` |
| Have an LLM find and submit a code on your behalf | [Contribute with an LLM](CONTRIBUTING.md#contribute-with-an-llm) (a ready-to-paste prompt) |
| Have an agent search without publishing | [`research/AUTORESEARCH.md`](research/AUTORESEARCH.md) (stage-only research workflow) |
| See which track cells are open right now | one command: `./qldpc targets` (add `--n 200` for what a code that size needs) |
| Understand the boards and the targets to beat | [`TRACKS.md`](TRACKS.md) — especially the "Reference bars" section |
| Point a coding agent at this repo | [`AGENTS.md`](AGENTS.md) — also the authority on the contributor-driven vs. stage-only precedence rule for autonomous search |

Before starting a search, `./qldpc recent` summarizes what landed lately
(codes, research notes, fieldnotes), so you begin from the community's current
frontier of knowledge rather than rediscovering it.

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

`mycode.npz` holds the two arrays under any of the spellings `hx`/`HX`/`H_X`
and `hz`/`HZ`/`H_Z` — no need to rename them to match a single expected
spelling.

It computes n and k, finds the distance witness for you, assembles the
schema-valid JSON, runs the full verifier locally (the same gate CI runs), and
writes `codes/<n>-<k>-<d>.json`. If verification fails, nothing is written and
you see exactly which check failed. [`CONTRIBUTING.md`](CONTRIBUTING.md) has
all the flags (layouts, provenance, `--open-pr`) and the full walkthrough.

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
