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
| `not_derived` | the index has not been run against this entry at all; general stabilizer entries stay here, since the checker decides CSS pairs only, and the tracking issue lists them apart |

## Coverage is a state, not an error

Regenerating needs the literature index, which is not shipped, so nobody
merging a code PR can reconcile the table. Requiring it to cover `codes/`
exactly therefore turned `main` red on the first code merge and blocked the
people least able to fix it (issue #2391).

So a board entry the index has not seen gets its own bucket, `not_derived`,
distinct from `no_match`. `--top-up` adds those rows and drops rows for
entries that have left the board; it needs neither the index nor pynauty.
Nobody runs it by hand: the `provenance-top-up` workflow runs it on `main`
every Monday and commits the result, and a code PR gets a warning annotation
from `verify.yml` with the number of entries the table has not seen
(advisory; nothing to do in the PR). `--residual` writes the list of
`not_derived` entries, which the same workflow keeps in a tracking issue,
because only an index run (`--from-matches` with `--covered`) clears it
(issue #4023).

`--check` hard-fails only on what is wrong: an unknown bucket, `literature`
with no evidence, or counts that disagree with the entries. Staleness is
reported loudly and exits 0.

## The board screen: what the repository can settle without the index

`board_screen.py` compares every CSS entry with the board's own reference
set, the 355 entries seeded from the literature (`provenance.origin:
baseline`) plus the entries the index already matched (bucket `literature`
above), using the two primitives the gate uses for dedup: the exact
fingerprint (`css_fingerprint` in `verify/qldpc_verify.py`, the reduced row
echelon forms of H_X and H_Z) and the Weisfeiler-Leman signature of the typed
Tanner graph (`signature`, invariant under qubit permutations). `board_screen.json`
is the record, one verdict per entry (issue #4024):

| verdict | meaning | what to do with it |
|---|---|---|
| `exact_match` | the fingerprint equals a reference entry's: the same stabilizer group on the same labels | the entry is that code |
| `review` | the WL signature equals a reference entry's and the fingerprint does not | a review item, not a verdict; each pair is listed, with the permutation audit's decision (`research/audits/permutation_audit-<date>.json`: `equivalent`, `inequivalent`, `gb_family_no`, `undecided`) where it has one |
| `distinct` | the WL signature matches no reference entry | not permutation-equivalent to any seeded or literature entry on this board; says nothing about codes the board does not carry |

Reference entries are screened against the rest of the reference set.
Stabilizer (non-CSS) entries are outside the screen, as they are outside the
derived table. `distinct` is a statement about the board, not a novelty claim,
and nothing here changes an entry's `novelty` value or any ranking; the
index-only backlog stays in `derived.json` as `not_derived`.

```
# rescreen the board (needs numpy, not the index) and validate the record
python research/provenance/board_screen.py run
python research/provenance/board_screen.py check
```

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

# reconcile coverage after codes/ changes (needs neither)
python research/derive_provenance.py --top-up

# list the entries only an index run can settle (the tracking-issue body)
python research/derive_provenance.py --residual body.md
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
