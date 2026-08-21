"""Guard the trust boundary for public code-submission PRs.

Code submissions are untrusted data. Verifier, schema, workflow, and site-builder
changes are trusted-code changes. A PR that changes both can otherwise submit a
code and weaken the code that validates it in the same diff.

Also enforces one NEW code per PR: the deep refutation gate spends ~10 minutes
per frontier code, so batched submissions would blow the CI budget or force a
shallower search per code.

Usage:
  python verify/check_submission_scope.py [--root PATH] [--base origin/main]
"""

import os
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


def changed_files(base, root):
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", "--diff-filter=AMR",
             f"{base}...HEAD"],
            cwd=root, text=True)
    except Exception as e:
        print(f"could not diff vs {base}: {e}; failing closed")
        return None
    return [f for f in out.splitlines() if f]


def added_files(base, root):
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", "--diff-filter=A",
             f"{base}...HEAD"],
            cwd=root, text=True)
    except Exception as e:
        print(f"could not diff vs {base}: {e}; failing closed")
        return None
    return [f for f in out.splitlines() if f]


def is_code_submission(path):
    return path.startswith("codes/") and path.endswith(".json")


def is_critical(path):
    return path in CRITICAL_FILES or any(path.startswith(p) for p in CRITICAL_PREFIXES)


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
    if files is None or added is None:
        return 1
    codes = [f for f in files if is_code_submission(f)]
    new_codes = [f for f in added if is_code_submission(f)]
    critical = [f for f in files if is_critical(f)]
    # One new code per PR: the deep refutation gate budgets ~10 min per code, so
    # a PR that batches submissions would either blow the CI budget or dilute the
    # per-code scrutiny. Corrections to existing entries are not capped.
    if len(new_codes) > 1:
        print("Submission PR adds more than one new code; submit one code per PR "
              "so each gets the full refutation budget.")
        print("\nNew code submissions:")
        for f in new_codes:
            print(f"  {f}")
        return 1
    if not codes or not critical:
        print("submission scope ok")
        return 0

    print("Submission PR changes both untrusted code data and verifier-critical files.")
    print("Split the PR, or have a maintainer review the trusted-code changes first.")
    print("\nCode submissions:")
    for f in codes:
        print(f"  {f}")
    print("\nVerifier-critical changes:")
    for f in critical:
        print(f"  {f}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
