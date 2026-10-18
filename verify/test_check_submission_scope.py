"""Keep the scope check's notion of code data aligned with the workflow's.

codes/*.json and anything under circuits/<slug>/ are code data, so a PR
cannot pair a circuit-artifact change with a verifier edit any more than a
codes/ change.
"""
import subprocess

import check_submission_scope as S


def test_code_data_includes_entries_and_their_circuits():
    assert S.is_code_submission("codes/72-6-6.json")
    assert S.is_code_submission("circuits/72-6-6/memory_x.stim")
    assert S.is_code_submission("circuits/72-6-6/memory_z.dem")
    assert not S.is_code_submission("circuits/README.md")
    assert not S.is_code_submission("codes/README.md")
    assert not S.is_code_submission("verify/ler_tools.py")


def test_verifier_stack_is_critical_not_code_data():
    for f in ("verify/ler_tools.py", "uv.lock", "pyproject.toml"):
        assert S.is_critical(f) and not S.is_code_submission(f)


def test_one_entry_with_its_circuit_artifacts_is_one_submission():
    # A first circuit tier adds four files under circuits/<slug>/ next to an
    # existing codes/<slug>.json; that is one submission, not five.
    paths = ["codes/72-6-6.json", "circuits/72-6-6/memory_x.stim",
             "circuits/72-6-6/memory_x.dem", "circuits/72-6-6/memory_z.stim",
             "circuits/72-6-6/memory_z.dem"]
    assert {S.submission_slug(p) for p in paths} == {"72-6-6"}
    assert S.submission_slug("codes/168-20-14.json") == "168-20-14"
    assert {S.submission_slug(p) for p in ("codes/a-1-1.json", "circuits/b-2-2/x.stim")} == {"a-1-1", "b-2-2"}


# -- deletions are code data too (issue #2638) ----------------------------
#
# The rule is "a PR must not change code data and the code that validates it
# in the same diff". Deletions were outside both filters, so one shape slipped
# through entirely: tighten a rule in verify/ and delete the entries the new
# rule would reject. Neither this check nor the workflow step that decides to
# run it saw any code data, so the check was skipped and verify_all ran from
# the PR's own tree rather than the trusted one.

def _repo(tmp_path, base_files, change):
    """Build a repo with `base_files`, then apply `change`; return (root, base).

    `change` maps a path to its content, or to None to delete it. The base is
    returned as a commit SHA rather than a branch name, because both commits
    land on the same branch and a branch ref would point at the tip.
    """
    root = tmp_path / "repo"
    root.mkdir()

    def run(*a):
        return subprocess.run(["git", *a], cwd=root, check=True,
                              capture_output=True, text=True)

    run("init", "-q", "-b", "work")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    for rel, content in base_files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    run("add", "-A")
    run("commit", "-q", "-m", "base")
    base = run("rev-parse", "HEAD").stdout.strip()
    for rel, content in change.items():
        p = root / rel
        if content is None:
            p.unlink()
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
    run("add", "-A")
    run("commit", "-q", "-m", "change")
    return str(root), base


def test_a_deleted_entry_counts_as_code_data(tmp_path):
    """The shape the hole allowed: a rule change plus its own counterexamples."""
    root, base = _repo(
        tmp_path,
        {"codes/72-6-6.json": '{"n": 72}', "verify/qldpc_verify.py": "x = 1\n"},
        {"codes/72-6-6.json": None, "verify/qldpc_verify.py": "x = 2\n"})
    assert "codes/72-6-6.json" in S.changed_files(base, root), \
        "a deletion is a change to the board"
    assert S.main(["--root", root, "--base", base]) == 1, \
        "deleting entries while editing the verifier must be refused"


def test_a_deletion_alone_is_still_fine(tmp_path):
    """Removing an entry on its own is an ordinary board correction."""
    root, base = _repo(tmp_path, {"codes/72-6-6.json": '{"n": 72}'},
                       {"codes/72-6-6.json": None})
    assert S.main(["--root", root, "--base", base]) == 0


