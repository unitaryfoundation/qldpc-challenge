"""Refuse a submission that another open PR already carries (issue #4107).

verify_all.py rejects two entries with the same stabilizer group, but only
within the tree it verifies. Two PRs that each add one presentation of the
same code pass alone: #4064 and #4069 added [[12,5,2]] twice, as an X/Z swap
of each other, and neither tree held both files. They merged in a burst of
42 merges four minutes apart, the push runs in between were collapsed by the
workflow's concurrency group, and the first run to see both files was the
one after the second merge. From then on every run on main failed with
IDENTICAL CODES until a removal PR landed (#4106), and unrelated PRs were
blocked meanwhile (issue #4103).

This runs on a code PR before the gate and compares the entries it adds or
changes with the entries every other open PR adds or changes, under the
identities verify_all.py files an entry under: the exact fingerprint (the
reduced row echelon forms of the check matrices, so the stabilizer group),
the fingerprints of its local-Hadamard images (its X/Z swap, for a connected
CSS code), and the Weisfeiler-Leman signature as the permutation flag. A
shared fingerprint is one code filed twice. The later PR, the higher number,
is the one refused, so exactly one of the pair can merge and the other waits
until the first has landed or been withdrawn; the earlier PR gets a warning
naming the later one. A shared WL signature alone is a warning on both, as it
is in verify_all.py. Two PRs that change the same codes/<slug>.json are one
entry edited twice, not a duplicate, and are not compared.

Against the board itself nothing is needed here: a pull_request run checks
out the merge of the PR with the base branch as of the run, so verify_all.py
sees the current board together with the PR's entries and refuses a copy of
anything already merged.

Needs `gh` (the GitHub CLI, on every hosted runner) with a token that can
list the repository's pull requests, and a checkout whose `origin` serves
refs/pull/<n>/head (the base repository holds every PR's head commits, forks
included). A listing that fails is reported as a warning and the check
passes: an API outage must not hold every submission, and the detector on
main still catches, after the fact, what this could not see. A single PR
whose files or head cannot be read is skipped with a note.

Usage:
  python verify/check_pr_duplicates.py --root PATH --base origin/main --repo OWNER/NAME --pr-number N
"""

import argparse
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)                       # trusted verify/ only
import qldpc_verify  # noqa: E402
from validate_candidate import _identity_sets as identity_sets  # noqa: E402

# Where the other PRs' heads are fetched to; removed again before exit.
_REF_PREFIX = "refs/pr-dup/"


def _run(cmd, cwd=None):
    """Return the stdout of `cmd`, raising CalledProcessError with its stderr on failure."""
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout


def is_entry(path):
    """Return whether a changed path is a board entry."""
    return path.startswith("codes/") and path.endswith(".json") and path.count("/") == 1


def changed_entries(root, base):
    """Return the codes/<slug>.json paths the PR adds or modifies relative to `base`.

    Three-dot, so only the PR's own side of the diff counts; a deletion carries
    no code to compare.
    """
    out = _run(["git", "diff", "--name-only", "--diff-filter=AM", f"{base}...HEAD", "--", "codes"],
               cwd=root)
    return [f for f in out.splitlines() if is_entry(f)]


def identities(doc):
    """Return the (fingerprints, signatures) a document is recognized under.

    The structural pass of the verifier, refutation off, read the way
    verify_all.py and validate_candidate.py read it: the entry's own
    fingerprint and WL hash plus those of its local-Hadamard images. An
    entry that does not get as far as a fingerprint yields empty sets.
    """
    rep = qldpc_verify.verify(doc, refute=False)
    return identity_sets(rep)


def open_prs(repo, exclude):
    """Return the other open PRs of `repo` as {number: {"author", "title"}}."""
    out = _run(["gh", "api", "--paginate", f"repos/{repo}/pulls?state=open&per_page=100",
                "--jq", ".[] | {number: .number, author: .user.login, title: .title}"])
    prs = {}
    for line in out.splitlines():
        if not line.strip():
            continue
        pr = json.loads(line)
        if pr["number"] != exclude:
            prs[pr["number"]] = {"author": pr["author"], "title": pr["title"]}
    return prs


def pr_entries(repo, number):
    """Return the codes/<slug>.json paths PR `number` adds or modifies."""
    out = _run(["gh", "api", "--paginate", f"repos/{repo}/pulls/{number}/files?per_page=100",
                "--jq", '.[] | select(.status != "removed") | .filename'])
    return [f for f in out.splitlines() if is_entry(f)]


def fetch_heads(root, numbers):
    """Fetch refs/pull/<n>/head of each PR into the checkout at `root`."""
    if numbers:
        specs = [f"+refs/pull/{n}/head:{_REF_PREFIX}{n}" for n in numbers]
        _run(["git", "fetch", "--quiet", "--no-tags", "origin", *specs], cwd=root)


def drop_heads(root, numbers):
    """Remove the refs fetch_heads created; never fails."""
    for n in numbers:
        subprocess.run(["git", "update-ref", "-d", f"{_REF_PREFIX}{n}"], cwd=root,
                       capture_output=True, check=False)


