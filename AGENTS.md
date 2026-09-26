# Agent guide

This repo is a public, automatically verified leaderboard for quantum LDPC (qLDPC) codes.
The `verify/` stack machine-checks submissions; `research/` is a starter kit for constructing
and searching for new codes.

## Choose the workflow before acting

There are two supported workflows. The user's publication authorization determines which one
applies:

### Contributor-driven submission

Use this when the user explicitly asks you to submit a code, prepare a PR, create a branch,
commit, push, or open a PR on their behalf. Follow `CONTRIBUTING.md`. After the candidate passes
the trusted validation gate, the agent may write the verified submission to `codes/` and use
`./qldpc submit ... --open-pr` to create the branch, commit, push, and PR.

### Unattended autoresearch

Use this when the task is to explore or search for candidates without human review or explicit
publication authorization. Follow `research/AUTORESEARCH.md`. Candidates stay in
`research/candidates/`; do not write to `codes/`, commit, or open a PR. Report staged survivors
for a human to review and promote.

If both documents are read, this section is the precedence rule: an explicit contributor-driven
submission request selects the first workflow; otherwise use unattended autoresearch.

## Doing autoresearch (finding new codes)

Start from **[`research/QUICKSTART.md`](research/QUICKSTART.md)**: the minimal loop and the
rules, on one page. **[`research/AUTORESEARCH.md`](research/AUTORESEARCH.md)** is the detailed
manual and the reference for the `research/` kit — load the section you need rather than the
whole file.

The two rules, here so they are never missed:

**No code is a "find" until `verify/validate_candidate.py` returns `passed: true` for it.**
Never write your own distance/quality check or edit anything under `verify/` (the trusted,
CI-hash-pinned stack). In unattended autoresearch, stage candidates for human review; the
contributor-driven workflow above is allowed to promote a validated candidate into `codes/`
and open a PR when the user explicitly authorized that submission.

**A found low-weight logical (witness) is the most expensive data we produce — never lose it.**
Persist every candidate through `research/kit/submit.make_submission` and then
`submit.save_submission(doc, "research/candidates/<n>-<k>-<d>.json")`, which embed the witness;
an ad-hoc `python -c` that calls a distance search and prints the result discards it. If a
search finds a valid logical but the save fails, that is a hard error — stop and report it.

## Writing the submission (the PR body and the note)

The board's durable value is the evidence trail, and an evidence trail that cites a file
nobody else has is not one. `verify/check_prose.py` enforces this on every changed
`notes/`/`fieldnotes/` file and on the PR body:

**Every path you name must resolve in the PR's own tree.** Before writing a path, verify it
against the submitted PR tree, not only the base checkout or your local workspace. A path
that exists only locally, in ignored staging output, or on the base branch must not be
presented as a committed artifact. If the artifact lives elsewhere, name the source and
pin it — "taken from github.com/a7b/yarn @ 82fb695,
`processor_codes/mitten/[[300,60,14]]/Hx.npy`" — or do not cite it. Never write "available
on request", and never point at a private checkout (`~/…`, `/Users/…`) or a machine name.

**`research/candidates/` is gitignored working output; it can never be the audit trail.**
It is the right place to *stage* a candidate (see above) and the wrong place to *cite*. If a
search script matters to the result, either commit it or describe the method in the note
so someone can rewrite it. Do not mention the staging directory in submission prose unless
you are explicitly explaining that it is forbidden as evidence; describe it as local staging
output instead.

Two more, same reason:

- What you claim in the body must match the file in the diff. A distance is `upper_bound`
  until a certificate says otherwise — do not call a witnessed bound "certified", and do
  not put a distance in the filename that the JSON does not support.
- Delete the drafting scaffolding before asking for review: the `qldpc submit` footer, HTML
  comments, unticked checklist boxes, session URLs. If a checklist box is not true, make it
  true or say why. The drafted body also carries parenthetical prompts (e.g. "(Name the
  track and the existing entry this beats…)"): replace each with real content. Then run
  `uv run python verify/check_prose.py --body-file <body.md> --files <changed .md files>`
  locally; it must exit 0 before you request review.

**Before pushing: run the worktree gate.** A passing local run of `check_prose.py` is not
sufficient — it validates paths against your working tree, where uncommitted files exist.
CI validates against the PR tree only, so citations to uncommitted files pass locally and
fail remotely. Before every `git push` of a submission branch, run:

```
verify/prepush_prose_check.sh <pr-body.md>
```

It re-runs the check inside a clean worktree of HEAD (committed content only), which fails
exactly when CI would. It must exit 0 before the push. Treat this as part of pushing, not
as an optional review step — the working-tree check proves nothing about what CI sees.

A note named `<n>-<k>-<d>.md` must state its own `[[n,k,d]]` first. Follow
`notes/TEMPLATE.md`; its sections are what a later searcher reads.

**Attribution is checked, not assumed.** A fieldnote ADDED by a PR must credit
the PR author's own GitHub handle in its frontmatter `author:` line — CI passes
`--pr-author` to `check_prose.py` and fails on a missing or mismatched handle
(the 2026-09-23 escalation-gate note shipped with someone else's handle; this
closes that hole). Locally, reproduce it with
`PR_AUTHOR=<your-login> verify/prepush_prose_check.sh <body.md>`. Modifying
someone else's existing note is exempt.

## Working on the repo itself

- `verify/` is the trust anchor and is hash-pinned in CI (`verify/check_validator_integrity.py`).
  Changing it is deliberate: re-pin with `--update` and get the diff reviewed.
- Submissions live in `codes/` (schema: `schema/code.schema.json`); the board/site is generated
  from them by `site/build.py`. See `CONTRIBUTING.md` and `TRACKS.md`.
