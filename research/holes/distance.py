"""Exact CSS distances via MILP (scipy/HiGHS).

d_X = min weight of v with HZ v = 0 (mod 2), v not in rowspace(HX)
    = min over a basis {l} of Z-logicals of  min{wt v : HZ v=0 mod 2, <l,v> odd}.
"""
import numpy as np
from scipy.optimize import milp, LinearConstraint, Bounds


def gf2_rowspace_basis(M):
    M = M.copy().astype(np.uint8)
    r = 0
    for c in range(M.shape[1]):
        piv = None
        for i in range(r, M.shape[0]):
            if M[i, c]:
                piv = i
                break
        if piv is None:
            continue
        M[[r, piv]] = M[[piv, r]]
        for i in range(M.shape[0]):
            if i != r and M[i, c]:
                M[i] ^= M[r]
        r += 1
    return M[:r]


def gf2_kernel(M):
    """Basis of {v : M v = 0 mod 2}."""
    M = M.copy().astype(np.uint8)
    m, n = M.shape
    A = np.concatenate([M, np.eye(n, dtype=np.uint8)]).T.copy()  # rows=vars
    # gaussian eliminate on first m columns treating rows as candidate combos
    r = 0
    for c in range(m):
        piv = None
        for i in range(r, n):
            if A[i, c]:
                piv = i
                break
        if piv is None:
            continue
        A[[r, piv]] = A[[piv, r]]
        for i in range(n):
            if i != r and A[i, c]:
                A[i] ^= A[r]
        r += 1
    return A[r:, m:]  # rows with zero image = kernel vectors


def logical_basis(HA, HB):
    """Basis of ker(HA) modulo rowspace(HB)  (B-type logicals if HA=H_opposite)."""
    ker = gf2_kernel(HA)
    rsb = gf2_rowspace_basis(HB)
    out = []
    stack = rsb.copy() if len(rsb) else np.zeros((0, HA.shape[1]), dtype=np.uint8)
    base = rank2_of(stack)
    for v in ker:
        cand = np.vstack([stack, v[None, :]]) if len(stack) else v[None, :]
        r = rank2_of(cand)
        if r > base:
            out.append(v.copy())
            stack = gf2_rowspace_basis(cand)
            base = r
    return np.array(out, dtype=np.uint8)


def rank2_of(M):
    if len(M) == 0:
        return 0
    return len(gf2_rowspace_basis(M))


def min_weight_odd_overlap(HA, ell, tlim=300, ub=None):
    """min{wt v : HA v = 0 mod 2, <ell,v> odd}. Returns (weight, v, exact)."""
    m, n = HA.shape
    # vars: v (n binary), s (m int), t (1 int)
    nv = n + m + 1
    cost = np.concatenate([np.ones(n), np.zeros(m + 1)])
    A1 = np.zeros((m, nv))
    A1[:, :n] = HA
    A1[np.arange(m), n + np.arange(m)] = -2.0
    A2 = np.zeros((1, nv))
    A2[0, :n] = ell
    A2[0, -1] = -2.0
    cons = [LinearConstraint(A1, 0, 0), LinearConstraint(A2, 1, 1)]
    lb = np.zeros(nv)
    ubv = np.concatenate([np.ones(n), np.full(m, 2.0), [n / 2]])
    integrality = np.ones(nv)
    opts = {'time_limit': tlim, 'presolve': True}
    res = milp(c=cost, constraints=cons, bounds=Bounds(lb, ubv),
               integrality=integrality, options=opts)
    if res.x is None:
        return None, None, False
    v = (np.round(res.x[:n]).astype(int) % 2).astype(np.uint8)
    w = int(v.sum())
    exact = (res.status == 0)
    return w, v, exact


def css_distance(HX, HZ, side='both', tlim=300, verbose=False):
    """Exact d_X and/or d_Z. Returns dict side -> (d, witness, exact)."""
    out = {}
    if side in ('X', 'both'):
        KZ = logical_basis(HX, HZ)   # Z-logicals pair with X-candidates
        best = (None, None, True)
        for i, ell in enumerate(KZ):
            w, v, ex = min_weight_odd_overlap(HZ, ell, tlim)
            if verbose:
                print(f'  d_X class {i}: {w} (exact={ex})')
            if w is not None and (best[0] is None or w < best[0]):
                best = (w, v, ex)
            elif w is not None:
                best = (best[0], best[1], best[2] and True)
            if not ex:
                best = (best[0], best[1], False)
        out['X'] = best
    if side in ('Z', 'both'):
        KX = logical_basis(HZ, HX)
        best = (None, None, True)
        for i, ell in enumerate(KX):
            w, v, ex = min_weight_odd_overlap(HX, ell, tlim)
            if verbose:
                print(f'  d_Z class {i}: {w} (exact={ex})')
            if w is not None and (best[0] is None or w < best[0]):
                best = (w, v, ex)
            if not ex:
                best = (best[0], best[1], False)
        out['Z'] = best
    return out
