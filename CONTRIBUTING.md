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

- `--model "Claude Opus 4.8"` what produced the code, named to a specific
  version, not a bare vendor name (self-reported, shown on the board as a claim,
  not verified; if you name a model the verifier requires a version);
- `--construction "..."` how it was built (polynomials, group, search);
- `--family bivariate-bicycle` the construction family, a filterable tag from a
  fixed vocabulary (see TRACKS.md); it is never used for ranking;
- `--coords coords.npz --layers 2` a 2D layout; the verifier derives the locality
  class (single / bilayer / unrestricted) from it, you do not declare a track;
- `--open-pr` create the branch, commit, push, and open the PR for you;
- `--dry-run` build and verify without writing.

## Share the search, not just the code

A submission should ship with a public **research note** —
`notes/<n>-<k>-<d>.md`, in the same PR as the code (pass
`--note-file yournote.md` to `./qldpc submit` and it is staged for you).
The note is the how: your hypothesis, what you swept and at what depth, the
distance-confirmation ladder *including candidates that collapsed*, the dead
ends, your model/harness, and a reproduction recipe. See
[`notes/README.md`](notes/README.md) and the
[template](notes/TEMPLATE.md); 10 KiB cap. The site renders the note on your
code's page and in the
[research log](https://unitaryfoundation.github.io/qldpc-challenge/research-log.html),
next to your name and model.

Why this is worth your 20 minutes: the board's value compounds through shared
search experience, not just shared codes — the same way the ECDSA Fail
challenge makes every submission carry its method. Distance inflation, barren
families, and decoder quirks get rediscovered expensively by every
competitor unless someone writes them down once. Notes are requested for all
new submissions today and may become CI-required after an adoption period;
literature baselines are exempt (their note documents the reproduction
instead).

**Negative results are contributions too.** A route you can show is barren, a
heuristic that fails outside its regime, a calibration finding — PR it as a
stand-alone [fieldnote](fieldnotes/README.md), no code required. Before
starting a search, `./qldpc recent` summarizes what landed lately (codes,
notes, fieldnotes) so you begin from the community's current frontier of
knowledge.

Then open a pull request adding only your file under `codes/` (plus its
`notes/` file) — **one new code
per PR** (CI enforces this): each frontier submission gets a deep, ~10-minute
refutation search, and that budget is per code. CI re-runs the
verifier; a green check is required to merge. Open the PR from your own account:
CI checks that the PR author is one of the code's `@handle` authors, so list
yourself (literature baselines with no `@handle` are exempt).

Submission PRs are treated as untrusted data. CI validates `codes/*.json` with
verifier, schema, and gate code from the base branch, not from the PR itself. If
you need to change validation code (`verify/`, `schema/`, workflow files, or the
site builder), do that in a separate PR from any code submission so a submission
cannot redefine the checks that judge it.

The distance gate is probabilistic: it runs a random-information-set search with
a fresh random seed each run, so a green check is not a permanent guarantee. A
correct distance has no lighter logical to find and passes every time; an
over-claimed one may slip past one seed and get caught on a re-run, at merge, or
by the weekly board sweep, in which case the code is removed. The seed is printed
so any failure reproduces.

Public CI also enforces resource limits before dense verifier matrices are
allocated: 5 MB JSON files, `n <= 700`, at most 10000 checks per side, max check
weight 32, at most 200000 total support entries, and at most 700 locality
coordinates.

The `n <= 700` cap is the verification-budget rule (issue #249): the adaptive
distance gate runs under a fixed wall-clock budget, so its trials-per-qubit thin
out as `n` grows, and exact MILP certification scales worse still. Above the cap
the pipeline cannot stand behind a distance claim, so the board is kept a
finite-length benchmark. The cap is raise-only: it states what the verification
machinery can vouch for today, and rises as the tooling improves.

## Contribute with an LLM

If you have an LLM or coding agent, it can do the whole loop: pick a target,
search for a code, verify it, and open the PR. This is the lowest-effort way in.
Paste the prompt below into your agent.

A note on scope: here your agent acts on *your* behalf, so it may open the PR
from your account (you are the author of record and CI checks that the PR
author is listed in the code's `authors`). This is different from the in-repo
autoresearch manual, [`research/AUTORESEARCH.md`](research/AUTORESEARCH.md),
whose stage-only rule (never commit to `codes/`, never open a PR) governs
autonomous research runs where no human has reviewed the candidate yet. If
your agent reads both documents: this section wins for a contributor-driven
submission; AUTORESEARCH.md wins for an unattended search. 
The method follows IBM's LLM-guided
evolutionary search for these codes (arXiv:2606.02418): the model mutates the
program that generates a code, rather than tweaking numbers by hand.

```
You are contributing to the QEC Challenge, a leaderboard of quantum LDPC
codes. Goal: find a CSS qLDPC code that advances a frontier, and submit it.

1. Clone https://github.com/unitaryfoundation/qldpc-challenge. Read TRACKS.md
   (the tracks and the "Reference bars" section, which lists the live bars to
   beat) and research/AUTORESEARCH.md, the manual for the research/ starter
   kit (code constructors, the RIS distance surrogate, submission packaging).
   Pick one target from the reference bars.

2. Search a construction family. Represent each candidate as a small Python
   program that generates (H_X, H_Z), and mutate that generator (its
   polynomials / group / lattice / exponents), keeping an archive of the best
   non-dominated candidates binned by (n, k). Families, roughly most-headroom
   first:
     - weight-8 planar / tile codes (2d-local): the published exact bar is
       kd^2/n ~ 12.7 ([[512,18,19]], arXiv:2504.09171).
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

5. Submit: ./qldpc submit yourcode.npz --authors @yourhandle --family <family>
   --model "<exact model version, e.g. Claude Opus 4.8>". It finds the witness,
   runs the verifier (which computes the locality and weight classes), and opens
   the PR. CI re-verifies.

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

### What exact certification currently costs, and where it stops

`verify/certify.py` decides, for each side, whether any logical lighter than the
claimed distance exists. It does this with one MILP per logical-basis row, so
**k solves per side**, and `--tlim` is the budget for a *single* MILP rather than
for the whole run. The wall-clock worst case is therefore roughly

    2 * k * tlim          (default tlim = 600s)

which is about 20 minutes at k = 1 and about 6.7 hours at k = 20. Raising
`--tlim` multiplies the whole run, so it is not a cheap knob.

Measured envelope, from the codes that actually carry certificates today: all of
them have **d <= 13 and k <= 12**. Both k (which sets the number of solves) and
the weight cap d-1 (which sets how hard each solve is) drive the cost, so a code
can be small in n and still be out of reach.

Just past that envelope the problem is hard rather than merely slow. On
[[180,18,14]] and [[180,20,14]] (n = 180, k = 18 and 20, d = 14):

- scipy/HiGHS MILP hits the time limit on every side, and giving a single solve
  5x the budget changes nothing;
- an independent RC2 MaxSAT encoding of the minimum-weight-logical problem ran
  4.4 CPU-hours on one instance without returning an answer.

Two standard methods failing the same way is evidence about the instance, not
about the solver choice. Blocklength alone is not the obstruction: certified
codes exist at n = 180, 198, 200, 231, 240, 264 and 299, all at low k.

**So the rule is:** a code beyond that envelope stays a witness-backed upper
bound, refutation-tested at PR time and in the weekly sweeps. That is not a
lesser result, it is the honest one, and `d <=` is what the board displays. If
you have a certification approach that closes these, please open an issue; the
two n = 180 codes above are a good regression test.

## What makes a submission interesting

A code only matters if it advances a track's Pareto frontier over (n, k, d)
under that track's constraints (check weight, locality). Dominated codes are
accepted and recorded but will not sit on the frontier. See `TRACKS.md`.

## Tips

- Store `interaction_radius` as the exact measured max check diameter, not a
  rounded value.
- Do not repeat a qubit index within a single check.
- Use `provenance.origin` only for provenance (`baseline` vs `submission`), not
  novelty. If the same `[[n,k,d]]` parameter set exists in the literature, set
  `provenance.novelty` to `known_parameters` and cite it in
  `provenance.notes`. If you believe your code is equivalent to an existing
  entry under a code symmetry, say so in `provenance.notes`; novelty is part of
  review.
