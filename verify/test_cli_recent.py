"""Tests for `qldpc recent`.

The command is the "read before you search" step, so an agent or a newcomer
pays its output in context on every run. A busy fortnight adds hundreds of
codes, and printing all of them makes the command too expensive to run, which
is the same as not having it. What is tested here is that the default output
stays bounded regardless of history size, that the filters narrow both
sections, and that --full still reaches everything.
"""
import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stdout

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "cli"))
import qldpc  # noqa: E402


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True,
                   capture_output=True, text=True)


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    """Build a throwaway board.

    25 codes across two families, one with a research note, and three
    fieldnotes carrying frontmatter.
    """
    r = tmp_path_factory.mktemp("board")
    for d in ("codes", "notes", "fieldnotes"):
        (r / d).mkdir()
    for i in range(25):
        fam = "bivariate-bicycle" if i % 2 else "lifted-product"
        (r / "codes" / f"{100 + i}-4-6.json").write_text(json.dumps(
            {"n": 100 + i, "k": 4, "family": fam, "name": f"test code {i}"}))
    (r / "notes" / "100-4-6.md").write_text("# note\n")
    for name, topics in (("a", "[bivariate-bicycle, calibration]"),
                         ("b", "[lifted-product]"),
                         ("c", "[budgeting]")):
        (r / "fieldnotes" / f"2026-01-0{ord(name) - 96}-{name}.md").write_text(
            f"---\ntitle: fieldnote {name}\ntopics: {topics}\n---\n\nbody\n")
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "t")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "board")
    return r


@pytest.fixture(autouse=True)
def _at(repo, monkeypatch):
    monkeypatch.setattr(qldpc, "_ROOT", str(repo))


def _run(*argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert qldpc.main(["recent", *argv]) == 0
    return buf.getvalue()


def test_default_output_is_bounded_and_says_what_it_held_back():
    out = _run()
    assert "25 codes (1 with a research note), 3 fieldnotes" in out
    assert out.count("[[") == 10           # the --limit default
    assert "... 15 more" in out


def test_limit_bounds_both_sections():
    out = _run("--limit", "2")
    assert out.count("[[") == 2
    assert "... 23 more" in out
    assert "... 1 more" in out             # fieldnotes: 3 shown as 2


def test_full_prints_every_row():
    out = _run("--full")
    assert out.count("[[") == 25
    assert "more (--limit" not in out


def test_family_filter_narrows_both_sections():
    out = _run("--family", "lifted-product", "--full")
    assert out.count("[[") == 13
    assert "fieldnote b" in out
    assert "fieldnote a" not in out
    assert "(of 25 codes and 3 fieldnotes in the window)" in out


def test_topic_filter_matches_fieldnote_topics():
    out = _run("--topic", "budgeting", "--full")
    assert out.count("[[") == 0
    assert "fieldnote c" in out
    assert "0 codes" in out


def test_fieldnote_summary_carries_the_title_and_topics():
    out = _run("--full")
    assert "fieldnote a  [bivariate-bicycle, calibration]" in out
