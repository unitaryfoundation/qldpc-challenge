"""Board-aware screening target for a candidate ``(n, k, w)``.

A candidate is a *record* in its cell when nothing already on the board beats
it on all of ``(n lower, k higher, d higher, w lower)`` at once. That turns
into a scalar bar: for a fixed ``(n, k, w)`` the smallest ``d`` that would be
undominated is one more than the largest ``d`` the board already holds at
``n' <= n``, ``k' >= k``, ``w' <= w``. Anything at or below that bar is
dominated on arrival and there is no point spending a distance search on it.

Family-independent on purpose: it reads the board and the candidate's
parameters, so it serves any search that can state ``(n, k, w)``.

Read the result with care, in one specific way. The bar measures
*nondomination*, not merit, and at the ragged edge of the board the two come
apart: in a corner where the board holds nothing at that ``k`` and weight, the
bar collapses to 1 and a code with ``d = 3`` clears it trivially. Pass
``d_floor`` to say what distance you actually care about; the comparison is then
made at the larger of the two, which keeps the empty-corner case visible instead
of flattering it. This is not hypothetical -- it is what a first pass over the
quadcycle family reported as 158 "records", every one of them ``d = 3`` or
``d = 4``.

This is a *screen*, not a claim. It reads ``codes/*.json`` the way the site
does and it can be wrong about anything the verifier recomputes; the gate in
``verify/validate_candidate.py`` is what decides whether a candidate advances.
"""
import glob
import json
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_board(root=None):
    """``[(n, k, d, w, code_type, name)]`` for every entry in ``codes/``."""
    root = root or _ROOT
    out = []
    for path in glob.glob(os.path.join(root, "codes", "*.json")):
        try:
            doc = json.load(open(path))
        except (ValueError, OSError):
            continue
        n, k = doc.get("n"), doc.get("k")
        dist = doc.get("distance")
        if isinstance(dist, dict):
            dist = dist.get("d") or min(
                (v.get("value") for v in dist.values()
                 if isinstance(v, dict) and v.get("value")), default=None)
        checks = doc.get("checks") or {}
        w = max((len(s) for arr in checks.values() for s in arr), default=0)
        if n is None or k is None or dist is None:
            continue
        out.append((int(n), int(k), int(dist), int(w),
                    doc.get("code_type", "CSS"), doc.get("name", "")))
    return out


def bar(board, n, k, w, code_type="CSS", d_floor=1):
    """Smallest ``d`` at ``(n, k, w)`` that no board entry dominates.

    Returns ``(threshold, [names of the entries that set it])``. A threshold of
    1 means nothing on the board competes at this ``(n, k, w)``.

    ``d_floor`` is the smallest distance a caller cares about. The bar alone
    is not a merit test: at very large ``k`` the board holds nothing in the
    cell, the bar collapses to 1, and a code with ``d = 3`` reads as "past the
    bar" while being worthless. Comparing at ``max(threshold, d_floor)`` keeps
    that case visible instead of flattering.
    """
    best, who = 0, []
    for (bn, bk, bd, bw, bt, name) in board:
        if bt != code_type or bw > w or bk < k or bn > n:
            continue
        if bd > best:
            best, who = bd, [name]
        elif bd == best:
            who.append(name)
    return max(best, d_floor - 1) + 1, who


def summary(board, code_type="CSS", max_w=8, k_list=(2, 6, 12, 24)):
    """Print the bar as a function of ``n``, for a few ``k`` -- what a sweep aims at."""
    for k in k_list:
        row = []
        n = 6
        while n <= 1000:
            t, _ = bar(board, n, k, max_w, code_type)
            row.append((n, t - 1))
            n += 6 * 10  # every quadcycle blocklength
        print(f"k={k} w<={max_w}: " + "  ".join(f"n={n}:d>{d - 1}"
                                               for n, d in row[:14]))


if __name__ == "__main__":
    b = load_board()
    print(f"{len(b)} board entries")
    for w in (6, 8):
        summary(b, "CSS", max_w=w, k_list=(6, 12, 24))
