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

## Challenge operation (fill this in only if this PR touches verify/, .github/, schema/, decode/, Makefile, pyproject.toml, uv.lock, run_tests.py, site/build.py, or verify/validator_manifest.json)

- Behaviour change:
- Invariant / threshold affected (old -> new):
- Lighter alternative considered and why rejected:
- Who must approve (named code owner):
- What the agent did not do (if an agent assisted):
