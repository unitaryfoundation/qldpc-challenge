# Formal certificates: binding a Lean development to a board entry

A `formal` certificate (`certs/<slug>.json`, `verification.level: formal`)
records a theorem in a Lean development and a replay recipe for it, and
`verification.checks_sha256` binds the theorem to this entry's matrix pair:
`verify/check_certs.py` refuses the certificate when the hash is not the
entry's (`verify/qldpc_verify.py`, `checks_sha256`). The hash is of the
presentation, so a development that numbers the qubits differently has
proved a theorem about a relabeled code, and nothing in the certificate
can say so. Issue #7254 hit this for the Gross `[[144,12,12]]` code. This
directory holds the tool that makes the binding checkable and the
relabeling explicit.

## Two conventions

| development | qubit numbering, for group element `(a, b)` of `Z_l x Z_m` and block `0` or `1` |
|---|---|
| this board (`research/kit/bb.py`, `codes/<slug>.json`): `H_X = [A \| B]`, `H_Z = [B^T \| A^T]` | `block * (l * m) + (a * m + b)`, block-major |
| QECLean, `QEC/Stabilizer/Framework/Homological/BBChainComplex.lean`: qubits `G x Fin 2` | `2 * (a * m + b) + block`, interleaved by group element |
| Lean-QEC, `LeanQEC/Stabilizer/Examples/BB/BB*.lean`: `BitVec (rows * n)` literals, bit `i * n + j` | the board's (checked below) |

The reflected convolution QECLean notes in `BBChainComplex.lean` does not
separate it from the board: the board's `B^T` Z-checks are exactly
`d1`'s transpose, so the two differ by the qubit permutation alone, with no
`g -> -g`. `lean_binding.py relabel` checks this on the entry, row for row.

## The tool

```
uv run python research/formal/lean_binding.py emit codes/144-12-12.json --name BB144 --out BB144.lean
uv run python research/formal/lean_binding.py check codes/144-12-12.json --lean BB144.lean --name BB144
uv run python research/formal/lean_binding.py relabel codes/144-12-12.json --name Gross --out Gross.lean --json gross.json
```

`emit` writes the entry's two matrices as the `BitVec` literals the Lean-QEC
examples define, generated from the JSON with the entry's `checks_sha256`
in the header, so a theorem about those definitions is about this entry by
construction. `check` reads the literals back out of any Lean source and
compares them with the entry row for row, naming the first row that
differs and whether the rows are merely reordered or generate the same
group; it is how a cited development's binding is verified, and it exits
0 only on an exact match. `relabel`, for a bivariate-bicycle entry, builds
the code in QECLean's numbering from the entry's construction string,
finds the permutation onto the entry, checks the permuted checks against
the entry's rows, and writes the table as two Lean functions
(`<name>_fromQECLean`, `<name>_toQECLean`) and as JSON.

`fixtures/lean_qec_ae8bdd15.json` holds the `BB72_*` and `BB144_*`
literals of `github.com/vprusso/Lean-QEC` at the commit `certs/72-12-6.json`
pins. `research/test_lean_binding.py` checks that they are the board's
`72-12-6` and `144-12-12` entries row for row and that `emit` regenerates
them from the entries: the sentence in the 72-12-6 certificate's note is
now a test, and the same binding holds for BB144.

## Where the Gross proof stands

- `github.com/vprusso/Lean-QEC` at `ae8bdd15`: `BB144.lean` defines the
  entry's matrices in the board's numbering (checked above) and states
  `BB144_dist_12`, but at that commit the two kernel-rank lemmas it rests on
  are `sorry`, so it is not a proof.
- `github.com/QECLean/bb-distance-lean` (QECLean pinned at `f51011bd`):
  `grossStabilizerCode_hasCodeDistance_12_uncond` is a kernel-checked proof
  with the standard axioms only, about `grossComplex`, the chain complex in
  QECLean's numbering.
- What a formal certificate for `144-12-12` still needs is a Lean theorem
  in one of those developments stating that the entry's matrices (the
  `emit` literals) are the QECLean code relabeled by `Gross_fromQECLean`
  and that code distance is invariant under a qubit permutation, so the
  QECLean theorem transports to the entry's definitions; its replay recipe
  then goes in the certificate with the entry's `checks_sha256`. The table
  and the row-for-row check are the data that theorem needs; the proof is
  not in this repository.

A formal development cited by a certificate states its qubit numbering,
and the certificate's note says how the development's definitions were
checked against the entry (`lean_binding.py check`, or the development's
own generator from `codes/<slug>.json`).
