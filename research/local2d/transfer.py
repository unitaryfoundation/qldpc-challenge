"""Transfer-graph distance law for open-boundary planar BB families.

For a planar family (f, g), the X-distance obeys d_X(L) = min(s* L + O(1),
w_bdd): either it grows linearly with slope s* or it saturates at a bounded
corner-pinned logical (see ``corner_detector`` for w_bdd). This module
computes s* exactly as a MIN-MEAN-WEIGHT CYCLE of a transfer graph -- so you
can predict how a family's distance scales BEFORE building large lattices.
Verified against MILP-certified d_X for 7 families across 5 distinct slopes
(4/7, 2/3, 6/7, 1, 3/2).

Construction (general, no unit-leading-coefficient assumption).
An X-logical (a on A, b on B) obeys  a*g + b*f = 0  over F2[x^+-1, y^+-1].
Take x = "row" (the shorter-degree variable), y = "column" (width W, OPEN strip).
Write f = sum_k f_k(y) x^k, g = sum_k g_k(y) x^k with all x-powers shifted >= 0,
D = max x-degree. Per x-power i the constraint is

    C_i :  sum_k g_k * a_{i-k}  +  sum_k f_k * b_{i-k}  =  0   (in F2[y]),     (C)

checkable once rows 0..i are chosen. A vertical X-logical is a path:
  * state  = the last D rows of (a, b)  (a sliding window),
  * edge   = a choice of the new row (a_i, b_i) such that C_i holds and no
             y-multiplication overflows the open strip [0, W),
  * cost   = popcount(a_i) + popcount(b_i).
The asymptotic d_X / L is the MIN-MEAN-WEIGHT CYCLE of this graph; the finite-L
distance is a min-weight boundary-to-boundary path. States are translation-
normalized in y (shift so the lowest set bit across the window is column 0).

Example: the flagship [[288,8,12]] family's minimal logicals are truncated
Sierpinski triangles only in a pre-asymptotic regime (L <~ 16); asymptotically
d ~ 3L/2 - 6, realized by a period-4 weight-6 "drifting soliton" -- the slope
3/2 this module reproduces in its self-test.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, "..", "kit")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from boundary_engine import pmul  # noqa: E402


def pc(x):
    return bin(int(x)).count("1")


# ---------------------------------------------------------------------------
# Family -> (f_coeffs, g_coeffs): dict {x_power: F2[y] coefficient as bitmask}
# ---------------------------------------------------------------------------
def _poly_from_support(S, row_axis):
    """S = list of (i, j) monomials (x^i y^j). row_axis picks which of the two
    exponents is the row variable x; the other is the column variable y.
    """
    if row_axis == 0:
        pts = [(i, j) for (i, j) in S]
    else:
        pts = [(j, i) for (i, j) in S]
    return pts


def family_coeffs(Sf, Sg, row_axis):
    """Build {x_power: ymask} for f and g with a COMMON nonneg shift in both x
    (row) and y (column). Returns (fc, gc, D).
    """
    pf = _poly_from_support(Sf, row_axis)
    pg = _poly_from_support(Sg, row_axis)
    allpts = pf + pg
    xmin = min(k for k, _ in allpts)
    ymin = min(j for _, j in allpts)

    def build(pts):
        c = {}
        for k, j in pts:
            kk = k - xmin
            c[kk] = c.get(kk, 0) ^ (1 << (j - ymin))
        return c

    fc, gc = build(pf), build(pg)
    D = max(max(fc), max(gc))
    return fc, gc, D


def choose_row_axis(Sf, Sg):
    """Pick the row axis (0 or 1) that minimizes the max x-degree D -> smallest
    transfer-graph state. Tie-break: smaller column span.
    """
    best = None
    for ax in (0, 1):
        fc, gc, D = family_coeffs(Sf, Sg, ax)
        span = 0
        for c in (fc, gc):
            for m in c.values():
                span = max(span, m.bit_length())
        key = (D, span)
        if best is None or key < best[0]:
            best = (key, ax, D)
    return best[1], best[2]


# ---------------------------------------------------------------------------
# Transfer graph
# ---------------------------------------------------------------------------
def _ymul_inrange(coeff, val, W):
    """Coeff * val in F2[y]; return product or None if it leaves [0, W)."""
    p = pmul(coeff, val)
    if p >> W:
        return None
    return p


def build_transfer_graph(Sf, Sg, W, CMAX, row_axis=None, exclude_zero=True):
    """General transfer graph for the (f,g) X-logical recursion on an open strip
    of width W. State = a D-row window of (a, b); CMAX caps total window popcount
    (keeps it finite). The all-zero window (the trivial logical) is EXCLUDED so
    its zero-cost self-loop cannot win the min-mean-cycle. States are enumerated
    exhaustively (not BFS) so every periodic operator is present.
    Returns (states, edges) with edges[i] = list of (j, cost).
    """
    if row_axis is None:
        row_axis, _ = choose_row_axis(Sf, Sg)
    fc, gc, D = family_coeffs(Sf, Sg, row_axis)
    masks = [m for m in range(1 << W) if pc(m) <= CMAX]

    def norm(window):
        nz = [m for m in window if m]
        if not nz:
            return tuple(window)
        sh = min((m & -m).bit_length() - 1 for m in nz)
        return tuple(m >> sh for m in window)

    # Enumerate all nonzero windows (D a's then D b's) with cumulative popcount
    # <= CMAX, translation-normalized in y.
    states = set()

    def rec(slot, cum, acc):
        if slot == 2 * D:
            if any(acc) or not exclude_zero:
                states.add(norm(tuple(acc)))
            return
        for m in masks:
            if cum + pc(m) > CMAX:
                continue
            rec(slot + 1, cum + pc(m), acc + [m])

    rec(0, 0, [])
    states = list(states)
    idx = {s: i for i, s in enumerate(states)}

    # Constraint C_i after appending row i:
    #   sum_k gc[k]*a_{i-k} + sum_k fc[k]*b_{i-k} = 0.
    # Window = rows i-D .. i-1 (a's then b's, oldest first); append (a_i, b_i).
    E = [[] for _ in range(len(states))]
    for s in states:
        a_hist = s[:D]
        b_hist = s[D:]
        for a_new in masks:
            for b_new in masks:
                a_seq = a_hist + (a_new,)  # a_{i-D} .. a_i
                b_seq = b_hist + (b_new,)
                acc = 0
                ok = True
                for k, coeff in gc.items():
                    pr = _ymul_inrange(coeff, a_seq[D - k], W)
                    if pr is None:
                        ok = False
                        break
                    acc ^= pr
                if ok:
                    for k, coeff in fc.items():
                        pr = _ymul_inrange(coeff, b_seq[D - k], W)
                        if pr is None:
                            ok = False
                            break
                        acc ^= pr
                if not ok or acc != 0:
                    continue
                t = norm(a_seq[1:] + b_seq[1:])
                if t in idx:
                    E[idx[s]].append((idx[t], pc(a_new) + pc(b_new)))
    return states, E


def min_mean_cycle(V, E):
    """Minimum mean cycle weight via Howard's policy iteration.

    Returns min over directed cycles of (sum of edge costs)/(cycle length),
    or +inf if the graph is acyclic. E[u] = list of (v, cost).

    Memory is O(V + E): unlike Karp's algorithm (which needs a dense
    (V+1) x V distance table, i.e. O(V^2)), Howard keeps only a handful of
    length-V arrays plus the adjacency that is already part of the input. It
    is also typically far faster, converging in a small number of
    policy-improvement rounds.
    """
    from collections import deque

    INF = float("inf")
    EPS = 1e-9

    # --- 1. Peel away nodes that cannot lie on any cycle (no live out-edge). ---
    outdeg = [len(E[u]) for u in range(V)]
    rev = [[] for _ in range(V)]
    for u in range(V):
        for v, _c in E[u]:
            rev[v].append(u)
    alive = [d > 0 for d in outdeg]
    dead = deque(u for u in range(V) if not alive[u])
    while dead:
        v = dead.popleft()
        for u in rev[v]:
            if alive[u]:
                outdeg[u] -= 1
                if outdeg[u] == 0:
                    alive[u] = False
                    dead.append(u)
    rev = None  # free reverse adjacency

    # Adjacency restricted to alive -> alive edges.
    adj = [None] * V
    nodes = []
    for u in range(V):
        if alive[u]:
            ed = [(v, c) for (v, c) in E[u] if alive[v]]
            if ed:
                adj[u] = ed
                nodes.append(u)
            else:
                alive[u] = False
    if not nodes:
        return INF

    # --- 2. Initial policy: cheapest out-edge from each alive node. ---
    pi = [None] * V  # pi[u] = (successor, cost)
    for u in nodes:
        best = None
        for v, c in adj[u]:
            if best is None or c < best[1]:
                best = (v, c)
        pi[u] = best

    gain = [0.0] * V
    bias = [0.0] * V
    state = [0] * V  # scratch for functional-graph cycle detection

    for _ in range(len(nodes) + 5):  # generous cap; Howard converges quickly
        # --- 3. Value determination: every node follows pi to a unique cycle.
        for u in nodes:
            state[u] = 0
        for s in nodes:
            if state[s] != 0:
                continue
            path = []
            u = s
            while state[u] == 0:
                state[u] = 1
                path.append(u)
                u = pi[u][0]
            if state[u] == 1:  # discovered a fresh cycle
                ci = path.index(u)
                cyc = path[ci:]
                L = len(cyc)
                g = sum(pi[w][1] for w in cyc) / L
                bias[u] = 0.0
                for w in cyc:
                    gain[w] = g
                for i in range(L - 1, 0, -1):  # bias around cycle, ref bias[u]=0
                    w = cyc[i]
                    nx = cyc[(i + 1) % L]
                    bias[w] = pi[w][1] - g + bias[nx]
                tail = path[:ci]
            else:  # path feeds an already-valued node
                tail = path
            for w in reversed(tail):  # successor valued first
                sv = pi[w][0]
                gain[w] = gain[sv]
                bias[w] = pi[w][1] - gain[sv] + bias[sv]
            for w in path:
                state[w] = 2

        # --- 4. Policy improvement: first lower the gain, then the bias. ---
        improved = False
        for u in nodes:
            mg = min(gain[v] for (v, _c) in adj[u])
            if mg < gain[u] - EPS:  # an edge reaches a cheaper cycle
                bestval = None
                pick = None
                for v, c in adj[u]:
                    if gain[v] <= mg + EPS:
                        val = c - mg + bias[v]
                        if bestval is None or val < bestval:
                            bestval, pick = val, (v, c)
                pi[u] = pick
                improved = True
            else:  # same gain: try to reduce bias
                g = gain[u]
                bestval = bias[u]
                pick = None
                for v, c in adj[u]:
                    if abs(gain[v] - g) <= EPS:
                        val = c - g + bias[v]
                        if val < bestval - EPS:
                            bestval, pick = val, (v, c)
                if pick is not None:
                    pi[u] = pick
                    improved = True
        if not improved:
            break

    return min(gain[u] for u in nodes)


def slope(Sf, Sg, W, CMAX, row_axis=None):
    st, E = build_transfer_graph(Sf, Sg, W, CMAX, row_axis)
    return min_mean_cycle(len(st), E), len(st)


def distance_slope(Sf, Sg, W, CMAX, Dcap=3):
    """The DISTANCE-relevant slope = MIN over BOTH row-axis orientations of the
    transfer-graph min-mean-cycle slope.

    choose_row_axis() picks the axis with the smaller transfer-graph state set
    (for speed), but a logical may run along EITHER axis and d_X takes the
    cheaper one. Some families have equal slopes on both axes, masking the
    distinction; others expose it (e.g. axis0=2/3 vs axis1=2, with exact d_X
    following 2/3). Returns (min_slope, {axis: (slope, |states|)}).
    Axes whose max x-degree D exceeds Dcap are skipped (graph too large).
    """
    per = {}
    for ax in (0, 1):
        _, _, D = family_coeffs(Sf, Sg, ax)
        if D > Dcap:
            continue
        s, V = slope(Sf, Sg, W, CMAX, ax)
        per[ax] = (s, V)
    if not per:
        return float("inf"), per
    return min(v[0] for v in per.values()), per


# ---------------------------------------------------------------------------
# Self-test: must reproduce the flagship slope 3/2
# ---------------------------------------------------------------------------
def _shift_nonneg(S):
    mi = min(p for p, _ in S)
    mj = min(q for _, q in S)
    return [(p - mi, q - mj) for (p, q) in S]


FLAGSHIP = (1, 0, -1, 2, 0, 1, -2, -1)  # [[288,8,12]]


def flagship_supports():
    a1, b1, a2, b2, c1, d1, c2, d2 = FLAGSHIP
    Sf = _shift_nonneg([(0, 0), (a1, b1), (a2, b2)])
    Sg = _shift_nonneg([(0, 0), (c1, d1), (c2, d2)])
    return Sf, Sg


if __name__ == "__main__":
    print("transfer-graph distance law -- self-test on the flagship")
    print("=" * 58)
    Sf, Sg = flagship_supports()
    ax, D = choose_row_axis(Sf, Sg)
    print(f"flagship Sf={Sf} Sg={Sg}  row_axis={ax} D={D}")
    for W, C in [(5, 4), (6, 4)]:
        s, V = slope(Sf, Sg, W, C)
        print(f"  W={W} Cmax={C}: |states|={V:6d}  slope={s:.4f} /row   (expect ~1.5)", flush=True)
