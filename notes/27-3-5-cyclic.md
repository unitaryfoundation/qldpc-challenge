# [[27,3,5]] cyclic stabilizer with weight-6 checks

## Direction & hypothesis

Target the unrestricted, weight-6 non-CSS stabilizer board using sparse inversion-symmetric cyclic generators. This is an instance of established additive cyclic constructions, not a new family. The trusted gate reports board advancement against upstream 7ea128673cd867fec57d614d8c847d9f2d790c60. Literature novelty is unverified. No circuit-performance improvement is claimed.

## What was searched

The campaign sampled 320 candidates: 160 each at check weights 6 and 8, odd lengths 11 through 31. Disjoint inversion-pair supports define the X and Z halves. Candidate ordering used Python random seed 300930. Initial screening used 80 Pauli RIS trials per candidate; six representatives received deeper searches. This was a bounded sample, not exhaustive enumeration.

## Evidence trail

The earlier deep pass requested 20,000 Pauli RIS trials with a 30-second cap, followed by 400,000 accelerator trials on doubled matrices. The new pass requested the same Pauli budget followed by 2,000,000 accelerator trials, seed 301102; both returned lightest Pauli weight 5. The accelerated doubled-matrix search is re-scored by Pauli weight and is not two million independent direct-Pauli trials. Receipts are `repro/cyclic-27-3-5/previous-search.json` and `repro/cyclic-27-3-5/deep-search.json`.

The final candidate gate passed structural, rank, commutation, witness and refutation checks, with no exact or WL duplicate detected. Its receipt is `repro/cyclic-27-3-5/current-gate.json`. All distance metadata remains witness-backed upper_bound. A search that fails to find a lighter logical does not establish a distance lower bound. Duplicate tests do not cover every local Clifford equivalence.

## Dead ends and literature limits

None of the six campaign candidates establishes a new unrestricted parameter record. The weight-8 [[21,3,5]] candidate was set aside because an inspected published [[21,3,6]] admits weight-8 generators. For this submission, the [Grassl reference](https://www.codetables.de/QECC.php?q=4&n=27&k=3) achieves distance 9. Exhaustive rowspace analysis of that specific reference gave minimum spanning check weight 12; this is not an optimality claim across all published codes. The submission offers a sparse-check tradeoff or matching distance, not a general literature record.

## Tools

GPT-6 in Codex; repository GF(2), Pauli RIS, gf2_fast doubled-matrix search, and unchanged trusted validation tools. No custom distance checker or verifier modification. No decoding benchmark is included.

## Reproduction

For every shift t from 0 through 26, add one generator with X support {(a+t) mod 27: a in [2, 4, 23, 25]} and Z support {(b+t) mod 27: b in [12, 15]}. The resulting binary symplectic matrix has 27 rows and 54 columns. The code JSON stores all generators and a nontrivial weight-5 Pauli logical witness.

Run `python verify/qldpc_verify.py codes/27-3-5-cyclic.json` from the repository root. The construction is related to [CRSS, Section 5](https://arxiv.org/abs/quant-ph/9608006) and the [single-generator cyclic framework of Kovalev, Dumer and Pryadko](https://arxiv.org/abs/1108.5490). The search was initially inspired by challenge PR #2445.
