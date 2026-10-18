"""Guard the trust boundary for public code-submission PRs.

Code submissions are untrusted data. Verifier, schema, workflow, and site-builder
changes are trusted-code changes. A PR that changes both can otherwise submit a
code and weaken the code that validates it in the same diff.

Also enforces one NEW code per PR: the deep refutation gate spends ~10 minutes
per frontier code, so batched submissions would blow the CI budget or force a
shallower search per code.

And the submission surface: a PR that changes code data may carry nothing
outside codes/, circuits/, notes/, fieldnotes/, repro/, and certs/. Session
scratch under research/ rode along on three submission PRs (issue #3414); it
flipped the workflow's codes-only fast path into the full self-test suite and
failed them on defects unrelated to the entry. A builder a note cites goes in
its own PR first, so the citation resolves.

Under repro/ the surface is one file per entry: repro/<slug>.json, the manifest
`qldpc reproduce` and the reproduce workflow read, for an entry the PR itself
changes. Two submission PRs put their whole working tree under repro/<slug>/
instead, 40-odd files of compile receipts, captured stdout and stderr, and
exported columns (issue #3810); the directory was admitted as a whole, so
nothing refused them. A removal under repro/ is never refused, so an entry can
leave with its evidence.

Usage:
  python verify/check_submission_scope.py [--root PATH] [--base origin/main]
"""

import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CRITICAL_PREFIXES = (
    ".github/workflows/",
    "decode/",
    "schema/",
    "verify/",
)
CRITICAL_FILES = {
    "Makefile",         # builds the optional refutation accelerator
    "site/build.py",
    "pyproject.toml",
    "uv.lock",
    "run_tests.py",     # executes the self-tests CI relies on
}
# Everything a submission PR may carry: the entry, its circuit tier, its note or
# fieldnote, its repro manifest, its certificate. docs/ is rebuilt by site.yml,
# never by a contributor, and research/ changes are reviewed as code in their
# own PR (issue #3414).
SUBMISSION_SURFACE = ("codes/", "circuits/", "notes/", "fieldnotes/", "repro/", "certs/")
# Under repro/ a submission carries the manifest of its own entry and nothing
# else (issue #3810): qldpc reproduce and the reproduce workflow read
# repro/<slug>.json, and nothing reads a directory under repro/.
REPRO_MANIFEST = re.compile(r"^repro/([^/]+)\.json$")


def _diff_names(diff_filter, base, root):
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", f"--diff-filter={diff_filter}",
             f"{base}...HEAD"],
            cwd=root, text=True)
    except Exception as e:
        print(f"could not diff vs {base}: {e}; failing closed")
        return None
    return [f for f in out.splitlines() if f]


def changed_files(base, root):
    """Every code path the PR touches, deletions included.

    `D` is in the filter because removing an entry is a change to the board
    that a PR touching the verifier should not be able to make unreviewed.
    Without it, the rule had a shape-specific hole: tighten a rule in
    `verify/` and delete the entries the new rule would reject, in one diff,
    and neither this check nor the workflow step that decides to run it saw
    any code data at all (issue #2638).
    """
    return _diff_names("AMRD", base, root)


def added_files(base, root):
    """Only genuinely new codes, for the one-new-code-per-PR cap.

    Deliberately still `A` alone: the cap exists to keep each new submission
    inside the deep refutation budget, and a deletion consumes none of it.
    """
    return _diff_names("A", base, root)


def deleted_files(base, root):
    """Return the paths the PR removes; a removal under repro/ is never refused."""
    return _diff_names("D", base, root)


def is_code_submission(path):
    """Return whether path is untrusted code data.

    A board entry, or its circuit-tier artifacts under circuits/<slug>/ (the
    claim surface PR #1012 binds to the entry).
    """
    return ((path.startswith("codes/") and path.endswith(".json"))
            or (path.startswith("circuits/") and path.count("/") >= 2))


