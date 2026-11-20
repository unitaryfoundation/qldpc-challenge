"""Tests for `qldpc targets` (issue #639).

The command exists to tell a newcomer where to aim, so the property that
matters is that its numbers are the board's own. It reads the same cells() and
pareto() the site uses to award record stars; if it ever disagrees with them,
it is worse than not existing, because it would send people at cells that are
not actually open.
"""

import io
import os
import sys
from contextlib import redirect_stdout

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "cli"))
sys.path.insert(0, os.path.join(_ROOT, "site"))
import qldpc  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _cached_board():
    """Load the board once for the module.

    load_entries() runs the board's structural pass over every code -- minutes
    on today's board, not seconds -- and these tests call the command four
    times. Caching it keeps the CI job honest about what it is paying for; the
    logic under test is cmd_targets, not the loader.
    """
    from build import load_entries

    entries = load_entries()
    original = qldpc._load_board_entries
    qldpc._load_board_entries = lambda: entries
    yield
    qldpc._load_board_entries = original


def _run(*argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        qldpc.main(["targets", *argv])
    return buf.getvalue()


def test_runs_with_no_arguments_and_covers_every_populated_cell():
    from build import cells

    out = _run()
    populated = {c for e in qldpc._load_board_entries() for c in cells(e)}
    assert f"across {len(populated)} populated cells" in out
    assert out.count("nondominated") >= len(populated)


def test_counts_match_the_site_exactly():
    """Every cell's count must equal what the site computes, not approximate it."""
    from build import LOCALITY_LABEL, WEIGHT_LABEL, cells

    entries = qldpc._load_board_entries()
    by = {}
    for e in entries:
        for c in cells(e):
            by.setdefault(c, []).append(e)
    out = _run()
    for (loc, wt), peers in by.items():
        header = f"{LOCALITY_LABEL.get(loc, loc)} / {WEIGHT_LABEL.get(wt, wt)}"
        assert header in out, f"missing cell {header}"
        line = out.split(header, 1)[1].splitlines()[1]
        assert f"{len(peers)} codes" in line, f"{header}: printed {line.strip()!r}, board has {len(peers)}"


def test_cell_filter_narrows_and_rejects_nonsense():
    out = _run("--cell", "weight-6/unrestricted")
    assert "unrestricted / weight" in out
    assert "2D-local" not in out.split("populated cells")[0]
    with pytest.raises(SystemExit):
        _run("--cell", "not-a-cell")


def test_n_option_reports_what_must_be_beaten():
    out = _run("--cell", "unrestricted", "--n", "100")
    assert "at n <= 100" in out or "nothing at n <= 100" in out
