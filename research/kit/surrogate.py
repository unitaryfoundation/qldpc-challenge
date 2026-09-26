"""Cheap distance surrogates for screening codes -- and, as a free byproduct,
the explicit logical-operator *witnesses* a submission needs.

Two tools:

* ``mixed_volume(S_f, S_g)`` -- a matrix-free upper bound on k for a bivariate
  two-monomial-set construction (the Bernstein-Kushnirenko / mixed-volume
  bound; tight on the BB trinomial families). Use it to filter millions of
  candidate exponent sets before building any matrix.

* ``distance_rand_witness`` / ``distance_rand`` / ``lightest_logical`` -- a
  randomized GF(2) coset-leader search for a low-weight nontrivial logical
  operator. This is the cheap stand in for an exact distance solver.
  ``distance_rand_witness`` returns the operator itself and is the entry point
  for a caller that has to write the witness down; ``distance_rand`` is its
  weight. Both take ``pair_depth`` and both validate whatever a backend
  proposes through ``validate_logical`` before returning it.

HONEST SEMANTICS. ``distance_rand`` returns an **upper bound** on the true
distance: it found *a* logical of that weight, so d <= that. It is Monte Carlo,
not a proof. In practice, for small d, raise ``trials`` until the value stops
dropping (e.g. ``distance_rand(.., trials=t)`` == ``distance_rand(.., trials=2*t)``)
and treat that as a confident upper bound. The matching ``confidence`` for a
submission built this way is ``"upper_bound"``; an ``"exact"`` claim is a
separate, server-certified tier (see ``verify/certify.py``). The witness this
search returns is exactly what the verifier checks to certify the upper bound.

The default path is pure numpy. An optional ``gf2_fast`` backend accelerates the
randomized screening search after ``make fast``; no exact-solver or decoder
dependency is needed here.
"""
from collections import namedtuple

import numpy as np

from css import kernel_basis, logical_basis, commutes, in_rowspace

try:
    import gf2_fast as _fast
except ImportError:
    _fast = None


class LogicalWitness(namedtuple("LogicalWitness",
                                "weight side support rejected")):
    """A logical operator found by the search, or the absence of one.

    ``weight`` is its Hamming weight and an upper bound on the distance;
    ``side`` is 'X' or 'Z'; ``support`` is the sorted qubit list, which is
    exactly the witness a submission carries. When no logical was found, or
    when a backend's proposal failed Python validation, ``weight`` is
    ``float("inf")``, ``side`` is ``""`` and ``support`` is empty -- so
    ``if witness:`` reads as "something was found".

    ``rejected`` is empty except in the second case, where it carries the
    reason validation refused the proposal. A caller that wants to know the
    difference between "searched and found nothing" and "the backend proposed
    something that is not a logical" reads that field; both are a
    no-logical result for scoring.
    """

    __slots__ = ()

    def __bool__(self):
        return self.side in ("X", "Z")


NO_LOGICAL = LogicalWitness(float("inf"), "", [], "")


def validate_logical(HX, HZ, side, weight, support):
    """Re-check a proposed logical against the raw matrices: ``(ok, reason)``.

    The one validator in the kit. A witness is a logical of its side iff it
    commutes with the opposite checks and is not a product of its own -- the
    same two conditions the board's verifier applies, checked here in Python
    whichever backend proposed it.
    """
    if side not in ("X", "Z"):
        return False, "no witness"
    n = int(np.asarray(HX).shape[1])
    support = [int(q) for q in support]
    if len(support) != len(set(support)) or any(q < 0 or q >= n for q in support):
        return False, "bad support"
    if len(support) != int(weight):
        return False, "weight != support size"
    v = np.zeros(n, dtype=np.int8)
    v[support] = 1
    own, opposite = (HX, HZ) if side == "X" else (HZ, HX)
    if not commutes(v, opposite):
        return False, "does not commute with the opposite checks"
    if in_rowspace(v, own):
        return False, "lies in the stabilizer row space (trivial)"
    return True, "ok"


def _validate_fast_witness(HX, HZ, weight, side, support):
    """Report the boolean form of :func:`validate_logical`, plus no-logical.

    Kept under its old name because three committed ``reproduce.py`` evidence
    scripts import it: those files are the record of how a filed board entry
    was rebuilt, so their imports are not ours to rename. New code should call
    ``validate_logical`` and read the reason.
    """
    if side not in ("X", "Z"):
        return int(weight) == int(np.asarray(HX).shape[1]) + 1 and not support
    return validate_logical(HX, HZ, side, weight, support)[0]


