"""Bind a submission to the person opening the PR.

Author handles in a code's provenance are self-reported, so without a check
anyone could submit a code under someone else's @handle. This asserts that the
GitHub user opening the PR is listed among the @handle authors of every code
they add or change. Literature baselines (no @handle authors) are exempt, and a
maintainer submitting on someone's behalf just adds themselves as a co-author.

Fails CLOSED only on a definite author/PR-author mismatch. Anything ambiguous
(no author info, git/parse error) fails OPEN with a warning -- a bug here must
not block legitimate contributions, since impersonation is lower-stakes than the
distance checks and is also caught in human review.

Usage:
  python verify/check_authorship.py --author <github-login> [--base origin/main]
  python verify/check_authorship.py --author <login> codes/a.json codes/b.json
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HANDLE = re.compile(r"^@([A-Za-z0-9-]+)$")


def changed_codes(base):
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", "--diff-filter=AM",
             f"{base}...HEAD", "--", "codes"],
            cwd=ROOT, text=True)
    except Exception as e:
        print(f"(could not diff vs {base}: {e}); skipping authorship check")
        return None
    return [f for f in out.split() if f.endswith(".json")]


def handles(doc):
    auth = (doc.get("provenance") or {}).get("authors") or []
    out = []
    for a in auth:
        m = HANDLE.match(str(a).strip())
        if m:
            out.append(m.group(1).lower())
    return out


def main(argv):
    author = None
    if "--author" in argv:
        i = argv.index("--author")
        author = argv[i + 1].lower().lstrip("@")
        argv = argv[:i] + argv[i + 2:]
    base = "origin/main"
    if "--base" in argv:
        i = argv.index("--base")
        base = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    if not author:
        print("no --author given; skipping authorship check")  # fail open
        return 0

    files = [a for a in argv if a.endswith(".json")]
    if not files:
        files = changed_codes(base)
    if files is None or not files:
        print("no added/changed code submissions to check")
        return 0

    violations = []
    for f in files:
        p = f if os.path.isabs(f) else os.path.join(ROOT, f)
        if not os.path.exists(p):
            continue
        try:
            doc = json.load(open(p))
        except Exception as e:
            print(f"(could not parse {f}: {e}); skipping it")  # fail open
            continue
        hs = handles(doc)
        if not hs:
            print(f"ok    {f}: no @handle authors (baseline/anonymous), exempt")
            continue
        if author in hs:
            print(f"ok    {f}: PR author @{author} is listed")
        else:
            violations.append((f, hs))

    if violations:
        print("\nAuthorship mismatch: the PR author must be one of a code's "
              "@handle authors.")
        for f, hs in violations:
            print(f"  {f}: authors {['@' + h for h in hs]} do not include "
                  f"@{author}")
        print("If you are submitting on someone's behalf, add yourself as a "
              "co-author, or have them open the PR.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
