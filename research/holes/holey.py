"""Holey rotated surface codes with growing smooth/rough holes.

Qubits at integer coords (x,y), 0 <= x < W, 0 <= y < H.
Cells: 2x2 blocks with lower-left corner (cx,cy); type X if (cx+cy)%2==px else Z.
Boundary weight-2 checks parametrized by 4 parity bits (scanned for k=1,d=L).
Holes: rectangles of removed qubits with a boundary type (smooth='Z-loop carrier').

Conventions here: hole of type 'X' keeps truncated X-checks on its edge
(an X-type internal boundary). Its light logicals: Z-loop around it,
X-string to another X-hole or an X-type outer boundary side.
"""
import numpy as np
from itertools import product


def rank2(M):
    M = M.copy().astype(np.uint8)
    r = 0
    rows, cols = M.shape
    for c in range(cols):
        piv = None
        for i in range(r, rows):
            if M[i, c]:
                piv = i
                break
        if piv is None:
            continue
        M[[r, piv]] = M[[piv, r]]
        for i in range(rows):
            if i != r and M[i, c]:
                M[i] ^= M[r]
        r += 1
        if r == rows:
            break
    return r


def build(W, H, px=0, bl=0, br=0, bb=0, bt=0, holes=()):
    """Return dict with checks, coords, n, k for a rotated patch with holes.

    holes: list of (x0, y0, x1, y1, T) — qubits x0<=x<x1, y0<=y<y1 removed,
    T in {'X','Z'} = type of the internal boundary kept on the hole edge.
    px: cell-type parity. bl/br/bb/bt: boundary-pair parity bits (left/right/bottom/top).
    Left/right outer boundaries carry X pairs; bottom/top carry Z pairs (rotated std).
    """
    removed = set()
    for (x0, y0, x1, y1, T) in holes:
        for x in range(x0, x1):
            for y in range(y0, y1):
                removed.add((x, y))
    qubits = [(x, y) for x in range(W) for y in range(H) if (x, y) not in removed]
    qidx = {q: i for i, q in enumerate(qubits)}
    n = len(qubits)

    def hole_of(q):
        for hi, (x0, y0, x1, y1, T) in enumerate(holes):
            if x0 <= q[0] < x1 and y0 <= q[1] < y1:
                return hi
        return None

    X_checks, Z_checks = [], []
    # interior cells
    for cx in range(W - 1):
        for cy in range(H - 1):
            cell = [(cx, cy), (cx + 1, cy), (cx, cy + 1), (cx + 1, cy + 1)]
            alive = [q for q in cell if q not in removed]
            typ = 'X' if (cx + cy) % 2 == px else 'Z'
            if len(alive) == 4:
                (X_checks if typ == 'X' else Z_checks).append([qidx[q] for q in alive])
            elif len(alive) in (2, 3):
                # touching >=1 hole: keep only if this cell's type matches EVERY
                # adjacent hole's boundary type, and only the weight-2 truncations
                # (weight-3 corner truncations anticommute with neighbors: drop).
                dead = [q for q in cell if q in removed]
                htypes = {holes[hole_of(q)][4] for q in dead}
                if len(alive) == 2 and htypes == {typ}:
                    (X_checks if typ == 'X' else Z_checks).append([qidx[q] for q in alive])
            # len(alive) in (0,1): drop
    # outer boundary weight-2 checks (skip pairs touching removed qubits)
    for y in range(H - 1):
        if y % 2 == bl:
            pair = [(0, y), (0, y + 1)]
            if all(q not in removed for q in pair):
                X_checks.append([qidx[q] for q in pair])
        if y % 2 == br:
            pair = [(W - 1, y), (W - 1, y + 1)]
            if all(q not in removed for q in pair):
                X_checks.append([qidx[q] for q in pair])
    for x in range(W - 1):
        if x % 2 == bb:
            pair = [(x, 0), (x + 1, 0)]
            if all(q not in removed for q in pair):
                Z_checks.append([qidx[q] for q in pair])
        if x % 2 == bt:
            pair = [(x, H - 1), (x + 1, H - 1)]
            if all(q not in removed for q in pair):
                Z_checks.append([qidx[q] for q in pair])

    HX = np.zeros((len(X_checks), n), dtype=np.uint8)
    for i, ch in enumerate(X_checks):
        HX[i, ch] = 1
    HZ = np.zeros((len(Z_checks), n), dtype=np.uint8)
    for i, ch in enumerate(Z_checks):
        HZ[i, ch] = 1
    comm_ok = not ((HX @ HZ.T) % 2).any()
    k = n - rank2(HX) - rank2(HZ)
    return dict(n=n, k=k, comm=comm_ok, HX=HX, HZ=HZ, qubits=qubits, qidx=qidx,
                X_checks=X_checks, Z_checks=Z_checks)


