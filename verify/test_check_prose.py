"""Tests for verify/check_prose.py.

Fixtures are synthetic (written to a temp tree) so the suite does not depend on
which notes happen to be on the board; the last case pins the one behaviour that
must hold against the real repo -- a note citing an attributed external artifact
passes, and a note citing gitignored working output does not.
"""
import os
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
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

    # Against the real tree: the two behaviours the check exists to distinguish.
    real = os.path.join(ROOT, "notes", "300-60-14.md")
    if os.path.exists(real):
        r = subprocess.run([sys.executable, os.path.join(_HERE, "check_prose.py"),
                            "--files", "notes/300-60-14.md"],
                           cwd=ROOT, capture_output=True, text=True)
        check("real note with a pinned external artifact passes",
              r.returncode == 0, r.stdout.strip().splitlines()[-1:] or "")

    real = os.path.join(ROOT, "notes", "700-75-3.md")
    if os.path.exists(real):
        r = subprocess.run([sys.executable, os.path.join(_HERE, "check_prose.py"),
                            "--files", "notes/700-75-3.md"],
                           cwd=ROOT, capture_output=True, text=True)
        check("real note citing research/candidates/ fails", r.returncode == 1)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} failure(s): {', '.join(FAILURES)}")
        return 1
    print("all prose checks pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
