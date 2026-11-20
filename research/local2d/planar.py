"""Open-boundary planar BB codes, the fast greedy builder + exact MILP distance.

Construction of Liang-Eberhardt-Chen "Planar quantum LDPC codes with open
boundaries" (arXiv:2504.08887, Sec. II / Table V): a torus bivariate-bicycle
code with polynomials f, g is truncated to an open Lx x Ly grid with
directional anyon condensation -- X-type boundary terms (truncated bulk
X-stabilizers) may hang off the top/bottom edges (m-condensed), Z-type off the
left/right edges (e-condensed), and corner anticommutation is resolved by a
greedy drop of the conflicting X rows (the paper's footnote-6 convention).

These codes are 2D-LOCAL: qubits A(i,j)/B(i,j) live on a bilayer grid, every
check acts within a fixed radius. ``grid_coordinates`` produces the layout for
``submit.make_submission(coordinates=..., layers=2)`` so the verifier can
compute the ``2d-local-*`` track membership.

VALIDATED (against the paper, MILP-exact): the flagship [[288,8,12]] family
(f = x + x^2 + y^2, g = 1 + x^2 y + x^2 y^2) gives k = 8 for L = 6..12 square
AND rectangular, d = 4 (6x6), 6 (8x8), 9 (10x10), matching Table V.

SCOPE / LIMITS (measured, read before reusing):

* GENERIC (f,g) WARNING: for arbitrary exponents the directional truncation +
  greedy corner drop does NOT restore the topological-order condition (sampled:
  only ~13/60 of MV==8 candidates come out with the right k; the rest inflate k
  with weight-1/2 local logicals). This builder is validated for the
  [[288,8,12]] family; for other (f,g) treat its output as "a CSS code", not
  "the paper's planar code" -- screen with a k(L)-stability check across two
  sizes, or use the exact gauge engine in ``boundary_engine.build_planar``.
* Weight-6 families only, where boundary gauge operators ARE truncated bulk
  stabilizers. Weight-8 families need the secondary (non-truncation) boundary
  generators that only ``boundary_engine`` produces.
* Keeps all 2*Lx*Ly qubits; the qubit-removal layouts (e.g. [[188,8,9]]) come
  out of ``boundary_engine.build_planar``'s cleanup automatically.

The distance functions need scipy (the ``research`` extra); construction and
the coordinate helper stay numpy-only.
"""

import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, "..", "kit")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from css import compute_k, logical_basis, rref, verify_css  # noqa: E402

# Default polynomials of the [[288,8,12]] code (Eq. 9). Supports are (di, dj).
S_f = [(1, 0), (2, 0), (0, 2)]
S_g = [(0, 0), (2, 1), (2, 2)]
S_fbar = [(-1, 0), (-2, 0), (0, -2)]
S_gbar = [(0, 0), (-2, -1), (-2, -2)]


def build_open_directional(Lx, Ly, S_f=S_f, S_g=S_g, S_fbar=S_fbar, S_gbar=S_gbar, resolve_corners=True):
    """Open-boundary CSS code on an Lx x Ly grid, n = 2*Lx*Ly.

    Qubit indexing: A-qubits (one Pauli family) idx = i*Ly + j;
    B-qubits idx = Lx*Ly + i*Ly + j;  i in [0,Lx), j in [0,Ly).
    H_X rows = [f on A | g on B];  H_Z rows = [gbar on A | fbar on B].

    Boundary condensation:
      * X boundary terms allowed to hang off only the row (top/bottom) edges;
      * Z boundary terms allowed to hang off only the column (left/right) edges.
    Returns (HX, HZ) as int8 arrays over GF(2).
    """
    n2 = Lx * Ly
    n = 2 * n2
    A = lambda i, j: i * Ly + j
    B = lambda i, j: n2 + i * Ly + j
    row_in = lambda i: 0 <= i < Lx
    col_in = lambda j: 0 <= j < Ly
    inb = lambda i, j: row_in(i) and col_in(j)

    offs = S_f + S_g + S_fbar + S_gbar
    di_hi = max(d[0] for d in offs)
    di_lo = min(d[0] for d in offs)
    dj_hi = max(d[1] for d in offs)
    dj_lo = min(d[1] for d in offs)

    def make_row(ci, cj, suppA, suppB, keep_oob):
        """Build one truncated row; return None if a dropped (out-of-bounds)
        qubit violates keep_oob, or if the row is empty.
        """
        row = np.zeros(n, dtype=np.int8)
        any_in = False
        for di, dj in suppA:
            i, j = ci + di, cj + dj
            if inb(i, j):
                row[A(i, j)] ^= 1
                any_in = True
            elif not keep_oob(i, j):
                return None
        for di, dj in suppB:
            i, j = ci + di, cj + dj
            if inb(i, j):
                row[B(i, j)] ^= 1
                any_in = True
            elif not keep_oob(i, j):
                return None
        if not any_in or row.sum() == 0:
            return None
        return row

    # X may hang off top/bottom (column in range, row out); Z off left/right.
    x_keep = lambda i, j: col_in(j) and not row_in(i)
    z_keep = lambda i, j: row_in(i) and not col_in(j)

    xrows, zrows = [], []
    for ci in range(-di_hi, Lx - di_lo):
        for cj in range(-dj_hi, Ly - dj_lo):
            rx = make_row(ci, cj, S_f, S_g, x_keep)
            if rx is not None:
                xrows.append(rx)
            rz = make_row(ci, cj, S_gbar, S_fbar, z_keep)
            if rz is not None:
                zrows.append(rz)

    HX = np.array(xrows, dtype=np.int8)
    HZ = np.array(zrows, dtype=np.int8)

    if resolve_corners and HX.size and HZ.size:
        # Corner topological-order completion (validated greedy): drop the X
        # boundary terms that anticommute with any Z term. See footnote-6 note.
        conflict = ((HX @ HZ.T) % 2).sum(axis=1) > 0
        if conflict.any():
            HX = HX[~conflict]
    return HX, HZ


