"""Test the verifier's displayed-only diagnostics (issue #1844).

Tanner girth, weight profiles, bounded trapping-set counts, and witness
support diameter. Each is checked on a small code whose answer is known by hand and,
for girth and trapping sets, against a brute-force reference on the fixture.

Run: uv run pytest verify/test_diagnostics.py
"""

import copy
import json
import math
import os
from itertools import combinations

import qldpc_verify as V

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(ROOT, "verify", "fixtures", "72-6-6.json")


def steane_checks():
    """Return the [7,4] Hamming parity checks; H_X = H_Z for the Steane code."""
    return [[3, 4, 5, 6], [1, 2, 5, 6], [0, 2, 4, 6]]


def toric_code(L):
    """Build Kitaev's toric code on an L x L torus.

    Qubits sit on edges (horizontal edge (i, j) is 2(iL + j), vertical is
    2(iL + j) + 1), X checks on vertices, Z checks on plaquettes, and one
    [x, y] per edge midpoint (doubled so distinct sites are at least 1 apart).
    """

    def h(i, j):
        return 2 * ((i % L) * L + (j % L))

    def v(i, j):
        return h(i, j) + 1

    X = [sorted([h(i, j), h(i, j - 1), v(i, j), v(i - 1, j)]) for i in range(L) for j in range(L)]
    Z = [sorted([h(i, j), h(i + 1, j), v(i, j), v(i, j + 1)]) for i in range(L) for j in range(L)]
    coords = [None] * (2 * L * L)
    for i in range(L):
        for j in range(L):
            coords[h(i, j)] = [2 * j + 1, 2 * i]
            coords[v(i, j)] = [2 * j, 2 * i + 1]
    return X, Z, coords


def brute_girth(checks, n):
    """Compute the girth by a full BFS from every vertex, no pruning."""
    nbr = V._side_graph(checks, n)
    best = math.inf
    for s in range(len(nbr)):
        dist = {s: 0}
        parent = {s: None}
        queue = [s]
        for u in queue:
            for w in nbr[u]:
                if w not in dist:
                    dist[w] = dist[u] + 1
                    parent[w] = u
                    queue.append(w)
                elif parent[u] != w:
                    best = min(best, dist[u] + dist[w] + 1)
    return None if best == math.inf else best


def brute_trapping_sets(checks, n, max_size):
    """Count every connected qubit set of size <= max_size exhaustively."""
    inc = [set() for _ in range(n)]
    for i, s in enumerate(checks):
        for q in s:
            inc[q].add(i)
    counts = {}
    for a in range(1, max_size + 1):
        for S in combinations(range(n), a):
            seen = {S[0]}
            stack = [S[0]]
            while stack:
                x = stack.pop()
                for y in S:
                    if y not in seen and inc[x] & inc[y]:
                        seen.add(y)
                        stack.append(y)
            if len(seen) != a:
                continue
            parity = {}
            for q in S:
                for c in inc[q]:
                    parity[c] = parity.get(c, 0) ^ 1
            b = sum(parity.values())
            counts[(a, b)] = counts.get((a, b), 0) + 1
    return sorted([a, b, c] for (a, b), c in counts.items())


def test_girth_steane_has_four_cycles():
    # rows 2 and 3 of the Hamming matrix share qubits 2 and 6
    assert V.tanner_girth(steane_checks(), 7) == 4


def test_girth_toric_is_eight():
    # on the square lattice two plaquettes share at most one edge (no
    # 4-cycle) and, once L >= 4, no three are pairwise adjacent (no 6-cycle);
    # the four plaquettes around a vertex close an 8-cycle. Same for vertices.
    X, Z, _ = toric_code(4)
    assert V.tanner_girth(X, 32) == 8
    assert V.tanner_girth(Z, 32) == 8
    # on the 3-torus the three plaquettes of one row are pairwise adjacent
    X, Z, _ = toric_code(3)
    assert V.tanner_girth(X, 18) == 6
    assert V.tanner_girth(Z, 18) == 6


def test_girth_acyclic_side_reports_none():
    # a path check-qubit-check-qubit-... is a tree
    assert V.tanner_girth([[0, 1], [1, 2], [2, 3]], 4) is None
    assert V.tanner_girth([], 3) is None
    # one isolated cycle: two checks sharing two qubits
    assert V.tanner_girth([[0, 1], [0, 1]], 2) == 4


def test_girth_matches_brute_force_on_fixture_and_verify_reports_it():
    doc = json.load(open(FIXTURE))
    for side in ("X", "Z"):
        assert V.tanner_girth(doc["checks"][side], doc["n"]) == brute_girth(doc["checks"][side], doc["n"])
    X, Z, _ = toric_code(4)
    assert V.tanner_girth(X, 32) == brute_girth(X, 32) == 8
    rep = V.verify(doc)
    assert rep["ok"]
    diag = rep["computed"]["diagnostics"]
    assert diag["tanner_girth"] == {side: V.tanner_girth(doc["checks"][side], doc["n"]) for side in "XZ"}


