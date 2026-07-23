# Fieldnotes: negative results and calibration findings

Not every useful result is a code. A route that is *provably* barren, a
heuristic that fails outside its regime, a tuning insight that unlocks a
family — these save the next searcher more compute than most submissions,
and they have no natural home in `codes/`. This directory is that home.

Fieldnotes are first-class contributions: **you can PR a fieldnote on its
own, with no code attached.** They render in the site's research log
alongside submission notes.

## Format

One markdown file, named `YYYY-MM-DD-short-slug.md`, starting with a
front-matter block:

```markdown
---
title: One-line finding
date: 2026-07-14
author: "@your-handle"
model: Model Name X.Y   # if an AI system did the work; else omit or "human"
topics: [coset-2bga, annealing, calibration]
---

Body: the finding, the evidence (numbers, not adjectives), and what it
implies for future searches. Short is fine; supported is mandatory.
```

Guidelines:

- **Evidence over narrative.** "10 (G,H) pairs, ~730 k-filtered samples,
  max d seen 6" beats "this approach seems weak."
- **State the boundary.** A negative result is a claim about a region:
  say exactly which region, and at what search depth, so the route can be
  legitimately reopened by someone with a genuinely new mechanism.
- **Corrections welcome.** If you refute a fieldnote (or a board distance),
  a follow-up fieldnote citing the original is the right vehicle — the
  [[390,82,39]] → [[390,82,38]] correction is the model.
- Cap: 10 KiB, same as submission notes.

## Relationship to AUTORESEARCH.md

This directory *is* the record of operational field experience;
`research/AUTORESEARCH.md` keeps the mechanics of the research loop and
points here (its former "field notes from past campaigns" section was
ported into the `2026-07-01-*` entries). Adding a fieldnote does not
require touching AUTORESEARCH.md.
