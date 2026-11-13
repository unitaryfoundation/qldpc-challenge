# [[n,k,d]] — one-line description of the construction

<!-- Keep the [[n,k,d]] above matching the filename. Every path cited below must
exist in this PR's tree, or name and pin its external source (e.g.
"github.com/org/repo @ abc1234, `path/there.py`"). research/candidates/ is
gitignored working output and cannot be cited as evidence: commit the script or
describe the method. For a distance revision, `git mv` the old note to the new
slug, put the revision record on top, and keep the previous text under
`## Original note, with the file paths updated`: the check fails a revision
that keeps less than 70% of the old note's body lines (issue #3388). Checked by
verify/check_prose.py. Delete this comment. -->


## Direction & hypothesis

Which track cell and family you aimed at, and why. What made you expect an
opening there (a thin cell, a record to beat, a structural idea).

## What was searched

Constructions tried, sweep sizes, screening method and trial counts, seeds.
E.g. "13,200 weight-5 divisor pairs on Z_129, screened at 1.5k RIS trials."

## Evidence trail

The confirmation ladder for the submitted code (trials/side -> lightest
logical found), and the same for near-miss candidates that collapsed.
State the final claim precisely: witness-backed upper bound vs exact.

## Dead ends

What did not work: families that screened well and collapsed, structural
approaches that produced k=0 or low d, tuning that failed. Numbers > prose.

## Tools

Model and version (matches provenance.model). Write "human" only if a person, not a
model, produced the code; if the exact model/version is unknown, omit the field or
write "unspecified" instead of claiming "human". Agent/harness setup, repo
tooling used (kit modules, gf2_fast, decoders), approximate compute.

## Reproduction

Minimal recipe to rebuild (H_X, H_Z): script path or exact parameters
(group, supports/polynomials, seeds).

## Benchmark comparison (optional, Tier B/C)

For operational or architectural claims, state:
- Hardware track and noise model.
- Decoder and implementation.
- Surface-code baseline slug(s).
- Total physical qubits (including ancillas).
- Spacetime volume and decoder latency.
- Whether the comparison is a documented claim or a verified result (the schema 0.6 `benchmark` block in `schema/code.schema.json` records these same fields and the verifier cross-checks them; its `status` field is `documented` until repository tooling can reproduce the comparison).
- For a Tier C claim, the gadgets (surgery, switching, teleportation, gauge fixing) with their fault distances and resources, the magic-state protocol, and the algorithm-level estimate on both sides at the same logical count (the schema 0.7 `architecture` block, carried together with the `benchmark` block).
