# Reproducing the GF(4) [[124,20,13]] distance certificate

This directory provides a local exhaustive distance certificate for one binary CSS stabilizer group. It independently reconstructs the GF(4) recipe, binds the reconstructed group to the supplied candidate JSON, verifies its weight13 logical witnesses, and optionally repeats two complete orbit meet-in-the-middle enumerations. The measured presentation has maximum check weight13, maximum qubit degree12,104 checks and1352 incidences.

The certificate establishes mathematical dX=dZ=d=13 for this physical stabilizer group and equivalent generator bases. It does **not** assign an official server `exact` status, run a submission gate, or claim novelty. The candidate's distance metadata remains `upper_bound`; this script never edits the input JSON. Stored results were generated against the original optimized JSON SHA256 `748df148634412298876764cf231e70619c751148ac9225fe5872f135f0413ee`. A promoted JSON may have a different file hash or different weight13 witnesses: the checker accepts it through exact group equality and independent witness verification, not a hard-coded file-hash requirement.

## Run

Requirements: Python3.10+ with its standard library on a POSIX system. Full replay additionally needs a C++17 compiler (`g++` by default), a little-endian host, approximately1.2GB available RAM and1.3GB temporary disk space. The enumerators run sequentially. No NumPy, repository verifier, network access, or external package is required.

From a repository containing `codes/124-20-13.json`:

```sh
python3 repro/124-20-13/reproduce.py codes/124-20-13.json --output /tmp/qldpc-124-binding
python3 repro/124-20-13/reproduce.py codes/124-20-13.json --output /tmp/qldpc-124-full --full
```

The default invocation only reconstructs and binds matrices, validates both supplied witnesses, and writes correctly aligned syndrome columns. It does not prove the distance lower bound by itself. `--full` compiles and executes the two unchanged enumerators, parses all count and collision checks, verifies the full sorted array with a streaming checker, and compares its SHA256. It writes `full-result.json` only after every check passes. Compiler/run stdout, stderr and timing receipts are retained. The1.2GB key file and compiled binaries are temporary and are removed; the exact key SHA, byte count and verification result remain. Use `--cxx` to choose a compiler and `--timeout` to change the per-process timeout.

The complete replay took roughly30 seconds on the original audit host; timings on other machines will vary. See the actual per-process receipts in `results/`.

## Construction and binding

Work in GF(4)=GF(2)[omega]/(omega²+omega+1), representing1,omega,omega² by integers1,2,3. Let

```
f(x) = 3 + 2x + x^3 + 2x^8 + 3x^11
g(x) = 3 + x + x^4 + 2x^12 + 3x^13
R    = GF(4)[x]/(x^31+1).
```

The circulant convention is C(p)[i,j]=p[(i−j) mod31]. Expand scalar multiplication in the binary basis(1,omega), giving A=rho(C(f)), B=rho(C(g)), HX=[A B], HZ=[Bᵀ Aᵀ]. Physical qubit coordinates are `62*block+2*j+bit`, with block0,1; j0..30; bit0,1. The checker derives these scalar maps using polynomial arithmetic rather than importing a supplied matrix table.

Both raw matrices have62 rows and rank52; their rows commute. Each actual candidate matrix and its stack with the corresponding raw matrix must have rank52, so their stabilizer rowspaces are identical. This yields k=124−52−52=20. Each candidate witness must have weight13, zero opposite syndrome, and increase its own stabilizer rank from52 to53.

The physical involution swaps the two62-qubit blocks and maps symbol j to−j, keeping its binary lane. Each scalar multiplication matrix is symmetric. Hence reversal R satisfies RAR=Aᵀ and RBR=Bᵀ, and HX P=R HZ, HZ P=R HX. The checker verifies these identities entrywise. They prove dX=dZ and preserve logical nontriviality.

The exported columns are reordered into four bit lanes: block0/bit0, block0/bit1, block1/bit0, block1/bit1, with31 positions per lane. Simultaneous physical j→j+1 shifts induce a left rotation by2 among the62 syndrome bits. This is checked on all124 columns of both matrices before enumeration. The optimized52-row presentation is never incorrectly treated as a cyclic list of syndrome bits.