def pr_doc(root, number, path):
    """Return the parsed document at `path` in PR `number`'s fetched head."""
    return json.loads(_run(["git", "show", f"{_REF_PREFIX}{number}:{path}"], cwd=root))


def collisions(mine, others):
    """Compare the PR's entries with the other PRs' entries.

    `mine` maps codes/<slug>.json to (fingerprints, signatures); `others` is a
    list of (number, path, (fingerprints, signatures)). Returns one dict per
    pair that shares an identity: kind "identical" when a fingerprint is
    shared (the same stabilizer group, directly or through a local-Hadamard
    image), "possible" when only a WL signature is. The same path on both
    sides is one entry changed in two PRs and is skipped.
    """
    found = []
    for path, (fps, sigs) in sorted(mine.items()):
        for number, other_path, (ofps, osigs) in others:
            if other_path == path:
                continue
            if fps & ofps:
                kind = "identical"
            elif sigs & osigs:
                kind = "possible"
            else:
                continue
            found.append({"kind": kind, "path": path, "number": number, "other_path": other_path})
    return found


def verdict(found, pr_number, prs):
    """Return (exit code, lines to print) for the collisions found.

    An identical code in a lower-numbered open PR refuses this one (exit 1);
    an identical code in a higher-numbered PR, or a shared WL signature in
    either direction, is a warning. The lines carry GitHub's ::error:: and
    ::warning:: prefixes so they surface as annotations on the run.
    """
    lines, code = [], 0
    for c in sorted(found, key=lambda c: (c["kind"] != "identical", c["number"], c["path"])):
        who = prs.get(c["number"], {}).get("author", "?")
        where = f"open PR #{c['number']} by {who} as {c['other_path']}"
        if c["kind"] == "identical":
            what = (f"{c['path']} and {where} are one code (the same stabilizer group, directly "
                    f"or up to a local Hadamard relabeling)")
            if c["number"] < pr_number:
                code = 1
                lines.append(f"::error::{what}: one code, one entry (CONTRIBUTING.md); this PR is "
                             f"the later filing, so it waits until #{c['number']} has merged or "
                             f"been withdrawn, then re-run this check")
            else:
                lines.append(f"::warning::{what}; this PR is the earlier filing and may merge, "
                             f"#{c['number']} is held by this check")
        else:
            lines.append(f"::warning::{c['path']} shares a Weisfeiler-Leman signature with {where}: "
                         f"possibly the same code up to a qubit permutation, review before "
                         f"merging both")
    return code, lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=os.path.dirname(_HERE),
                    help="the submitted checkout (default: this repository)")
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"),
                    help="OWNER/NAME (default: $GITHUB_REPOSITORY)")
    ap.add_argument("--pr-number", type=int, required=True)
    args = ap.parse_args(argv)
    if not args.repo:
        print("--repo or GITHUB_REPOSITORY is required")
        return 2

    try:
        changed = changed_entries(args.root, args.base)
    except subprocess.CalledProcessError as e:
        print(f"could not diff vs {args.base}: {e.stderr.strip()}; failing closed")
        return 1
    if not changed:
        print("no board entry added or changed; nothing to compare")
        return 0
    mine = {}
    for path in changed:
        try:
            with open(os.path.join(args.root, path), encoding="utf-8") as f:
                mine[path] = identities(json.load(f))
        except Exception as e:                  # verify_all reports the entry's own defects
            print(f"note: {path} has no identity to compare ({type(e).__name__}: {e})")
    if not any(fps or sigs for fps, sigs in mine.values()):
        print("no entry of this PR carries an identity; nothing to compare")
        return 0

    try:
        prs = open_prs(args.repo, args.pr_number)
    except (subprocess.CalledProcessError, OSError, ValueError) as e:
        detail = getattr(e, "stderr", None) or str(e)
        print(f"::warning::could not list the open pull requests of {args.repo} "
              f"({str(detail).strip()}); duplicate check against open PRs skipped")
        return 0
    files = {}
    for number in sorted(prs):
        try:
            paths = pr_entries(args.repo, number)
        except subprocess.CalledProcessError as e:
            print(f"note: could not list the files of #{number} ({e.stderr.strip()}); skipped")
            continue
        if paths:
            files[number] = paths
    print(f"{len(prs)} other open PR(s), {len(files)} of them changing board entries")
    if not files:
        return 0
    try:
        fetch_heads(args.root, sorted(files))
    except subprocess.CalledProcessError as e:
        print(f"::warning::could not fetch the heads of the open PRs ({e.stderr.strip()}); "
              f"duplicate check against open PRs skipped")
        return 0
    others = []
    try:
        for number in sorted(files):
            for path in files[number]:
                try:
                    others.append((number, path, identities(pr_doc(args.root, number, path))))
                except Exception as e:
                    print(f"note: #{number} {path} has no identity to compare "
                          f"({type(e).__name__}: {e})")
    finally:
        drop_heads(args.root, sorted(files))

    code, lines = verdict(collisions(mine, others), args.pr_number, prs)
    for line in lines:
        print(line)
    if not lines:
        print(f"no entry of this PR matches an entry of the {len(files)} open PR(s) that change "
              f"board entries")
    return code


if __name__ == "__main__":
    sys.exit(main())