def _weight_or_inf(weight, n):
    """Normalize gf2_fast's no-logical sentinel to NumPy's infinity result."""
    return float("inf") if int(weight) > n else int(weight)


def _fast_witness(HX, HZ, trials, seed, threads, pair_depth):
    """One accelerator search, validated in Python before it is returned."""
    if _fast is None:
        raise RuntimeError("gf2_fast backend is unavailable")
    weight, side, support = _fast.distance_rand_witness(
        np.asarray(HX, dtype=np.int8), np.asarray(HZ, dtype=np.int8),
        trials=int(trials), seed=int(seed), pair_depth=int(pair_depth),
        threads=int(threads))
    n = int(np.asarray(HX).shape[1])
    if side not in ("X", "Z"):
        # The n+1 sentinel: no logical of either type. That is a result, not a
        # failure, and not a reason to re-run the budget on the NumPy path.
        if _weight_or_inf(weight, n) == float("inf") and not support:
            return NO_LOGICAL
        return NO_LOGICAL._replace(rejected="no side reported for a witness")
    ok, why = validate_logical(HX, HZ, side, weight, support)
    if not ok:
        return NO_LOGICAL._replace(rejected=why)
    return LogicalWitness(_weight_or_inf(weight, n), side,
                          sorted(int(q) for q in support), "")


# =====================================================================
#  Part 1: mixed-volume proxy for k  (matrix-free)
# =====================================================================
def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def convex_hull_2d(points):
    pts = sorted(set(points))
    if len(pts) <= 1:
        return list(pts)
    lower = []
    for p in pts:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _polygon_area(v):
    n = len(v)
    if n < 3:
        return 0.0
    return abs(sum(v[i][0] * v[(i + 1) % n][1] - v[(i + 1) % n][0] * v[i][1]
                   for i in range(n))) / 2.0


def _minkowski(P, Q):
    """Minkowski sum of two convex hulls via pairwise sums + re-hull (hulls here
    have <= 4 vertices, so the brute force is correct and free)."""
    if not P or not Q:
        return []
    return convex_hull_2d([(p[0] + q[0], p[1] + q[1]) for p in P for q in Q])


def mixed_volume(S_f, S_g):
    """k upper bound = Area(N(f)+N(g)) - Area(N(f)) - Area(N(g)) for the Newton
    polygons of two bivariate monomial sets ``S_f``, ``S_g`` (lists of (i, j)
    exponent pairs)."""
    hf, hg = convex_hull_2d(S_f), convex_hull_2d(S_g)
    af, ag = _polygon_area(hf), _polygon_area(hg)
    a_sum = _polygon_area(convex_hull_2d(_minkowski(hf, hg)))
    return int(round(a_sum - af - ag))


# =====================================================================
#  Part 2: randomized min-weight-logical search (distance + witness)
# =====================================================================
def _rref_perm(M, perm):
    """RREF over GF(2) visiting columns in the order ``perm``; returns the
    nonzero reduced rows."""
    M = M.copy() % 2
    rows = M.shape[0]
    r = 0
    for col in perm:
        piv = next((i for i in range(r, rows) if M[i, col]), None)
        if piv is None:
            continue
        M[[r, piv]] = M[[piv, r]]
        for i in range(rows):
            if i != r and M[i, col]:
                M[i] ^= M[r]
        r += 1
        if r == rows:
            break
    return M[:r]


class PreparedSearch:
    """Reusable GF(2) state for repeated distance searches on one code.

    ``kernel_basis`` and ``logical_basis`` depend only on the check matrices, so
    a workflow that searches the same code at several budgets (a staged screen,
    a ladder that widens until it converges) recomputes them every time for no
    reason. Building this once and passing it to ``distance_rand`` keeps the
    per-call work to the trials themselves.

    The bases are treated as immutable: each search allocates its own scratch
    and never writes through them, so one prepared object is safe to reuse
    across calls and across budgets.
    """

    __slots__ = ("HX", "HZ", "n", "_sides")

    def __init__(self, HX, HZ):
        self.HX = np.asarray(HX, dtype=np.int8) % 2
        self.HZ = np.asarray(HZ, dtype=np.int8) % 2
        self.n = int(self.HX.shape[1])
        self._sides = {}
        for tag, Hself, Hopp in (("X", self.HX, self.HZ),
                                 ("Z", self.HZ, self.HX)):
            K = kernel_basis(Hopp)
            LO = logical_basis(Hself, Hopp)
            self._sides[tag] = (Hself, Hopp, K, LO)

    def side(self, tag):
        """Return (Hself, Hopp, kernel basis, opposite-logical basis).

        ``tag`` is 'X' or 'Z'.
        """
        return self._sides[tag]


