"""The workflow's data-only rule must agree with the scope check, and must work.

Two files say which directories hold submitted data. `check_submission_scope.py`
lists them as SUBMISSION_SURFACE, what a submission PR may carry. `verify.yml`
lists them as DATA_SURFACE, what a PR may change and still skip the full
self-test suite. They were maintained by hand in different files and they
drifted: the scope check admitted `repro/` and `certs/` and the workflow did
not, so a submission that carried its own certificate was a legal submission
that ran about an hour of self-tests, nearly none of which read a certificate.

The first half of this file pins the two lists together. The second half runs
the workflow's own shell, the script of the `detect changed code submissions`
step, against small git repositories, because the rule is thirty lines of
shell inside a YAML string and nothing else executes it before a pull request
does. Slugs here are fictitious, for the reason test_check_submission_scope.py
gives: the workflow runs any test that names a changed entry.

  uv run pytest verify/test_data_surface.py
"""

import os
import re
import subprocess

import check_submission_scope as S

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_WORKFLOW = os.path.join(_ROOT, ".github", "workflows", "verify.yml")
_STEP = "detect changed code submissions"


def workflow_text():
    with open(_WORKFLOW, encoding="utf-8") as f:
        return f.read()


def workflow_env(name):
    """Return the entries of a space-separated list in the verify job's env."""
    match = re.search(rf"^\s+{name}:\s*(.+?)\s*$", workflow_text(), re.M)
    assert match, f"{_WORKFLOW}: no {name} env entry; update this test"
    return match.group(1).split()


def step_script(name):
    """Return the `run: |` script of the named step, dedented.

    Read by indentation rather than by a YAML parser (the repo has no yaml
    dependency), as test_workflow_paths.py reads the paths block.
    """
    lines = workflow_text().splitlines()
    header = f"      - name: {name}"
    assert lines.count(header) == 1, f"{_WORKFLOW}: no single {header!r} line; update this test"
    start = lines.index(header) + 1
    run = next(i for i in range(start, len(lines)) if lines[i] == "        run: |")
    body = []
    for line in lines[run + 1:]:
        if line.strip() and not line.startswith(" " * 10):
            break
        body.append(line[10:])
    return "\n".join(body) + "\n"


def test_the_workflow_list_is_the_submission_surface():
    listed = workflow_env("DATA_SURFACE")
    expected = {prefix.rstrip("/") for prefix in S.SUBMISSION_SURFACE}
    assert set(listed) == expected, (
        f"DATA_SURFACE in .github/workflows/verify.yml lists {sorted(set(listed) - expected)} "
        f"that check_submission_scope.SUBMISSION_SURFACE does not and misses "
        f"{sorted(expected - set(listed))} that it does. A directory the scope check admits "
        f"and the workflow omits sends every submission that uses it through the full "
        f"self-test suite; update the list and re-pin verify/validator_manifest.json, which "
        f"hashes that workflow."
    )
    assert len(listed) == len(set(listed)), f"DATA_SURFACE repeats an entry: {listed}"


def test_the_data_only_rule_reads_the_list():
    script = step_script(_STEP)
    assert "for d in $DATA_SURFACE; do" in script and "...HEAD -- $DATA_SURFACE &&" in script, (
        "the data-only rule in verify.yml must build both of its diffs from $DATA_SURFACE"
    )


def test_a_data_only_pr_gets_the_board_tests_from_the_runner(pytestconfig):
    """The step that replaces the suite selects by marker, through run_tests.py.

    run_tests.py is what decides which directories are collected, so the
    narrowed run goes through it rather than naming test files: a marked test
    joins the step the moment it exists.
    """
    assert "python run_tests.py -m board" in workflow_text()
    registered = [line.split(":")[0].strip() for line in pytestconfig.getini("markers")]
    assert "board" in registered, "conftest.py no longer registers the `board` marker"


# -- the rule itself, run as the workflow runs it ---------------------------

_BASE = {
    "codes/a-1-1.json": '{"n": 1}',
    "certs/a-1-1.json": '{"level": "solver"}',
    "verify/qldpc_verify.py": "x = 1\n",
    "verify/test_pins.py": "# [[a,1,1]] keeps its side value\n",
    "research/audits/test_census.py": "SLUG = 'b-2-2'\n",
    "research/test_unrelated.py": "SLUG = 'z-9-9'\n",
    "research/audits/census.py": "SLUG = 'b-2-2'  # not a test file\n",
}


