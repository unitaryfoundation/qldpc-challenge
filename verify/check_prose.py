"""Check that a PR body and its research notes only point at things a reader can open.

The board's durable value is the evidence trail, and an evidence trail that cites
a file nobody else has is not one. Three habits recur in agent-written submissions
and this check refuses all three:

  * a repo-relative path that does not exist in the PR's own tree (local tooling
    named as if it were committed here);
  * `research/candidates/` and other gitignored working output offered as the
    audit trail -- it is deliberately never committed, so the citation cannot be
    resolved by anyone, ever;
  * an absolute local path (/Users/..., /tmp/...).

The escape hatch is the convention the good notes already use: name the source
and pin it, e.g. "taken from github.com/a7b/yarn @ 82fb695,
`processor_codes/mitten/[[300,60,14]]/Hx.npy`". A file that names an external
source is trusted to be citing that source, not this repo.

Also refuses leftover tool scaffolding (an unedited `qldpc submit` draft footer,
HTML comments, unticked checklist boxes), session URLs, and -- for a note named
`<n>-<k>-<d>.md` -- a missing or mismatched [[n,k,d]] header.

Only files CHANGED by the PR are checked. Notes already on the board are left
alone; this guards what arrives from here on.

Usage:
  python verify/check_prose.py [--root PATH] [--base origin/main]
                               [--body-file PATH] [--files a.md b.md]

The PR body is passed as a FILE, never as a command-line string: it is untrusted
input and must not reach a shell.
"""

import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Directories the repo deliberately does not commit. Citing one as evidence is
# unfalsifiable by construction -- AGENTS.md defines research/candidates/ as
# gitignored working output.
GITIGNORED = (
    "research/candidates/",
    "research/out/",
    "research/runs/",
    "build/",
    ".venv/",
    "__pycache__",
)

# Top-level directories that make a token repo-relative rather than incidental
# prose. Anything starting with one of these must resolve in the tree.
TOPDIRS = (
    "codes/", "notes/", "verify/", "research/", "site/", "schema/", "certs/",
    "docs/", "cli/", "decode/", "qldpc/", "talks/", "fieldnotes/", "tests/",
    ".github/",
)

FILE_EXT = (
    ".py", ".json", ".md", ".npz", ".npy", ".txt", ".csv", ".tex", ".yml",
    ".yaml", ".ipynb", ".sh", ".lean", ".log", ".pkl",
)

ABSOLUTE_LOCAL = re.compile(
    r"(?:^|[\s(`\"'])((?:/Users/|/home/|/tmp/|/private/tmp/|/var/folders/|~/|C:\\)[\w./\\~-]+)")

# A file may cite an external artifact if it says where that artifact lives.
EXTERNAL_MARKERS = re.compile(
    r"https?://|github\.com|gitlab\.com|zenodo|doi\.org|arxiv\.org/abs|"
    r"upstream repo|authors'? (?:own )?(?:published )?(?:repo|artifact)",
    re.I)

SESSION_URL = re.compile(r"claude\.ai/code/session[_/]|chatgpt\.com/c/", re.I)

SCAFFOLDING = (
    ("unedited `qldpc submit` draft footer",
     re.compile(r"edit before requesting review", re.I)),
    ("HTML comment left in the text", re.compile(r"<!--")),
    ("unticked checklist box", re.compile(r"^\s*[-*]\s*\[ \]", re.M)),
    ("TODO/FIXME placeholder", re.compile(r"\b(TODO|FIXME|TBD)\b")),
)

# Backticked span, or a bare slash-separated token.
TOKEN = re.compile(r"`([^`\n]+)`|(?<![\w/`])((?:\.{0,2}/)?[\w.\-]+(?:/[\w.\-]+)+)")

# arXiv-style identifiers look like paths (quant-ph/9601029) but are not.
ARXIV_ID = re.compile(r"^(quant-ph|math|cs|cond-mat|physics)/")

NKD = re.compile(r"\[\[\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]\]")
SLUG = re.compile(r"^(\d+)-(\d+)-(\d+)$")

# The note template is scaffolding by definition: it carries the placeholder
# header and the instruction comment that every real note must not.
EXEMPT = {"notes/TEMPLATE.md"}