def submission_slug(path):
    """Return the board entry a code-data path belongs to.

    codes/<slug>.json and every file under circuits/<slug>/ are one submission,
    so a first circuit tier (four artifacts) counts as one new code, not four.
    """
    if path.startswith("codes/"):
        return os.path.splitext(os.path.basename(path))[0]
    return path.split("/")[1]


def is_critical(path):
    return path in CRITICAL_FILES or any(path.startswith(p) for p in CRITICAL_PREFIXES)


def outside_surface(files):
    """Return the changed paths a submission PR may not carry."""
    return [f for f in files if not f.startswith(SUBMISSION_SURFACE)]


def misplaced_repro(files, slugs, deleted=()):
    """Return the repro/ paths a submission PR may not add or change.

    `slugs` are the entries whose code data the PR changes. A path under
    repro/ passes only as repro/<slug>.json for one of them. A file in a
    directory under repro/ (run output, receipts, scripts, exported matrices)
    or a manifest for some other entry is returned. A deletion passes:
    removing an evidence directory along with its entry is the cleanup this
    rule asks for.
    """
    bad = []
    for f in files:
        if not f.startswith("repro/") or f in deleted:
            continue
        m = REPRO_MANIFEST.match(f)
        if m is None or m.group(1) not in slugs:
            bad.append(f)
    return bad


def main(argv):
    root = ROOT
    if "--root" in argv:
        i = argv.index("--root")
        root = os.path.abspath(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    base = "origin/main"
    if "--base" in argv:
        i = argv.index("--base")
        base = argv[i + 1]

    files = changed_files(base, root)
    added = added_files(base, root)
    deleted = deleted_files(base, root)
    if files is None or added is None or deleted is None:
        return 1
    codes = [f for f in files if is_code_submission(f)]
    new_codes = [f for f in added if is_code_submission(f)]
    new_slugs = sorted({submission_slug(f) for f in new_codes})
    critical = [f for f in files if is_critical(f)]
    # One new code per PR: the deep refutation gate budgets ~10 min per code, so
    # a PR that batches submissions would either blow the CI budget or dilute the
    # per-code scrutiny. Corrections to existing entries are not capped.
    if len(new_slugs) > 1:
        print("Submission PR adds more than one new code; submit one code per PR "
              "so each gets the full refutation budget.")
        print("\nNew code submissions:")
        for f in new_codes:
            print(f"  {f}")
        return 1
    if not codes:
        print("submission scope ok")
        return 0
    if critical:
        print("Submission PR changes both untrusted code data and verifier-critical files.")
        print("Split the PR, or have a maintainer review the trusted-code changes first.")
        print("\nCode submissions:")
        for f in codes:
            print(f"  {f}")
        print("\nVerifier-critical changes:")
        for f in critical:
            print(f"  {f}")
        return 1
    outside = outside_surface(files)
    if outside:
        print("Submission PR carries paths outside the submission surface.")
        print("A submission PR adds the entry under codes/ plus its own notes/ file, fieldnote,")
        print("repro/ manifest, or certs/ certificate, and nothing else. A script or evidence")
        print("file under research/ goes in its own PR first, so the note can cite it.")
        print("\nOutside the surface:")
        for f in outside:
            print(f"  {f}")
        return 1
    misplaced = misplaced_repro(files, {submission_slug(f) for f in codes},
                                set(deleted))
    if misplaced:
        print("Submission PR carries files under repro/ that are not its entry's manifest.")
        print("repro/ holds one file per entry, repro/<slug>.json, the manifest that")
        print("`qldpc reproduce` reads. Run output, receipts, scripts, and exported matrices")
        print("do not go in the tree: describe the method in the note, or commit a builder")
        print("under research/ in its own PR first, so the note can cite it.")
        print("\nNot a manifest of this PR's entry:")
        for f in misplaced:
            print(f"  {f}")
        return 1
    print("submission scope ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
