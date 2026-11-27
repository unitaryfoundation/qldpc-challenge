# RFC 0002: cross-PR reuse of completed refutation searches

Status: draft for maintainer design review (issue #7453). Tier 1 when
implemented: it changes what the gate reads before it searches, in
`verify/gate_changed.py`, `verify/refutation_cache.py`, and
`.github/workflows/verify.yml`. This document is Tier 0. RFC 0001 was the
circuit tier (issue #505), which is why this one is numbered 0002.

## The claim being examined

Issue #7453 proposes a content-addressed store of completed refutation
searches, keyed by the code's bytes and readable from any pull request, so
that a code the gate has already refuted is refused again without the search
being paid a second time. A cached refutation would be honored only after the
gate re-validates its witness. A clean result would never be trusted from a
cache. The motivation calls this the largest potential speedup for bulk
submission.

The second half of that design is already how the per-PR cache works, so the
question is what crossing the PR boundary adds, what it costs, and whether it
is the speedup the motivation says. One of the issue's bullets reads "a
cached 'no lighter logical' result is only honored after the gate re-validates
the witness". A no-lighter-logical result has no witness, so that bullet can
only mean a refutation, and the next bullet says so. This document takes the
rule to be the one the issue ends on: clean results never, refutations after
re-validation.

## What exists

What the gate already reuses, and under what rule:

1. The per-PR search cache (issue #2633, `verify/refutation_cache.py`). A
   pull request's runs restore a GitHub Actions cache under the prefix
   `gate-search-<PR>-`. The record is keyed by the sha256 of the candidate's
   bytes, the digest of the pinned validation closure
   (`verify/validator_manifest.json`), the deep flag, and whether the
   accelerator was built. Only a refutation is stored: the gate's verdict
   with `refuted` set and the `hits` (found weight and witness support per
   mechanism). On load, `gate_changed._revalidated_hits` re-checks every
   witness against the candidate's matrices on both sides and drops any that
   is not a lighter nontrivial logical than the claimed d. A record with no
   surviving witness leaves the search in front of the run, not behind it.
   The module's docstring states the threat model: a pull request run
   executes the pull request's own workflow and builds the submitted tree's
   accelerator before the gate fires, so anything a run writes is the
   contributor's to forge. A forged refutation either validates (and the
   claim really is overstated) or is discarded. A forged clean result would
   retire the search, so clean results are never stored. GitHub scopes the
   cache to the pull request's own ref, so the prefix cannot reach another
   pull request's entries (`verify.yml`, "restore completed searches").

2. The early-exit verdict cache (issue #2615). A passing run saves its
   receipts under the digest of the trees the gate reads, and a later run of
   the same pull request whose digest matches skips the gate. Also PR-scoped,
   and it carries a clean result precisely because it is scoped to the ref
   whose run produced it and keyed on the exact bytes.

3. Board dedup. `validate_candidate.py` refuses a candidate whose exact
   fingerprint (for a CSS code, `css_fingerprint`: a hash of the reduced row
   echelon forms of the X and Z check matrices H_X and H_Z) equals a board
   entry's, and flags a WL-signature match for the permutation audit. A code
   already on the board is never searched again.

The trusted precedent for a cross-run record is the circuit record (#5371):
written and read only by runs on main, restored only on pushes, never handed
to a pull request. Its trust comes from who writes it, not from what it
contains.

## Why a refutation can cross the boundary and a clean result cannot

A refutation is a witness: a set of qubit indices that the gate can check
against the candidate's matrices in milliseconds. Its truth does not depend
on who found it or when. The validation closure can change, the search budget
can change, the author can lie, and the witness still either is or is not a
lighter nontrivial logical of this code. That is why the per-PR cache does
not need to trust its writer, and it is why a cross-PR store does not need
to either: the reader re-validates, as `_revalidated_hits` does today, and a
planted record costs one failed validation and nothing else.

"Not refuted" carries no such fact. It says a search of some budget, with
some seeds, under some verifier, found nothing. A pull request run cannot
attest to its own budget or seeds, because it ran its own workflow file and
its own accelerator build before the gate, and nothing inside the run
distinguishes an honest log from a written one. GitHub's run history could
in principle attest that a specific trusted workflow produced a specific
receipt (the sketch mentioned in #2633), but no such attestation exists
today, and PR runs from forks have no secrets to sign with. The rule the
issue states, clean results never from cache, is therefore not a
conservatism to be relaxed later. It is the whole reason the cache is safe, and it bounds what
the proposal can buy.

## What the proposal can buy

A cross-PR refutation store makes one case cheaper: a code the gate has
already refuted arrives again, in another pull request, and is refused
without the search. It does not make any clean submission faster, because
clean results stay untrusted. The motivation's "largest potential
bulk-submission speedup" is therefore a speedup of refusals, not of
acceptances, and its size is the rate at which refuted codes are re-filed
without change.

The rate was measured on 2026-11-27 over every closed-unmerged pull request
of this repository (389, created 2026-06-26 to 2026-11-26), with the scripts
and the summary in `research/rfcs/0002-measurement/`. The method: take the
`codes/` paths each of those pull requests added, find every later pull
request (closed, open, or merged) that added the same path, and compare the
two files by blob and by the verifier's fingerprint, then read each pull
request's verify check.

| quantity | count |
|---|---|
| closed-unmerged pull requests that added a code | 332 |
| codes they added | 539 |
| of those codes, re-filed later with the same fingerprint | 197 (from 105 pull requests) |
| of those 105 first pull requests, verify had passed | 77 |
| of those 105, verify had failed | 24 |
| re-filings after a failed verify, at the same or a higher claim | 112 codes in 24 later pull requests |
| of those 112, byte-identical | 106 |
| of those 24 later pull requests, whose verify failed after more than five minutes | 4 |

Most re-filings follow a closure that was not a refutation: the first pull
request had passed verify and was closed as a superseded batch or a
duplicate, and the store has nothing to offer there. Of the 24 pull requests
that re-filed a code after a failed verify, 20 failed again inside three
minutes or passed, so no search was paid twice; the first failure had been a
cheap one (format, scope, a stale base), not a refutation. Every one of the
112 re-filings was by the author of the first pull request, and the
re-filing typically arrived within the hour, often before the first pull
request was closed.

The store would have short-circuited two searches, both on 2026-11-21: the
[[840,18,28]] and [[880,18,29]] claims refuted in pull requests 6934 and
6935 (weight-27 logicals, 66 and 72 minutes) were re-filed from the same
commits as pull requests 7151 and 7152, closed by their author within 90
seconds of opening, and the verify runs they had triggered went on to
refute the same claims again, 66 and 90 minutes. A third pair fits the
pattern in August (pull requests 444 and 463, the same [[432,8,58]] code at
the same claim, 27 and 28 minutes, both failed) but its logs have expired
and the refutation cannot be confirmed. The measured saving over four and a
half months is therefore about two and a half hours of runner time, in one
morning, for one author. The same two runs would have been stopped by a
workflow rule that cancels verify when its pull request closes, which is a
Tier 1 change to `verify.yml` of two lines and no trust decision, or by the
kit refusing to open a pull request for a commit whose verify run already
failed.

A re-filing of the same bytes after a refutation is a defect in the
submitter's loop (the claim should have been lowered, which changes the
bytes and the fingerprint), so the store speeds up a path that should be
rare, and the cheaper fix for that path is on the client side: `./qldpc
submit` already searches before it files. The gate's refusal of a refuted
code today costs one search, minutes for a
small code and over an hour for a frontier claim near n = 900, under the
verify job's cap of 130 minutes. The store turns that into seconds for the
repeat, which is the entire saving. Issue #2633 measured the same waste
inside one pull request, 293 minutes in a day spent re-gating byte-identical
code across retriggers, and the per-PR cache was the answer to that. The
cross-PR case is the same waste at a lower rate.

## Design

If the maintainers want the store, this design holds under the existing
trust model and adds the least to it.

Key. Not the code's bytes. Two files of the same code differ in indentation,
key order, provenance text, and the note the author edited after the
refutation, and none of that changes the code. Key the store by the
verifier's own exact-duplicate fingerprint, the `fingerprint` field of its
report (for a CSS code the hash of the reduced row echelon forms of H_X and
H_Z, for a stabilizer code the hash of the reduced symplectic matrix), with
`n` and `code_type`. It identifies the stabilizer group under the labeling
the file uses. A witness refutes every file with that fingerprint, because the
row spaces are the same and the witness is checked against them at read
time. A relabeled copy (a qubit permutation) has another fingerprint and is
not covered. That case belongs to the WL screen and the permutation audit
(#6186), and extending the store to it would mean permuting the witness,
which is a later step if the audit ever finds permuted re-filings. The
validation closure is not part of the key: a logical stays a logical across
verifier versions, and the record carries the head that found it for the
log, not for the decision.

Record. One record per fingerprint: the lightest witness known, its weight,
the side it was validated on, the head and seed of the run that found it,
and the pull request number. About 250 bytes. A heavier witness for the
same fingerprint never replaces a lighter one.

Where it lives. Committed to main as one JSON Lines file in a new
directory under `research/audits/`, read by the gate from the base branch's
checkout exactly as the entries under `codes/` are. A GitHub Actions cache
on the main ref would also be readable by pull request runs, but caches are
evicted after seven days of disuse, are not diffable, and leave no record
of what refused what. A committed file is an audit trail, which is what the
board's evidence rules ask for everywhere else. The file is not part of the
validator manifest: it is data the verifier reads, like an entry, and a
bad line costs one failed validation.

Who writes it. A workflow on main, weekly or on a schedule after
`refute-weekly.yml`, that reads the verification receipts pull request runs
upload (`verification-receipts-<PR>` artifacts, which already carry the
gate's verdict and its witnesses) and appends the refutations whose witness
re-validates against the refuted candidate's matrices, taken from the pull
request's head commit (`refs/pull/<N>/head` stays fetchable after the pull
request closes). The receipts are untrusted input, and that is fine: a
witness that does not validate is dropped at fold time, and one that does is
a fact. Writing from main keeps the file's history clean and lets a reviewer
see every addition in a diff.

How the gate uses it. Before the search, `gate_changed.py` computes the
candidate's fingerprint, looks it up, and runs `_revalidated_hits` on the
stored witness against the candidate. A surviving witness lighter than the
candidate's claimed d refutes it, printed as a reuse with the originating
pull request and head, and the search is skipped for that candidate. Anything
else leaves the gate exactly as it is. The per-PR cache stays for same-PR
pushes, which is a different case (byte-identical, same ref).

The Tier 0 half. `research/kit/dedup_oracle.py` indexes the board and the
open pull requests by fingerprint so a campaign does not stage a duplicate.
Reading the same store there refuses a known-refuted code before it is
staged, which is where a bulk submitter actually loses time: not in CI, but
in opening a pull request that will fail. This needs no gate change and no
trust decision, and it can ship first.

## Impact analysis for the Tier 1 half (AGENTS.md template)

1. Behavior change. On a code pull request, the gate consults a committed
   refutation store by fingerprint before searching, and refuses a candidate
   whose stored witness re-validates and is lighter than its claim without
   running the search. Every other candidate is handled as today.

2. Invariant or threshold affected. No search budget, seed count, trial
   count, or cap moves. The set of codes the board accepts is unchanged: a
   stored witness that validates is a refutation the search is meant to find,
   and a candidate the store refuses is one the gate would refuse with that
   witness in hand. One trusted input is added, the store file on the base
   branch, read like `codes/` and written only by a run on main from
   re-validated receipts.

3. Lighter alternative considered and rejected. Keying by bytes, as the
   issue proposes, misses every reformatted re-filing and is rejected for
   the fingerprint. A GitHub Actions cache on the main ref would work as
   storage and is rejected for eviction and for leaving no audit trail.
   Doing nothing is a real option: the recurrence measurement puts what
   the store would have saved at two runs in four and a half months, and the kit-side refusal (the Tier 0 half) takes
   most of that without touching `verify/`.

4. Who must approve. A code owner of `verify/` and `.github/workflows/`:
   @FarLab, @MathysRennela, or @vprusso, and not the author of the change.

## Questions for the maintainers

- Is the kit-side refusal enough? It stops the re-filing before CI, which is
  where the time is lost, and it leaves the gate untouched. Cancelling a
  verify run whose pull request has closed would have covered both measured
  cases on its own.
- If the gate half goes ahead, committed file or main-ref cache? This RFC
  argues for the file.
- Should the fold workflow comment on a refused pull request with the
  earlier refutation it reused, so the author sees which pull request
  already found the lighter logical?
