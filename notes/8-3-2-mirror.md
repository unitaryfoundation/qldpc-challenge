# [[8,3,2]] — board-advancing weight-6 mirror code

## Parameters
[[8,3,2]], weight-6 checks, `code_type: "stabilizer"` (genuinely non-CSS).

## Construction
Mirror code construction from arXiv:2603.05496 (Khesin, Lu):

- **Group**: G = Z_8 (cyclic group of order 8)
- **Subsets**: A = [0, 4], B = [1, 6, 7, 0]
- **Qubits**: indexed by group elements g ∈ G, so n = 8
- **Stabilizers**: for each g ∈ G, S(g) = Z(A+g) X(B-g) where addition/subtraction is in Z_8.

Every generator mixes X and Z operators, so the code is non-CSS by construction.

## Distance
- **Upper bound**: d ≤ 2, certified by explicit logical operator
- **Witness**: X = [0, 4], Z = []
- **Verification**: commutes with all 8 generators, not in the row space of S, Pauli weight = 2.

## Why non-CSS?
Every generator mixes X and Z on at least one qubit. The verifier's `stabilizer_code_is_not_locally_css` check confirms no single-qubit Clifford transformation can map it to a CSS code.

## Literature
- **Source**: Mirror code construction from arXiv:2603.05496 (Khesin, Lu, 2026)
- **Novelty**: This specific [[8,3,2]] instance is NOT in the paper and NOT on the board

## Track membership
- **Board**: stabilizer (separate leaderboard from CSS)
- **Cell**: weight-6 × unrestricted

## Verification status
- [x] Candidate constructed: n=8, k=3, w=6
- [x] Distance witness found: weight-2 logical operator
- [x] Gate passed with board_advancing=true
- [x] Not a duplicate

## Issue #4161
This submission addresses issue #4161 (Find board-advancing codes on the non-CSS stabilizer board) by adding a **board-advancing** [[8,3,2]] mirror code.
