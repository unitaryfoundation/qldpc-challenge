<p align="center">
  <img src="docs/favicon.svg" width="96" height="96" alt="qLDPC Challenge logo">
</p>

# qLDPC Challenge

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
weight, geometric locality). So the
boards are stratified into tracks, and within a track the ranking is a Pareto
frontier rather than one winner. See `TRACKS.md`.

## Installation

This repo uses [uv](https://docs.astral.sh/uv/) to manage the Python environment. No explicit install step is needed — `uv run` sets up the environment on first use.

**Install uv** (one-time):

```bash
brew install uv        # macOS
# or: pip install uv   # any platform
```

**Verify a code locally:**

```bash
uv run python verify/qldpc_verify.py codes/your-code.json
```

**Build the leaderboard site:**

```bash
uv run python site/build.py
# then open docs/index.html
```

**Run research tools** (requires scipy + ldpc):

```bash
uv run --extra research python research/recipes/01_build_and_submit_bb.py
```

## Submitting

A submission is one JSON file in `codes/`, following `schema/code.schema.json`
(explained in `schema/SCHEMA.md`). Open a pull request adding it. CI runs the
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

Verify locally before opening a PR (uv handles the environment):

```
uv run python verify/qldpc_verify.py codes/your-code.json
```

The [qLDPC library](https://github.com/qLDPCOrg/qLDPC) is a convenient way to
construct codes and export the parity checks a submission needs.

## Layout

```
schema/    the submission format (JSON Schema + human spec)
research/  starter kit for BUILDING codes (constructors, distance surrogate,
           submission packager) + GETTING_STARTED.md
verify/    the verifier (gf2.py is the GF(2) core; qldpc_verify.py is the checker)
examples/  worked examples that pass verification
codes/     accepted submissions (the leaderboard data)
certs/     server-side exact-distance certificates, one per certified code
site/      build.py, which generates the static site into docs/
docs/      the generated site (index, per-code pages, references, badges)
refs.bib   bibliography; references.html is generated from it
TRACKS.md  the tracks and how ranking works
```

The boards are seeded with the codes of Liang, Eberhardt, Chen
(arXiv:2504.08887) as the reference baseline.
