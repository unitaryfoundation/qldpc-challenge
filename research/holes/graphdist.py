"""Exact distances for boundary-edge holey codes via connectivity graphs.

For side X: dual basis = Z-logicals l_1..l_b. Any nontrivial X-logical pairs
oddly with some l_i (nondegeneracy of the quotient form). For each l:
treat supp(l) as a cut; BFS the parity-doubled Z-connectivity graph from
each seed s (the single merged virtual node V, plus endpoints of cut edges)
for the shortest (s,0)->(s,1) walk. XOR-reduce the walk to an F2 vector,
verify it is syndrome-free with odd pairing: it is then a genuine logical.

Soundness: reduced candidates are verified. Completeness: the min-weight
logical has a single path/cycle component with odd l-pairing; it uses a cut
edge (odd crossing), so its endpoint (or V, if boundary-anchored) is a seed,
and the BFS walk it induces is no longer than it. A walk with odd parity
XOR-reduces to a nonzero syndrome-free vector of no greater weight with the
same parity. Hence min over verified candidates = exact distance.
"""
import numpy as np
from collections import deque
from distance import gf2_rowspace_basis, rank2_of, logical_basis


def _graph(code, opp):
    """Connectivity graph of `opp`-type checks; ONE merged virtual node V.
    Returns (adj, V, nodes, edges) with adj[u] = [(v, qubit)]."""
    H = code['HZ'] if opp == 'Z' else code['HX']
    n = H.shape[1]
    m = H.shape[0]
    V = m
    edges = []
    for q in range(n):
        cs = np.nonzero(H[:, q])[0]
        if len(cs) == 2:
            edges.append((int(cs[0]), int(cs[1]), q))
        elif len(cs) == 1:
            edges.append((int(cs[0]), V, q))
        # degree-0 qubits handled separately by caller
    nodes = m + 1
    adj = [[] for _ in range(nodes)]
    for u, v, q in edges:
        adj[u].append((v, q))
        adj[v].append((u, q))
    return adj, V, nodes, edges


def _bfs_parity(adj, nodes, cut, s):
    """Shortest (s,0)->(s,1) walk in the parity-doubled graph. Edge list."""
    dist = {}
    prev = {}
    start = (s, 0)
    dist[start] = 0
    dq = deque([start])
    tgt = (s, 1)
    while dq:
        st = dq.popleft()
        if st == tgt:
            break
        u, par = st
        for v, q in adj[u]:
            st2 = (v, par ^ (1 if q in cut else 0))
            if st2 not in dist:
                dist[st2] = dist[st] + 1
                prev[st2] = (st, q)
                dq.append(st2)
    if tgt not in dist:
        return None
    path = []
    st = tgt
    while st != start:
        pst, q = prev[st]
        path.append(q)
        st = pst
    return path


def graph_distance(code, side='X', return_support=True):
    """Exact min-weight nontrivial `side`-type logical: (d, support)."""
    opp = 'Z' if side == 'X' else 'X'
    Hopp = code['HZ'] if side == 'X' else code['HX']   # syndrome matrix
    Hown = code['HX'] if side == 'X' else code['HZ']   # triviality matrix
    n = Hopp.shape[1]
    # dual-basis logicals (opposite type): for side X these are Z-logicals
    duals = logical_basis(Hown, Hopp)
    if len(duals) == 0:
        return None, None
    adj, V, nodes, edges = _graph(code, opp)
    best, bestsup = None, None

    def consider(vec):
        nonlocal best, bestsup
        w = int(vec.sum())
        if w == 0 or (best is not None and w >= best):
            return
        if (Hopp @ vec % 2).any():
            return
        if not any(int(vec @ l) % 2 for l in duals):
            return
        best, bestsup = w, np.nonzero(vec)[0].tolist()

    # weight-1 candidates: qubits unconstrained by the opposite side
    for q in range(n):
        if not Hopp[:, q].any():
            vec = np.zeros(n, dtype=np.uint8)
            vec[q] = 1
            consider(vec)

    for l in duals:
        cut = set(np.nonzero(l)[0].tolist())
        seeds = {V}
        for u, v, q in edges:
            if q in cut:
                seeds.add(u)
                seeds.add(v)
        for s in seeds:
            walk = _bfs_parity(adj, nodes, cut, s)
            if walk is None:
                continue
            if best is not None and len(walk) >= best + 2:
                continue
            vec = np.zeros(n, dtype=np.uint8)
            for q in walk:
                vec[q] ^= 1
            consider(vec)
    return best, bestsup