def prepare_distance_search(HX, HZ):
    """Precompute the GF(2) bases ``distance_rand`` would rebuild on every call.

    Pass the result as ``distance_rand(..., prepared=obj)``. Worth it when the
    same code is searched more than once, which is what a staged screen does.
    """
    return PreparedSearch(HX, HZ)


def _search_lightest(Hself, Hopp, trials, seed, pair_depth=10, bases=None):
    """Randomized upper-bound search for the lightest nontrivial logical of one
    type: a vector v with v in ker(Hopp) (commutes with the opposite checks) but
    v not in rowspace(Hself) (not a stabilizer product). Returns
    ``(weight, support)``, or ``(inf, [])`` if the code has no logical of this
    type.

    Per trial it takes the rows of a randomly column-permuted RREF of ker(Hopp),
    plus pairwise sums of the lightest such rows (this closes most of the gap to
    minima realized only as short combinations). Still an upper bound.
    """
    Hself = np.asarray(Hself, dtype=np.int8) % 2
    Hopp = np.asarray(Hopp, dtype=np.int8) % 2
    n = Hself.shape[1]
    if bases is None:
        K = kernel_basis(Hopp)        # operators commuting with the opposite checks
        LO = logical_basis(Hself, Hopp)   # opposite-type logicals -> nontriviality
    else:
        K, LO = bases                 # prepared once; never written through here
    if K.size == 0 or LO.size == 0:
        return float("inf"), []
    rng = np.random.default_rng(seed)
    best_w, best_v = n + 1, None
    for _ in range(trials):
        red = _rref_perm(K, rng.permutation(n))
        w = red.sum(axis=1)
        nz = ((red @ LO.T) % 2).any(axis=1)
        for i in np.where(nz & (w > 0))[0]:
            if int(w[i]) < best_w:
                best_w, best_v = int(w[i]), red[i].copy() % 2
        if pair_depth > 1 and red.shape[0] >= 2:
            light = np.argsort(w)[:min(pair_depth, red.shape[0])]
            sub = red[light]
            for i in range(len(light)):
                pr = (sub[i] + sub[i + 1:]) % 2
                if pr.size == 0:
                    continue
                pw = pr.sum(axis=1)
                pnz = ((pr @ LO.T) % 2).any(axis=1) & (pw > 0)
                for j in np.where(pnz)[0]:
                    if int(pw[j]) < best_w:
                        best_w, best_v = int(pw[j]), pr[j].copy()
    if best_v is None:
        return float("inf"), []
    return best_w, sorted(int(j) for j in np.where(best_v)[0])


def lightest_logical(Hself, Hopp, trials=8000, seed=0, pair_depth=10):
    """Lightest nontrivial logical of one type, as ``(weight, support)``.

    For the X side pass ``(HX, HZ)``; for the Z side pass ``(HZ, HX)``. The
    returned support is a valid distance witness for that side (the verifier
    checks: in ker(opposite), outside rowspace(own), weight == value).
    """
    return _search_lightest(Hself, Hopp, trials, seed, pair_depth=pair_depth)


