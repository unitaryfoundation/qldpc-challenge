"""An artifact whose entry does not exist must fail, and only then.

The check exists because nothing used to ask the question: 38 notes and 21
certificates sat in the tree for entries that had been deleted, invisible to
`check_prose.py` (which only reads files a PR changes) and to `check_certs.py`
(which validates a certificate without asking whether its entry survives).

The tests that matter most here are the ones about what is *not* a violation.
`notes/README.md` makes a note optional for an entry, so an entry with no note
is the documented state of roughly 170 codes and this checker must not touch
it; and the documentation files and the non-certificate files under `certs/`
are not artifacts of a code at all.
"""
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)

import check_tree_consistency as T  # noqa: E402


@pytest.fixture
def tree(tmp_path):
    """A minimal consistent tree: one entry, with a note, a cert, a circuit."""
    for d in ("codes", "notes", "certs", "circuits"):
        (tmp_path / d).mkdir()
    (tmp_path / "codes" / "12-4-2.json").write_text('{"n": 12}\n')
    (tmp_path / "notes" / "12-4-2.md").write_text("# [[12,4,2]]\n")
    (tmp_path / "certs" / "12-4-2.json").write_text("{}\n")
    (tmp_path / "circuits" / "12-4-2").mkdir()
    return tmp_path


def test_the_committed_tree_has_no_orphans():
    """The whole point: the repository this check guards must satisfy it."""
    assert T.main([]) == 0, "codes/, notes/, certs/ or circuits/ has an orphan"


def test_a_consistent_tree_passes(tree):
    assert T.main(["--root", str(tree)]) == 0
    assert T.scan(str(tree)) == {"notes": [], "certs": [], "circuits": []}


def test_a_note_with_no_entry_is_an_orphan(tree):
    (tree / "notes" / "18-2-5.md").write_text("# [[18,2,5]]\n")
    assert T.orphan_notes(str(tree)) == ["18-2-5"]
    assert T.main(["--root", str(tree)]) == 1


def test_a_certificate_with_no_entry_is_an_orphan(tree):
    (tree / "certs" / "18-2-5.json").write_text("{}\n")
    assert T.orphan_certificates(str(tree)) == ["18-2-5"]
    assert T.main(["--root", str(tree)]) == 1


def test_a_circuit_directory_with_no_entry_is_an_orphan(tree):
    (tree / "circuits" / "18-2-5").mkdir()
    assert T.orphan_circuits(str(tree)) == ["18-2-5"]
    assert T.main(["--root", str(tree)]) == 1


def test_an_entry_without_a_note_is_allowed(tree):
    """`notes/README.md` requests a note; it does not require one.

    Roughly 170 entries have none, including every literature baseline that
    took the exemption. Treating that as a failure would fail the whole board
    on a documented policy choice and push contributors towards filler.
    """
    (tree / "codes" / "18-2-5.json").write_text('{"n": 18}\n')
    assert T.scan(str(tree)) == {"notes": [], "certs": [], "circuits": []}
    assert T.main(["--root", str(tree)]) == 0


def test_the_note_documentation_is_not_a_note(tree):
    """notes/README.md documents the contract and TEMPLATE.md drafts into it."""
    (tree / "notes" / "README.md").write_text("# Research notes\n")
    (tree / "notes" / "TEMPLATE.md").write_text("# [[n,k,d]]\n")
    assert T.orphan_notes(str(tree)) == []


def test_non_certificate_files_under_certs_are_not_counted(tree):
    """heuristic/ has no schema and the batch log is not one cert per entry.

    The same non-recursive rule check_certs.py applies, for the same reason:
    making the glob recursive would fail the whole heuristic directory on a
    check that was never meant to cover it.
    """
    (tree / "certs" / "proof_log_batch.jsonl").write_text("{}\n")
    (tree / "certs" / "heuristic").mkdir()
    (tree / "certs" / "heuristic" / "99-9-9.json").write_text("{}\n")
    assert T.orphan_certificates(str(tree)) == []


def test_an_artifact_is_not_orphaned_by_a_sibling_slug(tree):
    """`18-2-5` present must not satisfy a citation of `18-2-5-s`."""
    (tree / "codes" / "18-2-5.json").write_text('{"n": 18}\n')
    (tree / "notes" / "18-2-5-s.md").write_text("# stabilizer variant\n")
    assert T.orphan_notes(str(tree)) == ["18-2-5-s"]


def test_a_tree_without_the_directories_is_refused(tmp_path, capsys):
    """Wrong --root must fail loudly rather than read as a clean board."""
    assert T.main(["--root", str(tmp_path)]) == 2
    assert "wrong --root" in capsys.readouterr().out


def test_the_real_tree_is_reachable_from_the_default_root():
    assert os.path.isdir(os.path.join(T.ROOT, "codes"))
    assert os.path.isdir(os.path.join(T.ROOT, "notes"))
    assert os.path.isdir(os.path.join(T.ROOT, "certs"))
    assert os.path.isdir(os.path.join(T.ROOT, "circuits"))
