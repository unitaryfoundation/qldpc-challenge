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

When `--pr-author` is given (CI always passes it), every fieldnote ADDED by the
PR must credit the PR author's handle in its frontmatter `author:` line. The
2026-09-23 escalation-gate note shipped with someone else's handle because
nothing checked attribution; this closes that hole. Modified files are exempt
(fixing a typo in someone else's note is fine); a missing author line fails.

A distance revision moves `notes/<n>-<k>-<old d>.md` to the new slug, and the
convention that keeps the record intact is to paste the previous note under a
`## Original note, with the file paths updated` heading beneath the revision
record. 42 of the first 186 revisions deleted the old note and wrote a fresh one
instead, and four of those lost most of the search narrative (#3388). So when
the PR changes a `codes/` or `notes/` slug's d, the old note's body lines must
still be found, slug-normalized, in the new note or in a fieldnote the PR
touches: at least 70% of them, or the check fails and names the two ways out
(fold the old note forward, or reclassify its narrative into `fieldnotes/`).
Whether git saw a rename is reported but not judged: a fold-in that more than
doubles the note can fall under git's similarity threshold and still keep
every line.

Only files CHANGED by the PR are checked. Notes already on the board are left
alone; this guards what arrives from here on. `--all` sweeps every committed
notes/ and fieldnotes/ file instead: the weekly prose-sweep workflow runs it and
keeps a tracking issue of what no longer resolves (#3379). `--report PATH`
writes the problems as markdown grouped by target, for that issue.

Usage:
  python verify/check_prose.py [--root PATH] [--base origin/main]
                               [--body-file PATH] [--files a.md b.md]
                               [--all] [--report PATH]

The PR body is passed as a FILE, never as a command-line string: it is untrusted
input and must not reach a shell.
"""

import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Label for problems that came from the PR description rather than a committed
# file. Named once because the reporter prints it and the closing hint tests for
# it: a body problem is fixed by editing the PR, not by touching the tree.
BODY_LABEL = "PR body"

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

# Raw run logs are gitignored by *.log, so a note quoting a trial count or a
# ladder trace out of one is citing a file no reviewer has. The way out is the
# run manifest written by research/kit/campaign.py, which promotes the lines a
# claim rests on into a committed file; this is called out separately from the
# directories above because the fix is different.
LOG_SUFFIXES = (".log",)

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

# Frontmatter of a fieldnote: the block between the opening and closing `---`.
FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
# `author: "@handle"` (quotes and @ optional). GitHub logins are case-insensitive.
AUTHOR_LINE = re.compile(
    r"^author:\s*[\"']?@?([A-Za-z0-9][A-Za-z0-9-]*)[\"']?\s*$", re.M)

# The note template is scaffolding by definition: it carries the placeholder
# header and the instruction comment that every real note must not.
EXEMPT = {"notes/TEMPLATE.md"}

# The heading under which a distance revision carries the note it replaces.
# The check measures what survives rather than looking for the heading, so a
# narrative moved to fieldnotes/ (as #3053 did) passes too.
FOLD_IN_HEADING = "## Original note, with the file paths updated"
RETENTION_MIN = 0.70

# n, k, d, and the optional disambiguating suffix (`-b`, `-s`) of a slug.
CODE_PATH = re.compile(r"^codes/(\d+)-(\d+)-(\d+)((?:-[a-z0-9]+)?)\.json$")
NOTE_PATH = re.compile(r"^notes/(\d+)-(\d+)-(\d+)((?:-[a-z0-9]+)?)\.md$")
# A slug anywhere in prose: n and k are kept, d is dropped, so updating the
# file paths inside a folded-in note does not count against it.
SLUG_IN_TEXT = re.compile(r"\b(\d+)-(\d+)-\d+\b")
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)


def strip_rel_prefix(tok):
    """Remove a leading './' only.

    NOT lstrip('./'): that eats every leading dot, so a legitimate
    dot-directory path like `.github/workflows/prose.yml` became 'github/...'
    and could never resolve.
    """
    return tok[2:] if tok.startswith("./") else tok


def is_repo_pathish(tok):
    """True when a token claims to be a path inside THIS repo."""
    if not tok or " " in tok or tok.startswith(("http", "www.", "@", "#")):
        return False
    if ARXIV_ID.match(tok):
        return False
    if "<" in tok or ">" in tok or "*" in tok:      # placeholder or glob
        return False
    bare = strip_rel_prefix(tok)
    if bare.startswith(TOPDIRS):
        return True
    return "/" in bare and bare.endswith(FILE_EXT)


def resolves(tok, root, near=None):
    """A token resolves if the path, or the module file behind a
    `module.function` / `file.py::symbol` reference, exists in the tree.

    `near` is the directory the text itself lives in, and a token is tried
    there as well as at the repository root. A markdown link is relative to
    its own file, so `research/AUTORESEARCH.md` writing `campaigns/README.md`
    is correct and opens for a reader on GitHub; resolving only from the root
    reported those as missing. The guarantee is unchanged, since a path
    relative to the containing file is one a reader can open.
    """
    bare = strip_rel_prefix(tok).rstrip("/")
    candidates = [bare]
    if "::" in bare:                                 # file.py::symbol
        candidates.append(bare.split("::", 1)[0])
    if not bare.endswith(FILE_EXT):                  # research/kit/mod.function
        head = bare.rsplit(".", 1)[0]
        candidates += [head, head + ".py", bare + ".py"]
    bases = [root] if near is None else [root, os.path.join(root, near)]
    if any(os.path.exists(os.path.join(b, c))
           for b in bases for c in candidates):
        return True
    # An extensionless reference to a source file that is not .py: `verify/gf2_fast`
    # is the C++ accelerator, shipped as gf2_fast.cpp and a built .so.
    for b, c in ((b, c) for b in bases for c in candidates):
        d, base = os.path.split(os.path.join(b, c))
        if base and os.path.isdir(d):
            if any(f.startswith(base + ".") for f in os.listdir(d)):
                return True
    return False


def check_text(text, label, root, problems, is_note_slug=None,
               near=None):
    external_ok = bool(EXTERNAL_MARKERS.search(text))
    # One line per distinct problem: a path repeated through a note should be
    # reported once, and never under two headings at the same time.
    def add(why, detail):
        if (label, why, detail) not in problems:
            problems.append((label, why, detail))

    absolute = set()
    for m in ABSOLUTE_LOCAL.finditer(text):
        absolute.add(m.group(1))
        add("absolute local path", m.group(1))

    if SESSION_URL.search(text):
        add("session URL", "links a private session")

    for why, pat in SCAFFOLDING:
        if pat.search(text):
            add("leftover scaffolding", why)

    seen = set()
    for m in TOKEN.finditer(text):
        span = (m.group(1) or m.group(2) or "").strip()
        # A backticked command names its files one word at a time:
        # `python verify/coordination.py gate x.json` claims verify/coordination.py.
        toks = [span]
        if m.group(1) and " " in span:
            toks += [w for w in span.split() if strip_rel_prefix(w).startswith(TOPDIRS)]
        for raw in toks:
            # `file.py::func(args)` names file.py; the call is not part of the path.
            tok = raw.strip().rstrip(".,;:)`").lstrip("(").split("(", 1)[0]
            if not is_repo_pathish(tok) or tok in seen or tok in absolute:
                continue
            seen.add(tok)
            bare = strip_rel_prefix(tok)
            # A file under one of this repo's top-level directories claims this
            # repo, so an external source named elsewhere in the text does not
            # excuse it (#3379: ten notes cited research/kit/clp.py beside an
            # arXiv link and passed). An external artifact that happens to sit
            # under a codes/ or research/ of its own repo keeps the excuse as
            # long as it does not carry one of this repo's file extensions.
            claims_this_repo = bare.startswith(TOPDIRS) and bare.endswith(FILE_EXT)
            if any(g in bare for g in GITIGNORED):
                add("gitignored working output cited as evidence", tok)
            elif bare.endswith(LOG_SUFFIXES) and not resolves(tok, root, near):
                add("raw run log cited as evidence (*.log is gitignored; promote "
                    "the lines the claim rests on into a run manifest)", tok)
            elif not resolves(tok, root, near) and (claims_this_repo or not external_ok):
                add("path does not exist in this tree", tok)

    if is_note_slug:
        n, k, d = is_note_slug
        found = NKD.findall(text)
        if not found:
            add("note states no [[n,k,d]]", f"expected [[{n},{k},{d}]]")
        elif found[0] != (n, k, d):
            add("note's first [[n,k,d]] disagrees with its filename",
                f"[[{','.join(found[0])}]] vs [[{n},{k},{d}]]")


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


def all_prose(root):
    """Every committed notes/*.md and fieldnotes/*.md, or None if git failed."""
    try:
        out = subprocess.check_output(
            ["git", "ls-files", "--", "notes", "fieldnotes"], cwd=root, text=True)
    except Exception as e:
        print(f"could not list committed prose: {e}; failing closed")
        return None
    return [f for f in out.splitlines() if f.endswith(".md")]


def write_report(problems, nfiles, path):
    """Write the problems as markdown grouped by (kind, target), largest group first."""
    groups = {}
    for label, why, detail in problems:
        groups.setdefault((why, detail), set()).add(label)
    nbad = len({label for label, _, _ in problems})
    lines = [f"`verify/check_prose.py --all` over {nfiles} committed notes and fieldnotes: "
             f"{len(problems)} problem(s) in {nbad} file(s).", ""]
    for (why, detail), labels in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        names = ", ".join(f"`{label}`" for label in sorted(labels))
        lines.append(f"- {why}: `{detail}` in {len(labels)} file(s): {names}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def added_fieldnotes(base, root):
    """Fieldnotes ADDED (not modified) by this PR, or None if git failed."""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", "--diff-filter=A", f"{base}...HEAD",
             "--", "fieldnotes/"],
            cwd=root, text=True)
    except Exception as e:
        print(f"could not diff vs {base}: {e}; failing closed")
        return None
    return [f for f in out.splitlines() if f.endswith(".md")]


def check_fieldnote_author(rel, text, pr_author, problems):
    """A newly added fieldnote must credit the PR author's own handle."""
    fm = FRONTMATTER.match(text)
    if not fm:
        problems.append((rel, "fieldnote has no frontmatter",
                         "cannot verify the author line"))
        return
    am = AUTHOR_LINE.search(fm.group(1))
    if not am:
        problems.append((rel, "fieldnote frontmatter states no author",
                         f'expected author: "@{pr_author}"'))
    elif am.group(1).lower() != pr_author.lower():
        problems.append((rel, "fieldnote author does not match the PR author",
                         f"note credits @{am.group(1)} but the PR is by "
                         f"@{pr_author}"))


def body_lines(text):
    """Return the prose lines of a note, normalized for comparison across a revision.

    Headings, table rows, fenced blocks, HTML comments, and blank lines are
    dropped. A slug or [[n,k,d]] keeps n and k and loses d, and runs of
    whitespace collapse, so a fold-in that only updated paths matches line
    for line.
    """
    lines = set()
    fenced = False
    for raw in HTML_COMMENT.sub("", text).splitlines():
        line = raw.strip()
        if line.startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced or not line or line.startswith(("#", "|")):
            continue
        line = NKD.sub(lambda m: f"[[{m.group(1)},{m.group(2)},d]]", line)
        line = SLUG_IN_TEXT.sub(r"\1-\2-d", line)
        lines.add(re.sub(r"\s+", " ", line))
    return lines


def retention(old_text, new_text):
    """Return the fraction of the old note's body lines present in the new text.

    1.0 when the old note had no body to lose.
    """
    old = body_lines(old_text)
    if not old:
        return 1.0
    return len(old & body_lines(new_text)) / len(old)


def slug_into(path, table):
    """Record a codes/ or notes/ slug as (n, k, suffix) -> {d}; other paths are ignored."""
    m = CODE_PATH.match(path) or NOTE_PATH.match(path)
    if m:
        table.setdefault(m.group(1, 2, 4), set()).add(m.group(3))


def slug_changes(base, root):
    """Return the distance revisions in the diff vs `base`.

    A dict old-slug -> new-slug for every codes/ or notes/ file whose n and k
    stayed and whose d changed, whether git saw a rename or a delete beside
    an add; the set of old-note paths git did report as renames; and the
    fieldnotes the PR adds or modifies. None if git failed.
    """
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-status", "-M", f"{base}...HEAD",
             "--", "codes/", "notes/", "fieldnotes/"],
            cwd=root, text=True)
    except Exception as e:
        print(f"could not diff vs {base}: {e}")
        return None
    gone, came, renamed_notes, fieldnotes = {}, {}, set(), []
    for row in out.splitlines():
        parts = row.split("\t")
        status, paths = parts[0][0], parts[1:]
        if paths[-1].startswith("fieldnotes/"):
            if status in "AMR":
                fieldnotes.append(paths[-1])
            continue
        if status in "DR":
            slug_into(paths[0], gone)
        if status in "AR":
            slug_into(paths[-1], came)
        if status == "R" and NOTE_PATH.match(paths[0]):
            renamed_notes.add(paths[0])
    events = {}
    for (n, k, suffix), old_ds in gone.items():
        for old_d in old_ds:
            for new_d in came.get((n, k, suffix), ()):
                if new_d != old_d:
                    events[f"{n}-{k}-{old_d}{suffix}"] = f"{n}-{k}-{new_d}{suffix}"
    return events, renamed_notes, fieldnotes


def check_revisions(base, root, problems):
    """Fail a distance revision that drops the previous note's body (#3388).

    For every slug whose d the PR changed, the old note as it stood at `base`
    is compared with the new note plus every fieldnote the PR touches. Returns
    False only if git could not produce the diff.
    """
    found = slug_changes(base, root)
    if found is None:
        return False
    events, renamed_notes, fieldnotes = found
    carried = ""
    for rel in fieldnotes:
        path = os.path.join(root, rel)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                carried += f.read() + "\n"
    for old_slug, new_slug in sorted(events.items()):
        old_note, new_note = f"notes/{old_slug}.md", f"notes/{new_slug}.md"
        if os.path.exists(os.path.join(root, old_note)):
            continue                                    # note not touched
        try:
            old_text = subprocess.check_output(
                ["git", "show", f"{base}:{old_note}"], cwd=root, text=True,
                stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            continue                                    # no note to lose
        new_text = ""
        if os.path.exists(os.path.join(root, new_note)):
            with open(os.path.join(root, new_note), encoding="utf-8") as f:
                new_text = f.read()
        kept = retention(old_text, new_text + "\n" + carried)
        if kept >= RETENTION_MIN:
            continue
        how = ("git saw a rename" if old_note in renamed_notes
               else "git saw a delete beside an add, not a rename")
        where = new_note if new_text else "no note under the new slug"
        problems.append((
            new_note if new_text else old_note,
            "distance revision drops the previous note's body",
            f"{old_note} -> {where}: {kept:.0%} of its body lines survive "
            f"(minimum {RETENTION_MIN:.0%}); {how}"))
    return True


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--body-file",
                    help="file holding the PR body (never pass the body inline)")
    ap.add_argument("--files", nargs="*",
                    help="explicit files to check instead of the diff")
    ap.add_argument("--pr-author",
                    help="GitHub login of the PR author; every fieldnote added "
                         "by the PR must credit this handle (CI passes it; "
                         "local runs without it skip the attribution check)")
    ap.add_argument("--all", action="store_true",
                    help="check every committed notes/ and fieldnotes/ file instead of the diff")
    ap.add_argument("--report", help="write the problems as grouped markdown to this file")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)

    files = args.files
    if files is None:
        files = all_prose(root) if args.all else changed_prose(args.base, root)
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
        check_text(text, rel, root, problems, is_note_slug=slug,
                   near=os.path.dirname(rel))

    if args.body_file and os.path.exists(args.body_file):
        with open(args.body_file, encoding="utf-8") as f:
            check_text(f.read(), BODY_LABEL, root, problems)

    if args.pr_author:
        added = added_fieldnotes(args.base, root)
        if added is None:
            return 1
        for rel in added:
            path = os.path.join(root, rel)
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as f:
                check_fieldnote_author(rel, f.read(), args.pr_author, problems)

    # Not under --all: a sweep has no diff to read revisions from. Under
    # --files the diff is still the source of truth for this check, but the
    # root may be a bare directory with no git history (the self-tests), so
    # only the CI shape, where the diff also chose the files, fails closed.
    if not args.all and not check_revisions(args.base, root, problems):
        if files is not args.files:
            print("failing closed")
            return 1
        print("skipping the revision check")

    if args.report:
        write_report(problems, len(files), args.report)

    if not problems:
        print(f"prose check ok ({len(files)} file(s) checked)")
        return 0

    print("Prose check failed: the text points at things a reviewer cannot open.\n")
    for label, why, detail in problems:
        print(f"  {label}: {why}\n    {detail}")
    if any(label == BODY_LABEL for label, _, _ in problems):
        print(f"\nAnything labelled '{BODY_LABEL}' above is in the PR description, "
              "not in a\ncommitted file: fix it by editing the PR body. Nothing in "
              "the tree has to\nchange for it.")

    if any(why.startswith("distance revision") for _, why, _ in problems):
        print("\nA distance revision keeps the note it replaces: `git mv` it to the new")
        print("slug, put the revision record on top, and carry the previous text under")
        print(f"'{FOLD_IN_HEADING}', with its paths pointed at the new")
        print("slug. If the narrative belongs elsewhere, move it to a dated fieldnotes/")
        print("entry in the same PR instead (PR #3053 did this for [[502,102,50]]). See")
        print("research/audits/README.md, 'Filing a distance revision'.")

    print("\nFix by pointing at something that exists in this PR, or by naming the")
    print("external source and pinning it (e.g. 'github.com/org/repo @ abc1234,")
    print("`path/in/that/repo.py`'). research/candidates/ is gitignored working")
    print("output and can never be cited as evidence. See AGENTS.md, 'Writing the")
    print("submission'.")
    print("\nFor a number that came out of a campaign run, cite the run manifest")
    print("committed beside the note (research/campaigns/<id>/manifest.json). It")
    print("carries the code snapshot, the parameters actually invoked, the seeds,")
    print("and any log excerpt the claim rests on. See research/campaigns/README.md.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
