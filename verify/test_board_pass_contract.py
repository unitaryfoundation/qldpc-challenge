"""One structural pass serves both consumers, and the split is written down.

`board_reports` is the single whole-board structural pass. Two consumers read
it: the gate (`validate_candidate._board_entries`) and the site
(`site/build.py`). Roughly a fifth of each entry's cost is the
`computed.diagnostics` block, which only the site reads, so moving it out of
`verify()` is a standing proposal (issue #2616).

The reason that proposal needs a guard is not the saving, it is the drift. If
the two consumers ever draw from different passes, or if a field one of them
needs stops being produced, the board and the gate can disagree about the
same code while both look healthy. So this pins three things:

* both consumers get the same report objects, not equal ones;
* every field each consumer reads is in that report;
* which fields belong to which consumer, so a split that drops one fails
  here rather than on the rendered board.

The field lists are the contract. Adding a read to either consumer without
adding it here is the mistake this catches.
"""
import glob
import json
import os
import re
import shutil
import sys

import pytest
import qldpc_verify as Q
import validate_candidate as V

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "site"))

# What verify/validate_candidate.py:_board_entries reads off each report.
# Everything the dedup and novelty decisions rest on.
GATE_READS = (
    "fingerprint",
    "signature.hash",
    "computed.weight_class",
    "computed.max_check_weight",
    "computed.locality_class",
)

# What site/build.py reads off each report between its board_reports loop and
# the entry it appends. `computed.diagnostics` is the block issue #2616
# proposes to move; it appears here and NOT in GATE_READS, which is the whole
# claim that moving it is safe for the gate.
SITE_READS = (
    "ok",
    "earned_distance",
    "computed.locality_class",
    "computed.weight_class",
    "computed.max_check_weight",
    "computed.diagnostics",
)

# Optional on a given entry (a code with no layout has no routing cost), so
# they are checked for being producible rather than present on every entry.
SITE_READS_OPTIONAL = (
    "computed.locality",
    "computed.routing_cost",
    "computed.transversal_gates",
    "computed.modules",
    "computed.flags",
)


def _resolve(report, path):
    """Walk a dotted path, returning (found, value)."""
    cur = report
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False, None
        cur = cur[part]
    return True, cur


def _fixture_of_type(code_type):
    """Path of any verifying fixture of this code_type.

    Chosen by reading the fixtures rather than by name. Naming one couples
    this test to a filename it has no stake in: it pinned 18-2-3.json, which
    #2599 deletes because that fixture is the very thing its new rule
    rejects, and the test then failed on a PR it has nothing to do with.
    What the test needs is one CSS and one stabilizer entry, not those two.
    """
    for path in sorted(glob.glob(os.path.join(_HERE, "fixtures", "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError):
            continue
        if doc.get("code_type", "CSS") == code_type and Q.verify(doc)["ok"]:
            return path
    raise AssertionError(f"no verifying {code_type} fixture in verify/fixtures")


@pytest.fixture
def board(tmp_path, monkeypatch):
    """Build a two-entry board, one CSS and one stabilizer, memo off."""
    monkeypatch.setenv("QLDPC_BOARD_CACHE", "")
    d = tmp_path / "codes"
    d.mkdir()
    for code_type in ("CSS", "stabilizer"):
        src = _fixture_of_type(code_type)
        shutil.copy(src, d / os.path.basename(src))
    Q._BOARD_CACHE.clear()
    return d


def test_both_consumers_read_the_same_report_objects(board, monkeypatch):
    """Not equal reports: the same objects, so divergence is unrepresentable.

    board_reports memoizes per board state and the entries are shared, which
    is what makes one pass serve everyone. A consumer that took its own pass
    would double the largest fixed cost in a run and could disagree with the
    other one.
    """
    passes = []
    real = Q.verify
    monkeypatch.setattr(
        Q, "verify",
        lambda doc, *a, **k: (passes.append(1), real(doc, *a, **k))[1])

    first = Q.board_reports(str(board))
    assert len(passes) == 2, "one structural verification per entry"
    assert Q.board_reports(str(board)) is first, "the second caller reuses it"
    assert len(passes) == 2, "and pays nothing"


@pytest.mark.parametrize("path", GATE_READS)
def test_the_gate_s_inputs_are_in_the_report(board, path):
    for e in Q.board_reports(str(board)):
        found, value = _resolve(e["report"], path)
        assert found, f"{e['slug']}: the gate reads {path} and it is absent"
        assert value is not None, f"{e['slug']}: {path} is None"


@pytest.mark.parametrize("path", SITE_READS)
def test_the_site_s_inputs_are_in_the_report(board, path):
    for e in Q.board_reports(str(board)):
        found, _ = _resolve(e["report"], path)
        assert found, f"{e['slug']}: the site reads {path} and it is absent"


def test_the_gate_does_not_read_the_diagnostics_block(board):
    """The claim that makes issue #2616's option 2 safe for the gate.

    `_board_entries` digests each report into the fields dedup and novelty
    use. If the girth, weight profile or trapping sets ever reach that digest,
    moving the block becomes a change to the gate and not an optimization.
    """
    entries = V._board_entries()
    assert entries, "expected the committed board, not an empty read"
    keys = set()
    for b in entries:
        keys |= set(b)
    assert "diagnostics" not in keys
    assert not any("girth" in k or "trapping" in k or "profile" in k
                   for k in keys), sorted(keys)


def test_the_site_s_board_loop_reads_nothing_this_file_does_not_list():
    """Keep the contract from going stale as build.py grows.

    A read added to the loop without being added above would make the lists
    here a description of the past. Scanning the source is crude and it is
    also the only thing that fails when someone forgets.
    """
    src = os.path.join(_ROOT, "site", "build.py")
    with open(src, encoding="utf-8") as f:
        lines = f.readlines()
    start = next(i for i, ln in enumerate(lines) if "board_reports(" in ln)
    body = "".join(lines[start:start + 160])

    known = {p.split(".")[-1] for p in SITE_READS + SITE_READS_OPTIONAL}
    known |= {"computed", "ok", "earned_distance"}
    seen = set(re.findall(r'rep\["computed"\]\.get\("([a-z_]+)"', body))
    seen |= set(re.findall(r'rep\["([a-z_]+)"\]', body))
    unlisted = sorted(seen - known)
    assert not unlisted, (
        "site/build.py reads report fields this contract does not list: "
        f"{unlisted}. Add them to SITE_READS so a split cannot drop them.")
