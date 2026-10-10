"""Quadcycle codes: the 4D multi-cyclic family of arXiv:2610.10731.

A quadcycle code is specified by a finite abelian group ``G`` (here a torus
``Z_l1 x Z_l2 x ...``) and four elements ``a, b, c, d`` of ``R = F_2[G]``,
written as lists of exponent tuples. It has ``n = 6|G|`` qubits in six blocks of
size ``|G|``, with ``4|G|`` generators per Pauli basis:

    H_X = B[[c*, 0, b*, d*, 0, 0],          H_Z = B[[b, a, c, 0, 0, 0],
             [0, c*, a*, 0, d*, 0],                    [d, 0, 0, c, 0, a],
             [a*, b*, 0, 0, 0, d*],                    [0, d, 0, 0, c, b],
             [0, 0, 0, a*, b*, c*]]                    [0, 0, d, b, a, 0]]

``B(x)`` is the ``|G| x |G|`` matrix of the regular representation of ``x``
(left multiplication), applied entrywise to the block matrix, and ``x*`` is the
group inversion ``sum_g x_g g^{-1}``. Because ``G`` is abelian, ``R`` is
commutative and every generator pair cancels in ``H_X H_Z^T``, so the code is
CSS for any choice of the four elements.

Each generator is a sum of three of the four elements, so the check weight is
``max over the four rows of the sum of three weights``. The paper's own
factory codes use weights ``(2,2,2,4)``, giving checks of weight 6 and 8; the
board-relevant region is the other end of that range, where low check weight
coincides with a sparse, high-rate code.

Calibration anchors are Table 2 of that paper (group order in the first
column; ``a, b, c`` define the paired tricycle code and ``d`` the quadcycle):

    Z_3 x Z_3      a=1+x   b=1+y   c=x+y     d=1+xy             [[54,6,6]]
    Z_3 x Z_4      a=1+xy  b=1+y   c=x+y     d=1+x+x^2+y^2      [[72,6,8]]
    Z_3 x Z_9      a=1+y   b=x+y^2 c=x^2+y^2 d=1+x+y^3+y^6     [[162,6,14]]
    Z_2 x Z_19     a=x+y^2 b=x+y^3 c=x+y^5  d=1+xy+y^2+y^9      [[228,6,17]]
    Z_2xZ_5xZ_7    a=1+yz  b=x+z^2 c=xy+z^3 d=1+xy+xy^2+y^3z  [[420,6,25]]

Exponents are read mod the corresponding modulus, so ``x`` on ``Z_3`` is the
tuple ``(1, 0)`` and ``y`` is ``(0, 1)``.

Status: the constructor is sound, the family is closed
------------------------------------------------------

Kept for the calibration and not as a route to a code. Two measurements, both
on this board, both against the Pareto bar at each candidate's own ``(n, k, w)``
(see ``research/board_bar.py``):

* **No quadcycle code can enter a weight-4 board.** The paper's closed form for
  the logical count (its Eq. 7) is ``k = 6 sum_lambda |lambda| min(v_a, v_b,
  v_c, v_d)`` -- a sum over Frobenius orbits of characters of the *minimum*
  valuation of the four factors. So ``k > 0`` requires all four of ``a, b, c,
  d`` to share a non-unit divisor, not merely to be individually non-unit, and
  a generator being a sum of three of the four puts the minimum check weight at
  ``2+2+2 = 6``. Check weight 5 and below is unreachable. (The weight-4
  ``unrestricted`` cell is otherwise the emptiest on the board, bar ``kd2/n =
  2.25``, which is what makes this worth stating rather than leaving to be
  rediscovered.)
* **At check weight 6 and 8 the family does not reach the frontier.** 15,005
  sampled codes plus the five published instances, every one short of the bar
  (best margin -2). Sampling the shared divisor directly -- the structure
  ``k > 0`` actually requires -- reaches the paper's own operating point
  (``k = 24`` at ``n = 456``) and buys rate at the cost of distance: forcing
  ``a = f * g`` with a common small non-unit ``f`` gives ``k`` up to 120 at rate
  0.25 and ``d`` of 3 to 6, while the paper's ``[[456,24,16]]`` there is still
  12 short of the bar (which needs ``d >= 25``, set by ``[[336,24,24]]``).

So: do not spend a weekend here without a mechanism that reaches the paper's
*distance* at high ``k``. Its ``d = 16`` at ``k = 24`` comes from shared
*valuations* in a particular Frobenius-orbit pattern, not from a shared monomial
divisor, and neither sampler above reproduces it.

One discrepancy worth checking before trusting the paper's numbers: for the
``Z_3 x Z_4`` anchor, a 30k-trial search returns a weight-7 X-logical, accepted
by the kit's ``validate_logical`` (in the kernel of the opposite checks, outside
the row space of its own), where the paper reports ``d = 8`` and calls it exact
by MaxSAT. ``n``, ``k`` and check weight all match the printed row, so this is
not a transcription slip in the parameters.

This module is a constructor for research use only: it makes no claim about
distance. Distance is an upper bound read off a witness, and no code is a find
until ``verify/validate_candidate.py`` says so.
"""
import os

