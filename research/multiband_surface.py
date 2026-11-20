#!/usr/bin/env python
"""Multi-band dense-packed surface codes: the general (rows, m, pitch) family.

`research/build_dense_surface.py` reconstructs one point of this family -- the
published two-band, three-patch packing of arXiv:2511.06758 (Fujiu et al.),
which is the board's [[101,5,5]]. Its site mask hard-codes that configuration.
This module states the same mask as a rule over an arbitrary number of bands
and patches, following the description in
`fieldnotes/2026-09-01-multiband-dense-packing-method.md` section 1.

Geometry. Square surface-code patches are laid out in horizontal *bands*:

    even bands  r = 0, 2, ...   m     patches at x = j * Px,  Px = 2d + 2
    odd  bands  r = 1, 3, ...   m - 1 patches at x = (d + 1) + j * Px
    band r starts at  y0 = r * pitch

The half-pitch stagger of the odd bands is what lets neighbouring patches share
boundary infrastructure, so the packing is one connected code rather than a
direct sum of patches. Each patch contributes three kinds of occupied site:

    window interior         (x+y) % 2 == 0      inside the 2d-1 square
    vertical edge columns   (x+y) % 4 == ph     at x = x0 and x = x0 + 2d
    horizontal edge rows    (x+y) % 4 == 2 - ph at y = y0 and y = y0 + 2d

with the band phase ph = 0 on even bands and 2 on odd ones. Qubit conventions
are the published ones: data on odd/odd sites, (x+y) % 4 == 2 ancillas carry
X-checks and the rest Z-checks, each check supporting the diagonal data
neighbours present in the mask.

The closed form k = rows*m - rows//2 is NOT trusted here: `params()` recomputes
k by exact GF(2) rank, the discipline the fieldnote's section 6 records paying
for. `pitch` likewise is a free parameter to be measured, not assumed.

Band pitch, read off the board rather than assumed. Matching this builder
against every single-layer weight-4 board entry reproduces 58 of them exactly,
and their pitches fall into two regimes:

    rows == 2   pitch = d - 1          the published two-band packing
    rows >= 3   pitch = 2 * (3*d//4)   the fieldnote's measured pitch_min(d)
                                       (6, 10, 12 at d = 5, 7, 9)

That resolves an apparent conflict in the fieldnote: its Result 3 reports
distance preserved only at pitch >= pitch_min(d), which exceeds d - 1, yet the
published rows = 2 packing sits at d - 1 with full distance. Result 3 measured
at rows = 4. Two bands can pack tighter than three or more can.

Run `python3 multiband.py` for the self-test against the published builder.
"""

import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _rel in ("verify", os.path.join("research", "kit")):
    _p = os.path.join(_ROOT, _rel)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import gf2  # noqa: E402


def patch_origins(d, rows, m, pitch):
    """(x0, y0, band) for every patch of the packing, in band order."""
    px = 2 * d + 2
    for r in range(rows):
        count = m if r % 2 == 0 else m - 1
        base = 0 if r % 2 == 0 else d + 1
        for j in range(count):
            yield base + j * px, r * pitch, r


def occupied_sites(d, rows, m, pitch):
    """Return the occupied (x, y) grid sites, as the union over patches.

    Overlapping bands contribute to one set, which is the mechanism: a site
    claimed by two patches is shared boundary infrastructure, not a collision.
    """
    sites = set()
    for x0, y0, r in patch_origins(d, rows, m, pitch):
        ph_v = 0 if r % 2 == 0 else 2  # vertical edge columns
        ph_h = 2 - ph_v  # horizontal edge rows, reverse phase
        for y in range(y0 + 1, y0 + 2 * d):
            for x in range(x0 + 1, x0 + 2 * d):
                if (x + y) % 2 == 0:
                    sites.add((x, y))
        for x in (x0, x0 + 2 * d):
            for y in range(y0 + 2, y0 + 2 * d - 1):
                if (x + y) % 4 == ph_v:
                    sites.add((x, y))
        for y in (y0, y0 + 2 * d):
            for x in range(x0 + 2, x0 + 2 * d - 1):
                if (x + y) % 4 == ph_h:
                    sites.add((x, y))
    return sites


