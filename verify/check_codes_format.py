"""Check that board JSON under codes/ is written one way: json.dumps(doc, indent=1), and named for what it holds.

A one-line or re-indented file still parses and verifies, so nothing objected
to it (PR #3413), but every later revision of such a file (a tightened
distance, a new witness) then diffs as one changed line and cannot be
reviewed. Only files CHANGED by the PR are checked; entries already on the
board are left alone. `--fix` rewrites files in place.

    python verify/check_codes_format.py                          # changed vs origin/main
    python verify/check_codes_format.py --files codes/<slug>.json
    python verify/check_codes_format.py --fix --files codes/<slug>.json
"""

import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def canonical(doc):
    """Return the form the writers emit: indent 1, one key per line, trailing newline."""
    return json.dumps(doc, indent=1) + "\n"


def changed_codes(base, root):
    """codes/*.json added, modified, or renamed since ``base``; None if git failed."""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", "--diff-filter=AMR", f"{base}...HEAD", "--", "codes"], cwd=root, text=True
        )
    except Exception as e:
        print(f"could not diff vs {base}: {e}; failing closed")
        return None
    return [f for f in out.splitlines() if f.endswith(".json")]


def check_text(text):
    """None when ``text`` is canonical, else a short reason.

    The trailing newline is optional: the writers emit one, but many entries
    on the board predate that and the point here is the line structure.
    """
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        return f"not valid JSON ({e})"
    body = text[:-1] if text.endswith("\n") else text
    if body in (json.dumps(doc, indent=1), json.dumps(doc, indent=1, ensure_ascii=False)):
        return None
    if "\n" not in body.strip():
        return "written on one line"
    m = re.match(r"[\[{]\n( +)", body)
    if m and len(m.group(1)) != 1:
        return f"indent {len(m.group(1))}"
    return "whitespace differs from json.dumps(doc, indent=1)"


def check_file(path):
    with open(path, encoding="utf-8") as f:
        return check_text(f.read())


SLUG = re.compile(r"^(\d+)-(\d+)-(\d+)(?:-[0-9A-Za-z]+)*$")


def slug_problem(rel, doc):
    """None when the file name agrees with the entry, else a short reason (issue #7108).

    A board file is named ``<n>-<k>-<d>.json``, with an optional suffix when
    that slug is taken, and everything keyed by slug (certificates, notes,
    receipts, the provenance table, links) reads the distance off the name.
    51 entries were once filed under the distance their construction
    predicted while ``distance.d`` held the smaller value the gate had
    already imposed, and nothing objected. ``d`` is ``distance.d`` for a CSS
    entry and ``distance.P.value`` for a stabilizer one; a document without
    a distance block is left to the schema check.
    """
    stem = os.path.splitext(os.path.basename(rel))[0]
    m = SLUG.match(stem)
    if not m or not isinstance(doc, dict):
        return None
    dist = doc.get("distance")
    if not isinstance(dist, dict):
        return None
    d = dist.get("d")
    if d is None and isinstance(dist.get("P"), dict):
        d = dist["P"].get("value")
    want = (doc.get("n"), doc.get("k"), d)
    if any(not isinstance(v, int) for v in want):
        return None
    have = tuple(int(g) for g in m.groups())
    if have == want:
        return None
    n, k, dd = want
    return (
        f"named for [[{have[0]},{have[1]},{have[2]}]] but holds n={n}, k={k}, d={dd}; "
        f"rename the file, its note, and its certificate to {n}-{k}-{dd} (with a suffix if taken)"
    )


def fix_file(path):
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(canonical(doc))


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--files", nargs="*", help="files to check (relative to --root) instead of the diff")
    ap.add_argument("--fix", action="store_true", help="rewrite the files in canonical form")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)

    files = args.files
    if files is None:
        files = changed_codes(args.base, root)
        if files is None:
            return 1

    bad = []
    for rel in files:
        path = rel if os.path.isabs(rel) else os.path.join(root, rel)
        if not os.path.exists(path):
            continue
        if args.fix:
            try:
                fix_file(path)
            except json.JSONDecodeError as e:
                bad.append((rel, f"not valid JSON ({e})"))
                continue
            print(f"rewrote {rel}")
            continue
        why = check_file(path)
        if why:
            bad.append((rel, why))
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except json.JSONDecodeError:
            continue  # already reported above
        why = slug_problem(rel, doc)
        if why:
            bad.append((rel, why))

    if not bad:
        print(f"codes format ok ({len(files)} file(s) checked)")
        return 0
    print(
        "Codes format check failed: a board file is json.dumps(doc, indent=1), one key per line, "
        "named <n>-<k>-<d>.json for the entry it holds.\n"
    )
    for rel, why in bad:
        print(f"  {rel}: {why}")
    fixable = [rel for rel, why in bad if not why.startswith("named for")]
    if fixable:
        print(
            "\nFix the formatting in place with\n\n  python3 verify/check_codes_format.py --fix --files "
            + " ".join(fixable)
        )
    if len(fixable) < len(bad):
        print("\nA misnamed file is renamed by hand (git mv the code, its note, and its certificate);")
        print("--fix does not rename.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
