"""
Minimal GF(2) linear algebra for the verifier.

Deliberately simple and slow over correct-and-auditable. Verification is not
the hot path (search is, and that lives elsewhere); a reviewer should be able
to read this file in two minutes and trust it. numpy int8, schoolbook RREF.
"""

import numpy as np


def _as_gf2(M):
    return (np.asarray(M, dtype=np.int8) % 2).astype(np.int8)


def rref(M):
    """Reduced row echelon form over GF(2). Returns (R, pivot_columns) where R
    holds only the nonzero reduced rows.
    """
    A = _as_gf2(M).copy()
    if A.ndim != 2 or A.size == 0:
        return A.reshape(0, A.shape[-1] if A.ndim == 2 else 0), []
    rows, cols = A.shape
    r = 0
    pivots = []
    for c in range(cols):
        if r >= rows:
            break
        sel = np.nonzero(A[r:, c])[0]
        if sel.size == 0:
            continue
        i = r + int(sel[0])
        if i != r:
            A[[r, i]] = A[[i, r]]
        mask = A[:, c].astype(bool).copy()
        mask[r] = False
        if mask.any():
            A[mask] ^= A[r]
        pivots.append(c)
        r += 1
    return A[:r], pivots


def rank(M):
    return len(rref(M)[1])


def in_rowspace(v, M):
    """Is the vector v in the GF(2) rowspace of M?"""
    R, piv = rref(M)
    v = _as_gf2(v).copy()
    for i, c in enumerate(piv):
        if v[c]:
            v = (v ^ R[i]).astype(np.int8)
    return not bool(v.any())


def commutes(v, H):
    """Does v lie in ker(H), i.e. H @ v == 0 over GF(2)? For a CSS code an
    X-type logical commutes with the Z-checks iff it is in ker(H_Z).
    """
    H = _as_gf2(H)
    v = _as_gf2(v)
    return not bool(((H @ v) % 2).any())


def kernel_basis(H):
    """Basis of {v : H v = 0 over GF(2)} as rows of an array."""
    H = _as_gf2(H)
    n = H.shape[1]
    R, piv = rref(H)
    pivset = set(piv)
    free = [c for c in range(n) if c not in pivset]
    B = np.zeros((len(free), n), dtype=np.int8)
    for idx, fc in enumerate(free):
        B[idx, fc] = 1
        for i, p in enumerate(piv):
            B[idx, p] = R[i, fc] % 2
    return B


def logical_basis(HX, HZ):
    """Z-type logical representatives: ker(H_X) reduced modulo rowspace(H_Z).
    These are the operators a nontrivial X-type logical must anticommute with.
    Mirror with (HZ, HX) for the X-type logicals.
    """
    SZ, piv = rref(HZ)
    SZ = SZ.copy()
    piv = list(piv)
    out = []
    for v in kernel_basis(HX):
        v = v.copy()
        for i, p in enumerate(piv):
            if v[p]:
                v = (v ^ SZ[i]).astype(np.int8)
        if v.any():
            out.append(v.copy())
            SZ = np.vstack([SZ, v])
            SZ, p2 = rref(SZ)
            SZ = SZ.copy()
            piv = list(p2)
    return np.array(out, dtype=np.int8) if out else np.zeros((0, HX.shape[1]), dtype=np.int8)
