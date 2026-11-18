# Independent public-solvers distance verification (no private engine)

This contribution follows issue [#274](https://github.com/unitaryfoundation/qldpc-challenge/issues/274). It concerns the **existing** CSS code entries `codes/180-18-14.json` and `codes/180-20-14.json`. It does not submit any new CSS code, and leaves the original code files and trusted verifier unchanged.

## Claim and evidence level

The two independently implemented, previously **publicly published** solvers `exactA` and `exactB` returned **no nontrivial X or Z logical operator of weight at most 13**, for both entries. Each input's two public weight-14 logical witnesses were separately checked as weight-14, commuting with the opposite checks, and outside the corresponding stabilizer rowspace. Hence the **solver-level computational** conclusion is `d_X = d_Z = d = 14` for each entry, **conditional on the completeness proofs and implementations of the cited external solvers**. This is **not** a machine-checkable proof object nor a formal certificate.

The two proposed `certs/180-18-14.json` and `certs/180-20-14.json` entries declare `verification.level = solver` only, the repository's lowest evidence level. The result is subject to maintainer review before acceptance.

## Public sources, pinned exactly

The complete code for both independent methods is already available at:

- `https://github.com/TimoKellerMath/quantum-error-correction/tree/ae52261bfdbd/board-certificates-2026-11/src`
- `src/exactA.c`, SHA256 `2d1f0d1a55d9b9d71eff102eab6f131b4a6ff2da0e973518651877c3c3187856`
- `src/exactB.c`, SHA256 `e793e5b34eb60098f9ff72d02f6608e4a7f5975fc8e4f02ada8b5213ad0ae1a1`

The existing board inputs were taken from `unitaryfoundation/qldpc-challenge @ db19f655b4d2ecfde32c0e16b1bf178d8a5fcac2`:

- `codes/180-18-14.json`, SHA256 `805fd91dd45c4af9eaa50c18ef60754702b655fe4cd779576719e15b1fcc63e1`
- `codes/180-20-14.json`, SHA256 `eec53895ef4c1b72c3ef428ed0445e81403c9370ad14c5b94c7676ef98e2549d`

The search algorithms, optimization rules, and their completeness arguments are **not introduced by this PR**; they are external third-party work by Timo Keller. Their paper and proofs are documented in the pinned upstream `board-certificates-2026-11/README.md` and `src/exactA_NOTES.md`, `src/exactB_NOTES.md`. This PR does not contain or depend on any private research engine.

## Reproduce on a clean machine

Requirements: Python 3.9+, `gcc`, internet access to download the four pinned public files. The script SHA256-checks downloaded tools and code inputs before compilation/search, constructs the shift automorphism `q -> 90 floor(q/90) + ((q mod 90 + 3) mod 90)` and checks that it preserves **both** matrix row sets, independently checks each code's ranks and the existing witnesses, compiles the two third-party C programs, and runs them for both CSS sides at cap 13.

```bash
python3 research/exact_distance_180_pair/PUBLIC_REPLAY.py --all --threads 2 --timeout 600
```

The output includes `independent_status.json` and the original stdout/stderr of each of the eight external solver runs. `UNKNOWN_TIMEOUT`, errors, or an early stop do **not** certify the result. The supplied `PUBLIC_RESULTS.json` records the original Colab run and its SHA hashes, which can be compared against a fresh replay.

The public source programs report a complete exhaustive search only when they return the completed `RESULT` verdicts without a node-limit indication. Under the parameters above, the original eight runs reported `none`, exit code 0, with `Weff=13` (exactA) or `searched=13` (exactB). A separate Steane control in the runner checks that both tools reject weight `<=2` and find a logical at weight `<=3`.

**Important limit:** This report cross-checks two independent external implementations of *their* published proof method. The absence of a refutation alone is not sufficient; the proof relies on the validity of their documented exhaustive-search rules. No unpublished research software or source code is included or required.

Reported by Henryk Soboń; AI assisted with test orchestration, result parsing and packaging. The independent solvers' author retains credit for their implementations.