def scan_boundary(L, px=0):
    """Find boundary bits giving the standard [[L^2,1,L]] rotated code."""
    good = []
    for bl, br, bb, bt in product((0, 1), repeat=4):
        c = build(L, L, px, bl, br, bb, bt)
        if c['comm'] and c['k'] == 1:
            good.append((bl, br, bb, bt))
    return good


def build_greedy(W, H, px=0, bl=0, br=0, bb=0, bt=0, holes=()):
    """Like build(), but hole boundaries are found by greedy completion to a
    maximal commuting set of 2x2-local checks (full cells first, then
    hole-type-biased truncations, then everything else largest-first)."""
    removed = set()
    holetype = {}
    for (x0, y0, x1, y1, T) in holes:
        for x in range(x0, x1):
            for y in range(y0, y1):
                removed.add((x, y))
    qubits = [(x, y) for x in range(W) for y in range(H) if (x, y) not in removed]
    qidx = {q: i for i, q in enumerate(qubits)}
    n = len(qubits)

    def near_hole(cell_qs):
        # returns type of adjacent hole if the cell overlaps a removed region
        for (x0, y0, x1, y1, T) in holes:
            for (x, y) in cell_qs:
                if x0 <= x < x1 and y0 <= y < y1:
                    return T
        return None

    from itertools import combinations
    Xc, Zc = [], []          # accepted checks (as sorted index tuples)
    HXrows, HZrows = [], []  # as numpy rows for commutation tests

    def commutes(support, typ):
        v = np.zeros(n, dtype=np.uint8)
        v[list(support)] = 1
        opp = HZrows if typ == 'X' else HXrows
        for row in opp:
            if (int(v @ row) % 2) == 1:
                return False
        return True

    def add(support, typ):
        v = np.zeros(n, dtype=np.uint8)
        v[list(support)] = 1
        if typ == 'X':
            Xc.append(tuple(sorted(support))); HXrows.append(v)
        else:
            Zc.append(tuple(sorted(support))); HZrows.append(v)

    seen = set()

    def try_add(support, typ):
        key = (typ, tuple(sorted(support)))
        if key in seen or len(support) == 0:
            return False
        seen.add(key)
        # skip if dependent duplicate of existing same-type check on same support
        if commutes(support, typ):
            add(support, typ)
            return True
        return False

    # candidate cells
    cells = []
    for cx in range(W - 1):
        for cy in range(H - 1):
            cell = [(cx, cy), (cx + 1, cy), (cx, cy + 1), (cx + 1, cy + 1)]
            alive = [qidx[q] for q in cell if q not in removed]
            typ = 'X' if (cx + cy) % 2 == px else 'Z'
            hT = near_hole(cell)
            cells.append((cx, cy, typ, alive, hT))
    # pass 1: full cells
    for cx, cy, typ, alive, hT in cells:
        if len(alive) == 4:
            try_add(alive, typ)
    # outer boundary pairs (standard)
    for y in range(H - 1):
        for (bit, x) in ((bl, 0), (br, W - 1)):
            if y % 2 == bit:
                pair = [(x, y), (x, y + 1)]
                if all(q not in removed for q in pair):
                    try_add([qidx[q] for q in pair], 'X')
    for x in range(W - 1):
        for (bit, y) in ((bb, 0), (bt, H - 1)):
            if x % 2 == bit:
                pair = [(x, y), (x + 1, y)]
                if all(q not in removed for q in pair):
                    try_add([qidx[q] for q in pair], 'Z')
    # pass 2: hole-type-matching truncations, full alive support, largest first
    for sz in (3, 2):
        for cx, cy, typ, alive, hT in cells:
            if hT is not None and typ == hT and len(alive) == sz:
                try_add(alive, typ)
    # pass 3: everything else — truncations and sub-supports, largest first
    cand = []
    for cx, cy, typ, alive, hT in cells:
        if len(alive) in (2, 3):
            for sz in range(len(alive), 1, -1):
                for sub in combinations(alive, sz):
                    for t2 in ('X', 'Z') if hT is None else (hT, ('X' if hT == 'Z' else 'Z')):
                        cand.append((-sz, cx, cy, t2, sub))
    cand.sort()
    for _, cx, cy, t2, sub in cand:
        try_add(list(sub), t2)

    HX = np.array(HXrows, dtype=np.uint8) if HXrows else np.zeros((0, n), np.uint8)
    HZ = np.array(HZrows, dtype=np.uint8) if HZrows else np.zeros((0, n), np.uint8)
    comm_ok = not ((HX @ HZ.T) % 2).any() if len(HXrows) and len(HZrows) else True
    k = n - rank2(HX) - rank2(HZ)
    return dict(n=n, k=k, comm=comm_ok, HX=HX, HZ=HZ, qubits=qubits, qidx=qidx,
                X_checks=[list(c) for c in Xc], Z_checks=[list(c) for c in Zc])


