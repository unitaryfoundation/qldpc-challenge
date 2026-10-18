"""The pre-push prose gate has to diff against the canonical main, not a fork's.

Issue #2762: in a fork, origin/main is whatever the fork last synced. A
stale one reported every note in the repository as changed; one ahead of
upstream would report a branch with broken citations as clean. These tests
build a small upstream, a fork of it with a stale main, and a branch on the
fork, and check which base the script resolves and what it says.
"""
import os
import re
import subprocess
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
SCRIPT = os.path.join(_HERE, "prepush_prose_check.sh")


def _git(cwd, *args, check=True):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                           "-c", "commit.gpgsign=false", *args],
                          cwd=cwd, check=check, capture_output=True, text=True)


def _commit_note(repo, name, body):
    os.makedirs(os.path.join(repo, "notes"), exist_ok=True)
    with open(os.path.join(repo, "notes", name), "w", encoding="utf-8") as f:
        f.write(body)
    _git(repo, "add", "notes")
    _git(repo, "commit", "-q", "-m", f"add {name}")


@pytest.fixture
def fork(tmp_path):
    """Build an upstream with notes on main and a fork whose main is stale."""
    up = tmp_path / "upstream"
    up.mkdir()
    _git(up, "init", "-q", "-b", "main")
    # The script's own tree is what check_prose.py runs from, so give the
    # repositories the verifier they will be asked to run.
    os.makedirs(up / "verify")
    for name in ("check_prose.py", "check_submission_scope.py",
                 "prepush_prose_check.sh"):
        with open(os.path.join(_HERE, name), encoding="utf-8") as f:
            (up / "verify" / name).write_text(f.read(), encoding="utf-8")
    _git(up, "add", "verify")
    _git(up, "commit", "-q", "-m", "verifier")
    _commit_note(str(up), "a.md", "# a\n")
    stale = _git(up, "rev-parse", "HEAD").stdout.strip()
    for i in range(3):
        _commit_note(str(up), f"later{i}.md", f"# later {i}\n")

    fk = tmp_path / "fork"
    _git(tmp_path, "clone", "-q", str(up), str(fk))
    # The fork's main stopped syncing after the first note.
    _git(fk, "update-ref", "refs/remotes/origin/main", stale)
    _git(fk, "reset", "-q", "--hard", stale)
    _git(fk, "checkout", "-q", "-b", "submission")
    _commit_note(str(fk), "mine.md", "# mine\n")
    return {"upstream": str(up), "fork": str(fk), "stale": stale}


def _run(repo, env=None, body="/dev/null"):
    e = dict(os.environ, QLDPC_PYTHON=sys.executable)
    e.pop("BASE", None)
    e.update(env or {})
    return subprocess.run(["sh", os.path.join(repo, "verify",
                                              "prepush_prose_check.sh"), body],
                          cwd=repo, env=e, capture_output=True, text=True, check=False)


def test_without_an_upstream_remote_a_fork_origin_is_refused(fork):
    """Refuse a fork origin, since its main is not what CI diffs against."""
    r = _run(fork["fork"])
    assert r.returncode == 2, r.stderr
    assert "not unitaryfoundation/qldpc-challenge" in r.stderr
    assert "git remote add upstream" in r.stderr


def test_with_an_upstream_remote_the_base_is_upstream_main(fork):
    _git(fork["fork"], "remote", "add", "upstream", fork["upstream"])
    _git(fork["fork"], "fetch", "-q", "upstream")
    r = _run(fork["fork"])
    assert r.returncode == 0, r.stderr + r.stdout
    assert "base: upstream/main" in r.stdout
    # The one note the branch added, not the three the fork never synced.
    assert "later" not in r.stdout


def test_a_forced_stale_base_is_warned_about(fork):
    _git(fork["fork"], "remote", "add", "upstream", fork["upstream"])
    _git(fork["fork"], "fetch", "-q", "upstream")
    r = _run(fork["fork"], env={"BASE": "origin/main"})
    assert "WARNING: origin/main is not upstream/main" in r.stderr


def test_an_explicit_base_is_honored_without_an_upstream_remote(fork):
    r = _run(fork["fork"], env={"BASE": fork["stale"]})
    assert r.returncode == 0, r.stderr + r.stdout
    assert "ERROR" not in r.stderr


def test_uncommitted_notes_are_refused_and_other_dirt_is_not(fork):
    repo = fork["fork"]
    _git(repo, "remote", "add", "upstream", fork["upstream"])
    _git(repo, "fetch", "-q", "upstream")
    with open(os.path.join(repo, "scratch.txt"), "w") as f:
        f.write("another session's work\n")
    r = _run(repo)
    assert r.returncode == 0, r.stderr + r.stdout
    assert "uncommitted changes outside notes/" in r.stderr
    with open(os.path.join(repo, "notes", "draft.md"), "w") as f:
        f.write("# draft\n")
    r = _run(repo)
    assert r.returncode == 2
    assert "notes/draft.md" in r.stderr


def test_the_contributor_prompt_checks_the_note_and_names_the_gate():
    """The paste-ready prompt in CONTRIBUTING.md is what a contributor's agent executes.

    It once ran the prose check on the code JSON, which the scanner passes
    trivially, and never named this gate (#3382).
    """
    with open(os.path.join(_ROOT, "CONTRIBUTING.md"), encoding="utf-8") as f:
        text = f.read()
    start = text.index("You are contributing to the QEC Challenge")
    block = text[start:start + text[start:].index("```")]
    files = re.findall(r"--files\s+(\S+)", block)
    assert files and all(f.endswith(".md") for f in files), files
    assert "verify/prepush_prose_check.sh <body.md>" in block
    assert os.access(SCRIPT, os.X_OK)
