"""The support invariant must agree with brute force and with the paper's counts.

Three checks, all on codes small enough that nothing here is slow or pinned
to board data: the meet-in-the-middle kernel enumeration against a full
2^n sweep on the 18-qubit weighted-seed code; the paper's own numbers for
that code (38 minimum supports, minimum stabilizer weight 6, a weight-3
logical); and the automorphism count of the Steane code's incidence graph
(|PGL(3,2)| = 168) through whichever backend is installed.

Run: uv run pytest research/test_supports.py
"""

import itertools

import numpy as np
from group_algebra import build_paper_instance
from supports import automorphisms, low_weight_kernel, split_stabilizers


def _brute_kernel(H, wmax):
    H = np.asarray(H) % 2
    n = H.shape[1]
    out = set()
    for w in range(1, wmax + 1):
        for S in itertools.combinations(range(n), w):
            x = np.zeros(n, dtype=np.int8)
            x[list(S)] = 1
            if not ((H @ x) % 2).any():
                out.add(frozenset(S))
    return out


def test_low_weight_kernel_matches_brute_force_on_18_4_3():
    HX, HZ = build_paper_instance("c3w-18-4-3")
    for H in (HX, HZ):
        for wmax in (3, 6, 7):
            found, _ = low_weight_kernel(H, wmax)
            assert found == _brute_kernel(H, wmax)


def test_paper_counts_for_the_weighted_18_4_3():
    HX, HZ = build_paper_instance("c3w-18-4-3")
    n = HX.shape[1]
    xs, xl = split_stabilizers(low_weight_kernel(HZ, 6)[0], HX, n)
    zs, zl = split_stabilizers(low_weight_kernel(HX, 6)[0], HZ, n)
    assert min(len(v) for v in xs | zs) == 6
    assert len({v for v in xs | zs if len(v) == 6}) == 38  # paper, Sec. 5
    assert min(len(v) for v in xl) == 3 and min(len(v) for v in zl) == 3


def test_steane_incidence_graph_has_168_automorphisms():
    H = np.array([[1, 0, 1, 0, 1, 0, 1], [0, 1, 1, 0, 0, 1, 1], [0, 0, 0, 1, 1, 1, 1]], dtype=np.int8)
    sup = {v for v in low_weight_kernel(H, 4)[0] if len(v) == 4}
    assert len(sup) == 7
    order, orbits, _backend, capped = automorphisms(7, sup)
    assert (order, orbits, capped) == (168, [7], False)
