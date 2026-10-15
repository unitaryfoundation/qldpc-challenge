"""Tests for verify/check_prose.py.

Fixtures are synthetic (written to a temp tree) so the suite does not depend on
which notes happen to be on the board. That holds for the negative cases too:
asserting that a *real* note fails, as an earlier revision of this file did,
makes the suite depend on a specific note staying broken, and repairing it
turns the test red. One positive case still runs against the real repository,
because a note citing a pinned external artifact passing is a property worth
holding live.
"""
import os
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
import check_prose

FAILURES = []


def check(name, ok, detail=""):
    print(("PASS" if ok else "FAIL"), name, detail)
    if not ok:
        FAILURES.append(name)


def problems_for(text, root, slug=None):
    out = []
    check_prose.check_text(text, "t.md", root, out, is_note_slug=slug)
    return [why for _, why, _ in out]


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "research", "kit"))
        open(os.path.join(tmp, "research", "kit", "group_algebra.py"), "w").close()

        check("path that exists resolves",
              problems_for("built with `research/kit/group_algebra.py`", tmp) == [])

        check("module.function form resolves",
              problems_for("call `research/kit/group_algebra.build_2bga`", tmp) == [])

        check("file::symbol form resolves",
              problems_for("see `research/kit/group_algebra.py::build_2bga`", tmp) == [])

        check("missing path is caught",
              problems_for("MILP via `evaluation/distance_milp.py`", tmp)
              == ["path does not exist in this tree"])

        check("missing path is allowed when an external source is named",
              problems_for(
                  "MILP via `evaluation/distance_milp.py` from "
                  "https://github.com/qiskit-community/qcode-discovery", tmp) == [])

        check("pinned external artifact passes",
              problems_for(
                  "taken from github.com/a7b/yarn @ 82fb695, "
                  "`processor_codes/mitten/Hx.npy`", tmp) == [])

        check("gitignored dir is caught even with an external source named",
              problems_for(
                  "evidence in `research/candidates/run1/` see https://example.com",
                  tmp) == ["gitignored working output cited as evidence"])

        check("absolute local path is caught",
              "absolute local path"
              in problems_for("ran /Users/me/scratch/search.py", tmp))

        check("session URL is caught",
              "session URL" in problems_for(
                  "https://claude.ai/code/session_01ABC", tmp))

        check("scaffolding is caught",
              "leftover scaffolding" in problems_for(
                  "Drafted by `qldpc submit`; edit before requesting review.", tmp))

        check("unticked checkbox is caught",
              "leftover scaffolding" in problems_for("- [ ] verified", tmp))

        check("arXiv id is not treated as a path",
              problems_for("see quant-ph/9601029 for the original", tmp) == [])

        check("placeholder path is not treated as a path",
              problems_for("writes `codes/<n>-<k>-<d>.json`", tmp) == [])

        check("note slug mismatch is caught",
              "note's first [[n,k,d]] disagrees with its filename"
              in problems_for("# [[270,54,12]] code", tmp, slug=("270", "54", "10")))

        check("note with no params is caught",
              "note states no [[n,k,d]]"
              in problems_for("A note with no parameters.", tmp,
                              slug=("482", "146", "42")))

        check("matching note slug passes",
              problems_for("# [[270,54,10]] code", tmp, slug=("270", "54", "10"))
              == [])

        # #3379: a path under this repo's own top-level directories is a claim
        # about this tree, whatever else the text cites.
        check("repo path is caught even with an external source named",
              problems_for("built with `research/kit/clp.py`, see "
                           "https://arxiv.org/abs/2607.14091", tmp)
              == ["path does not exist in this tree"])

        check("external artifact under a codes/ of its own repo still passes",
              problems_for("`codes/GB_106_w8_X.mtx` from github.com/a/b @ 1234abc", tmp)
              == [])

        check("repo path inside a backticked command is caught",
              problems_for("gate it with `python verify/coordination.py gate x.json`", tmp)
              == ["path does not exist in this tree"])

        check("command naming an existing repo path passes",
              problems_for("run `uv run python research/kit/group_algebra.py`", tmp) == [])

        check("a call on a module resolves to the module",
              problems_for("`research/kit/group_algebra.py::build_2bga(mul, a, b)`", tmp) == [])

    # --all sweeps what is committed, and --report writes the grouped body the
    # weekly tracking issue carries (#3379).
    with tempfile.TemporaryDirectory() as tmp:
        def git(*args):
            subprocess.run(["git", *args], cwd=tmp, check=True, capture_output=True)
        git("init", "-q")
        os.makedirs(os.path.join(tmp, "notes"))
        with open(os.path.join(tmp, "notes", "1-1-1.md"), "w") as f:
            f.write("# [[1,1,1]] built with `research/kit/missing.py`\n")
        with open(os.path.join(tmp, "notes", "2-1-1.md"), "w") as f:
            f.write("# [[2,1,1]] clean\n")
        with open(os.path.join(tmp, "notes", "3-1-1.md"), "w") as f:
            f.write("# [[3,1,1]] uncommitted, with `research/kit/missing.py`\n")
        git("add", "notes/1-1-1.md", "notes/2-1-1.md")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x")
        report = os.path.join(tmp, "report.md")
        r = subprocess.run([sys.executable, os.path.join(_HERE, "check_prose.py"),
                            "--root", tmp, "--all", "--report", report],
                           cwd=ROOT, capture_output=True, text=True, check=False)
        check("--all sweeps committed prose only",
              r.returncode == 1 and "notes/1-1-1.md" in r.stdout
              and "notes/3-1-1.md" not in r.stdout, r.stdout[-200:])
        with open(report) as f:
            body = f.read()
        check("--report groups by target",
              "over 2 committed" in body and "1 problem(s) in 1 file(s)" in body
              and "`research/kit/missing.py` in 1 file(s): `notes/1-1-1.md`" in body, body)

    # A body-sourced problem must say so and point the reader at the PR
    # description; a file-only failure must not mention the body (issue #897).
    with tempfile.TemporaryDirectory() as tmp:
        body = os.path.join(tmp, "body.md")
        with open(body, "w") as f:
            f.write("Research note: `notes/700-206-74.md`\n")
        r = subprocess.run([sys.executable, os.path.join(_HERE, "check_prose.py"),
                            "--root", tmp, "--files", "--body-file", body],
                           cwd=ROOT, capture_output=True, text=True)
        check("body-only problem fails", r.returncode == 1)
        check("body problem is labelled as such", "PR body:" in r.stdout)
        check("body problem points at the PR description",
              "editing the PR body" in r.stdout, r.stdout.strip()[-80:])

        note = os.path.join(tmp, "n.md")
        with open(note, "w") as f:
            f.write("Built with `evaluation/distance_milp.py`\n")
        r = subprocess.run([sys.executable, os.path.join(_HERE, "check_prose.py"),
                            "--root", tmp, "--files", note],
                           cwd=ROOT, capture_output=True, text=True)
        check("file-only problem fails", r.returncode == 1)
        check("file-only problem does not blame the PR body",
              "editing the PR body" not in r.stdout)

        # The gitignored-output rule, end to end through the CLI. It has to run
        # against a synthetic note: the first version asserted this on a real
        # committed note, so repairing that note failed the suite. A check that
        # demands a known-bad file stay bad fights the cleanup it exists to
        # encourage.
        dirty = os.path.join(tmp, "notes")
        os.makedirs(dirty, exist_ok=True)
        dirty_note = os.path.join(dirty, "9-3-3.md")
        with open(dirty_note, "w") as f:
            f.write("# [[9,3,3]]\n\nevidence in `research/candidates/run1/` "
                    "see https://example.com\n")
        r = subprocess.run([sys.executable, os.path.join(_HERE, "check_prose.py"),
                            "--root", tmp, "--files", dirty_note],
                           cwd=ROOT, capture_output=True, text=True)
        check("a note citing gitignored output fails end to end",
              r.returncode == 1, r.stdout.strip().splitlines()[-1:] or "")
        check("...and names the reason",
              "gitignored working output" in r.stdout)

    # Against the real tree: a note whose citation is sound passes. The
    # converse is not asserted against a real file -- see above; the board is
    # expected to get cleaner over time, and the suite must not need a dirty
    # note to stay green.
    real = os.path.join(ROOT, "notes", "300-60-14.md")
    if os.path.exists(real):
        r = subprocess.run([sys.executable, os.path.join(_HERE, "check_prose.py"),
                            "--files", "notes/300-60-14.md"],
                           cwd=ROOT, capture_output=True, text=True)
        check("real note with a pinned external artifact passes",
              r.returncode == 0, r.stdout.strip().splitlines()[-1:] or "")

    # A distance revision must carry the previous note's body forward (#3388).
    check("slug update inside a fold-in is not a loss",
          check_prose.retention("built as `codes/10-2-6.json`, see [[10,2,6]]\n",
                                "built as `codes/10-2-5.json`, see [[10,2,5]]\n") == 1.0)
    check("headings, tables, fences, and comments are not body",
          check_prose.retention("# [[10,2,6]]\n| a | b |\n```\nx = 1\n```\n<!-- c -->\n",
                                "") == 1.0)
    table = {}
    check_prose.slug_into("codes/12-4-2-b.json", table)
    check_prose.slug_into("notes/12-4-3-b.md", table)
    check_prose.slug_into("codes/12-4-2.json", table)
    check("a suffixed slug pairs only with its own suffix",
          table == {("12", "4", "-b"): {"2", "3"}, ("12", "4", ""): {"2"}}, table)
    check("a stub keeps nothing",
          check_prose.retention("# t\n\nline one\nline two\n", "# t\n\nother\n") == 0.0)

    OLD_NOTE = ("# [[10,2,6]] a construction\n\n## What was searched\n\n"
                "Rebuild from `codes/10-2-6.json`.\n"
                + "".join(f"Sweep {i} at {1000 * (i + 1)} trials found nothing lighter "
                          "than weight 6.\n" for i in range(12)))
    OLD_NOTE_UPDATED = OLD_NOTE.replace("10-2-6", "10-2-5").replace("[[10,2,6]]", "[[10,2,5]]")
    STUB = ("# [[10,2,5]] distance revision\n\nOnly the distance block differs; "
            "a weight-5 logical was found.\n")

    def revision_repo(tmp, new_note, fieldnote=None, mv=True):
        """Commit the old entry on main, then a revision of it on a branch."""
        def git(*args):
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                           cwd=tmp, check=True, capture_output=True)
        git("init", "-q")
        git("symbolic-ref", "HEAD", "refs/heads/main")
        os.makedirs(os.path.join(tmp, "codes"))
        os.makedirs(os.path.join(tmp, "notes"))
        with open(os.path.join(tmp, "codes", "10-2-6.json"), "w") as f:
            f.write('{"name": "[[10,2,6]]", "distance": 6}\n')
        with open(os.path.join(tmp, "notes", "10-2-6.md"), "w") as f:
            f.write(OLD_NOTE)
        git("add", "-A")
        git("commit", "-q", "-m", "base")
        git("checkout", "-q", "-b", "revision")
        if mv:
            git("mv", "codes/10-2-6.json", "codes/10-2-5.json")
            git("mv", "notes/10-2-6.md", "notes/10-2-5.md")
        else:
            git("rm", "-q", "codes/10-2-6.json", "notes/10-2-6.md")
            os.makedirs(os.path.join(tmp, "codes"), exist_ok=True)
            os.makedirs(os.path.join(tmp, "notes"), exist_ok=True)
        with open(os.path.join(tmp, "codes", "10-2-5.json"), "w") as f:
            f.write('{"name": "[[10,2,5]]", "distance": 5}\n')
        if new_note is not None:
            with open(os.path.join(tmp, "notes", "10-2-5.md"), "w") as f:
                f.write(new_note)
        if fieldnote is not None:
            os.makedirs(os.path.join(tmp, "fieldnotes"))
            with open(os.path.join(tmp, "fieldnotes", "2026-10-15-ten-two.md"), "w") as f:
                f.write(fieldnote)
        git("add", "-A")
        git("commit", "-q", "-m", "Tighten [[10,2,6]] to 5")
        return subprocess.run([sys.executable, os.path.join(_HERE, "check_prose.py"),
                               "--root", tmp, "--base", "main"],
                              cwd=ROOT, capture_output=True, text=True, check=False)

    folded = STUB + "\n## Original note, with the file paths updated\n\n" + OLD_NOTE_UPDATED
    with tempfile.TemporaryDirectory() as tmp:
        r = revision_repo(tmp, folded)
        check("fold-in under the heading passes", r.returncode == 0,
              r.stdout[-200:] + r.stderr[-300:])
    with tempfile.TemporaryDirectory() as tmp:
        r = revision_repo(tmp, STUB, mv=False)
        check("stub replacing the note fails", r.returncode == 1
              and "distance revision drops the previous note's body" in r.stdout
              and "notes/10-2-6.md -> notes/10-2-5.md: 0% of its body lines" in r.stdout
              and "delete beside an add" in r.stdout, r.stdout[-300:])
        check("...and names the way out", "Filing a distance revision" in r.stdout)
    # Nine of thirteen body lines kept: similar enough for git to call it a
    # rename, and still a third of the record gone.
    partial = (STUB + "\n## Original note, with the file paths updated\n\n"
               + "\n".join(OLD_NOTE_UPDATED.splitlines()[:-4]) + "\n")
    with tempfile.TemporaryDirectory() as tmp:
        r = revision_repo(tmp, partial, mv=True)
        check("a rename that drops a third of the body still fails", r.returncode == 1
              and "69% of its body lines" in r.stdout
              and "git saw a rename" in r.stdout, r.stdout[-300:])
    with tempfile.TemporaryDirectory() as tmp:
        fieldnote = ("---\ntitle: ten-two search\nauthor: \"@t\"\n---\n\n"
                     "# The search behind [[10,2,5]]\n\n" + OLD_NOTE_UPDATED.split("\n", 2)[2])
        r = revision_repo(tmp, STUB, fieldnote=fieldnote, mv=False)
        check("narrative moved to a fieldnote passes", r.returncode == 0, r.stdout[-200:])
    with tempfile.TemporaryDirectory() as tmp:
        r = revision_repo(tmp, None, mv=False)
        check("entry revised with its note dropped fails",
              r.returncode == 1 and "no note under the new slug" in r.stdout, r.stdout[-300:])

    print()
    if FAILURES:
        print(f"{len(FAILURES)} failure(s): {', '.join(FAILURES)}")
        return 1
    print("all prose checks pass")
    return 0


def test_main():
    """pytest entry point; the suite body lives in main()."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
