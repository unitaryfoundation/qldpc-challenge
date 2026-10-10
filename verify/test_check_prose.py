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