def test_verify_reports_acyclic_as_a_string():
    doc = {
        "schema_version": "0.1",
        "name": "path",
        "code_type": "CSS",
        "n": 3,
        "k": 1,
        "checks": {"X": [[0, 1], [1, 2]], "Z": [[0, 1, 2]]},
        "distance": {
            "d": 1,
            "X": {"value": 1, "confidence": "upper_bound", "witness": [0]},
            "Z": {"value": 1, "confidence": "upper_bound", "witness": [0]},
        },
        "provenance": {"authors": ["@test"], "construction": "synthetic"},
    }
    rep = V.verify(doc)  # k = 0 fails the gate; the diagnostics still run
    assert rep["computed"]["diagnostics"]["tanner_girth"] == {"X": "acyclic", "Z": "acyclic"}


def test_weight_profile_steane():
    prof = V.weight_profile(steane_checks(), 7)
    assert prof["row"] == {"min": 4, "max": 4, "mean": 4.0}
    # Hamming columns are the nonzero 3-bit strings: weights 1,1,1,2,2,2,3
    assert prof["column"] == {"min": 1, "max": 3, "mean": round(12 / 7, 3)}
    # an untouched qubit has column weight 0
    assert V.weight_profile([[0, 1]], 3)["column"]["min"] == 0


def test_trapping_sets_toric_by_hand():
    X, Z, _ = toric_code(3)
    ts = V.trapping_sets(X, 18)
    assert ts["complete_through_size"] == 3
    counts = {(a, b): c for a, b, c in ts["counts"]}
    # every edge sits in two vertex checks: 18 (1,2) sets
    assert counts[(1, 2)] == 18
    # two edges sharing one vertex: syndrome weight 2 + 2 - 2 = 2; each of
    # the 9 vertices contributes C(4,2) = 6 such pairs
    assert counts[(2, 2)] == 54
    assert not any(a == 2 and b != 2 for (a, b) in counts)
    # a straight path of three edges around a 3-cycle of the torus meets its
    # three vertices twice each: a (3,0) set, 3 rows + 3 columns of them
    assert counts[(3, 0)] == 6


def test_trapping_sets_match_brute_force():
    for checks, n in ((steane_checks(), 7), toric_code(3)[:1] + (18,)):
        assert V.trapping_sets(checks, n)["counts"] == brute_trapping_sets(checks, n, 3)
    doc = json.load(open(FIXTURE))
    for side in ("X", "Z"):
        got = V.trapping_sets(doc["checks"][side], doc["n"])
        assert got["complete_through_size"] == 3
        assert got["counts"] == brute_trapping_sets(doc["checks"][side], doc["n"], 3)


def test_trapping_sets_stop_at_the_cost_cap():
    X, _, _ = toric_code(3)
    ts = V.trapping_sets(X, 18, max_candidates=1)
    assert ts["complete_through_size"] == 2
    assert max(a for a, _, _ in ts["counts"]) == 2
    assert V.trapping_sets(X, 18, max_size=1)["complete_through_size"] == 1
    # no two qubits share a check: nothing connected above size 1, complete
    assert V.trapping_sets([[0], [1]], 2)["complete_through_size"] == 3


def test_support_diameter_and_logical_diameter_in_verify():
    X, Z, coords = toric_code(3)
    # a horizontal Z-logical: the three horizontal edges of row 0, at
    # x = 1, 3, 5 and y = 0, spread 4 apart
    row = [0, 2, 4]
    assert V.support_diameter(coords, row) == 4.0
    # an X-logical is a dual loop: all three vertical edges of row 0, at
    # x = 0, 2, 4 and y = 1, so each plaquette of that row meets it twice
    col = [1, 3, 5]
    assert V.support_diameter(coords, col) == 4.0
    assert V.support_diameter(coords, [0]) == 0.0
    assert math.isclose(V.support_diameter([[0, 0], [1, 1]], [0, 1]), math.sqrt(2))
    doc = {
        "schema_version": "0.1",
        "name": "toric 3",
        "code_type": "CSS",
        "n": 18,
        "k": 2,
        "checks": {"X": X, "Z": Z},
        "distance": {
            "d": 3,
            "X": {"value": 3, "confidence": "upper_bound", "witness": col},
            "Z": {"value": 3, "confidence": "upper_bound", "witness": row},
        },
        "locality": {"coordinates": coords, "layers": 1},
        "provenance": {"authors": ["@test"], "construction": "toric code L=3"},
    }
    rep = V.verify(doc)
    assert rep["ok"], [c for c in rep["checks"] if not c["ok"]]
    assert rep["computed"]["diagnostics"]["logical_diameter"] == {"X": 4.0, "Z": 4.0}
    # without a layout the diameter is not reported at all
    bare = copy.deepcopy(doc)
    del bare["locality"]
    rep = V.verify(bare)
    assert rep["ok"]
    assert "logical_diameter" not in rep["computed"]["diagnostics"]
    assert rep["computed"]["diagnostics"]["tanner_girth"] == {"X": 6, "Z": 6}