def test_a_deletion_does_not_consume_the_one_new_code_budget(tmp_path):
    """The cap prices the deep refutation budget, and a deletion costs none.

    The contents differ on purpose. Given two byte-identical files git pairs
    the delete with the add as a rename, and the new code is then reported
    under R rather than A, which would make this test pass for the wrong
    reason.
    """
    root, base = _repo(
        tmp_path,
        {"codes/a-1-1.json": '{"n": 1}', "codes/b-2-2.json": '{"n": 2}'},
        {"codes/a-1-1.json": None, "codes/c-3-3.json": '{"n": 3}'})
    assert S.added_files(base, root) == ["codes/c-3-3.json"]
    assert S.main(["--root", root, "--base", base]) == 0


# -- the submission surface (issue #3414) ----------------------------------
#
# Three submission PRs carried a working tree's untracked scratch under
# research/: builders, sweep scripts, parked PR bodies, a malformed campaign
# summary. Nothing was critical, so the check passed, the workflow's codes-only
# fast path flipped to the full suite, and the only failure named the summary.
# Slugs here are fictitious: a test anchored to a real entry goes stale when
# that entry is corrected, and the workflow runs any test naming a changed slug.

def test_the_surface_is_the_entry_and_its_own_artifacts():
    inside = ["codes/x-1-1.json", "circuits/x-1-1/memory_x.stim", "notes/x-1-1.md",
              "fieldnotes/2026-10-14-concatenation.md", "repro/x-1-1.json", "certs/x-1-1.json"]
    assert S.outside_surface(inside) == []
    scratch = ["research/build_concat.py", "research/pr-bodies/x-1-1.md",
               "research/campaigns/z4/summary.json", "docs/codes/x-1-1.html", "README.md"]
    assert S.outside_surface(inside + scratch) == scratch


def test_scratch_riding_on_a_submission_is_refused(tmp_path, capsys):
    root, base = _repo(
        tmp_path, {"codes/y-2-2.json": '{"n": 2}'},
        {"codes/x-1-1.json": '{"n": 1}', "notes/x-1-1.md": "# [[x,1,1]]\n",
         "research/build_concat.py": "x = 1\n", "research/pr-bodies/x-1-1.md": "body\n"})
    assert S.main(["--root", root, "--base", base]) == 1
    out = capsys.readouterr().out
    assert "outside the submission surface" in out
    listed = out.split("Outside the surface:")[1]
    assert "research/build_concat.py" in listed and "research/pr-bodies/x-1-1.md" in listed
    assert "notes/x-1-1.md" not in listed and "codes/x-1-1.json" not in listed


def test_an_entry_with_its_own_artifacts_passes(tmp_path):
    root, base = _repo(
        tmp_path, {"codes/y-2-2.json": '{"n": 2}'},
        {"codes/x-1-1.json": '{"n": 1}', "notes/x-1-1.md": "# [[x,1,1]]\n",
         "fieldnotes/2026-10-14-concatenation.md": "---\nauthor: t\n---\n",
         "repro/x-1-1.json": "{}", "certs/x-1-1.json": "{}",
         "circuits/x-1-1/memory_x.stim": "H 0\n"})
    assert S.main(["--root", root, "--base", base]) == 0


def test_research_changes_without_code_data_are_not_a_submission(tmp_path):
    root, base = _repo(tmp_path, {"research/x.py": "x = 1\n"},
                       {"research/x.py": "x = 2\n", "research/y.py": "y = 1\n"})
    assert S.main(["--root", root, "--base", base]) == 0


def test_a_correction_that_removes_an_entry_is_held_to_the_surface(tmp_path):
    root, base = _repo(
        tmp_path, {"codes/x-1-1.json": '{"n": 1}', "research/x.py": "x = 1\n"},
        {"codes/x-1-1.json": None, "research/x.py": "x = 2\n"})
    assert S.main(["--root", root, "--base", base]) == 1


def test_the_trust_boundary_message_still_wins_over_the_surface_message(tmp_path, capsys):
    root, base = _repo(
        tmp_path, {"verify/qldpc_verify.py": "x = 1\n"},
        {"codes/x-1-1.json": '{"n": 1}', "verify/qldpc_verify.py": "x = 2\n"})
    assert S.main(["--root", root, "--base", base]) == 1
    assert "verifier-critical" in capsys.readouterr().out


