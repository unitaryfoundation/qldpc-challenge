"""The verify workflow must trigger for every directory run_tests.py collects.

`run_tests.py` decides what the suite is; `.github/workflows/verify.yml`'s
`pull_request.paths` decides which PRs run it at all. The two lists live in
different files and are maintained by hand, and every time they have drifted the
failure was silent: the tests existed, CI just never ran them for the PR that
added them, so they merged and ran for the first time on somebody else's diff
(PR #2321 for `cli/`, PR #2335 for `site/`). This pins the invariant directly, so
the next divergence fails here instead of merging.

  uv run pytest verify/test_workflow_paths.py   # this file
  uv run --frozen python run_tests.py           # what CI runs
"""

import os
import re
import sys
import types

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_WORKFLOW = os.path.join(_ROOT, ".github", "workflows", "verify.yml")

if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import run_tests


@pytest.fixture
def runner_cmd(monkeypatch):
    """Capture the exact pytest command run_tests.py builds for the CI invocation.

    run_tests.py only ever shells out, so the command is captured by standing in
    for subprocess rather than by re-reading its source: the extraction cannot go
    stale on a refactor of how the command is assembled.
    """
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(run_tests, "subprocess", types.SimpleNamespace(run=fake_run))
    assert run_tests.main([]) == 0
    return captured["cmd"]


def pytest_directories(cmd):
    """Return the positional directory arguments pytest is invoked with."""
    assert "pytest" in cmd, f"run_tests.py no longer invokes pytest: {cmd!r}"
    tail = cmd[cmd.index("pytest") + 1 :]
    directories = [arg for arg in tail if not arg.startswith("-")]
    assert directories, f"run_tests.py passes pytest no directories: {cmd!r}"
    return directories


def pull_request_paths():
    """Return the `pull_request.paths` entries of the verify workflow, quotes stripped.

    Read by indentation rather than by a YAML parser (the repo has no yaml
    dependency), so a restructure of that block fails here with a message naming
    the line rather than silently returning the wrong list.
    """
    with open(_WORKFLOW, encoding="utf-8") as f:
        lines = f.read().splitlines()
    on = _line_index(lines, 0, 0, "on:")
    pull_request = _line_index(lines, on + 1, 2, "pull_request:")
    paths = _line_index(lines, pull_request + 1, 4, "paths:")
    entries = []
    for line in lines[paths + 1 :]:
        if not line.strip():
            continue
        if len(line) - len(line.lstrip()) <= 4:  # the block ended
            break
        match = re.match(r"\s*-\s*(.+?)\s*$", line)
        if match:
            entries.append(match.group(1).strip("\"'"))
    assert entries, f"no path entries found under pull_request.paths in {_WORKFLOW}"
    return entries


def _line_index(lines, start, indent, header):
    target = " " * indent + header
    for index in range(start, len(lines)):
        if lines[index] == target:
            return index
    raise AssertionError(f"{_WORKFLOW}: no {target!r} line found; update this test")


def covers(patterns, path):
    """Report whether a change at path triggers the workflow.

    True when some positive pattern matches it and no negation takes it back out.
    """

    def matches(pattern):
        return pattern in ("**", path) or pattern.startswith(path + "/")

    positive = [p for p in patterns if not p.startswith("!")]
    negative = [p[1:] for p in patterns if p.startswith("!")]
    if not any(matches(p) for p in positive):
        return False
    return not any(matches(p) for p in negative)


def test_workflow_triggers_for_every_collected_directory(runner_cmd):
    patterns = pull_request_paths()
    uncovered = [d for d in pytest_directories(runner_cmd) if not covers(patterns, d)]
    assert not uncovered, (
        f"run_tests.py collects {uncovered}, but no pull_request.paths entry matches "
        f"them: a PR touching only those files runs ruff and prose and merges without "
        f"the suite. Add the entries to .github/workflows/verify.yml (and re-pin "
        f"verify/validator_manifest.json, which hashes that workflow)."
    )


def test_workflow_triggers_for_the_test_runner_itself():
    patterns = pull_request_paths()
    assert covers(patterns, "run_tests.py"), (
        "a change to run_tests.py itself has to re-run the suite it defines; "
        "add a run_tests.py entry to .github/workflows/verify.yml"
    )


def test_collected_directories_exist(runner_cmd):
    for directory in pytest_directories(runner_cmd):
        assert os.path.isdir(os.path.join(_ROOT, directory)), (
            f"run_tests.py collects {directory}, which is not a directory in this tree"
        )
