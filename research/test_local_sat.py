"""Regression test for the lex symmetry break in local_sat.py.

Asserted: the break yields at most one model per D4+XZ group-orbit, so a
broken break cannot silently duplicate codes. lex_symmetry_selftest sits
under `if __name__ == "__main__"` in local_sat.py, which run_tests.py never
executes; this module makes it a collected test.

Not covered: drop detection. Set equality with the unconstrained run is the
assertion that would catch a break silently removing codes, but no cheap
exhaustible cell exists for it (3x3 at G = 3 and G = 4 blow past a
4000-model cap in single-digit seconds; 4x4 at G = 3 is empty), so the
comparison windows are truncated and non-comparable. A dropped orbit looks
identical to a genuinely empty cell -- the worse failure for a search tool
-- so treat that property as open.

Run: uv run pytest research/test_local_sat.py
"""

import pytest

pytest.importorskip("pysat")

from local_sat import lex_symmetry_selftest  # noqa: E402


def test_lex_yields_at_most_one_per_d4xz_orbit():
    stats = lex_symmetry_selftest()
    assert stats["lex_yields"] == stats["lex_group_orbits"] > 0