## Why the enumeration is complete

Let T be this simultaneous cyclic shift and U its induced syndrome action. Every nonempty support of weight at most6 has orbit size31:31 is prime, and a nonidentity stabilizing shift would force a whole31-position coordinate orbit into the support.

Each enumerator chooses the first nonempty lane, anchors an occupied position at0, recursively generates the remaining increasing support, and retains exactly one lexicographically canonical anchored rotation. The primary uses forward lane order and the minimum syndrome rotation; the second uses reverse lane order and the maximum syndrome rotation. Both compare complete62-bit syndrome integers, without approximate hashing or probabilistic filtering.

| Half weight | Number of support orbits |
|---:|---:|
|1|4|
|2|246|
|3|10004|
|4|302621|
|5|7262904|
|6|144047596|
|Total nonempty|151623375|

For every support representative, the code also checks whether U fixes its syndrome. Because31 is prime, this catches every syndrome orbit shorter than31, including zero. This extra check handles self-orbit collisions that duplicate-key checks alone would miss. Both full enumerations return zero fixed syndromes and zero repeated canonical syndrome keys.

Suppose a nonzero kernel vector v had weight at most12. If its weight is at most6, its orbit representative has zero syndrome, contrary to the fixed-syndrome check. Otherwise split its support into disjoint a,b, each of weight at most6. Their syndromes agree. If a,b belong to different support orbits, their canonical syndrome keys collide. If b=T^r a in the same orbit, r is nonzero and U^r Ha=Ha, making Ha shift-fixed because the group order is prime. Both cases contradict the measured zero counters. Thus the tested classical kernel has no nonzero word of weight at most12. Empty support is safely omitted because its dangerous collisions are precisely the zero-syndrome cases already checked.

This is stronger than merely excluding nontrivial quantum logicals: no nonzero short kernel vector, including a stabilizer, exists. Therefore no stabilizer-quotient classification of collisions is needed for the successful zero-collision certificate. The independently validated non-stabilizer weight13 witnesses attain the lower bound on both CSS sides.

## Files and integrity

- `reproduce.py`: independent standard-library construction, candidate binding, witness checks and opt-in full-run orchestration.
- `orbit_mitm.cpp`: unchanged first exhaustive implementation.
- `independent_orbit_check.cpp`: unchanged second implementation, with different support/syndrome normalization and the opposite CSS matrix.
- `check_sorted_keys.cpp`: streaming verification of every sorted key, adjacent order and all fixed syndromes.
- `results/`: actual binding, exported columns, full logs, timing receipts and final certificate from this package's own execution.
- `SHA256SUMS`: hashes of every retained file except the manifest itself.

The primary's exit code alone is insufficient: it returns0 even if its reported counters are positive. The wrapper explicitly requires completed enumeration, exact per-weight totals, and zero duplicate/fixed counters. The second implementation additionally returns nonzero on those failures. Its compressed line36 produces a harmless misleading-indentation compiler warning; its actual control flow was reviewed.

The primary field named `fnv1a64` uses a nonstandard starting offset. It is only an implementation-specific replay digest; equality tests use complete integer keys. The full sorted-key SHA256 must be

```
87c3d881051f044ba8c5c15287aca06b58dbfdf58d20a0a0e524d8795b357510
```

The array has151623375 entries and1212987000 bytes. This large array is deliberately not shipped. It is reproducible from the included small input recipe and source files.

This certificate does not cover other polynomial pairs, field coordinate bases, unrelated [[124,20]] codes, subsystem/gauge modifications, or measurement-circuit performance. In particular it must not be reused as a distance lower bound after modifying the physical stabilizer group.

The integration may additionally include `ris-ladder.json` and `replay_ris.py`, maintained separately, for fresh official randomized upper-bound checks. They are supplemental to this exhaustive certificate and are not covered by this bundle's manifest. `fresh-candidate-binding/` records a light replay against the promotion candidate with its freshly replaced weight13 witnesses; it verifies the same group without requiring the historical JSON bytes.

Compiler diagnostics in the published receipt use source filenames in place of host-specific absolute paths.
