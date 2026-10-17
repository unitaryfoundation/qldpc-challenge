# Replaying the randomized search

Build the optional accelerator with `make fast` in this repository and use the
repository's Python environment with NumPy. From the repository root:

```sh
python repro/117-13-6/replay_ris.py --output replay-117-13-6
```

The output directory must be new. Each recorded rung calls the unchanged
`surrogate.distance_rand_witness` API with `backend="fast"`, `threads=1`,
and `pair_depth=16`. It runs 1,000,000 trials on EACH CSS side. The two fresh
seeds total 2,000,000 trials per side, or 4,000,000 across both sides. The
returned reading is the minimum over the two sides, not a separate minimum
for each. Existing opposite-side witnesses remain independently checked.

`ris-ladder.json` records actual seeds, raw returned supports and weights,
CPU timings, source hashes and a digest of the exact check basis. The final
JSON has different provenance metadata and possibly a replaced witness; the
check-basis digest binds it to both actual runs. Raw supports are saved before
packaging, and replay writes schema-checked candidate documents using the
official save helper. Do not mix this count with the exhaustive distance proof
or any Pauli, doubling or fold-search budget.