def is_repo_pathish(tok):
    """True when a token claims to be a path inside THIS repo."""
    if not tok or " " in tok or tok.startswith(("http", "www.", "@", "#")):
        return False
    if ARXIV_ID.match(tok):
        return False
    if "<" in tok or ">" in tok or "*" in tok:      # placeholder or glob
        return False
    bare = tok.lstrip("./")
    if bare.startswith(TOPDIRS):
        return True
    return "/" in bare and bare.endswith(FILE_EXT)


def resolves(tok, root):
    """A token resolves if the path, or the module file behind a
    `module.function` / `file.py::symbol` reference, exists in the tree."""
    bare = tok.lstrip("./").rstrip("/")
    candidates = [bare]
    if "::" in bare:                                 # file.py::symbol
        candidates.append(bare.split("::", 1)[0])
    if not bare.endswith(FILE_EXT):                  # research/kit/mod.function
        head = bare.rsplit(".", 1)[0]
        candidates += [head, head + ".py", bare + ".py"]
    if any(os.path.exists(os.path.join(root, c)) for c in candidates):
        return True
    # An extensionless reference to a source file that is not .py: `verify/gf2_fast`
    # is the C++ accelerator, shipped as gf2_fast.cpp and a built .so.
    for c in candidates:
        d, base = os.path.split(os.path.join(root, c))
        if base and os.path.isdir(d):
            if any(f.startswith(base + ".") for f in os.listdir(d)):
                return True
    return False


def check_text(text, label, root, problems, is_note_slug=None):
    external_ok = bool(EXTERNAL_MARKERS.search(text))

    for m in ABSOLUTE_LOCAL.finditer(text):
        problems.append((label, "absolute local path", m.group(1)))

    if SESSION_URL.search(text):
        problems.append((label, "session URL", "links a private session"))

    for why, pat in SCAFFOLDING:
        if pat.search(text):
            problems.append((label, "leftover scaffolding", why))

    seen = set()
    for m in TOKEN.finditer(text):
        tok = (m.group(1) or m.group(2) or "").strip().rstrip(".,;:)`").lstrip("(")
        if not is_repo_pathish(tok) or tok in seen:
            continue
        seen.add(tok)
        bare = tok.lstrip("./")
        if any(g in bare for g in GITIGNORED):
            problems.append((label, "gitignored working output cited as evidence", tok))
        elif not resolves(tok, root) and not external_ok:
            problems.append((label, "path does not exist in this tree", tok))

    if is_note_slug:
        n, k, d = is_note_slug
        found = NKD.findall(text)
        if not found:
            problems.append((label, "note states no [[n,k,d]]",
                             f"expected [[{n},{k},{d}]]"))
        elif found[0] != (n, k, d):
            problems.append((label, "note's first [[n,k,d]] disagrees with its filename",
                             f"[[{','.join(found[0])}]] vs [[{n},{k},{d}]]"))


def changed_prose(base, root):
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", "--diff-filter=AMR", f"{base}...HEAD"],
            cwd=root, text=True)
    except Exception as e:
        print(f"could not diff vs {base}: {e}; failing closed")
        return None
    return [f for f in out.splitlines()
            if f.endswith(".md") and (f.startswith("notes/")
                                      or f.startswith("fieldnotes/"))]


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--body-file",
                    help="file holding the PR body (never pass the body inline)")
    ap.add_argument("--files", nargs="*",
                    help="explicit files to check instead of the diff")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)

    files = args.files
    if files is None:
        files = changed_prose(args.base, root)
        if files is None:
            return 1

    problems = []
    for rel in files:
        if rel in EXEMPT:
            continue
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()
        slug = None
        m = SLUG.match(os.path.basename(rel)[:-3])
        if m and rel.startswith("notes/"):
            slug = m.groups()
        check_text(text, rel, root, problems, is_note_slug=slug)

    if args.body_file and os.path.exists(args.body_file):
        with open(args.body_file, encoding="utf-8") as f:
            check_text(f.read(), "PR body", root, problems)

    if not problems:
        print(f"prose check ok ({len(files)} file(s) checked)")
        return 0

    print("Prose check failed: the text points at things a reviewer cannot open.\n")
    for label, why, detail in problems:
        print(f"  {label}: {why}\n    {detail}")
    print("\nFix by pointing at something that exists in this PR, or by naming the")
    print("external source and pinning it (e.g. 'github.com/org/repo @ abc1234,")
    print("`path/in/that/repo.py`'). research/candidates/ is gitignored working")
    print("output and can never be cited as evidence. See AGENTS.md, 'Writing the")
    print("submission'.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
