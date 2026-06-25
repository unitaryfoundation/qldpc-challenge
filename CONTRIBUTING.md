# Contributing a code

You bring `H_X` and `H_Z`; one command turns them into a verified, PR-ready
submission.

## One command

```
./qldpc submit mycode.npz --authors @yourhandle
```

(or, without the launcher shim: `uv run python cli/qldpc.py submit ...`)

`mycode.npz` holds your parity checks under keys `hx` and `hz` (dense 0/1
arrays or scipy sparse). The tool:

- computes n, k (= n - rank H_X - rank H_Z) and the max check weight;
- searches for the lightest logical on each side and records it as a
  self-certifying distance witness, so you never hand-write a witness;
- assembles the schema-valid JSON;
- runs the full verifier locally, the same gate CI runs; and
- writes `codes/<n>-<k>-<d>.json` and prints the steps to open the PR.

If verification fails, nothing is written and you see exactly which check
failed before anything leaves your machine.

Useful flags:

- `--model "Opus 4.8"` what produced the code (self-reported, shown on the
  board as a claim, not verified);
- `--construction "..."` how it was built (family, polynomials, search);
- `--coords coords.npz --layers 2` a 2D layout to enter the `2d-local` tracks
  (the verifier proves the locality; see TRACKS.md);
- `--open-pr` create the branch, commit, push, and open the PR for you;
- `--dry-run` build and verify without writing.

Then open a pull request adding only your file under `codes/`. CI re-runs the
verifier; a green check is required to merge.

## By hand

If you would rather write the JSON yourself, follow `schema/code.schema.json`
(`schema/SCHEMA.md` documents each field), include a distance witness (an
explicit logical operator of the claimed weight for each side, or the verifier
rejects the claim), put the file in `codes/`, and verify locally before the PR:

```
uv run python verify/qldpc_verify.py codes/my-128-6-8.json
```

Exit 0 with an `earned_distance` block means it will pass CI.

## Confidence tiers

- `upper_bound`: your witness proves `d <= value`. Anyone can climb this board
  instantly; the math is checked, not trusted.
- `exact`: you also claim no lighter logical exists. Mark it `exact`, but know
  that the board shows it as an upper bound until a maintainer runs
  `verify/certify.py` (a bounded exact solver) and confirms it. We never
  silently upgrade a claim.

## What makes a submission interesting

A code only matters if it advances a track's Pareto frontier over (n, k, d)
under that track's constraints (check weight, locality). Dominated codes are
accepted and recorded but will not sit on the frontier. See `TRACKS.md`.

## Tips

- Store `interaction_radius` as the exact measured max check diameter, not a
  rounded value.
- Do not repeat a qubit index within a single check.
- If you believe your code is equivalent to an existing entry under a code
  symmetry, say so in `provenance.notes`; novelty is part of review.
