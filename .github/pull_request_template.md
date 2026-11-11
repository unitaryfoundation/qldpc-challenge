## Code submission

- Parameters: [[n, k, d]] =
- Tracks:
- Distance confidence: upper_bound / exact
- Surface-code parity bar (only when claiming `g >= 1`): 1 to 5, as listed in TRACKS.md under "Scalable families at surface-code parity"

### Checklist
- [ ] One JSON file under `codes/`, conforming to `schema/code.schema.json`
- [ ] Distance witness(es) included for each reported side
- [ ] `python verify/qldpc_verify.py codes/<file>.json` passes locally
- [ ] `python verify/check_codes_format.py --files codes/<file>.json` exits 0 (`--fix` rewrites the file)
- [ ] Construction and references filled in under `provenance`
- [ ] If this may be equivalent to an existing entry, noted in `provenance.notes`

### What frontier does this advance?
(Which track, and which existing entry does it beat or extend, and on which axis.)

<!-- Challenge operation: fill this in only if this PR is Tier 1 per `verify/check_submission_scope.py --classify`
(see `.github/CODEOWNERS` and AGENTS.md "Two tiers of change"). Delete this comment and the block
below if it does not apply, or uncomment and complete it if it does.

## Challenge operation

- Behaviour change:
- Invariant / threshold affected (old -> new):
- Lighter alternative considered and why rejected:
- Who must approve (named code owner):
-->