def grid_coordinates(Lx, Ly, kept=None):
    """Per-qubit [x, y] layout for the bilayer grid, for
    ``submit.make_submission(coordinates=..., layers=2)``.

    A(i,j) and B(i,j) share the site (i, j) on two layers. ``kept`` (from
    ``boundary_engine.build_planar``'s cleanup info) restricts to the surviving
    qubits of a qubit-removal layout, in their post-cleanup order.
    """
    n2 = Lx * Ly
    coords = [[i, j] for i in range(Lx) for j in range(Ly)] * 2
    if kept is not None:
        coords = [coords[int(q)] for q in kept]
    return coords


# ---- distance: min-weight logical via MILP, computing BOTH d_X and d_Z ------
def _min_logical_weight(HX, HZ, tlim=None):
    """Min weight of a nontrivial operator in ker(HZ) that anticommutes with a
    logical of ker(HX)/im(HZ). Calling with (HX,HZ) gives d_X; with (HZ,HX)
    gives d_Z. Returns (weight, proved_optimal).

    Semantics under a time limit: if some per-logical subproblems time out,
    proved=False and the returned weight is only an UPPER bound on the true
    minimum (the min over the solved subproblems). If NO subproblem solved,
    returns (inf, False) -- never a fake finite sentinel.
    """
    try:
        from scipy.optimize import Bounds, LinearConstraint, milp
    except ImportError as e:
        raise ImportError("exact planar distance needs scipy: uv run --with scipy ...") from e
    n = HX.shape[1]
    LZ = logical_basis(HX, HZ)
    if LZ.shape[0] == 0:
        return float("inf"), True

    # Use a full-rank basis of HZ as parity constraints (fewer rows -> faster).
    Hc, _piv = rref(HZ)
    numC = Hc.shape[0]
    best, proved = n + 1, True
    for tL in LZ:
        nv = n + numC + 1
        c = np.zeros(nv)
        c[:n] = 1.0
        lb = np.zeros(nv)
        ub = np.zeros(nv)
        ub[:n] = 1.0
        ub[n : n + numC] = np.sum(Hc, axis=1) // 2
        ub[-1] = int(tL.sum()) // 2
        Amat = np.zeros((numC + 1, nv))
        Amat[:numC, :n] = Hc
        Amat[:numC, n : n + numC] = -2 * np.eye(numC)
        Amat[numC, :n] = tL
        Amat[numC, -1] = -2
        blb = np.zeros(numC + 1)
        bub = np.zeros(numC + 1)
        blb[-1] = 1
        bub[-1] = 1
        opts = {"time_limit": tlim} if tlim else {}
        res = milp(
            c=c,
            constraints=LinearConstraint(Amat, blb, bub),
            integrality=np.ones(nv),
            bounds=Bounds(lb, ub),
            options=opts,
        )
        if res.x is not None and res.fun is not None:
            best = min(best, int(round(res.fun)))
            if not res.success:
                proved = False  # time limit hit: incumbent is valid but not proved optimal
        else:
            proved = False  # no feasible solution found at all
    if best > n:
        # No subproblem solved at all (e.g. tlim too small): there is no
        # incumbent, so do NOT return the n+1 sentinel as if it were a weight.
        return float("inf"), False
    return best, proved


def distance(HX, HZ, tlim=None):
    """Returns (d_X, d_Z, d, proved). d = min(d_X, d_Z)."""
    dX, pX = _min_logical_weight(HX, HZ, tlim)
    dZ, pZ = _min_logical_weight(HZ, HX, tlim)
    return dX, dZ, min(dX, dZ), (pX and pZ)


def code_params(Lx, Ly, tlim=None):
    HX, HZ = build_open_directional(Lx, Ly)
    n = HX.shape[1]
    assert verify_css(HX, HZ), "CSS commutation failed"
    k = compute_k(HX, HZ)
    dX, dZ, d, proved = distance(HX, HZ, tlim)
    return dict(n=n, k=k, dX=dX, dZ=dZ, d=d, proved=proved)


if __name__ == "__main__":
    HX, HZ = build_open_directional(6, 6)
    print("flagship family, 6x6 grid:")
    print(f"  n = {HX.shape[1]}  CSS = {verify_css(HX, HZ)}  k = {compute_k(HX, HZ)}  (expect n=72, k=8)")
    try:
        p = code_params(6, 6, tlim=60)
        print(f"  MILP distance: dX={p['dX']} dZ={p['dZ']} d={p['d']} proved={p['proved']}  (expect d=4)")
    except ImportError as e:
        print(f"  (skipping exact distance: {e})")