def repo(tmp_path, change):
    """Build a small repo, apply `change` on top, and return its root.

    `change` maps a path to its content, or to None to delete it. The base
    commit is published as origin/main, which is the ref the step diffs
    against for a pull request into main.
    """
    root = tmp_path / "repo"
    root.mkdir(parents=True)

    def git(*a):
        return subprocess.run(["git", *a], cwd=root, check=True,
                              capture_output=True, text=True)

    git("init", "-q", "-b", "work")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    for rel, content in _BASE.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    for rel, content in change.items():
        p = root / rel
        if content is None:
            p.unlink()
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
    git("add", "-A")
    git("commit", "-q", "-m", "change")
    return root


def run_step(root):
    """Run the step's script in `root` as a pull request into main; return its outputs."""
    script = step_script(_STEP)
    assert script.count("${{ github.base_ref }}") == 1 and script.count("${{") == 1, (
        "the step interpolates something this test does not supply; update this test"
    )
    script = script.replace("${{ github.base_ref }}", "main")
    out = root.parent / "github_output"
    out.write_text("")
    env = dict(os.environ, GITHUB_OUTPUT=str(out), GITHUB_STEP_SUMMARY=os.devnull,
               DATA_SURFACE=" ".join(workflow_env("DATA_SURFACE")),
               LER_STACK=" ".join(workflow_env("LER_STACK")))
    # `bash -e`, without pipefail, is what GitHub gives a `run:` step that
    # names no shell, and no step in verify.yml names one.
    done = subprocess.run(["bash", "--noprofile", "--norc", "-e", "-c", script],
                          cwd=root, env=env, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    return dict(line.split("=", 1) for line in out.read_text().splitlines())


def detect(tmp_path, change):
    return run_step(repo(tmp_path, change))


def test_an_entry_with_its_certificate_and_manifest_is_data_only(tmp_path):
    got = detect(tmp_path, {
        "codes/c-3-3.json": '{"n": 3}', "notes/c-3-3.md": "# [[c,3,3]]\n",
        "circuits/c-3-3/memory_x.stim": "TICK\n", "certs/c-3-3.json": '{"level": "solver"}',
        "repro/c-3-3.json": "{}"})
    assert got["codes_changed"] == "true" and got["data_only"] == "true"


def test_a_certificate_alone_is_data_only_and_is_not_a_code_change(tmp_path):
    """The certificate-only PR: no entry changed, so none of the entry gates run."""
    got = detect(tmp_path, {"certs/a-1-1.json": '{"level": "proof_log"}'})
    assert got["codes_changed"] == "false" and got["data_only"] == "true"


def test_anything_outside_the_surface_runs_the_suite(tmp_path):
    for i, extra in enumerate(["verify/qldpc_verify.py", "research/build.py", "docs/index.html",
                               "conftest.py", ".github/workflows/verify.yml"]):
        got = detect(tmp_path / str(i), {"certs/a-1-1.json": '{"level": "formal"}', extra: "y = 2\n"})
        assert got["data_only"] == "false", extra


def test_a_pr_that_changes_no_data_runs_the_suite(tmp_path):
    got = detect(tmp_path, {"verify/qldpc_verify.py": "x = 2\n"})
    assert got["codes_changed"] == "false" and got["data_only"] == "false"


def test_a_diff_that_cannot_be_computed_runs_the_suite(tmp_path):
    """Fail closed: with no base ref to diff against, nothing is skipped."""
    root = repo(tmp_path, {"certs/a-1-1.json": '{"level": "formal"}'})
    assert run_step(root)["data_only"] == "true"
    subprocess.run(["git", "update-ref", "-d", "refs/remotes/origin/main"], cwd=root, check=True)
    assert run_step(root) == {"codes_changed": "true", "data_only": "false", "slug_tests": "",
                              "ler_stack_changed": "true"}


def test_the_tests_naming_a_changed_entry_are_found_by_either_spelling(tmp_path):
    """By slug or by [[n,k,d]], and from any part of the surface named for the entry."""
    for i, path in enumerate(["codes/a-1-1.json", "circuits/a-1-1/memory_x.stim",
                              "certs/a-1-1.json", "certs/heuristic/a-1-1.json",
                              "repro/a-1-1.json"]):
        got = detect(tmp_path / str(i), {path: '{"n": 11}'})
        assert got["slug_tests"] == "verify/test_pins.py", path


def test_a_test_in_a_subdirectory_is_not_dropped(tmp_path):
    """research/audits/ and its siblings hold tests that name entries.

    The shape filter once admitted only research/test_*.py, so these matched
    the grep and were then discarded; a non-test file that names the slug is
    still left out.
    """
    got = detect(tmp_path, {"codes/b-2-2.json": '{"n": 2}'})
    assert got["slug_tests"] == "research/audits/test_census.py"


def test_removing_an_entry_still_runs_the_tests_that_name_it(tmp_path):
    got = detect(tmp_path, {"codes/a-1-1.json": None, "certs/a-1-1.json": None})
    assert got["data_only"] == "true" and got["slug_tests"] == "verify/test_pins.py"
