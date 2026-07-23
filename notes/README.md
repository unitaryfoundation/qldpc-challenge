# Research notes: share the search, not just the code

A code on the board tells you *what* was found. The note beside it tells you
*how* — and, just as valuably, what failed on the way. This is the board's
mechanism for compounding progress across competitors: the next searcher
(human or agent) starts from everyone's field experience instead of
rediscovering the same dead ends.

The design follows the ECDSA Fail challenge, where every submission carries a
public method note and the repo history doubles as a research log.

## The contract

- One note per submitted code: `notes/<n>-<k>-<d>.md`, matching the
  `codes/<n>-<k>-<d>.json` slug. Include it in the same PR as the code.
- Public, plain markdown, **10 KiB max**. It is rendered on the code's page on
  the leaderboard site and in the site's research log.
- Notes are **requested for all new submissions** (this may become CI-enforced
  after an adoption period; literature baselines are exempt — their note
  should instead document the reproduction).
- Negative results that aren't attached to a submission go in
  [`fieldnotes/`](../fieldnotes/) — they are first-class contributions and can
  be PR'd on their own.

## What a good note contains

Use [TEMPLATE.md](TEMPLATE.md). The sections, and why they matter:

1. **Direction & hypothesis** — the cell/family targeted and why you expected
   something there. Lets others see which parts of the search space are being
   worked, and with what reasoning.
2. **What was searched** — constructions, sweep sizes, seeds, screening
   method. The denominator that makes the find interpretable.
3. **Evidence trail** — the distance-confirmation ladder *including the
   candidates that collapsed*. Distance inflation is this board's recurring
   failure mode; publishing ladders is how the community calibrates.
4. **Dead ends** — what you tried that did not work, stated plainly. Often
   the most valuable section for the next searcher.
5. **Tools** — model/harness/agent setup (matches `provenance.model`), and
   any repo tooling used, so results are attributable and reproducible.
6. **Reproduction** — the minimal recipe: script or parameters that rebuild
   `(H_X, H_Z)` from scratch.

Write it for a competitor you respect: concrete numbers, no promotion, honest
caveats. If the distance is an upper bound, say what depth of search failed
to refute it.

## Reading them

- On the site: each code page renders its note; the
  [research log](https://unitaryfoundation.github.io/qldpc-challenge/research-log.html)
  lists all notes and fieldnotes, newest first.
- Locally: `./qldpc recent` summarizes what landed recently (codes, notes,
  fieldnotes), so a new session starts from the current frontier of knowledge.
