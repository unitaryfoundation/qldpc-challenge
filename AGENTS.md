# Agent guide

This repo is a public, automatically verified leaderboard for quantum LDPC (qLDPC) codes.
The `verify/` stack machine-checks submissions; `research/` is a starter kit for constructing
and searching for new codes.

## Doing autoresearch (finding new codes)

Read **[`research/AUTORESEARCH.md`](research/AUTORESEARCH.md)** and follow it. That is the
tool-agnostic operating manual for the research loop and the reference for the `research/` kit.

The one rule, up front so it is never missed:

**No code is a "find" until `verify/validate_candidate.py` returns `passed: true` for it.**
Never write your own distance/quality check; never edit anything under `verify/` (the trusted,
CI-hash-pinned stack); stage candidates for human review — never commit to `codes/` or open a PR.

A second rule, equally non-negotiable:

**A found low-weight logical (witness) is the most expensive data we produce — never lose it.**
Never run an ad-hoc `python -c` that calls a witness/distance search and only prints the result; that discards the data. Always persist the candidate through the kit's own path: call
`research/kit/submit.make_submission` (which computes and embeds the witness) and then `research/kit/submit.save_submission(doc, "research/candidates/<n>-<k>-<d>.json")`. 
The `research/candidates/` directory is gitignored working output, so writes there are safe and never pollute the board. If a search finds a valid logical but the save fails, that is a hard
error — stop and report it, do not just print.

## Writing the submission (the PR body and the note)

The board's durable value is the evidence trail, and an evidence trail that cites a file
nobody else has is not one. `verify/check_prose.py` enforces this on every changed
`notes/`/`fieldnotes/` file and on the PR body:

**Every path you name must resolve in the PR's own tree.** If the artifact lives somewhere
else, name the source and pin it — "taken from github.com/a7b/yarn @ 82fb695,
`processor_codes/mitten/[[300,60,14]]/Hx.npy`" — or do not cite it. Never write "available
on request", and never point at a private checkout (`~/…`, `/Users/…`) or a machine name.

**`research/candidates/` is gitignored working output; it can never be the audit trail.**
It is the right place to *stage* a candidate (see above) and the wrong place to *cite*. If
a search script matters to the result, either commit it or describe the method in the note
so someone can rewrite it.

Two more, same reason:

- What you claim in the body must match the file in the diff. A distance is `upper_bound`
  until a certificate says otherwise — do not call a witnessed bound "certified", and do
  not put a distance in the filename that the JSON does not support.
- Delete the drafting scaffolding before asking for review: the `qldpc submit` footer, HTML
  comments, unticked checklist boxes, session URLs. If a checklist box is not true, make it
  true or say why.

A note named `<n>-<k>-<d>.md` must state its own `[[n,k,d]]` first. Follow
`notes/TEMPLATE.md`; its sections are what a later searcher reads.

## Working on the repo itself

- `verify/` is the trust anchor and is hash-pinned in CI (`verify/check_validator_integrity.py`).
  Changing it is deliberate: re-pin with `--update` and get the diff reviewed.
- Submissions live in `codes/` (schema: `schema/code.schema.json`); the board/site is generated
  from them by `site/build.py`. See `CONTRIBUTING.md` and `TRACKS.md`.
