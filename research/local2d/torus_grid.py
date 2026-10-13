"""Torus-grid layouts for two-block codes, by scanning index factorisations.

A code whose qubit index runs `block * l*m + i*m + j` -- the convention of
``bb.py``, and of most entries built from it -- has a canonical 2D layout: qubit
``(i,j)`` of block 0 and qubit ``(i,j)`` of block 1 both sit at grid site
``(i,j)``, one per layer. Nothing is searched. The layout is read off the index
convention and its interaction radius is measured exactly.

So for a candidate with ``n = 2*l*m``, scanning the divisor pairs of ``n/2`` is a
constructive test for a layout: a wrong factorisation scrambles the grid and
gives a large radius, the right one gives the true one.

It is a SCREEN, not a search. Measured against the 62 entries in PRs #3389,
#3390 and #3391, it placed exactly one of them; for the other 61 the divisor scan
gave a radius well over the bilayer cap (for some entries absurdly over -- a
factorisation it guessed wrong) and the annealer in ``fold_layout`` found a much
better embedding. Its value is that it is exact and free: when it does report a
radius at or under a cap, that is a layout with no stochastic search behind it,
and it is worth running first for that reason. When it misses, use the annealer.

The occupancy is exactly 2 by construction, which is the ceiling a 2D class cap
allows. Folding an axis (``i -> min(i, l-i)``, so a cell and its opposite share a
site) shrinks the radius but multiplies occupancy to 4 or 8, which no class cap
admits; it is offered here only so the trade can be measured, and
``--occupancy`` defaults to the 2 that matters.

Usage::

    python research/local2d/torus_grid.py codes/18-8-3.json
    python research/local2d/torus_grid.py codes/18-8-3.json --layers 1 --top 5

The radius it prints is the quantity ``verify/qldpc_verify.py`` measures, and the
occupancy and spacing it reports are its two honesty checks. The verifier, not
this script, is the authority on whether a layout is accepted.
"""
import argparse
import json
import math
import os
import sys
from collections import Counter

CONVENTIONS = ((False, False), (True, False), (False, True), (True, True))
SINGLE_CAP, BILAYER_CAP = 4.0, 7.0


def supports(doc):
    """Check supports, X rows then Z rows; None for a non-CSS entry."""
    if doc["code_type"] != "CSS":
        return None
    return ([list(map(int, r)) for r in doc["checks"]["X"]] +
            [list(map(int, r)) for r in doc["checks"]["Z"]])


def divisors(n):
    """Every (w, h) with w*h == n, both orders, ascending."""
    out, i = [], 1
    while i * i <= n:
        if n % i == 0:
            out.append((i, n // i))
            if i != n // i:
                out.append((n // i, i))
        i += 1
    return sorted(out)


def grid(l, m, fold_i=False, fold_j=False):
    """coords for the two-block index convention on Z_l x Z_m."""
    coords = []
    for q in range(2 * l * m):
        _, r = divmod(q, l * m)
        i, j = divmod(r, m)
        coords.append((min(i, l - i) if fold_i else i,
                       min(j, m - j) if fold_j else j))
    return coords


def radius(sup, pts):
    """Max check diameter, the verifier's interaction radius."""
    return max((max(math.dist(pts[a], pts[b]) for a in s for b in s)
                for s in sup), default=0.0)


def honesty(coords):
    """(max qubits per site, min spacing between distinct sites)."""
    mult = Counter(coords)
    sites = sorted(mult)
    md = min((math.dist(a, b) for i, a in enumerate(sites) for b in sites[i + 1:]),
             default=float("inf"))
    return max(mult.values()), (0.0 if md == float("inf") else round(md, 6))


def scan(doc, occupancy=2, top=1):
    """Best torus-grid layouts, tightest first.

    ``occupancy`` is the maximum qubits per site to admit: 2 is the only value a
    2D class cap allows, since both caps need ``layers <= 2``.
    """
    sup = supports(doc)
    if sup is None or doc["n"] % 2:
        return []
    cands = []
    for (l, m) in divisors(doc["n"] // 2):
        for fi, fj in CONVENTIONS:
            pts = grid(l, m, fi, fj)
            cands.append((radius(sup, pts), l, m, fi, fj))
    cands.sort()
    out, seen = [], set()
    for r, l, m, fi, fj in cands:
        if (l, m, fi, fj) in seen:
            continue
        seen.add((l, m, fi, fj))
        pts = grid(l, m, fi, fj)
        occ, spacing = honesty(pts)
        if occ > occupancy or spacing < 1.0 - 1e-9:
            continue
        cap = SINGLE_CAP if occ == 1 else BILAYER_CAP
        out.append({"l": l, "m": m, "fold": (fi, fj), "layers": occ,
                    "radius": round(r, 4), "spacing": spacing,
                    "within_cap": r <= cap + 1e-9})
        if len(out) >= top:
            break
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("doc", help="a codes/<n>-<k>-<d>.json entry")
    ap.add_argument("--occupancy", type=int, default=2,
                    help="max qubits per site to admit (default 2, the only "
                         "value a 2D class cap allows)")
    ap.add_argument("--top", type=int, default=1, help="how many candidates")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    args = ap.parse_args(argv)

    with open(args.doc) as f:
        doc = json.load(f)
    got = scan(doc, occupancy=args.occupancy, top=args.top)
    if args.json:
        print(json.dumps(got, indent=1))
        return 0
    if not got:
        print("no torus-grid layout at that occupancy: this entry is not a "
              "two-block code on Z_l x Z_m with the bb.py index convention")
        return 1
    for c in got:
        tag = (f"within the {'single-layer' if c['layers'] == 1 else 'bilayer'} "
               f"cap" if c["within_cap"] else "over the cap")
        print(f"Z_{c['l']} x Z_{c['m']} fold={c['fold']} layers={c['layers']} "
              f"radius={c['radius']} spacing={c['spacing']} -- {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())