import numpy as np

# Block structure of H_X and H_Z, as (row, col) -> element letter.  Entries are
# read off Eqs. (1) and (2) of arXiv:2610.10731; "*" marks the group inverse.
_HX_BLOCKS = [
    [("c", True), None, ("b", True), ("d", True), None, None],
    [None, ("c", True), ("a", True), None, ("d", True), None],
    [("a", True), ("b", True), None, None, None, ("d", True)],
    [None, None, None, ("a", True), ("b", True), ("c", True)],
]
_HZ_BLOCKS = [
    [("b", False), ("a", False), ("c", False), None, None, None],
    [("d", False), None, None, ("c", False), None, ("a", False)],
    [None, ("d", False), None, None, ("c", False), ("b", False)],
    [None, None, ("d", False), ("b", False), ("a", False), None],
]


def _inverse(term, dims):
    """``g -> g^{-1}``: negate every exponent mod its modulus."""
    return tuple((-e) % r for e, r in zip(term, dims))


def _strides(dims):
    """Flat index of a multi-index, first factor varying fastest.

    Same convention as ``research/quadricycle.py`` (``np.kron`` over the
    factors in order), so the two modules' indexings agree.
    """
    out, s = [], 1
    for r in dims:
        out.append(s)
        s *= r
    return out


def _mul(dims, p, q):
    """Product of two elements of ``R``, as a sorted list of exponent tuples.

    Convolution in the group algebra: ``(pq)[h] = sum_{g+k=h} p[g] q[k]``,
    reduced mod 2 and mod each factor. Used to build factors as a *product*
    (``a = f * g``) rather than by drawing monomials independently, which is
    what makes a shared-divisor sampler possible.
    """
    dims = tuple(int(r) for r in dims)
    out = {}
    for g in set(tuple(t) for t in p):
        for h in set(tuple(t) for t in q):
            k = tuple((u + v) % r for u, v, r in zip(g, h, dims))
            out[k] = out.get(k, 0) ^ 1
    return sorted(k for k, bit in out.items() if bit)


