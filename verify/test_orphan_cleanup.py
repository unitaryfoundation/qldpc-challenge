"""Real Git diffs distinguish orphan edits from complete circuit cleanup."""

import subprocess

import check_authorship as authorship
import gate_changed as gate
import pytest


def git(root, *args):
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


@pytest.mark.parametrize(
    "case,expected",
    [
        ("edit_orphan", 1),
        ("add_orphan", 1),
        ("remove_orphan", 0),
        ("partial_cleanup", 1),
        ("remove_both", 0),
        ("remove_json_only", 1),
        ("rename_both", 0),
    ],
)
def test_orphan_cleanup(tmp_path, capsys, case, expected):
    git(tmp_path, "init", "-q", "-b", "main")
    code = tmp_path / "codes" / "old.json"
    code.parent.mkdir()
    circuits = tmp_path / "circuits" / "old"
    circuits.mkdir(parents=True)
    (tmp_path / "README.md").write_text("fixture\n")
    if case != "add_orphan":
        (circuits / "memory_x.stim").write_text("# x\n")
        (circuits / "memory_z.stim").write_text("# z\n")
    if case in ("remove_both", "remove_json_only", "rename_both"):
        code.write_text('{"provenance":{"authors":["@alice"]}}\n')
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "base")
    git(tmp_path, "checkout", "-qb", "change")
    if case in ("edit_orphan", "add_orphan"):
        (circuits / "memory_x.stim").write_text("# changed\n")
    elif case == "partial_cleanup":
        git(tmp_path, "rm", "circuits/old/memory_x.stim")
    elif case == "remove_orphan":
        git(tmp_path, "rm", "-r", "circuits/old")
    elif case == "remove_both":
        git(tmp_path, "rm", "-r", "codes/old.json", "circuits/old")
    elif case == "remove_json_only":
        git(tmp_path, "rm", "codes/old.json")
    else:
        git(tmp_path, "mv", "codes/old.json", "codes/new.json")
        git(tmp_path, "mv", "circuits/old", "circuits/new")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "change")
    assert authorship.main(["--root", str(tmp_path), "--base", "main", "--author", "alice"]) == expected
    output = capsys.readouterr().out
    if expected:
        assert "remaining circuits/ artifacts" in output
        assert "authors []" not in output
    if case == "rename_both":
        # Both sides of an exact rename stay visible regardless of similarity.
        assert set(gate.changed_codes("main", str(tmp_path))) == {"codes/old.json", "codes/new.json"}
        args = ["codes/old.json"]  # the removed side has no claim to refute
    else:
        args = []
    assert gate.main(["--code-root", str(tmp_path), "--seed", "1", "main", *args]) == expected
