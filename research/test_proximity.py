"""Proximity profile on a hand-built detector error model (issue #6242, campaign 3)."""
import os
import sys

import stim

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (os.path.join(_ROOT, "verify"), os.path.join(_ROOT, "research", "kit")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import circuit_tools as ct  # noqa: E402
import proximity as px  # noqa: E402

# A chain D0 - D1 - D2 with the observable on the left boundary: the lightest
# undetected logical fault set along the chain is {0, 1, 2, 3} (weight 4);
# mechanism 4 shortcuts D0 to D2, so {0, 4, 3} (weight 3) also completes 0.
CHAIN = """
error(0.01) D0 L0
error(0.01) D0 D1
error(0.01) D1 D2
error(0.01) D2
error(0.01) D0 D2
"""


def _cols():
    return ct.dem_columns(stim.DetectorErrorModel(CHAIN))


def test_proximity_finds_the_shortcut_inside_the_neighborhood():
    cols = _cols()
    by_det = px.fault_adjacency(cols)
    Q = px.neighborhood(cols, by_det, 0, (0, 1, 2, 3), size=8)
    assert set(Q) == {0, 1, 2, 3, 4}
    assert px.proximity(cols, 0, Q, cap=3) == (2, 1)          # {0, 4, 3}, the only one
    assert px.proximity(cols, 1, Q, cap=3) == (3, 1)          # 1 needs 0, 2, 3
    assert px.proximity(cols, 0, [0, 1, 2, 3], cap=3) == (3, 1)   # without the shortcut
    assert px.proximity(cols, 0, [0, 1, 2], cap=3) == (None, 0)   # no completion at all


def test_profile_reads_the_minimum_over_the_witness_seeds():
    prof = px.profile(_cols(), [(0, 1, 2, 3)], size=8)
    assert prof["seeds"] == 4 and prof["p_min"] == 2 and prof["at_min"] == 2
    assert prof["per_seed"] == {0: [2, 1], 1: [3, 1], 2: [3, 1], 3: [2, 1]}
    assert prof["completions"] == 1.0
    assert px.schedule_key({"Z": prof, "X": prof}) == (2, prof["p_mean"], -1.0)


def test_neighborhood_is_capped_and_deterministic():
    cols = _cols()
    by_det = px.fault_adjacency(cols)
    Q = px.neighborhood(cols, by_det, 3, (3,), size=2)
    assert Q == [3, 2] and px.neighborhood(cols, by_det, 3, (3,), size=2) == Q


def test_milp_agrees_with_the_enumeration_on_the_chain():
    cols = _cols()
    Q = [0, 1, 2, 3, 4]
    assert px.proximity_milp(cols, 0, Q, cap=3) == 2
    assert px.proximity_milp(cols, 1, Q, cap=3) == 3
    assert px.proximity_milp(cols, 0, [0, 1, 2, 3], cap=3) == 3
    assert px.proximity_milp(cols, 0, [0, 1, 2], cap=3) is None


def test_hook_profile_on_the_chain():
    cols = _cols()
    by_det = px.fault_adjacency(cols)
    Q = px.neighborhood_layers(cols, by_det, (0, 1, 2, 3), size=10)
    assert Q == [0, 1, 2, 3, 4]
    # the shortcut fires two detectors; with min_detectors 2 it is the one hook seed
    assert px.hook_seeds(cols, Q, (0, 1, 2, 3), min_detectors=2) == [4]
    prof = px.profile_hooks(cols, (0, 1, 2, 3), size=10, min_detectors=2)
    assert prof["seeds"] == 1 and prof["p_min"] == 2 and prof["cap"] == 3   # {4} + {0, 3}
