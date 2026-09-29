# Derived provenance

Which board entries reproduce a published code, and which were found here.

The board could not answer that. The declared fields do not support it: of
1,564 rendered entries, 1,280 carry `provenance.origin: submission` and 1,074
carry no `novelty` at all, while 556 of those cite a paper in their own
construction text. `submission` records the path an entry arrived by, not
where the code came from. `arXiv:2306.16400` alone appears in 326 construction
strings.

So the tag is computed. `iso_check.py` in this directory decides permutation equivalence
of the given generating sets using nauty's canonical form of the typed Tanner
graph, and re-verifies every hit by mapping row spaces with the recovered
qubit permutation. `derived.json` is that output, bucketed:

| bucket | meaning |
|---|---|
| `literature` | isomorphic to a published code, with source, reference, and the matched id |
| `parameters_only` | a published code shares its parameters but ships no matrices, so equivalence is undecided |
| `no_match` | nothing in the index matches |

## What `no_match` does not mean

It does not mean the code is new. Two different sparse generating sets of the
same stabilizer group can have non-isomorphic Tanner graphs, so a non-match is
"not found in this index", not "not published". Any count that reads
`no_match` as a novelty claim is overstating it.

## Why the source list is separate

`sources.json` says which index sources are published work. This matters
because the index also holds **this project's own deep-search output**, added
so internal duplicates get caught. A match against `deep_search_2026-09` means
a code was found here, and reporting it as literature would invert the claim
the whole tag exists to make. 33 such rows were present the first time this
ran.

A source that appears in the index but in neither list is reported and treated
as not-literature, so adding an index source can never silently promote board
entries.

## Regenerating

```
# 1. run the isomorphism check (needs pynauty, networkx, and the index)
LITERATURE_INDEX=/path/to/index python research/provenance/iso_check.py

# 2. bucket its output
python research/derive_provenance.py \
    --from-matches isomorphism_matches.csv \
    --from-params  param_matches.csv

# validate the committed table against codes/ (needs neither)
python research/derive_provenance.py --check
```

`iso_check.py` and `iso_common.py` are vendored from this project'"'"'s `novelty`
working repository so the method is reviewable here rather than taken on
trust. Only the algorithm is committed: the literature index it reads is about
1.3 GB of matrices, so it stays out of the repository and its location is
given by `LITERATURE_INDEX`. The board side reads `codes/` directly, so the
checker runs against any checkout.

The table is keyed by slug and lives here rather than inside each
`codes/*.json`, because a derived field written into a submission document
would drift from its derivation the moment the index grows.

Nothing here gates a submission. `verify/` is untouched; this only reports.
