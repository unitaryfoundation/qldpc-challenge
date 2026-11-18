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


def test_row_sort_yields_sorted_rows():
    from local_sat import row_sort_symmetry_selftest
    stats = row_sort_symmetry_selftest()
    assert stats["unsorted"] == 0
    assert stats["models"] > 0


def test_cube_isometries_form_a_group_of_48_and_keep_the_orbit_key_invariant():
    import numpy as np
    from local_sat import _site_permutations, orbit_canonical_key
    perms = _site_permutations(3, dimension=3)
    assert len(perms) == len(set(perms)) == 48
    members = set(perms)
    for p in perms:
        for q in perms:
            assert tuple(p[q[i]] for i in range(27)) in members
    rng = np.random.default_rng(1)
    HX = rng.integers(0, 2, size=(3, 27)).astype(np.int8)
    HZ = rng.integers(0, 2, size=(3, 27)).astype(np.int8)
    ref = orbit_canonical_key(3, 3, HX, HZ, perms=perms)
    for p in perms[::4]:
        M = np.vstack([HX, HZ])[:, list(p)]
        assert orbit_canonical_key(3, 3, M[:3], M[3:], perms=perms) == ref


def test_a_cube_cell_yields_codes_whose_checks_respect_the_diameter():
    import math

    from local_sat import enumerate_local_sat_codes
    out = list(enumerate_local_sat_codes(2, 2, 4, 1, math.sqrt(3), dimension=3,
                                         max_diameter=math.sqrt(2), max_codes=3))
    assert out
    for spec, HX, HZ in out:
        sites = spec["sites"]
        assert spec["dimension"] == 3 and len(sites) == 8 and len(sites[0]) == 3
        for H in (HX, HZ):
            for row in H:
                sup = [q for q in range(len(row)) if row[q]]
                assert all(math.dist(sites[a], sites[b]) <= math.sqrt(2) + 1e-9
                           for a in sup for b in sup)
