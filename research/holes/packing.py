"""Checkerboard mixed-type hole packings: build, measure (n,k,d), ratio.

Family: h x h holes on an m x m array with pitch t, types checkerboarded
(X/Z by (i+j) parity), centered in a rotated patch with margin `pad`.
Ratio reported: kd^2/(c^2 n) with c = 4 (w=2, rho=1), and the interior-cell
prediction 2 d^2 / (16 (t^2 - 2 h^2)) for comparison.
"""
import sys
import time
import numpy as np
from holey import build_greedy, rank2
import distance as dst
import graphdist as gd


def fast_logical_basis(HA, HB):
    """Rows of ker(HA) independent modulo rowspace(HB), vectorized."""
    K = dst.gf2_kernel(HA)
    if len(K) == 0:
        return np.zeros((0, HA.shape[1]), dtype=np.uint8)
    M = np.vstack([HB, K]).astype(np.uint8)
    origin = np.array([0] * len(HB) + [1] * len(K))
    rows, cols = M.shape
    r = 0
    piv_origin = []
    for c in range(cols):
        piv = None
        for i in range(r, rows):          # prefer stabilizer-origin pivots
            if M[i, c] and origin[i] == 0:
                piv = i
                break
        if piv is None:
            for i in range(r, rows):
                if M[i, c]:
                    piv = i
                    break
        if piv is None:
            continue
        M[[r, piv]] = M[[piv, r]]
        origin[[r, piv]] = origin[[piv, r]]
        mask = (M[:, c] == 1)
        mask[r] = False
        M[mask] ^= M[r]
        piv_origin.append((r, origin[r]))
        r += 1
        if r == rows:
            break
    out = [M[i] for i, o in piv_origin if o == 1]
    return np.array(out, dtype=np.uint8) if out else np.zeros((0, cols), np.uint8)


# monkey-patch the faster basis into graphdist
gd.logical_basis = fast_logical_basis


def build_packing(h, t, m, pad, verbose=True):
    """m x m checkerboard of h-holes at pitch t, margin pad."""
    span = (m - 1) * t + h
    W = span + 2 * pad
    if W % 2 == 0:
        W += 1
    H = W
    holes = []
    for i in range(m):
        for j in range(m):
            x0 = pad + i * t
            y0 = pad + j * t
            T = 'X' if (i + j) % 2 == 0 else 'Z'
            holes.append((x0, y0, x0 + h, y0 + h, T))
    c = build_greedy(W, H, 0, 1, 0, 0, 1, holes=holes)
    c['holes'] = holes
    if verbose:
        print(f'  built W={W} n={c["n"]} k={c["k"]} comm={c["comm"]}', flush=True)
    return c


def measure(h, t, m, pad):
    t0 = time.time()
    c = build_packing(h, t, m, pad)
    dX, _ = gd.graph_distance(c, 'X')
    dZ, _ = gd.graph_distance(c, 'Z')
    d = min(x for x in (dX, dZ) if x is not None)
    n, k = c['n'], c['k']
    ratio = k * d * d / (16.0 * n)
    interior = 2 * d * d / (16.0 * (t * t - 2 * h * h))
    print(f'h={h} t={t} m={m}x{m}: [[{n},{k},{d}]] dX={dX} dZ={dZ} '
          f'ratio={ratio:.4f} interior-cell-pred={interior:.4f} '
          f'({time.time()-t0:.0f}s)', flush=True)
    return dict(h=h, t=t, m=m, n=n, k=k, d=d, dX=dX, dZ=dZ, ratio=ratio)


if __name__ == '__main__':
    h = int(sys.argv[1])
    t = int(sys.argv[2])
    m = int(sys.argv[3])
    pad = int(sys.argv[4]) if len(sys.argv) > 4 else 3 * h + 2
    measure(h, t, m, pad)
