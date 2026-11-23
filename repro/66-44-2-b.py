#!/usr/bin/env python3
"""Rebuild the [[66,44,2]] weight-6 CSS code submitted in this PR.

Construction: pair-partition relative-permutation CSS (CPM-PP), produced by the code-calculus v0.3.1rc consumer
(repo unitaryfoundation/code-calculus-dev @ 8aa97b9, machine/constructors.py,
`L-PAIR-PARTITION`; Okada-Kasai v4 Thm 4).

Parameters: p = 11 (permutation domain Z_11), L = 6 paired columns, one X block row and one Z block row, unit slopes (a = 1). X shifts b_X = (0, 0, 0, 0, 0, 0); Z shifts b_Z = (0, 0, 1, 1, 2, 2). The relative affine maps pair columns (0,1), (2,3), (4,5), so the natural rows commute.
Natural rows: for each u in Z_11 and each block row, the check touches qubits
(c, (a_c*u + b_c) mod 11) for c in 0..5; 11 X checks and 11 Z checks
of weight 6. n = 6 * 11 = 66, k = n - rank H_X - rank H_Z = 44.
Writes 66-44-2-b.npz with keys hx, hz (dense 0/1 matrices).
"""
import numpy as np

P = 11
L = 6
BX = [([1, 1, 1, 1, 1, 1], (0, 0, 0, 0, 0, 0))]
BZ = [([1, 1, 1, 1, 1, 1], (0, 0, 1, 1, 2, 2))]

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
    assert (n, k) == (66, 44) and w == 6, (n, k, w)
    np.savez("66-44-2-b.npz", hx=hx, hz=hz)
    print("wrote 66-44-2-b.npz")

if __name__ == "__main__":
    main()