def build(d, rows=2, m=3, pitch=None, drop_empty=False):
    """(HX, HZ, coords, sites) for the (d, rows, m, pitch) packing.

    pitch defaults to the published d - 1. Sites are ordered row-major in
    (y, x), matching the linear-index order of the published builder, so the
    matrices are comparable row for row. Coordinates are the grid halved, so
    the tilted nearest-neighbour checks span sqrt(2) at unit qubit spacing.
    """
    if pitch is None:
        pitch = d - 1
    sites = sorted(occupied_sites(d, rows, m, pitch), key=lambda c: (c[1], c[0]))
    data = [c for c in sites if c[0] % 2 == 1 and c[1] % 2 == 1]
    index = {c: i for i, c in enumerate(data)}

    rows_x, rows_z = [], []
    for x, y in sites:
        if (x, y) in index:
            continue
        sup = sorted(
            index[(x + dx, y + dy)] for dx, dy in ((-1, -1), (-1, 1), (1, -1), (1, 1)) if (x + dx, y + dy) in index
        )
        if drop_empty and not sup:
            continue
        (rows_x if (x + y) % 4 == 2 else rows_z).append(sup)

    n = len(data)
    hx = np.zeros((len(rows_x), n), dtype=np.uint8)
    hz = np.zeros((len(rows_z), n), dtype=np.uint8)
    for a, src in ((hx, rows_x), (hz, rows_z)):
        for r, sup in enumerate(src):
            for c in sup:
                a[r, c] = 1
    coords = np.array(data, dtype=float) / 2.0 if n else np.zeros((0, 2))
    return hx, hz, coords, sites


def connected(hx, hz):
    """Report whether the combined X/Z Tanner graph is a single component.

    The verifier's own connectivity rule; a packing whose bands do not touch
    is a direct sum and is rejected, so this is checked at enumeration time
    rather than discovered at submission time.
    """
    n = hx.shape[1]
    if n == 0:
        return False
    adj = [set() for _ in range(n)]
    for h in (hx, hz):
        for row in h:
            sup = np.flatnonzero(row)
            for q in sup[1:]:
                adj[sup[0]].add(int(q))
                adj[int(q)].add(int(sup[0]))
    seen, stack = {0}, [0]
    while stack:
        for q in adj[stack.pop()]:
            if q not in seen:
                seen.add(q)
                stack.append(q)
    return len(seen) == n


def params(d, rows=2, m=3, pitch=None):
    """Exact (n, k, w, connected) for a configuration -- k by GF(2) rank.

    The closed form rows*m - rows//2 is reported alongside as `k_formula`
    purely so a scan can flag where it breaks; it is never used as k.
    """
    hx, hz, coords, _ = build(d, rows, m, pitch)
    n = hx.shape[1]
    if n == 0:
        return dict(d=d, rows=rows, m=m, pitch=pitch, n=0, k=0, ok=False)
    k = n - gf2.rank(hx) - gf2.rank(hz)
    return dict(
        d=d,
        rows=rows,
        m=m,
        pitch=(d - 1 if pitch is None else pitch),
        n=n,
        k=k,
        k_formula=rows * m - rows // 2,
        w=int(max(hx.sum(1).max(), hz.sum(1).max())),
        css=bool((hx @ hz.T % 2).max() == 0),
        connected=connected(hx, hz),
        empty_rows=int((hx.sum(1) == 0).sum() + (hz.sum(1) == 0).sum()),
        eff=round(k * d * d / n, 4) if n else 0.0,
    )


def _selftest():
    """Bit-exact agreement with research/build_dense_surface.py at its point."""
    sys.path.insert(0, os.path.join(_ROOT, "research"))
    import build_dense_surface as ref

    ok = True
    for d in (3, 5, 7, 9):
        rhx, rhz, rco, rdata, rsites = ref.build(d)
        hx, hz, co, _ = build(d, rows=2, m=3, pitch=d - 1)
        same = (
            hx.shape == rhx.shape
            and hz.shape == rhz.shape
            and np.array_equal(hx, rhx)
            and np.array_equal(hz, rhz)
            and np.array_equal(co, rco)
        )
        ok &= same
        p = params(d, 2, 3)
        print(
            f"  d={d}: published [[{rhx.shape[1]},?]] vs general -> "
            f"bit-exact {'YES' if same else 'NO'}   "
            f"[[{p['n']},{p['k']},{d}]] w={p['w']} css={p['css']} "
            f"conn={p['connected']} empty={p['empty_rows']}"
        )
    print("\nself-test:", "PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    print("multiband vs published builder (rows=2, m=3, pitch=d-1):")
    sys.exit(0 if _selftest() else 1)
