---
title: "Uncertified search evidence for 12 board entries with listed distances 14 to 24"
date: 2026-10-22
author: "@carsoncrocker"
model: "Claude Opus 5.5 (Claude Code); review by OpenAI Codex"
topics: [exact-distance, exhaustive-search, bivariate-bicycle, generalized-bicycle, uncertified]
status: active
---

## Finding

For 11 of the 12 entries below, two separately written exhaustive searches find no nontrivial
X-logical and no nontrivial Z-logical of weight d-1 or less, where d is the listed distance. For
`510-16-24`, both find none of weight 22 or less, and the parity argument below rules out 23. The
entries' own weight-d witnesses give the matching upper bound. If the searches are complete and
correct, each listed distance is exact.

This is search evidence, not a certificate. No entry's distance or confidence changes, and this
note asks for no change to any entry. It records the evidence behind #3629 for the 12 entries in
that table that still have no certificate. The other two entries in that table, 420-8-14 (#3901)
and 280-8-15 (#3666), now have certificates.

| slug | d | searched up to | k |
|---|---|---|---|
| `510-16-24` | 24 | 22, plus parity (below) | 16 |
| `432-4-23` | 23 | 22 | 4 |
| `420-4-22` | 22 | 21 | 4 |
| `246-4-22` | 22 | 21 | 4 |
| `310-10-22` | 22 | 21 | 10 |
| `312-8-22` | 22 | 21 | 8 |
| `454-8-17` | 17 | 16 | 8 |
| `420-6-16` | 16 | 15 | 6 |
| `316-8-16` | 16 | 15 | 8 |
| `192-20-16` | 16 | 15 | 20 |
| `432-8-15` | 15 | 14 | 8 |
| `210-26-14` | 14 | 13 | 26 |

For `510-16-24`, both searches stop at weight 22. Every column of H_X and H_Z has weight 3, so
the rows of each matrix sum to the all-ones vector, and every X- or Z-logical has even weight.
That rules out weight 23.

## Method

Both programs search for a lightest logical by growing a support from an anchor qubit, in the
style of the irreducible-cluster algorithm of Dumer, Kovalev and Pryadko (IEEE Trans. Inf.
Theory 2017). A lightest logical has no nonempty proper subset with zero syndrome. So a branch
picks an unsatisfied check, tries each of its free qubits in turn (excluding the earlier ones),
and stops as soon as the syndrome is zero. At that point it tests whether the support lies
outside the stabilizer row space. Code automorphisms reduce the anchors to one per qubit orbit:
orbit i is anchored at its first qubit, with the qubits of earlier orbits excluded, following
Rowshan and Devitt (arXiv:2609.39395). `454-8-17` and `316-8-16` were run with n anchors, since
no symmetry was used for them. Each search was run directly at W = d-1 (W = 22 for `510-16-24`).

## The two implementations

- Program 1 (Python with numba) branches on unsatisfied checks and prunes with
  |S| + ceil(u / D) > W, where u is the number of unsatisfied checks and D is the largest column
  degree.
- Program 2 (C) is an exclusion depth-first search written by a separate AI agent that did not
  see program 1. It prunes with a greedy covering bound.

They share the code definitions, the orbits and the mathematics. So this is two implementations
of one method, not two methods, and an error in the method itself would affect both.

The package gives an explicit qubit permutation from each published construction onto the board
matrices: the weight-5 bivariate bicycle entries (`432-4-23`, `420-4-22`, `420-6-16`, `432-8-15`)
from the polynomials in arXiv:2610.06623, `246-4-22`, `310-10-22` and `312-8-22` from the
twisted-torus construction of Liang, Liu, Song and Chen (arXiv:2503.03827), and `192-20-16` from
Symons, Rajput and Browne (arXiv:2511.13560). Some runs used those constructions rather than the
board files. For `510-16-24`, program 2 ran on the board's check lists, and program 1 ran on a
presentation with an explicit permutation onto them.

## The pruning bug and the rerun

The first version of program 2 hard-coded a quick bound, |S| + ceil(u/3), that is valid only when
every column has degree 3 or less. On codes with heavier columns it could prune a branch that
still held a logical. A positive control caught it: run at W = d, version 1 missed a weight-16
logical of `192-20-16` that exists. Version 2 uses the real largest column degree. All seven
codes in the package with a column degree above 3 were rerun with version 2. Three are board
entries here: `192-20-16`, `210-26-14` and `316-8-16`. The other nine entries have column
degree at most 3, where the two versions do the same arithmetic. Program 1 always used the real
largest column degree. The superseded version 1 logs for the seven codes with column degree above
3 are kept in the package and marked superseded.

## Package and reruns

Zenodo, DOI 10.5281/zenodo.23423011: both programs, the code files, the equivalences, every run
log, the limitations and a one-command check. Its quick mode takes a few minutes and includes the
W = d positive control, which must find a weight-d logical. Its full mode reruns every search,
about 12 CPU-hours.

For scale: `432-4-23` took 8.3e8 and 8.4e8 nodes in program 1 (about 2,000 s per side) and
8.9e8 and 1.2e9 nodes in program 2. `210-26-14`, where the SAT certifier times out, took about
5e5 nodes per side in program 1.

## Relation to the board's certifier

I also ran `verify/sat_certify.py` on all 12 at `--tlim 3600` (symmetry on where the certifier
turns it on). Both sides timed out on every one, so none has a certificate. On 2026-10-22 I
started the 14400 s pass with `--proof` on `210-26-14` that was suggested in #3629. I will
report its result there, whatever it is.

## Limits

There is no certificate a third party can check mechanically. A bug shared by both programs
cannot be fully ruled out, and their completeness rests on the anchoring and pruning arguments in
the package. I am not a QEC researcher. Claude, via Claude Code, did the computations and drafted
this text under my direction. OpenAI Codex reviewed the package and this text. There was no
human expert review, so corrections are welcome.