def distance_rand_witness(HX=None, HZ=None, trials=2000, seed=0, *,
                          backend="numpy", threads=1, pair_depth=10,
                          prepared=None):
    """Search both sides for the lightest logical.

    Returns a :class:`LogicalWitness`.

    This is the witness-returning form of :func:`distance_rand`, and the entry
    point to use when the operator itself is wanted and not just its weight: a
    re-measurement that has to write the witness it found, or a submission
    being packaged. Both backends return through here and both are validated
    in Python first, so a proposal that is not a logical is never returned as
    one -- it comes back as a no-logical result carrying ``rejected``.

    ``backend`` is ``"numpy"`` (portable), ``"fast"`` (requires ``make fast``),
    or ``"auto"`` (fast when available, otherwise NumPy). ``trials`` counts
    different search operations in the two backends, so the same value is not a
    comparable screening budget across backends.

    ``pair_depth`` is how many of the lightest RREF rows the search also sums
    in pairs, and it reaches both backends. It is the depth a claim was
    measured at, so re-measuring a claim that used 24-80 at the default of 10
    reads high for a reason that is the instrument, not the code.

    Pass ``prepared`` (from :func:`prepare_distance_search`) to skip rebuilding
    the GF(2) bases. ``HX``/``HZ`` may then be omitted. The bases do not depend
    on ``trials`` or ``seed``, so a prepared search returns exactly what the
    unprepared one would for the same arguments.

    The two sides draw independent streams spawned from ``seed``, so neither
    replays the other, and the Z side of one seed is not the X side of the
    next.
    """
    if backend not in ("numpy", "fast", "auto"):
        raise ValueError("backend must be 'numpy', 'fast', or 'auto'")
    if threads < 1:
        raise ValueError("threads must be at least 1")
    if pair_depth < 1:
        raise ValueError("pair_depth must be at least 1")
    if prepared is not None:
        HX, HZ = prepared.HX, prepared.HZ
    elif HX is None or HZ is None:
        raise TypeError("distance_rand needs HX and HZ, or prepared=")
    if backend in ("fast", "auto") and _fast is not None:
        return _fast_witness(HX, HZ, trials, seed, threads, pair_depth)
    if backend == "fast":
        raise ImportError("gf2_fast is unavailable; run `make fast` to build it")
    x_seed, z_seed = np.random.SeedSequence(int(seed)).spawn(2)
    if prepared is None:
        wx, sx = _search_lightest(HX, HZ, trials, x_seed, pair_depth=pair_depth)
        wz, sz = _search_lightest(HZ, HX, trials, z_seed, pair_depth=pair_depth)
    else:
        hx_self, hx_opp, kx, lx = prepared.side("X")
        hz_self, hz_opp, kz, lz = prepared.side("Z")
        wx, sx = _search_lightest(hx_self, hx_opp, trials, x_seed,
                                  pair_depth=pair_depth, bases=(kx, lx))
        wz, sz = _search_lightest(hz_self, hz_opp, trials, z_seed,
                                  pair_depth=pair_depth, bases=(kz, lz))
    side, weight, support = ("X", wx, sx) if wx <= wz else ("Z", wz, sz)
    n = int(np.asarray(HX).shape[1])
    if weight > n:
        return NO_LOGICAL
    ok, why = validate_logical(HX, HZ, side, weight, support)
    if not ok:
        return NO_LOGICAL._replace(rejected=why)
    return LogicalWitness(int(weight), side,
                          sorted(int(q) for q in support), "")


def distance_rand(HX=None, HZ=None, trials=2000, seed=0, *,
                  backend="numpy", threads=1, pair_depth=10, prepared=None):
    """Return a randomized upper bound on ``d = min(d_X, d_Z)``.

    This is the weight of :func:`distance_rand_witness`, for callers that only want the
    number; see it for the arguments and the semantics. A backend proposal that
    fails Python validation raises here rather than reading as no logical,
    because a caller taking the scalar has nowhere to see the reason.
    """
    found = distance_rand_witness(HX, HZ, trials, seed, backend=backend,
                                  threads=threads, pair_depth=pair_depth,
                                  prepared=prepared)
    if found.rejected:
        raise RuntimeError(
            f"{backend} backend returned an invalid logical witness: "
            f"{found.rejected}")
    return found.weight


if __name__ == "__main__":
    # k-proxy calibration against the BB trinomial families (true k known).
    print("mixed_volume (k upper bound) vs known k:")
    cases = {6: (-1, -2, 1, -1), 7: (-1, 1, 1, 3), 8: (-1, 2, 1, 3),
             11: (-1, -3, 1, -3), 12: (-1, 2, 1, 5), 13: (5, 1, 3, -1)}
    for k, (a, b, c, d) in cases.items():
        mv = mixed_volume([(0, 0), (1, 0), (a, b)], [(0, 0), (0, 1), (c, d)])
        print(f"  true k={k:2d}  MV={mv:2d}  {'ok' if mv == k else 'MISMATCH'}")
