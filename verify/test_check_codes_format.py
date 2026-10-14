"""Tests for verify/check_codes_format.py: board JSON is json.dumps(doc, indent=1)."""
import json
import os
import subprocess
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import check_codes_format as ccf  # noqa: E402

DOC = {"schema_version": "0.3", "name": "[[4,1,1]] fixture", "n": 4, "k": 1,
       "checks": {"X": [[0, 1]], "Z": [[2, 3]]}}


def test_canonical_text_passes_with_or_without_the_trailing_newline():
    assert ccf.check_text(ccf.canonical(DOC)) is None
    assert ccf.check_text(json.dumps(DOC, indent=1)) is None
    assert ccf.check_text(json.dumps(DOC, indent=1, ensure_ascii=False) + "\n") is None


@pytest.mark.parametrize("text, why", [
    (json.dumps(DOC), "written on one line"),
    (json.dumps(DOC, indent=2) + "\n", "indent 2"),
    (json.dumps(DOC, indent=4) + "\n", "indent 4"),
    (json.dumps(DOC, indent=1, separators=(",", ": ")).replace("\n ", "\n\t") + "\n",
     "whitespace differs"),
    ("{not json", "not valid JSON"),
])
def test_non_canonical_text_is_named(text, why):
    assert why in ccf.check_text(text)


def test_fix_rewrites_in_place(tmp_path):
    p = tmp_path / "codes" / "4-1-1.json"
    p.parent.mkdir()
    p.write_text(json.dumps(DOC))
    assert ccf.check_file(str(p)) == "written on one line"
    ccf.fix_file(str(p))
    assert p.read_text() == ccf.canonical(DOC)
    assert ccf.check_file(str(p)) is None


def test_cli_names_the_file_and_the_fix(tmp_path, capsys):
    (tmp_path / "codes").mkdir()
    (tmp_path / "codes" / "4-1-1.json").write_text(json.dumps(DOC, indent=2) + "\n")
    rc = ccf.main(["--root", str(tmp_path), "--files", "codes/4-1-1.json"])
    out = capsys.readouterr().out
    assert rc == 1 and "codes/4-1-1.json: indent 2" in out and "--fix --files codes/4-1-1.json" in out
    assert ccf.main(["--root", str(tmp_path), "--fix", "--files", "codes/4-1-1.json"]) == 0
    assert ccf.main(["--root", str(tmp_path), "--files", "codes/4-1-1.json"]) == 0


def test_only_changed_codes_files_are_diffed(tmp_path):
    def git(*a):
        subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)
    git("init", "-q", "-b", "main")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base")
    (tmp_path / "codes").mkdir()
    (tmp_path / "notes").mkdir()
    (tmp_path / "codes" / "4-1-1.json").write_text(json.dumps(DOC))
    (tmp_path / "codes" / "README.md").write_text("x\n")
    (tmp_path / "notes" / "4-1-1.md").write_text("# [[4,1,1]]\n")
    git("checkout", "-q", "-b", "pr")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "add")
    assert ccf.changed_codes("main", str(tmp_path)) == ["codes/4-1-1.json"]
    assert ccf.main(["--root", str(tmp_path), "--base", "main"]) == 1
    ccf.fix_file(str(tmp_path / "codes" / "4-1-1.json"))
    assert ccf.main(["--root", str(tmp_path), "--base", "main"]) == 0


def test_a_failed_diff_fails_closed(tmp_path):
    assert ccf.changed_codes("nonexistent-base", str(tmp_path)) is None
    assert ccf.main(["--root", str(tmp_path), "--base", "nonexistent-base"]) == 1