def _elements(dims):
    """Flat index -> exponent tuple, for every element of ``G``.

    The flat index is mixed radix with the *first* factor varying fastest, the
    same convention as ``research/quadricycle.py``. Shifts must be taken on the
    exponent tuple, not on the flat index: adding a number to a mixed-radix
    index carries between factors, so a flat offset is not a group element and
    ``B(a) B(b) != B(ab)`` if you use one.
    """
    dims = tuple(int(r) for r in dims)
    strides = _strides(dims)
    out = []
    for i in range(int(np.prod(dims))):
        rest, e = i, []
        for s, r in zip(strides, dims):
            e.append((rest // s) % r)
        out.append(tuple(e))
    return out


def _regular(dims, terms, invert=False):
    """``B(x)`` for ``x = sum_t t``: the matrix of left multiplication by x.

    ``B(x)[i, i + t] = 1`` for every ``t`` in the support, with ``i + t``
    taken in ``G``. Duplicate terms cancel mod 2, so the support is a set.
    With this convention ``B(x) B(y) = B(xy)`` and ``B(x)^T = B(x*)``, which is
    what makes the block matrices of Eqs. (1)-(2) commute.
    """
    dims = tuple(int(r) for r in dims)
    elements = _elements(dims)
    index = {e: i for i, e in enumerate(elements)}
    support = {(_inverse(t, dims) if invert else tuple(int(x) % r
                 for x, r in zip(t, dims))) for t in terms}
    M = np.zeros((len(elements),) * 2, dtype=np.int8)
    for i, e in enumerate(elements):
        for t in support:
            shifted = tuple((u + v) % r for u, v, r in zip(e, t, dims))
            M[i, index[shifted]] ^= 1
    return M


def _assemble(dims, blocks, factors):
    """Expand a block matrix entrywise with the regular representation."""
    dims = tuple(int(r) for r in dims)
    nG = int(np.prod(dims))
    rows = []
    for block_row in blocks:
        acc = np.zeros((nG, 6 * nG), dtype=np.int8)
        for col, entry in enumerate(block_row):
            if entry is None:
                continue
            letter, invert = entry
            acc[:, col * nG:(col + 1) * nG] ^= factors[letter][invert]
        rows.extend(acc)
    return np.array(rows, dtype=np.int8)


def quadcycle_shape(dims, a, b, c, d):
    """Exact ``(n, check_weight)`` from the parameters alone.

    ``n = 6|G|``. A generator is the sum of three of the four elements, each
    in its **own** qubit block, so its weight is the sum of the three weights:
    there is no cancellation to account for across blocks, and ``|x*| = |x|``
    because group inversion permutes the support. The check weight is
    therefore the largest sum of three of ``|a|, |b|, |c|, |d|``.

    Both numbers are cheap and exact, which is what lets a sweep reject before
    it builds. They say nothing about ``k`` or ``d``: use ``css.compute_k`` for
    the first and a distance search for the second.
    """
    dims = tuple(int(r) for r in dims)
    n = 6 * int(np.prod(dims))
    weights = [len(set(tuple(t) for t in e)) for e in (a, b, c, d)]
    return n, max(sum(weights) - weights[i] for i in range(4))


def build_quadcycle(dims, a, b, c, d):
    """Build ``(HX, HZ)`` for the quadcycle code on ``G = prod Z_dims``.

    Returns int8 arrays of shape ``(4|G|, 6|G|)``.
    """
    factors = {}
    for letter, terms in (("a", a), ("b", b), ("c", c), ("d", d)):
        factors[letter] = (_regular(dims, terms, invert=False),
                           _regular(dims, terms, invert=True))
    HX = _assemble(dims, _HX_BLOCKS, factors)
    HZ = _assemble(dims, _HZ_BLOCKS, factors)
    return HX, HZ


def sample_quadcycle(num, *, dim_range=(2, 9), rank=2, max_site=200,
                     weights=(1, 1, 1, 2), seed=0, n_range=None,
                     max_weight=None, min_k=1, audit=None):
    """Yield ``num`` random quadcycle candidates ``(spec, HX, HZ)``.

    ``dims`` is a ``rank``-dimensional torus with product <= ``max_site`` (so
    ``n = 6*prod``); ``weights`` gives the number of monomials in each of
    ``a, b, c, d``, and therefore the check weight. Rejection sampling draws
    monomials uniformly from the torus and drops candidates outside
    ``n_range`` / ``max_weight`` **before** building, using the exact
    ``quadcycle_shape``. ``spec`` is JSON-serializable:
    ``{"family": "quadcycle", "dims": [...], "a": [...], ...}``.

    Pass ``audit`` as a dict to receive counts.
    """
    rng = np.random.default_rng(seed)
    tally = audit if audit is not None else {}
    for key in ("sampled", "rejected_n", "rejected_w", "built"):
        tally.setdefault(key, 0)

    lo, hi = dim_range
    for _ in range(num):
        for _try in range(200):
            dims = [int(rng.integers(lo, hi + 1)) for _ in range(rank)]
            if int(np.prod(dims)) <= max_site:
                break
        else:
            continue
        tally["sampled"] += 1
        terms = []
        for count in weights:
            for _try in range(200):
                picks = rng.choice(int(np.prod(dims)), size=count, replace=False)
                grid = _decode(dims, [int(p) for p in picks])
                if len(set(grid)) == count:
                    break
            else:
                break
            terms.append(grid)
        if len(terms) != 4:
            continue
        n, w = quadcycle_shape(dims, *terms)
        if n_range is not None and not (n_range[0] <= n <= n_range[1]):
            tally["rejected_n"] += 1
            continue
        if max_weight is not None and w > max_weight:
            tally["rejected_w"] += 1
            continue
        tally["built"] += 1
        HX, HZ = build_quadcycle(dims, *terms)
        yield ({"family": "quadcycle", "dims": list(dims),
                "a": [list(t) for t in terms[0]],
                "b": [list(t) for t in terms[1]],
                "c": [list(t) for t in terms[2]],
                "d": [list(t) for t in terms[3]]}, HX, HZ)


def sample_quadcycle_shared(num, *, dim_range=(2, 16), rank=2, max_site=166,
                            shared_weight=2, factor_weights=(1, 1, 2, 2),
                            seed=0, n_range=None, max_weight=8, min_k=1,
                            audit=None):
    """Yield ``num`` quadcycle candidates whose four factors share a divisor.

    The paper's closed form for the logical count (its Eq. 7) is
    ``k = 6 sum_lambda |lambda| min(v_a, v_b, v_c, v_d)``, a sum over the
    Frobenius orbits of characters of the *minimum* valuation of the four
    factors. So ``k > 0`` requires all four of ``a, b, c, d`` to be divisible
    by a common non-unit element -- not merely to be individually non-unit.
    Rejection sampling that draws the four factors independently hits that
    condition rarely, which is why the uniform sampler in
    :func:`sample_quadcycle` spends its budget at ``k = 6..12`` while the
    paper's own best instance sits at ``k = 24``.

    This sampler draws the shared divisor ``f`` first, then draws each factor
    as ``f * g`` with ``g`` a small random element, so every candidate has
    ``k > 0`` by construction. ``min_k`` then filters on the *exact* ``k``
    (GF(2) rank, the quantity the verifier recomputes), which is what selects
    for the high-``k`` corner the paper searched.

    The product can cancel monomials, so the realized factor weights are
    whatever ``f * g`` comes to; ``max_weight`` is checked against
    :func:`quadcycle_shape` rather than against ``factor_weights``.
    """
    rng = np.random.default_rng(seed)
    tally = audit if audit is not None else {}
    for key in ("sampled", "rejected_n", "rejected_w", "rejected_k"):
        tally.setdefault(key, 0)

    lo, hi = dim_range
    for _ in range(num):
        for _try in range(200):
            dims = [int(rng.integers(lo, hi + 1)) for _ in range(rank)]
            if int(np.prod(dims)) <= max_site:
                break
        else:
            continue
        tally["sampled"] += 1
        nG = int(np.prod(dims))
        # The shared divisor must be a genuine non-unit: a single monomial is
        # invertible in R and would leave every valuation at zero.
        shared = None
        for _try in range(200):
            picks = rng.choice(nG, size=shared_weight, replace=False)
            cand = _decode(dims, [int(p) for p in picks])
            if len(set(cand)) == shared_weight and len(cand) > 1:
                shared = cand
                break
        if shared is None:
            continue
        terms = []
        for count in factor_weights:
            picks = rng.choice(nG, size=max(count, 1), replace=False)
            terms.append(_mul(dims, shared, _decode(dims, [int(p) for p in picks])))
        if any(len(t) == 0 for t in terms):
            continue
        n, w = quadcycle_shape(dims, *terms)
        if n_range is not None and not (n_range[0] <= n <= n_range[1]):
            tally["rejected_n"] += 1
            continue
        if max_weight is not None and w > max_weight:
            tally["rejected_w"] += 1
            continue
        HX, HZ = build_quadcycle(dims, *terms)
        if min_k > 1:
            import sys as _sys
            _kit = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kit")
            if _kit not in _sys.path:
                _sys.path.insert(0, _kit)
            from css import compute_k
            if compute_k(HX, HZ) < min_k:
                tally["rejected_k"] += 1
                continue
        tally.setdefault("built", 0)
        tally["built"] += 1
        yield ({"family": "quadcycle", "dims": list(dims),
                "shared": [list(t) for t in shared],
                "a": [list(t) for t in terms[0]],
                "b": [list(t) for t in terms[1]],
                "c": [list(t) for t in terms[2]],
                "d": [list(t) for t in terms[3]]}, HX, HZ)


def _decode(dims, flats):
    """Flat indices back to exponent tuples (inverse of ``_strides``)."""
    strides = _strides(dims)
    out = []
    for f in flats:
        rest, e = f, []
        for s, r in zip(strides, dims):
            e.append((rest // s) % r)
        out.append(tuple(e))
    return out


TABLE2 = [
    # Table 2 of arXiv:2610.10731, as (dims, a, b, c, d, (n, k)).
    # Exponents are read mod their modulus: x on Z_3 is (1, 0), y is (0, 1).
    ((3, 3), [(1, 0), (0, 0)], [(0, 1), (0, 0)], [(1, 0), (0, 1)],
     [(0, 0), (1, 1)], (54, 6)),
    ((3, 4), [(0, 0), (1, 1)], [(0, 1), (0, 0)], [(1, 0), (0, 1)],
     [(0, 0), (1, 0), (2, 0), (0, 1)], (72, 6)),
    ((3, 9), [(0, 1), (0, 0)], [(1, 0), (0, 2)], [(2, 0), (0, 2)],
     [(0, 0), (1, 0), (0, 3), (0, 6)], (162, 6)),
    ((2, 19), [(1, 0), (0, 2)], [(1, 0), (0, 3)], [(1, 0), (0, 5)],
     [(0, 0), (1, 1), (0, 2), (0, 9)], (228, 6)),
    ((2, 5, 7), [(0, 0, 0), (0, 1, 1)], [(1, 0, 0), (2, 0, 1)],
     [(1, 1, 0), (0, 0, 3)], [(0, 0, 0), (1, 1, 0), (1, 2, 0), (0, 3, 1)],
     (420, 6)),
]


def check_table2():
    """Rebuild every anchor of Table 2 and return ``(n, k, w)`` per case.

    The paper states ``(n, k)`` for these five and the distances are measured
    elsewhere; matching ``(n, k)`` on all five, with ``H_X H_Z^T = 0``, is the
    calibration the constructor has to pass before any of it is believed.
    """
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "kit"))
    from css import compute_k, verify_css

    out = []
    for dims, a, b, c, d, claim in TABLE2:
        HX, HZ = build_quadcycle(dims, a, b, c, d)
        n, w = quadcycle_shape(dims, a, b, c, d)
        k = compute_k(HX, HZ)
        assert n == claim[0], f"{dims}: n {n} != {claim[0]}"
        assert k == claim[1], f"{dims}: k {k} != {claim[1]}"
        assert verify_css(HX, HZ), f"{dims}: not CSS"
        assert w == max(int(r.sum()) for r in HX), f"{dims}: weight mismatch"
        out.append((n, k, w))
    return out


if __name__ == "__main__":
    for (dims, a, b, c, d, claim), (n, k, w) in zip(TABLE2, check_table2()):
        print(f"G={dims}  [[{n},{k}]]  w={w}  (paper [[{claim[0]},{claim[1]}]])")
    print("calibration ok")