# -- the shape of repro/ (issue #3810) --------------------------------------
#
# Two submission PRs (#3706, #3707) each put a working tree under
# repro/<slug>/: a README, scripts, three C++ checkers, and a results/
# directory of compile receipts, captured stdout and stderr, and exported
# columns, 40-odd files for one entry. repro/ was admitted as a whole, so the
# surface rule passed them. Under repro/ a submission carries only the
# manifest of its own entry, repro/<slug>.json, the one file qldpc reproduce
# and the reproduce workflow read.

BUNDLE = {
    "repro/x-1-1/README.md": "# evidence\n",
    "repro/x-1-1/reproduce.py": "print(1)\n",
    "repro/x-1-1/results/compile-checker.receipt.json": "{}",
    "repro/x-1-1/results/run-ris.stdout": "",
    "repro/x-1-1/results/run-ris.stderr": "",
    "repro/x-1-1/fresh-candidate-binding/X-columns.txt": "0 1 2\n",
}


def test_under_repro_only_the_entrys_own_manifest_passes():
    slugs = {"x-1-1"}
    assert S.misplaced_repro(
        ["codes/x-1-1.json", "notes/x-1-1.md", "repro/x-1-1.json"], slugs) == []
    assert S.misplaced_repro(sorted(BUNDLE), slugs) == sorted(BUNDLE)
    # a manifest, but for an entry this PR does not touch
    assert S.misplaced_repro(["repro/y-2-2.json"], slugs) == ["repro/y-2-2.json"]
    # not a manifest: the wrong extension, or the right name one level down
    assert S.misplaced_repro(["repro/x-1-1.md", "repro/x-1-1/x-1-1.json"], slugs) \
        == ["repro/x-1-1.md", "repro/x-1-1/x-1-1.json"]
    # a removal is never refused
    gone = "repro/x-1-1/results/run-ris.stdout"
    assert S.misplaced_repro([gone], slugs, deleted={gone}) == []


def test_an_evidence_directory_riding_on_a_submission_is_refused(tmp_path, capsys):
    root, base = _repo(
        tmp_path, {"codes/y-2-2.json": '{"n": 2}'},
        {"codes/x-1-1.json": '{"n": 1}', "notes/x-1-1.md": "# [[x,1,1]]\n", **BUNDLE})
    assert S.main(["--root", root, "--base", base]) == 1
    out = capsys.readouterr().out
    assert "not its entry's manifest" in out
    listed = out.split("Not a manifest of this PR's entry:")[1]
    for p in BUNDLE:
        assert p in listed
    assert "codes/x-1-1.json" not in listed and "notes/x-1-1.md" not in listed


def test_a_manifest_for_another_entry_is_refused(tmp_path):
    root, base = _repo(
        tmp_path, {"codes/y-2-2.json": '{"n": 2}'},
        {"codes/x-1-1.json": '{"n": 1}', "repro/y-2-2.json": "{}"})
    assert S.main(["--root", root, "--base", base]) == 1


def test_a_circuit_tier_may_carry_its_entrys_manifest(tmp_path):
    # circuits/<slug>/ is code data for <slug>, so the manifest binds to it too
    root, base = _repo(
        tmp_path, {"codes/x-1-1.json": '{"n": 1}'},
        {"circuits/x-1-1/memory_x.stim": "H 0\n", "repro/x-1-1.json": "{}"})
    assert S.main(["--root", root, "--base", base]) == 0


def test_an_entry_may_leave_with_its_evidence_directory(tmp_path):
    had = {"codes/x-1-1.json": '{"n": 1}', "repro/x-1-1.json": "{}",
           "repro/x-1-1/deep-search.json": "{}"}
    root, base = _repo(tmp_path, had, {p: None for p in had})
    assert set(S.deleted_files(base, root)) == set(had)
    assert S.main(["--root", root, "--base", base]) == 0


def test_evidence_under_repro_without_code_data_is_not_a_submission(tmp_path):
    # the same bundle in a PR with no code data is reviewed as code, like a
    # research/ change; the surface rules apply to submissions only
    root, base = _repo(tmp_path, {"codes/x-1-1.json": '{"n": 1}'}, BUNDLE)
    assert S.main(["--root", root, "--base", base]) == 0
