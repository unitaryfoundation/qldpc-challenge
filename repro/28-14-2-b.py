#!/usr/bin/env python3
"""Rebuild the [[28,14,2]] weight-4 CSS code submitted in this PR.

Construction: PP-SCALE explicit extension (rung-3 transition, Kasai 2026) with mixed +1/-1 column slopes, produced by the code-calculus v0.3.1rc consumer
(repo unitaryfoundation/code-calculus-dev @ 8aa97b9, machine/constructors.py,
`PP-SCALE`; Okada-Kasai v4 Thm 4).

Parameters: SNF bundle with P0 = 3, orders_e = [2], roots_r0 = [2], Q rows = (1,0,1,0) (slope pattern 1 / -1 per column), G rows = shifts, theta = [1]; evaluated at P = 7 with roots_r = [6] (6^2 = 1 mod 7). Column slopes a_c = (6, 1, 6, 1); X shifts b_X = (0, 0, 0, 0); Z shifts b_Z = (0, 1, 0, 1). The relative affine maps pair columns (0,1) and (2,3).
Natural rows: for each u in Z_7 and each block row, the check touches qubits
(c, (a_c*u + b_c) mod 7) for c in 0..3; 7 X checks and 7 Z checks
of weight 4. n = 4 * 7 = 28, k = n - rank H_X - rank H_Z = 14.
Writes 28-14-2-b.npz with keys hx, hz (dense 0/1 matrices).
"""
import numpy as np

P = 7
L = 4
BX = [([6, 1, 6, 1], (0, 0, 0, 0))]
BZ = [([6, 1, 6, 1], (0, 1, 0, 1))]

def affine_rows():
    rows = []
    for sector, rows_spec in (("X", BX), ("Z", BZ)):
        for (slopes, shifts) in rows_spec:
            for u in range(P):
                support = sorted(c * P + (slopes[c] * u + shifts[c]) % P
                                 for c in range(L))
                rows.append((sector, support))
    return rows

def dense(rows, n):
    m = np.zeros((len(rows), n), dtype=np.uint8)
    for i, (_sector, sup) in enumerate(rows):
        m[i, sup] = 1
    return m

def gf2_rank(m):
    m = m.copy().astype(np.uint8)
    rows, cols = m.shape
    r = 0
    for c in range(cols):
        piv = next((i for i in range(r, rows) if m[i, c]), None)
        if piv is None:
            continue
        m[[r, piv]] = m[[piv, r]]
        for i in range(rows):
            if i != r and m[i, c]:
                m[i] ^= m[r]
        r += 1
    return r

def main():
    n = L * P
    rows = affine_rows()
    hx = dense([r for r in rows if r[0] == "X"], n)
    hz = dense([r for r in rows if r[0] == "Z"], n)
    cross = (hx.astype(np.int64) @ hz.astype(np.int64).T) % 2
    assert not cross.any(), "X and Z rows do not commute"
    k = n - gf2_rank(hx) - gf2_rank(hz)
    w = max(hx.sum(1).max(), hz.sum(1).max())
    print("n=%d checks X=%d Z=%d weight=%d k=%d" % (n, hx.shape[0], hz.shape[0], w, k))
    assert (n, k) == (28, 14) and w == 4, (n, k, w)
    np.savez("28-14-2-b.npz", hx=hx, hz=hz)
    print("wrote 28-14-2-b.npz")

if __name__ == "__main__":
    main()
