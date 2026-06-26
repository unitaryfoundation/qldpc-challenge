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

The distance gate is probabilistic: it runs a random-information-set search with
a fresh random seed each run, so a green check is not a permanent guarantee. A
correct distance has no lighter logical to find and passes every time; an
over-claimed one may slip past one seed and get caught on a re-run, at merge, or
by the weekly board sweep, in which case the code is removed. The seed is printed
so any failure reproduces.

## Contribute with an LLM

If you have an LLM or coding agent, it can do the whole loop: pick a target,
search for a code, verify it, and open the PR. This is the lowest-effort way in.
Paste the prompt below into your agent. The method follows IBM's LLM-guided
evolutionary search for these codes (arXiv:2606.02418): the model mutates the
program that generates a code, rather than tweaking numbers by hand.

```
You are contributing to the qLDPC Challenge, a leaderboard of quantum LDPC
codes. Goal: find a CSS qLDPC code that advances a frontier, and submit it.

1. Clone https://github.com/unitaryfoundation/qldpc-challenge. Read TRACKS.md
   (the tracks and the Open Challenges, which list the live bars to beat) and
   the research/ starter kit (code constructors, the RIS distance surrogate,
   submission packaging). Pick one target from the Open Challenges.

2. Search a construction family. Represent each candidate as a small Python
   program that generates (H_X, H_Z), and mutate that generator (its
   polynomials / group / lattice / exponents), keeping an archive of the best
   non-dominated candidates binned by (n, k). Families, roughly most-headroom
   first:
     - weight-8 planar / tile codes (2d-local): real room toward kd^2/n ~ 9.75.
     - lifted product over non-abelian groups (dihedral, dicyclic): less mined.
     - bivariate bicycle, generalized bicycle: strong but largely mined out by
       the published frontier; random search there mostly re-finds dominated
       codes, so only pursue with a deliberate construction.

3. Screen each candidate fast: k = n - rank(H_X) - rank(H_Z), CSS commutation
   (H_X H_Z^T = 0 over GF(2)), max check weight, and an RIS distance UPPER
   bound from research/. Keep only codes that beat the board's frontier for
   their track on (n, k, d) and kd^2/n.

4. Before trusting a candidate, RE-VERIFY its distance with far more RIS trials
   (100k+). Low-trial surrogates return inflated upper bounds that collapse
   under deeper search (e.g. [[390,8,<=26]] fell to 24, [[1080,60,<=116]] to
   18). Keep only a distance that holds.

5. Submit: ./qldpc submit yourcode.npz --authors @yourhandle --model "<model>".
   It finds the witness, runs the verifier, and opens the PR. CI re-verifies.

Report the [[n,k,d]], which track it advances, and that the distance held under
deep re-verification.
```

Two rules keep a submission honest and worth merging: every distance carries a
checkable witness (the CLI produces it), and a code only counts if it advances
a track's frontier rather than just filling the board.

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
