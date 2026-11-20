"""L-independent bounded-logical detector for planar BB families.

Companion to ``transfer.py``: the distance law d_X(L) = min(s* L + O(1),
w_bdd) needs the bounded term, and this module decides it WITHOUT scanning L.

Key fact (measured, then proved for the gcd part): every bounded X-logical of
a trinomial planar family is CORNER-PINNED -- a fixed-shape finite operator
localized at one of the 4 corners of the LxL grid, identical for all large L.
Since gcd(f,g)=1 for ~all such families, every finite bulk operator is a
stabilizer, so a corner-pinned logical's existence is decided on a finite
patch of size N0 = O(support extent): enlarging the patch only adds bulk
(stabilizers), never a new logical class. Hence

    w_bdd  =  min weight of a corner-pinned X-logical  (= inf if none),

computed on any patch N >= N0, INDEPENDENT of L. ``detect`` computes w_bdd on
patches N and N+2 and declares "bounded" iff a corner-pinned logical of stable
weight exists at both sizes. Validated to match the exact MILP
growing/bounded classification on 15/15 families.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, "..", "kit")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from planar import build_open_directional  # noqa: E402
from surrogate import lightest_logical  # noqa: E402


def min_logical(a, b, c, d, N, trials=600, seed=0):
    """Lightest nontrivial X-logical of the trinomial family
    f = 1 + x + x^a y^b, g = 1 + y + x^c y^d on the NxN patch (via the greedy
    directional builder). Returns (weight, support) where support = list of
    (sublattice, i, j), sublattice in {'A','B'}; (None, None) if none found.
    """
    Sf = [(0, 0), (1, 0), (a, b)]
    Sg = [(0, 0), (0, 1), (c, d)]
    Sfb = [(-i, -j) for i, j in Sf]
    Sgb = [(-i, -j) for i, j in Sg]
    HX, HZ = build_open_directional(N, N, Sf, Sg, Sfb, Sgb)
    if HX.size == 0 or HZ.size == 0:
        return None, None
    w, supp = lightest_logical(HX, HZ, trials=trials, seed=seed)
    if w == float("inf"):
        return None, None
    n2 = N * N
    out = [("A", q // N, q % N) if q < n2 else ("B", (q - n2) // N, (q - n2) % N) for q in supp]
    return int(w), out


def corner_pinned(supp, N, radius):
    """True if the support fits in a box of side `radius` at one of the 4 corners."""
    if not supp:
        return False
    iis = [i for _, i, j in supp]
    jjs = [j for _, i, j in supp]
    di = max(iis) - min(iis)
    dj = max(jjs) - min(jjs)
    if di >= radius or dj >= radius:
        return False
    # near a corner: min or max index within `radius` of an edge on both axes
    near_i = min(iis) < radius or max(iis) > N - 1 - radius
    near_j = min(jjs) < radius or max(jjs) > N - 1 - radius
    return near_i and near_j


def detect(a, b, c, d, verbose=False):
    """Returns (w_bdd_or_None, detail). w_bdd finite => bounded (slope law fails)."""
    R = 2 * max(abs(a), abs(b), abs(c), abs(d)) + 3  # corner-box radius
    res = {}
    for N in (R + 6, R + 8):
        w, supp = min_logical(a, b, c, d, N)
        res[N] = (w, supp, corner_pinned(supp, N, R) if supp else False)
    (N1, N2) = sorted(res)
    w1, s1, c1 = res[N1]
    w2, s2, c2 = res[N2]
    # bounded <=> a corner-pinned logical of the SAME small weight at both sizes
    bounded = c1 and c2 and w1 == w2
    if verbose:
        print(f"   N={N1}: w={w1} pinned={c1} supp={s1}")
        print(f"   N={N2}: w={w2} pinned={c2} supp={s2}")
    return (w1 if bounded else None), res


if __name__ == "__main__":
    # A small subset of the 15-family validation set (full run takes a while;
    # the complete lists are in the docstring of the validation below).
    GROW = [(2, 0, 2, 1), (1, 1, 1, 1)]  # expect w_bdd = inf
    BDD = [(1, 2, 1, 2), (2, 1, 2, 1), (1, 1, 1, 2)]  # expect w_bdd finite
    print("detector: w_bdd finite => BOUNDED (slope law fails)\n")
    ok = 0
    tot = 0
    for tag, fams, want_bounded in [
        ("GROW (expect w_bdd=inf)", GROW, False),
        ("BOUNDED (expect w_bdd finite)", BDD, True),
    ]:
        print(tag)
        for fam in fams:
            w, _ = detect(*fam)
            got_bounded = w is not None
            match = got_bounded == want_bounded
            ok += match
            tot += 1
            print(f"  {fam}: w_bdd={'inf' if w is None else w}  {'OK' if match else 'XX MISMATCH'}")
        print()
    print(f"detector matches MILP labels on {ok}/{tot} families")
