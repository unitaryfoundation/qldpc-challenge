"""Reed-Solomon Tanner codes over GF(2^m) and binary conversion."""

import numpy as np

_IRRED = {2: 0b111, 3: 0b1011, 4: 0b10011, 5: 0b100101, 6: 0b1000011}


def _poly(m):
    if m not in _IRRED:
        raise ValueError(f"no irreducible polynomial registered for m={m}")
    return _IRRED[m]


def gf_mul(a, b, m):
    poly = _poly(m)
    res = 0
    mask = (1 << m) - 1
    for _ in range(m):
        if b & 1:
            res ^= a
        b >>= 1
        hi = a >> (m - 1)
        a = (a << 1) & mask
        if hi:
            a ^= poly & mask
    return res


def gf_pow(a, e, m):
    res = 1
    base = a
    while e:
        if e & 1:
            res = gf_mul(res, base, m)
        base = gf_mul(base, base, m)
        e >>= 1
    return res


def gf_inv(a, m):
    if a == 0:
        raise ZeroDivisionError
    return gf_pow(a, (1 << m) - 2, m)


def _null_space_gf(M, m):
    M = [list(row) for row in M]
    r = len(M)
    c = len(M[0]) if r else 0
    M2 = [list(M[i]) for i in range(r)]
    pivots = []
    rr = 0
    for col in range(c):
        piv = None
        for i in range(rr, r):
            if M2[i][col] != 0:
                piv = i
                break
        if piv is None:
            continue
        M2[rr], M2[piv] = M2[piv], M2[rr]
        inv = gf_inv(M2[rr][col], m)
        M2[rr] = [gf_mul(x, inv, m) for x in M2[rr]]
        for i in range(r):
            if i != rr and M2[i][col] != 0:
                factor = M2[i][col]
                M2[i] = [M2[i][t] ^ gf_mul(factor, M2[rr][t], m) for t in range(c)]
        pivots.append(col)
        rr += 1
        if rr == r:
            break
    free_cols = [col for col in range(c) if col not in pivots]
    null = []
    for fc in free_cols:
        vec = [0] * c
        vec[fc] = 1
        for idx, pc in enumerate(pivots):
            s = 0
            for fc2 in free_cols:
                s ^= gf_mul(M2[idx][fc2], vec[fc2], m)
            vec[pc] = s
        null.append(vec)
    if not null:
        return np.zeros((0, c), dtype=int)
    return np.array(null, dtype=int)


def _rs_generator_matrix(S, k, m):
    n = len(S)
    G = np.zeros((k, n), dtype=int)
    for i in range(k):
        for j in range(n):
            G[i, j] = gf_pow(int(S[j]), i, m)
    return G


def rs_parity_check(S, k, m):
    G = _rs_generator_matrix(S, k, m)
    H = _null_space_gf(G.tolist(), m)
    return H


def make_tanner_code(edges, left_n, right_n, S, k, m):
    deg = len(S)
    left_inc = [[] for _ in range(left_n)]
    right_inc = [[] for _ in range(right_n)]
    for ei, (u, v) in enumerate(edges):
        left_inc[u].append((v, ei))
        right_inc[v].append((u, ei))
    for u in range(left_n):
        left_inc[u].sort()
        if len(left_inc[u]) != deg:
            raise ValueError(f"left vertex {u} degree {len(left_inc[u])} != {deg}")
    for v in range(right_n):
        right_inc[v].sort()
        if len(right_inc[v]) != deg:
            raise ValueError(f"right vertex {v} degree {len(right_inc[v])} != {deg}")

    Hloc = rs_parity_check(S, k, m)
    nchecks_local = Hloc.shape[0]
    n_edges = len(edges)
    rows = []
    for u in range(left_n):
        idx = [ei for (_, ei) in left_inc[u]]
        for r in range(nchecks_local):
            row = [0] * n_edges
            for c in range(deg):
                row[idx[c]] = int(Hloc[r, c])
            rows.append(row)
    for v in range(right_n):
        idx = [ei for (_, ei) in right_inc[v]]
        for r in range(nchecks_local):
            row = [0] * n_edges
            for c in range(deg):
                row[idx[c]] = int(Hloc[r, c])
            rows.append(row)
    if not rows:
        return np.zeros((0, n_edges), dtype=int)
    return np.array(rows, dtype=int)


def _int_to_bits(x, m):
    bits = []
    for i in range(m):
        bits.append((x >> i) & 1)
    return np.array(bits, dtype=np.int8)


def to_binary(H, m):
    if H.size == 0:
        return np.zeros((0, H.shape[1] * m), dtype=np.int8)
    rows, cols = H.shape
    Hb = np.zeros((m * rows, m * cols), dtype=np.int8)
    basis = [1 << i for i in range(m)]
    for i in range(rows):
        for j in range(cols):
            h = int(H[i, j])
            for t in range(m):
                prod = gf_mul(h, basis[t], m)
                vec = _int_to_bits(prod, m)
                Hb[m * i : m * i + m, m * j + t] = vec
    return Hb


def tanner_css_from_hp(Hbin):
    import os
    import sys

    sys.path.insert(0, os.path.dirname(__file__))
    from products import hypergraph_product

    HX, HZ = hypergraph_product(Hbin, Hbin)
    return HX, HZ


def sample_tanner(num, *, seed=0):
    yielded = 0
    edges_k33 = [(u, v) for u in range(3) for v in range(3)]
    for _ in range(num * 5):
        if yielded >= num:
            return
        Hgf = make_tanner_code(edges_k33, 3, 3, [1, 2, 3], 2, 2)
        Hbin = to_binary(Hgf, 2)
        HX, HZ = tanner_css_from_hp(Hbin)
        if HX.shape[1] > 1000:
            continue
        spec = {"family": "other", "construction": "rs-tanner-hp", "graph": "K3,3", "field": "F4", "local": "RS(3,2)"}
        yield (spec, HX, HZ)
        yielded += 1