def build_torus_greedy(L, px=0, holes=()):
    """Rotated toric code (all 2x2 cells on Z_L x Z_L, L even) with holes,
    boundaries via greedy completion as in build_greedy."""
    assert L % 2 == 0
    removed = set()
    for (x0, y0, x1, y1, T) in holes:
        for x in range(x0, x1):
            for y in range(y0, y1):
                removed.add((x % L, y % L))
    qubits = [(x, y) for x in range(L) for y in range(L)
              if (x, y) not in removed]
    qidx = {q: i for i, q in enumerate(qubits)}
    n = len(qubits)

    def near_hole(cell_qs):
        for (x0, y0, x1, y1, T) in holes:
            for (x, y) in cell_qs:
                for q in ((x, y), (x + L, y), (x, y + L), (x + L, y + L)):
                    if x0 <= q[0] < x1 and y0 <= q[1] < y1:
                        return T
        return None

    from itertools import combinations
    Xc, Zc, HXrows, HZrows = [], [], [], []

    def commutes(support, typ):
        v = np.zeros(n, dtype=np.uint8)
        v[list(support)] = 1
        for row in (HZrows if typ == 'X' else HXrows):
            if (int(v @ row) % 2) == 1:
                return False
        return True

    def add(support, typ):
        v = np.zeros(n, dtype=np.uint8)
        v[list(support)] = 1
        (Xc if typ == 'X' else Zc).append(tuple(sorted(support)))
        (HXrows if typ == 'X' else HZrows).append(v)

    seen = set()

    def try_add(support, typ):
        key = (typ, tuple(sorted(support)))
        if key in seen or len(support) == 0:
            return
        seen.add(key)
        if commutes(support, typ):
            add(support, typ)

    cells = []
    for cx in range(L):
        for cy in range(L):
            cell = [((cx + dx) % L, (cy + dy) % L)
                    for dx in (0, 1) for dy in (0, 1)]
            alive = [qidx[q] for q in cell if q not in removed]
            typ = 'X' if (cx + cy) % 2 == px else 'Z'
            cells.append((cx, cy, typ, alive, near_hole(cell)))
    for cx, cy, typ, alive, hT in cells:
        if len(alive) == 4:
            try_add(alive, typ)
    for sz in (3, 2):
        for cx, cy, typ, alive, hT in cells:
            if hT is not None and typ == hT and len(alive) == sz:
                try_add(alive, typ)
    cand = []
    for cx, cy, typ, alive, hT in cells:
        if len(alive) in (2, 3):
            for sz in range(len(alive), 1, -1):
                for sub in combinations(alive, sz):
                    for t2 in ('X', 'Z'):
                        cand.append((-sz, cx, cy, t2, sub))
    cand.sort()
    for _, cx, cy, t2, sub in cand:
        try_add(list(sub), t2)

    HX = np.array(HXrows, dtype=np.uint8) if HXrows else np.zeros((0, n), np.uint8)
    HZ = np.array(HZrows, dtype=np.uint8) if HZrows else np.zeros((0, n), np.uint8)
    comm_ok = not ((HX @ HZ.T) % 2).any()
    k = n - rank2(HX) - rank2(HZ)
    return dict(n=n, k=k, comm=comm_ok, HX=HX, HZ=HZ, qubits=qubits,
                qidx=qidx, X_checks=[list(c) for c in Xc],
                Z_checks=[list(c) for c in Zc])
