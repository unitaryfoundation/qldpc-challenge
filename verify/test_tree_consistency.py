"""An artifact whose entry does not exist must fail, and only then.

The check exists because nothing used to ask the question: 38 notes and 21
certificates sat in the tree for entries that had been deleted, invisible to
`check_prose.py` (which only reads files a PR changes) and to `check_certs.py`
(which validates a certificate without asking whether its entry survives).

Everything here runs against a synthetic tree. The committed tree is the CI
step's business, not the suite's: `test_the_committed_tree_has_no_orphans`
used to sweep the repository too, so a contributor who had removed an entry
on a branch and not yet cleaned up after it got a second, unrelated-looking
failure for the same cause the dedicated step already reports (#946 -> #986:
mechanism tests take fixtures, they do not assert live board state).

The tests that matter most here are the ones about what is *not* a violation.
`notes/README.md` makes a note optional for an entry, so an entry with no note
is the documented state of roughly 170 codes and this checker must not touch
it; and the documentation files and the non-artifact files under `certs/` and
`receipts/ler/` are not artifacts of a code at all.
"""

import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import check_tree_consistency as T  # noqa: E402


@pytest.fixture
def tree(tmp_path):
    """Build a minimal consistent tree: one entry, with an artifact per kind."""
    for d in T.REQUIRED:
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "codes" / "12-4-2.json").write_text('{"n": 12}\n')
    (tmp_path / "notes" / "12-4-2.md").write_text("# [[12,4,2]]\n")
    (tmp_path / "certs" / "12-4-2.json").write_text("{}\n")
    (tmp_path / "certs" / "heuristic" / "12-4-2.json").write_text("{}\n")
    (tmp_path / "receipts" / "ler" / "12-4-2.json").write_text("{}\n")
    (tmp_path / "circuits" / "12-4-2").mkdir()
    return tmp_path


def orphans(tree):
    """Every orphan in this tree, by kind."""
    return T.scan(str(tree))


def test_a_consistent_tree_passes(tree):
    assert T.main(["--root", str(tree)]) == 0
    assert orphans(tree) == {name: [] for name in T.KINDS}


def test_a_note_with_no_entry_is_an_orphan(tree):
    (tree / "notes" / "18-2-5.md").write_text("# [[18,2,5]]\n")
    assert orphans(tree)["notes"] == ["18-2-5"]
    assert T.main(["--root", str(tree)]) == 1


def test_a_certificate_with_no_entry_is_an_orphan(tree):
    (tree / "certs" / "18-2-5.json").write_text("{}\n")
    assert orphans(tree)["certs"] == ["18-2-5"]
    assert T.main(["--root", str(tree)]) == 1


def test_a_heuristic_certificate_with_no_entry_is_an_orphan(tree):
    """check_certs.py cannot validate heuristic/ (no schema), and does not.

    The question this sweep asks of a file there is the one it can answer
    without a schema: it is filed under an entry's slug, so does the entry
    exist? Six such files are committed today, none of them orphaned.
    """
    (tree / "certs" / "heuristic" / "18-2-5.json").write_text("{}\n")
    assert orphans(tree)["heuristic"] == ["18-2-5"]
    assert T.main(["--root", str(tree)]) == 1


def test_a_receipt_with_no_entry_is_an_orphan(tree):
    """A measured rate outlives its entry exactly as a certificate does.

    `site/` reads `receipts/ler/<slug>.json` only through an existing entry,
    so an orphaned receipt is neither shown nor noticed: the same invisible
    orphan the 38 notes were.
    """
    (tree / "receipts" / "ler" / "18-2-5.json").write_text("{}\n")
    assert orphans(tree)["receipts"] == ["18-2-5"]
    assert T.main(["--root", str(tree)]) == 1


def test_a_circuit_directory_with_no_entry_is_an_orphan(tree):
    (tree / "circuits" / "18-2-5").mkdir()
    assert orphans(tree)["circuits"] == ["18-2-5"]
    assert T.main(["--root", str(tree)]) == 1


def test_an_entry_without_a_note_is_allowed(tree):
    """`notes/README.md` requests a note; it does not require one.

    Roughly 170 entries have none, including every literature baseline that
    took the exemption. Treating that as a failure would fail the whole board
    on a documented policy choice and push contributors towards filler. The
    same one-way rule holds for every other kind in KINDS: an entry is never
    asked to justify its artifacts.
    """
    (tree / "codes" / "18-2-5.json").write_text('{"n": 18}\n')
    assert orphans(tree) == {name: [] for name in T.KINDS}
    assert T.main(["--root", str(tree)]) == 0


def test_the_documentation_is_not_an_artifact(tree):
    """Sweep files that live in an artifact directory without belonging to an entry."""
    (tree / "notes" / "README.md").write_text("# Research notes\n")
    (tree / "notes" / "TEMPLATE.md").write_text("# [[n,k,d]]\n")
    (tree / "certs" / "proof_log_batch.jsonl").write_text("{}\n")
    (tree / "receipts" / "ler" / "README.md").write_text("# Receipts\n")
    assert orphans(tree) == {name: [] for name in T.KINDS}


def test_an_artifact_is_not_orphaned_by_a_sibling_slug(tree):
    """`18-2-5` present must not satisfy a citation of `18-2-5-s`."""
    (tree / "codes" / "18-2-5.json").write_text('{"n": 18}\n')
    (tree / "notes" / "18-2-5-s.md").write_text("# stabilizer variant\n")
    assert orphans(tree)["notes"] == ["18-2-5-s"]


def test_the_report_spells_each_artifact_path(tree, capsys):
    """The listing names the real path, so what it prints is what to delete."""
    (tree / "certs" / "heuristic" / "18-2-5.json").write_text("{}\n")
    (tree / "receipts" / "ler" / "18-2-6.json").write_text("{}\n")
    (tree / "circuits" / "18-2-7").mkdir()
    assert T.main(["--root", str(tree)]) == 1
    out = capsys.readouterr().out
    for path in ("certs/heuristic/18-2-5.json", "receipts/ler/18-2-6.json", "circuits/18-2-7/"):
        assert f"    {path}" in out


def test_a_tree_without_the_directories_is_refused(tmp_path, capsys):
    """Wrong --root must fail loudly rather than read as a clean board."""
    assert T.main(["--root", str(tmp_path)]) == 2
    assert "wrong --root" in capsys.readouterr().out


def test_the_real_tree_has_every_directory_this_sweep_reads():
    """The default root is this repository, and the sweep needs all of them."""
    for d in T.REQUIRED:
        assert os.path.isdir(os.path.join(T.ROOT, d)), d
