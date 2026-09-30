# [[23,1,7]] cyclic stabilizer with weight-6 checks

## Direction & hypothesis

Target the unrestricted, weight-6 non-CSS stabilizer board using sparse inversion-symmetric cyclic generators. This is an instance of established additive cyclic constructions, not a new family. The trusted gate reports board advancement against upstream 7ea128673cd867fec57d614d8c847d9f2d790c60. Literature novelty is unverified. No circuit-performance improvement is claimed.

## What was searched

The campaign sampled 320 candidates: 160 each at check weights 6 and 8, odd lengths 11 through 31. Disjoint inversion-pair supports define the X and Z halves. Candidate ordering used Python random seed 300930. Initial screening used 80 Pauli RIS trials per candidate; six representatives received deeper searches. This was a bounded sample, not exhaustive enumeration.

## Evidence trail

The earlier deep pass requested 20,000 Pauli RIS trials with a 30-second cap, followed by 400,000 accelerator trials on doubled matrices. The new pass requested the same Pauli budget followed by 2,000,000 accelerator trials, seed 301100; both returned lightest Pauli weight 7. The accelerated doubled-matrix search is re-scored by Pauli weight and is not two million independent direct-Pauli trials. Receipts are `repro/cyclic-23-1-7/previous-search.json` and `repro/cyclic-23-1-7/deep-search.json`.

The final candidate gate passed structural, rank, commutation, witness and refutation checks, with no exact or WL duplicate detected. Its receipt is `repro/cyclic-23-1-7/current-gate.json`. All distance metadata remains witness-backed upper_bound. A search that fails to find a lighter logical does not establish a distance lower bound. Duplicate tests do not cover every local Clifford equivalence.

## Dead ends and literature limits

None of the six campaign candidates establishes a new unrestricted parameter record. The weight-8 [[21,3,5]] candidate was set aside because an inspected published [[21,3,6]] admits weight-8 generators. For this submission, the [Grassl reference](https://www.codetables.de/QECC.php?q=4&n=23&k=1) achieves distance 7. Exhaustive rowspace analysis of that specific reference gave minimum spanning check weight 8; this is not an optimality claim across all published codes. The submission offers a sparse-check tradeoff or matching distance, not a general literature record.

## Tools

GPT-6 in Codex; repository GF(2), Pauli RIS, gf2_fast doubled-matrix search, and unchanged trusted validation tools. No custom distance checker or verifier modification. No decoding benchmark is included.

## Reproduction

For every shift t from 0 through 22, add one generator with X support {(a+t) mod 23: a in [8, 15]} and Z support {(b+t) mod 23: b in [6, 11, 12, 17]}. The resulting binary symplectic matrix has 23 rows and 46 columns. The code JSON stores all generators and a nontrivial weight-7 Pauli logical witness.

Run `python verify/qldpc_verify.py codes/23-1-7-cyclic.json` from the repository root. The construction is related to [CRSS, Section 5](https://arxiv.org/abs/quant-ph/9608006) and the [single-generator cyclic framework of Kovalev, Dumer and Pryadko](https://arxiv.org/abs/1108.5490). The search was initially inspired by challenge PR #2445.

## Supplementary exhaustive calculation

The unmodified qLDPC 0.3.3 exact-distance implementation returned 7 after exhaustive evaluation of the three nonidentity logical cosets (12,582,912 operators). Two basis-generation routes used the same distance engine, not independent algorithms. This is reproducible software evidence, not a challenge-issued exact badge or a formal proof certificate. Run `python repro/cyclic-23-1-7/exact-distance.py` in an environment with qldpc==0.3.3 and numpy>=2. The script also reproduces the stabilizer-weight comparison with quantum Golay: 23 weight-6 stabilizers here versus none for Golay, excluding local-Clifford-plus-permutation equivalence. Wider novelty remains unverified.
