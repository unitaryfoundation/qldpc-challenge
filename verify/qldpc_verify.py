"""
qldpc-challenge submission verifier (Phase 0: structural + cheap semantic +
self-certifying distance upper bounds).

Usage:
    python verify/qldpc_verify.py codes/your-code.json

Exit code 0 if every required check passes, 1 otherwise. Prints a JSON report
to stdout. This covers the *trustless* tier: everything here is either a hard
arithmetic fact (CSS commutation, rank/k, witness validity) or a layout
measurement. It does NOT attempt to prove distance lower bounds / exactness;
that is the server-certification tier (Phase 5, separate solver stack).

What "verified" means per field:
  n           matches the qubit count implied by the checks
  k           = n - rank(H_X) - rank(H_Z), matches the claim exactly
  CSS         H_X H_Z^T = 0 over GF(2)
  distance    each provided side witness is a nontrivial logical operator of
              the claimed Pauli type and weight -> certifies d_side <= value
              as an UPPER BOUND. 'exact' claims are downgraded to upper_bound
              here and flagged for server certification.
  locality    for a 2d-local-* track: a layout (coordinates for all n qubits
              plus the number of physical `layers`) is required; at most
              `layers` qubits per site and distinct sites
              >= 1 apart (no cramming a small radius); measured interaction
              radius (max check diameter) within the track cap. Coordinates
              are planar or 3D (one dimension per layout); a 3D layout gets
              the same honesty checks but no 2D-local class. Reports layout
              diagnostics (dimension, radius, qubits/site, spacing, density,
              bbox) and, for every accepted layout, a heuristic routing cost:
              the nearest-neighbor SWAPs an MST lower bound says each check
              needs to become connected on that layout (total and max over
              checks).
  modules     optional per-qubit module ids in the layout: every qubit must
              carry one; reports the checks spanning more than one module,
              the ports (distinct neighboring modules) per module, and the
              qubits per module, and earns the Layer-3 flag `modular`. No
              track or score reads it.
  diagnostics computed, never ranked (issue #1844): per side, the Tanner-graph
              girth, row and column weight profiles, and bounded trapping-set
              counts, all read off H; for a laid-out code, the Euclidean
              support diameter of each stored distance witness. Reported under
              computed.diagnostics as evidence; no verdict depends on them.
"""

import glob
import json
import re
import math
import os
import secrets
import sys

import numpy as np

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import gf2

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCHEMA_PATH = os.path.join(_HERE, "..", "schema", "code.schema.json")
try:
    import jsonschema
    with open(_SCHEMA_PATH) as _f:
        _SCHEMA = json.load(_f)
except Exception:
    jsonschema = None
    _SCHEMA = None

# minimal required structure, used when jsonschema is unavailable
_REQUIRED = ["schema_version", "name", "code_type", "n", "k", "checks",
             "distance", "provenance"]

# Layer-2 family vocabulary. Self-declared (not recoverable from H), used only as
# a filterable tag. Validated here too, so enforcement holds even when jsonschema
# is unavailable and the minimal structure check runs instead.
_FAMILIES = {"bivariate-bicycle", "generalized-bicycle", "2bga-coset",
             "hypergraph-product", "lifted-product", "balanced-product",
             "quantum-tanner", "tile", "topological", "other"}
_NOVELTY = {"unknown", "known_parameters", "new_parameters"}

# Public CI resource limits. Finite by design so malformed or hostile JSON
# cannot force unbounded work. The blocklength cap is a verification-budget
# rule: above it the distance gate cannot stand behind a claim. It has two
# tiers, see admissible(): any code up to BASE_MAX_N, and up to MAX_N only for
# sparse checks (weight <= EXT_MAX_CHECK_WEIGHT) with a claimed distance the
# gate's search can reach (d <= EXT_MAX_D). Raise-only, as the tooling improves.
MAX_SUBMISSION_BYTES = 5_000_000
BASE_MAX_N = 700
MAX_N = 1000
EXT_MAX_CHECK_WEIGHT = 8
EXT_MAX_D = 40
MAX_CHECKS_PER_SIDE = 10_000
MAX_CHECK_WEIGHT = 32
MAX_TOTAL_SUPPORT = 200_000
MAX_COORDINATES = MAX_N
MAX_DENSE_MATRIX_CELLS = 50_000_000
MAX_COMMUTATION_CELLS = 50_000_000


def admissible(n, max_check_weight, claimed_d):
    """The blocklength contract as one boolean: n <= BASE_MAX_N, or n <= MAX_N
    with max check weight <= EXT_MAX_CHECK_WEIGHT and claimed d <= EXT_MAX_D.
    Call it before searching, with the parameters a candidate would have, to
    know whether the board can accept it at all."""
    if n <= BASE_MAX_N:
        return True
    return (n <= MAX_N and max_check_weight <= EXT_MAX_CHECK_WEIGHT
            and claimed_d <= EXT_MAX_D)


def file_size_error(path):
    """Return a validation error string if a JSON submission file is too large."""
    try:
        size = os.path.getsize(path)
    except OSError as e:
        return f"could not stat file: {e}"
    if size > MAX_SUBMISSION_BYTES:
        return f"file has {size} bytes, limit is {MAX_SUBMISSION_BYTES}"
    return ""


def resource_errors(doc):
    """Resource caps checked before dense matrices are allocated."""
    n = doc["n"]
    X, Z = doc["checks"]["X"], doc["checks"]["Z"]
    supports = X + Z
    errs = []
    max_weight = max((len(s) for s in supports), default=0)
    claimed = (doc.get("distance") or {}).get("d")
    claimed = claimed if isinstance(claimed, int) else 0
    if not admissible(n, max_weight, claimed):
        if n > MAX_N:
            errs.append(f"n={n} exceeds the blocklength cap {MAX_N}")
        else:
            errs.append(f"n={n} is above {BASE_MAX_N}, where the cap admits only "
                        f"max check weight <= {EXT_MAX_CHECK_WEIGHT} and claimed "
                        f"d <= {EXT_MAX_D} (found weight {max_weight}, claimed "
                        f"d {claimed})")
    if len(X) > MAX_CHECKS_PER_SIDE:
        errs.append(f"checks.X has {len(X)} rows, limit is {MAX_CHECKS_PER_SIDE}")
    if len(Z) > MAX_CHECKS_PER_SIDE:
        errs.append(f"checks.Z has {len(Z)} rows, limit is {MAX_CHECKS_PER_SIDE}")
    total_support = sum(len(s) for s in supports)
    if total_support > MAX_TOTAL_SUPPORT:
        errs.append(f"total support entries {total_support} exceeds limit "
                    f"{MAX_TOTAL_SUPPORT}")
    if max_weight > MAX_CHECK_WEIGHT:
        errs.append(f"max check weight {max_weight} exceeds limit {MAX_CHECK_WEIGHT}")
    for label, rows in (("H_X", len(X)), ("H_Z", len(Z))):
        cells = rows * n
        if cells > MAX_DENSE_MATRIX_CELLS:
            errs.append(f"{label} dense allocation would have {cells} cells, "
                        f"limit is {MAX_DENSE_MATRIX_CELLS}")
    comm_cells = len(X) * len(Z)
    if comm_cells > MAX_COMMUTATION_CELLS:
        errs.append(f"H_X H_Z^T commutation check would have {comm_cells} cells, "
                    f"limit is {MAX_COMMUTATION_CELLS}")
    loc = doc.get("locality") or {}
    coords = loc.get("coordinates") or []
    if len(coords) > MAX_COORDINATES:
        errs.append(f"locality.coordinates has {len(coords)} points, limit is "
                    f"{MAX_COORDINATES}")
    modules = loc.get("modules") or []
    if len(modules) > MAX_COORDINATES:
        errs.append(f"locality.modules has {len(modules)} entries, limit is "
                    f"{MAX_COORDINATES}")
    return errs


def structure_errors(doc):
    """Return a list of human-readable structural problems, or [] if the doc
    conforms. Uses jsonschema when installed, else a minimal key/type check."""
    if not isinstance(doc, dict):
        return ["top-level value is not a JSON object"]
    if jsonschema is not None and _SCHEMA is not None:
        v = jsonschema.Draft202012Validator(_SCHEMA)
        errs = [f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
                for e in sorted(v.iter_errors(doc), key=lambda e: list(e.path))]
    else:
        errs = [f"missing field: {k}" for k in _REQUIRED if k not in doc]
        if "checks" in doc and not (isinstance(doc["checks"], dict)
                                    and "X" in doc["checks"] and "Z" in doc["checks"]):
            errs.append("checks must have X and Z support lists")
        if "distance" in doc and not (isinstance(doc["distance"], dict)
                                      and all(k in doc["distance"] for k in ("d", "X", "Z"))):
            errs.append("distance must have d, X, and Z witness blocks")
        if "locality" in doc and not (isinstance(doc["locality"], dict)
                                      and "coordinates" in doc["locality"]
                                      and "layers" in doc["locality"]):
            errs.append("locality must have coordinates and layers")
    if errs:
        return errs
    return resource_errors(doc)


def signature(doc):
    """Permutation-invariant fingerprint via Weisfeiler-Leman color refinement
    on the Tanner graph (qubits + X-checks + Z-checks). Two codes equal up to a
    qubit permutation must share this hash; differing hashes are provably
    inequivalent. A collision only FLAGS a possible duplicate (WL is a strong
    necessary condition, not a complete equivalence test). Much finer than a
    plain degree multiset: it propagates neighborhood structure several hops."""
    import hashlib
    n = doc["n"]
    X, Z = doc["checks"]["X"], doc["checks"]["Z"]
    mx = len(X)
    # node ids: qubit q -> q; X-check i -> n+i; Z-check j -> n+mx+j
    nbr = [[] for _ in range(n + mx + len(Z))]
    for i, s in enumerate(X):
        for q in s:
            nbr[q].append(n + i)
            nbr[n + i].append(q)
    for j, s in enumerate(Z):
        for q in s:
            nbr[q].append(n + mx + j)
            nbr[n + mx + j].append(q)
    # initial colors by node type: qubit=0, X-check=1, Z-check=2
    color = [0] * n + [1] * mx + [2] * len(Z)
    for _ in range(min(6, len(nbr))):
        keyed = [(color[v], tuple(sorted(color[u] for u in nbr[v])))
                 for v in range(len(nbr))]
        order = {k: idx for idx, k in enumerate(sorted(set(keyed)))}
        newc = [order[k] for k in keyed]
        if newc == color:
            break
        color = newc
    cert = sorted(color)  # permutation-invariant multiset of final colors
    payload = json.dumps([n, doc["k"], doc["distance"]["d"], cert])
    return {"hash": hashlib.sha256(payload.encode()).hexdigest()[:16],
            "n": n, "k": doc["k"], "d": doc["distance"]["d"]}


def _matrix(support_list, n):
    H = np.zeros((len(support_list), n), dtype=np.int8)
    for r, sup in enumerate(support_list):
        for q in sup:
            H[r, q] ^= 1
    return H


def _vec(support, n):
    v = np.zeros(n, dtype=np.int8)
    for q in support:
        v[q] ^= 1
    return v


def _tanner_component_count(checks, n):
    """Count connected components of the combined qubit/check Tanner graph."""
    rows = checks["X"] + checks["Z"]
    neighbors = [[] for _ in range(n + len(rows))]
    for i, support in enumerate(rows):
        check_vertex = n + i
        for qubit in support:
            neighbors[qubit].append(check_vertex)
            neighbors[check_vertex].append(qubit)

    seen = bytearray(len(neighbors))
    components = 0
    for start in range(len(neighbors)):
        if seen[start]:
            continue
        components += 1
        seen[start] = 1
        stack = [start]
        while stack:
            vertex = stack.pop()
            for neighbor in neighbors[vertex]:
                if not seen[neighbor]:
                    seen[neighbor] = 1
                    stack.append(neighbor)
    return components


def _stabilizer_block_count(HX, HZ, n):
    """Count the disjoint qubit blocks the stabilizer GROUP splits into.

    ``_tanner_component_count`` looks at the submitted rows, so one linearly
    dependent check spanning two otherwise disjoint blocks (row_A XOR row_B)
    joins the Tanner graph without changing the code. The reduced row echelon
    form is canonical for the row space and block-diagonal whenever the row
    space is a direct sum over disjoint qubit sets, so counting components of
    the Tanner graph built from the RREF rows (both sides combined, isolated
    qubits included) is exact: it equals the number of independent blocks of
    the stabilizer group, whatever redundant rows the submission carries.
    Returns (block_count, sorted block sizes, descending).
    """
    rows = []
    for H in (HX, HZ):
        R, _ = gf2.rref(H)
        rows.extend([int(q) for q in np.nonzero(r)[0]] for r in np.asarray(R))
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for sup in rows:
        for q in sup[1:]:
            parent[find(q)] = find(sup[0])
    sizes = {}
    for q in range(n):
        r = find(q)
        sizes[r] = sizes.get(r, 0) + 1
    return len(sizes), sorted(sizes.values(), reverse=True)


def lattice_steps(a, b, step):
    """Nearest-neighbor hops between two layout points: their Euclidean
    distance in units of ``step`` (the layout's minimum site spacing), rounded
    up. Two qubits stacked on one site (a flip-chip pair) count as adjacent,
    so the result is never below 1."""
    return max(1, math.ceil(math.dist(a, b) / step - 1e-9))


def check_routing_cost(support, coords, step):
    """Heuristic SWAP cost of one check on a layout (issue #1847): the length
    of a minimum spanning tree over the check's support, in lattice steps of
    size ``step``, minus (|support| - 1). Each MST edge of s steps needs at
    least s - 1 nearest-neighbor SWAPs before its two qubits touch, and the
    MST is the cheapest tree to make the support connected, so this is a
    lower bound on any SWAP schedule, not an optimal one. A check whose
    support already forms a connected nearest-neighbor cluster costs 0."""
    m = len(support)
    if m <= 1:
        return 0
    pts = [coords[q] for q in support]
    # Prim's algorithm; supports are bounded-weight, so quadratic is fine.
    in_tree = [False] * m
    best = [lattice_steps(pts[0], p, step) for p in pts]
    in_tree[0] = True
    total = 0
    for _ in range(m - 1):
        j = min((i for i in range(m) if not in_tree[i]), key=lambda i: best[i])
        in_tree[j] = True
        total += best[j]
        for i in range(m):
            if not in_tree[i]:
                best[i] = min(best[i], lattice_steps(pts[j], pts[i], step))
    return total - (m - 1)


def routing_cost(checks, coords, step):
    """Total and max ``check_routing_cost`` over all X and Z checks."""
    costs = [check_routing_cost(sup, coords, step) for sup in checks]
    return sum(costs), max(costs, default=0)


# Diagnostics (issue #1844). Decoder-friendliness is read off each side's
# Tanner graph and logical-operator locality off the layout plus the stored
# witnesses, so every submission already carries the data. Side "X" means the
# Tanner graph of H_X (X-type checks against qubits), the graph a decoder of Z
# errors runs on; "Z" mirrors. Everything here is reported, never ranked, and
# no verdict depends on it. The trapping-set enumeration is bounded twice: by
# set size and by a cap on the candidate sets it may build, so a large or dense
# submission stops early (reported as incomplete) instead of stalling the gate.
TS_MAX_SIZE = 3
TS_MAX_CANDIDATES = 2_000_000


def _side_graph(checks, n):
    """Build the adjacency lists of one side's Tanner graph.

    Qubit q is vertex q, check i is vertex n + i, one edge per support entry.
    """
    nbr = [[] for _ in range(n + len(checks))]
    for i, s in enumerate(checks):
        c = n + i
        for q in s:
            nbr[q].append(c)
            nbr[c].append(q)
    return nbr


def tanner_girth(checks, n):
    """Return the girth of one side's Tanner graph, or None when it is acyclic.

    The girth is the length of the shortest cycle. Exact. A forest is
    recognized first by counting edges against vertices and connected
    components. Otherwise a BFS from every check vertex (every cycle
    passes through one) records the shortest cycle its non-tree edges close,
    and the minimum over start vertices is the girth. Because the graph is
    bipartite a vertex at depth t can only close a cycle of length >= 2t, so
    each BFS stops once 2t reaches the best cycle so far; for the small girths
    typical of LDPC codes (4 to 8) that keeps every BFS to a few dozen
    vertices, and the whole computation to milliseconds.
    """
    from collections import deque
    nbr = _side_graph(checks, n)
    nv = len(nbr)
    nedges = sum(len(s) for s in checks)
    seen = bytearray(nv)
    components = 0
    for start in range(nv):
        if seen[start]:
            continue
        components += 1
        seen[start] = 1
        stack = [start]
        while stack:
            u = stack.pop()
            for v in nbr[u]:
                if not seen[v]:
                    seen[v] = 1
                    stack.append(v)
    if nedges == nv - components:
        return None
    best = nv + 1
    dist = [-1] * nv
    parent = [-1] * nv
    for start in range(n, nv):
        touched = [start]
        dist[start] = 0
        queue = deque([start])
        while queue:
            u = queue.popleft()
            du = dist[u]
            if 2 * du >= best:
                break
            for v in nbr[u]:
                if dist[v] < 0:
                    dist[v] = du + 1
                    parent[v] = u
                    touched.append(v)
                    queue.append(v)
                elif v != parent[u]:
                    best = min(best, du + dist[v] + 1)
        for v in touched:
            dist[v] = -1
            parent[v] = -1
        if best == 4:
            break
    return best


def weight_profile(checks, n):
    """Return the row (check) and column (qubit) weight profiles of one side.

    Each profile is min, max, and mean. A qubit that no check of this side
    touches has column weight 0.
    """
    rows = [len(s) for s in checks]
    cols = [0] * n
    for s in checks:
        for q in s:
            cols[q] += 1

    def prof(ws):
        if not ws:
            return {"min": 0, "max": 0, "mean": 0.0}
        return {"min": min(ws), "max": max(ws),
                "mean": round(sum(ws) / len(ws), 3)}
    return {"row": prof(rows), "column": prof(cols)}


def _in_check_subsets(checks, r):
    """Return every sorted r-subset of qubits lying inside one check.

    One row per (check, subset), as an int64 array of shape (count, r), with
    repeats when several checks contain the same subset. Vectorized per check
    weight so the Python loop runs over distinct weights, not over checks.
    """
    from itertools import combinations
    by_weight = {}
    for s in checks:
        qs = sorted(set(s))
        if len(qs) >= r:
            by_weight.setdefault(len(qs), []).append(qs)
    out = []
    for w, rows in by_weight.items():
        idx = np.asarray(list(combinations(range(w), r)), dtype=np.int64)
        out.append(np.asarray(rows, dtype=np.int64)[:, idx].reshape(-1, r))
    if not out:
        return np.zeros((0, r), dtype=np.int64)
    return np.concatenate(out)


def trapping_sets(checks, n, max_size=TS_MAX_SIZE,
                  max_candidates=TS_MAX_CANDIDATES):
    """Count the small connected (a, b) trapping sets of one side.

    An (a, b) trapping set is a set S of a qubits such that exactly b checks
    meet S an odd number of times, i.e. the error pattern S has syndrome
    weight b. Only connected sets are counted (any two qubits of S joined by a
    path through checks inside S): a disconnected set is a union of smaller
    ones with b adding up, so the connected ones are the primitives. The
    census covers sizes 1..max_size; size 2 is read off the pair-overlap
    counts (two qubits sharing c checks form a (2, deg + deg' - 2c) set) and
    size 3 by generating each connected triple from its center qubit and
    reading the pair and triple overlaps, all vectorized. Before the size-3
    stage the number of candidate triples is estimated, and if it exceeds
    max_candidates the stage is skipped, so the cost is bounded and the report
    says how far it got.

    Returns {"complete_through_size": s, "counts": [[a, b, count], ...]}
    sorted by (a, b); sizes above s were not enumerated. Note that on the
    quantum side a (w, 0) set of this census can be a stabilizer of the
    opposite type (a harmless, degenerate error), so b = 0 is not by itself a
    defect; the census is the classical Tanner-graph notion, reported as such.
    """
    from itertools import combinations
    col = np.zeros(n, dtype=np.int64)
    for s in checks:
        for q in s:
            col[q] += 1
    counts = []
    for b, c in zip(*np.unique(col, return_counts=True)):
        counts.append([1, int(b), int(c)])
    if max_size < 2:
        return {"complete_through_size": 1, "counts": counts}
    pairs = _in_check_subsets(checks, 2)
    if not len(pairs):     # no two qubits share a check: nothing connected above size 1
        return {"complete_through_size": max_size, "counts": counts}
    key = pairs[:, 0] * n + pairs[:, 1]
    ukey, ov = np.unique(key, return_counts=True)   # ov = checks shared by the pair
    u, v = ukey // n, ukey % n
    b2 = col[u] + col[v] - 2 * ov
    for b, c in zip(*np.unique(b2, return_counts=True)):
        counts.append([2, int(b), int(c)])
    if max_size < 3:
        return {"complete_through_size": 2, "counts": counts}
    # connected triples, each generated once from its center: a qubit b and
    # two of its neighbors a < c in the qubit graph (qubits sharing a check).
    # A path a-b-c has one center; a triangle is generated from all three of
    # its vertices and is weighted 1/3, so no deduplication pass is needed.
    deg = np.bincount(np.concatenate([u, v]), minlength=n)
    in_check_triples = sum(len(s) * (len(s) - 1) * (len(s) - 2) // 6
                           for s in checks)
    if int((deg * (deg - 1) // 2).sum()) + in_check_triples > max_candidates:
        return {"complete_through_size": 2, "counts": counts}
    src = np.concatenate([u, v])
    dst = np.concatenate([v, u])
    order = np.argsort(src, kind="stable")
    dst = dst[order]
    first = np.zeros(n + 1, dtype=np.int64)
    np.cumsum(deg, out=first[1:])
    # dense pair-overlap matrix, n * n int32 cells (4 MB at MAX_N = 1000). The
    # blocklength cap is what keeps it small, so refuse anything above it here
    # rather than rely on the caller having enforced the cap.
    if n > MAX_N:
        raise ValueError(f"trapping_sets: n={n} exceeds MAX_N={MAX_N}; the "
                         f"dense pair-overlap matrix is sized for the cap")
    pair_over = np.zeros((n, n), dtype=np.int32)
    pair_over[u, v] = ov
    pair_over[v, u] = ov
    centers, ends_a, ends_c = [], [], []
    for g in np.unique(deg[deg >= 2]):
        bs = np.nonzero(deg == g)[0]
        nb = dst[first[bs][:, None] + np.arange(g)[None, :]]     # (len(bs), g)
        idx = np.asarray(list(combinations(range(int(g)), 2)), dtype=np.int64)
        pairs = np.sort(nb[:, idx], axis=2).reshape(-1, 2)      # a < c
        centers.append(np.repeat(bs, len(idx)))
        ends_a.append(pairs[:, 0])
        ends_c.append(pairs[:, 1])
    if not centers:
        return {"complete_through_size": 3, "counts": counts}
    b = np.concatenate(centers)
    a = np.concatenate(ends_a)
    c = np.concatenate(ends_c)
    o_ac = pair_over[a, c]
    tri = o_ac > 0
    # checks containing all three qubits: only possible for a triangle
    triple_over = np.zeros(len(b), dtype=np.int64)
    if tri.any():
        in3 = _in_check_subsets(checks, 3)
        if len(in3):
            tk, tc = np.unique((in3[:, 0] * n + in3[:, 1]) * n + in3[:, 2],
                               return_counts=True)
            t = np.sort(np.stack([a[tri], b[tri], c[tri]], axis=1), axis=1)
            key = (t[:, 0] * n + t[:, 1]) * n + t[:, 2]
            pos = np.minimum(np.searchsorted(tk, key), len(tk) - 1)
            triple_over[tri] = np.where(tk[pos] == key, tc[pos], 0)
    # a check meeting the triple once or three times is odd: by inclusion and
    # exclusion the count of such checks is sum(col) - 2 sum(pair) + 4 triple.
    b3 = (col[a] + col[b] + col[c]
          - 2 * (pair_over[a, b] + pair_over[b, c] + o_ac) + 4 * triple_over)
    weight = np.where(tri, 1.0 / 3.0, 1.0)
    for bb, cnt in enumerate(np.bincount(b3, weights=weight)):
        if cnt > 0.5:
            counts.append([3, int(bb), int(round(cnt))])
    return {"complete_through_size": 3, "counts": counts}


def support_diameter(coords, support):
    """Return the largest Euclidean distance between two qubits of `support`.

    `coords` is the layout, one [x, y] per qubit; a single qubit has
    diameter 0.0.
    """
    ps = [coords[q] for q in support]
    return max((math.dist(a, b) for i, a in enumerate(ps) for b in ps[i + 1:]),
               default=0.0)


def verify(doc, refute=False, seed=None):
    """Verify a submission. If ``refute`` is set, run the distance refutation with
    ``seed`` -- when ``seed is None`` a fresh RANDOM seed is drawn, so the gate is
    non-deterministic by design (an over-claim cannot reliably evade one fixed
    search). The seed used is reported in the ``distance_not_refuted`` detail, so a
    failing run is reproducible (re-run with that seed). Pass an explicit ``seed``
    to reproduce a run or for a deterministic test."""
    report = {"name": doc.get("name") if isinstance(doc, dict) else None,
              "checks": [], "ok": True, "computed": {}, "earned_distance": {}}

    def record(label, ok, detail=""):
        report["checks"].append({"check": label, "ok": bool(ok),
                                  "detail": detail})
        if not ok:
            report["ok"] = False

    # structural validation first: a malformed doc fails cleanly here rather
    # than crashing the arithmetic below.
    serr = structure_errors(doc)
    record("schema_valid", not serr, "; ".join(serr[:4]))
    if serr:
        return report
    # index bounds, gated before anything that indexes by qubit (signature,
    # matrix building) so an out-of-range index is reported here, cleanly,
    # rather than crashing into the generic guard below.
    n = doc["n"]
    sup = doc["checks"]["X"] + doc["checks"]["Z"]
    max_idx = max((max(s) for s in sup if s), default=-1)
    in_range = 0 <= max_idx < n
    record("qubit_indices_in_range", in_range, f"max index {max_idx}, n={n}")
    if not in_range:
        return report
    try:
        report["signature"] = signature(doc)
        return _verify_semantic(doc, report, record, refute, seed)
    except Exception as e:  # never crash on a hostile submission
        record("verifier_ran", False, f"{type(e).__name__}: {e}")
        return report


def _verify_semantic(doc, report, record, refute=False, seed=None):

    n = doc["n"]
    # index bounds already gated in verify(); safe to build matrices.
    HX = _matrix(doc["checks"]["X"], n)
    HZ = _matrix(doc["checks"]["Z"], n)

    # exact-duplicate fingerprint: the reduced row echelon forms pin the
    # stabilizer GROUP (invariant to row recombination/reordering, sensitive
    # to qubit relabeling). Equal fingerprint => identical code, not just
    # equivalent. Permuted copies are caught by the WL signature instead.
    import hashlib
    fp = (gf2.rref(HX)[0].tobytes() + b"|" + gf2.rref(HZ)[0].tobytes())
    report["fingerprint"] = hashlib.sha256(fp).hexdigest()[:16]

    # checks have distinct supports per row (no repeated qubit within a row
    #    would have been XORed away; flag any that collapsed)
    empty_rows = [i for i, s in enumerate(doc["checks"]["X"] + doc["checks"]["Z"])
                  if len(set(s)) != len(s)]
    record("no_repeated_qubits_in_a_check", not empty_rows,
           f"rows with repeats: {empty_rows[:5]}")

    # The challenge rule applies to the combined X/Z Tanner graph. Count all
    # qubit and check vertices, including isolated vertices, so a disconnected
    # direct sum or an unused qubit cannot pass by construction.
    ncomponents = _tanner_component_count(doc["checks"], n)
    record("tanner_connected", ncomponents == 1,
           f"Tanner graph has {ncomponents} connected component(s)")
    # The same rule applied to the stabilizer group rather than the submitted
    # rows: a direct sum padded with a redundant cross-block check, or a qubit
    # frozen by a weight-1 stabilizer hiding in the row space, has a connected
    # Tanner graph but is still not one code.
    nblocks, block_sizes = _stabilizer_block_count(HX, HZ, n)
    shown = ", ".join(map(str, block_sizes[:6])) + (", ..." if nblocks > 6 else "")
    record("stabilizer_group_connected", nblocks == 1,
           f"stabilizer group splits into {nblocks} independent block(s) on "
           f"disjoint qubit sets (sizes {shown})")

    # 3. CSS commutation
    css = not bool(((HX @ HZ.T) % 2).any())
    record("css_commutation", css, "H_X H_Z^T = 0 over GF(2)")

    # 4. logical dimension k
    rx, rz = gf2.rank(HX), gf2.rank(HZ)
    k_computed = n - rx - rz
    report["computed"].update(n=n, rank_HX=rx, rank_HZ=rz, k=k_computed)
    record("k_matches_claim", k_computed == doc["k"],
           f"computed k={k_computed}, claimed {doc['k']}")
    # A code must encode at least one logical qubit; k<=0 is degenerate (nothing
    # to protect) and has no distance, so reject it outright.
    record("k_at_least_1", k_computed >= 1,
           f"computed k={k_computed}; a submission must encode >= 1 logical qubit")

    # 5. check weights (for the weight-bounded tracks)
    wmax = max((len(s) for s in doc["checks"]["X"] + doc["checks"]["Z"]),
               default=0)
    report["computed"]["max_check_weight"] = wmax
    # Layer-1 weight class (computed, nested: weight-4 < weight-6 < weight-8).
    # The tightest cap the max check weight fits under; ">8" for anything heavier
    # so every code still has a home on the weight axis.
    report["computed"]["weight_class"] = (
        "weight-4" if wmax <= 4 else "weight-6" if wmax <= 6
        else "weight-8" if wmax <= 8 else "weight-9plus")
    # Sparsity backstop: LDPC means a bounded, small check weight. The cap is far
    # above any plausible qLDPC code on this board (weights run to ~10), so it
    # only rejects a dense matrix submitted as a "code", not a real entry.
    record("check_weight_is_ldpc", wmax <= MAX_CHECK_WEIGHT,
           f"max check weight {wmax} far exceeds LDPC sparsity "
           f"(cap {MAX_CHECK_WEIGHT})"
           if wmax > MAX_CHECK_WEIGHT else f"max check weight {wmax}")

    # 5a. decoder-friendliness diagnostics (issue #1844), read off each side's
    #     Tanner graph: girth, weight profiles, and a bounded trapping-set
    #     census. Reported under computed.diagnostics; nothing here is ranked
    #     and no verdict depends on it. See tanner_girth and trapping_sets.
    diag = {"tanner_girth": {}, "weight_profile": {},
            "trapping_sets": {"max_size": TS_MAX_SIZE,
                              "candidate_cap": TS_MAX_CANDIDATES}}
    for side in ("X", "Z"):
        rows = doc["checks"][side]
        g = tanner_girth(rows, n)
        diag["tanner_girth"][side] = "acyclic" if g is None else g
        diag["weight_profile"][side] = weight_profile(rows, n)
        diag["trapping_sets"][side] = trapping_sets(rows, n)
    report["computed"]["diagnostics"] = diag

    # The model field is self-reported and unverifiable, but if one is claimed it
    # must name a specific version, not a bare vendor name: "Claude" tells a reader
    # nothing reproducible, "Claude Opus 4.8" does. Omitting it (a human or unknown
    # author) is fine; "human" is the explicit non-model sentinel.
    model = (doc.get("provenance") or {}).get("model")
    if isinstance(model, (list, tuple)):
        # an ensemble of models: every named member must carry a version
        model = ", ".join(str(x) for x in model)
    if model and model.strip() and model.strip().lower() != "human":
        specific = all(any(ch.isdigit() for ch in part)
                       for part in model.split(",") if part.strip())
        record("model_version_specified", specific,
               model if specific else
               f"'{model}' names no version; give the exact model, e.g. "
               "'Claude Opus 4.8', or omit the field")

    # Layer-2 family tag: optional, but if present must be from the vocabulary.
    family = doc.get("family")
    if family is not None:
        known = family in _FAMILIES
        # A genuinely new construction should not be forced into "other" just
        # because the vocabulary has not caught up. Accept a well-formed new tag
        # and flag it for review; the family is a filter, never a ranking input.
        wellformed = bool(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", str(family)))
        record("family_in_vocabulary", known or wellformed,
               family if known
               else f"'{family}' is a new family tag, accepted but not yet in "
                    "the vocabulary; please open an issue so the tracks and the "
                    "site labels can follow"
               if wellformed
               else f"'{family}' is malformed; use a lowercase-hyphenated tag, "
                    f"e.g. one of {sorted(_FAMILIES)}")

    novelty = (doc.get("provenance") or {}).get("novelty")
    if novelty is not None:
        record("novelty_in_vocabulary", novelty in _NOVELTY,
               novelty if novelty in _NOVELTY
               else f"'{novelty}' is not a known novelty status; use one of "
               f"{sorted(_NOVELTY)}")

    # 6. distance witnesses (self-certifying upper bounds)
    dist = doc["distance"]
    earned_d = []
    earned_sides = set()
    for side, opp_H, own_H in (("X", HZ, HX), ("Z", HX, HZ)):
        if side not in dist:
            record(f"distance_{side}_present", False,
                   "both X and Z distance witnesses are required")
            continue
        sd = dist[side]
        v = _vec(sd["witness"], n)
        wt = int(v.sum())
        in_ker = gf2.commutes(v, opp_H)          # commutes with opposite checks
        nontrivial = not gf2.in_rowspace(v, own_H)  # not a stabilizer product
        good = (wt == sd["value"]) and in_ker and nontrivial
        record(f"distance_{side}_witness", good,
               f"weight={wt} (claim {sd['value']}), in_ker={in_ker}, "
               f"nontrivial={nontrivial}")
        if good:
            tier = "upper_bound"  # 'exact' must be earned by server cert
            report["earned_distance"][side] = {"value": sd["value"],
                                               "tier": tier}
            earned_d.append(sd["value"])
            earned_sides.add(side)
            if sd["confidence"] == "exact":
                record(f"distance_{side}_exact_flagged", True,
                       "exact claim accepted as upper_bound pending server "
                       "certification")

    # 7. code distance consistency
    if earned_sides == {"X", "Z"}:
        d_earned = min(earned_d)
        matches = d_earned == dist["d"]
        record("d_matches_min_side", matches,
               f"min earned side = {d_earned}, claimed d = {dist['d']}")
        if matches:
            report["earned_distance"]["d"] = {"value": dist["d"],
                                              "tier": "upper_bound"}
    else:
        record("distance_global_earned", False,
               "valid X and Z witnesses are required to earn a global distance")

    # 8. independent distance refutation. A bounded RIS search must not find a
    #    logical lighter than the claimed distance. This is SOUND -- any hit is a
    #    checkable lighter logical, so a real over-claim -- but not complete (a
    #    clean pass is "no over-claim found at this budget", not a proof). Opt-in
    #    (`refute=True`): the per-submission gate runs it; fast/non-gate callers
    #    (site build, verify_all, research recipes) pass refute=False.
    #
    #    NON-DETERMINISTIC BY DESIGN: the seed is random unless one is passed, so an
    #    over-claim cannot reliably evade a single fixed search -- a re-run draws a
    #    new seed and gets another chance to catch it. The trade-off is that a
    #    re-run can change the verdict; the seed is always reported so a failing run
    #    is reproducible (verify(doc, refute=True, seed=<that seed>)).
    #
    #    FAILS CLOSED: if the refuter cannot run, that is recorded as a FAILURE, not
    #    a silent pass -- a gate that fails open is no gate.
    if refute and "d" in report["earned_distance"]:
        run_seed = seed if seed is not None else secrets.randbelow(2**31)
        try:
            import heuristic_distance
            refuted, d_found, wit, ntr = heuristic_distance.refute_check(doc, seed=run_seed)
            record("distance_not_refuted", not refuted,
                   (f"found weight-{d_found} logical < claimed {dist['d']} "
                    f"(seed {run_seed}); witness={wit}" if refuted
                    else f"no lighter logical in {ntr} RIS trials (seed {run_seed})"))
        except Exception as e:
            record("distance_not_refuted", False,
                   f"refutation could not run ({type(e).__name__}: {e}; seed "
                   f"{run_seed}); failing closed -- manual review required")

    # 9. locality / geometric 2D embedding. The locality CLASS is computed from
    #    the layout, never trusted from a self-declared track. A class is earned
    #    only by an honest layout:
    #      (a) a coordinate for every qubit;
    #      (b) no cramming: at most `layers` qubits may share a site (the
    #          flip-chip stack) and any two distinct sites are >= 1 apart, so a
    #          check of diameter r genuinely spans r grid units and a small
    #          radius cannot be faked by collapsing qubits onto a point;
    #      (c) short range: the measured interaction radius (largest check
    #          diameter) is within the class cap.
    #    A layout that fails (b) FAILS VERIFICATION: attaching coordinates is a
    #    locality claim, and a dishonest layout that merges green while earning
    #    nothing is a silent footgun for batch layout submissions. Codes that
    #    pass (b) but miss every cap in (c), or carry no layout at all, are
    #    simply `unrestricted` (an honest long-range layout is legitimate --
    #    unrestricted g is well defined); the computed class is surfaced as a
    #    named check either way, so demotion is never silent.
    #    "Short range" means a bounded,
    #    n-independent check diameter. The bilayer cap admits the weight-8 planar
    #    (tile-code) family: bulk checks span ~5.83, open-boundary corners ~6.71,
    #    both constant in n; 7.0 covers the family while rejecting layouts whose
    #    range grows with the code. Nesting: local-2d-single < local-2d-bilayer <
    #    unrestricted (the tighter class also qualifies for the looser ones; the
    #    site derives that). See TRACKS.md.
    #    Coordinates are planar or 3D (issue #1849), one dimension per layout;
    #    a mixed layout is rejected. The honesty checks (a) and (b) and the
    #    radius are dimension-free. The class caps are planar: a 3D layout is
    #    checked the same way, reported with dimension 3, and lands in
    #    `unrestricted`, where the site prices it by the D = 3 geometric
    #    efficiency (TRACKS.md).
    LOCALITY_CLASSES = [   # tightest first
        ("local-2d-single",  1, 4.0),
        ("local-2d-bilayer", 2, 7.0),
    ]
    locality_class = "unrestricted"
    loc = doc.get("locality")
    if loc is not None:
        coords = loc["coordinates"]
        layers = loc.get("layers", 1)
        cover = len(coords) == n
        record("coordinates_cover_all_qubits", cover,
               f"{len(coords)} coords, n={n}")
        dims = {len(c) for c in coords}
        dim = next(iter(dims)) if len(dims) == 1 else None
        if cover:
            record("coordinates_uniform_dimension", dim in (2, 3),
                   f"D = {dim}" if dim in (2, 3)
                   else f"points of dimension {sorted(dims)}; every point in "
                        "a layout must be [x, y] or [x, y, z]")
        if cover and dim in (2, 3):
            pts = [tuple(c) for c in coords]

            def diam(sup):
                ps = [coords[q] for q in sup]
                return max((math.dist(a, b) for a in ps for b in ps),
                           default=0.0)
            radius = max((diam(s) for s in doc["checks"]["X"]
                          + doc["checks"]["Z"]), default=0.0)

            from collections import Counter
            mult = Counter(pts)
            max_mult = max(mult.values())
            sites = sorted(mult)
            min_spacing = min((math.dist(a, b)
                               for i, a in enumerate(sites)
                               for b in sites[i + 1:]), default=float("inf"))
            bbox = [round(max(axis) - min(axis), 4) for axis in zip(*pts)]
            extent = math.prod(bbox)
            density_key = ("qubits_per_unit_area" if dim == 2
                           else "qubits_per_unit_volume")
            report["computed"]["locality"] = {
                "dimension": dim,
                "interaction_radius": round(radius, 4),
                "layers": layers,
                "max_qubits_per_site": max_mult,
                "min_site_spacing": (round(min_spacing, 4)
                                     if min_spacing != float("inf") else None),
                density_key: round(len(pts) / extent, 4) if extent else None,
                "bbox": bbox,
            }
            # logical-operator locality (issue #1844): the Euclidean support
            # diameter of each stored distance witness in this layout. The
            # witnesses are upper bounds on the logical weight, so this is an
            # upper bound on how far the exhibited logicals spread, not a
            # minimum over all logicals (that would be a co-design search).
            ldiam = {}
            for side in ("X", "Z"):
                wit = (doc["distance"].get(side) or {}).get("witness") or []
                if wit and all(0 <= q < n for q in wit):
                    ldiam[side] = round(support_diameter(coords, wit), 4)
            report["computed"]["diagnostics"]["logical_diameter"] = ldiam
            if "interaction_radius" in loc:
                record("interaction_radius_within_claim",
                       radius <= loc["interaction_radius"] + 1e-9,
                       f"measured {radius:.4f} <= claim "
                       f"{loc['interaction_radius']}")
            record("site_occupancy_within_layers", max_mult <= layers,
                   f"max {max_mult} qubit(s) per site, layers={layers}")
            record("site_spacing_at_least_one",
                   min_spacing >= 1.0 - 1e-9,
                   "single occupied site" if min_spacing == float("inf")
                   else f"min spacing between distinct sites "
                        f"{min_spacing:.4f} (>= 1.0 required)")
            honest = max_mult <= layers and min_spacing >= 1.0 - 1e-9
            if honest:
                # Heuristic routing cost (issue #1847), computed from every
                # accepted layout, cap-exceeding ones included: how many
                # nearest-neighbor SWAPs an MST lower bound says each check
                # needs before its support is connected on this layout.
                # "Nearest neighbor" is one lattice step, the layout's minimum
                # site spacing (1.0 when only one site is occupied). A
                # diagnostic, never a rank; a code without a layout gets none.
                step = min_spacing if min_spacing != float("inf") else 1.0
                total, worst = routing_cost(
                    doc["checks"]["X"] + doc["checks"]["Z"], coords, step)
                report["computed"]["routing_cost"] = {
                    "heuristic": "mst-lower-bound",
                    "total_swaps": total,
                    "max_swaps_per_check": worst,
                    "lattice_step": round(step, 4),
                }
            if honest and dim == 2:
                for cls, max_layers, cap in LOCALITY_CLASSES:
                    if layers <= max_layers and radius <= cap + 1e-9:
                        locality_class = cls
                        break
                caps = ", ".join(f"{c} <= {cap} at <= {ml} layer(s)"
                                 for c, ml, cap in LOCALITY_CLASSES)
                record("locality_class_computed", True,
                       locality_class if locality_class != "unrestricted"
                       else f"unrestricted: radius {radius:.4f} at {layers} "
                            f"layer(s) meets no class cap ({caps})")
            elif honest:
                record("locality_class_computed", True,
                       f"unrestricted: 3D layout (radius {radius:.4f} at "
                       f"{layers} layer(s)); the 2D-local classes need planar "
                       "coordinates, and the layout is priced by the D = 3 "
                       "geometric efficiency")

    # 10. module structure (issue #1846). `locality.modules` assigns every
    #     qubit to a hardware module (one integer per qubit). It is the same
    #     kind of cheap, checkable layout evidence as the coordinates and is
    #     read independently of them: module membership says nothing about
    #     distance, and coordinates say nothing about which chip a qubit sits
    #     on. A partial assignment is rejected (a layout claim covers every
    #     qubit or it is not a layout claim). From a full assignment the
    #     verifier reports what a modular machine pays for: the checks whose
    #     support crosses a module boundary, the ports each module needs (the
    #     number of distinct modules it shares a check with), and the qubits
    #     per module. Earns the Layer-3 flag `modular`; the locality class and
    #     the efficiency scores never read it.
    modular = False
    modules = loc.get("modules") if loc is not None else None
    if modules is not None:
        cover_m = len(modules) == n
        record("modules_cover_all_qubits", cover_m,
               f"{len(modules)} module ids, n={n}")
        if cover_m:
            from collections import Counter
            ids = sorted(set(modules))
            per_module = Counter(modules)
            crossing = {"X": [], "Z": []}
            neighbors = {m: set() for m in ids}
            for side in ("X", "Z"):
                for i, sup in enumerate(doc["checks"][side]):
                    touched = {modules[q] for q in sup}
                    if len(touched) > 1:
                        crossing[side].append(i)
                        for m in touched:
                            neighbors[m] |= touched - {m}
            ports = {m: len(neighbors[m]) for m in ids}
            n_cross = len(crossing["X"]) + len(crossing["Z"])
            report["computed"]["modules"] = {
                "count": len(ids),
                "qubits_per_module": {str(m): per_module[m] for m in ids},
                "cross_module_checks": n_cross,
                "cross_module_check_indices": crossing,
                "ports_per_module": {str(m): ports[m] for m in ids},
                "max_ports": max(ports.values()),
            }
            modular = True
            record("modules_computed", True,
                   f"{len(ids)} module(s), {n_cross} cross-module check(s), "
                   f"max {max(ports.values())} port(s) per module")

    # 11. transversal logical gates (issue #1850, stage 1). Optional claims in
    #     circuit.gates: a qubit permutation, possibly with H or S on every
    #     qubit, or a block-to-block CX, each with its claimed action on the
    #     logical operators of circuit.logicals. Pure GF(2): the gate must map
    #     every stabilizer generator into the stabilizer group and induce
    #     exactly the claimed action modulo stabilizers (transversal_gates.py
    #     documents the phase condition S additionally needs). Witness-backed
    #     and penalty-only: a verified gate is recorded in the computed block
    #     and listed on the code page, never ranked; a wrong claim fails the
    #     entry. Entries without the field are untouched.
    import transversal_gates
    gchecks, gcomputed = transversal_gates.verify_gates(doc, HX, HZ)
    for label, ok, detail in gchecks:
        record(label, ok, detail)
    if gcomputed is not None:
        report["computed"]["transversal_gates"] = gcomputed
    # Layer-1 locality class (computed) + Layer-3 flags (verifier-proven only;
    # the exact-d flag is added at site-build time from certs/, since exactness
    # is certified separately, not by this trustless check).
    report["computed"]["locality_class"] = locality_class
    report["computed"]["flags"] = {
        "css": bool(report["checks"] and
                    all(c["ok"] for c in report["checks"]
                        if c["check"] == "css_commutation")),
        "locality_class": locality_class,
        "modular": modular,
    }

    return report



def _board_entry(path, data):
    """Verify one board file from the bytes already read (None = oversize)."""
    entry = {"path": path, "slug": os.path.splitext(os.path.basename(path))[0],
             "doc": None, "report": None,
             "size_error": file_size_error(path) or None, "load_error": None}
    if entry["size_error"] is None and data is not None:
        try:
            entry["doc"] = json.loads(data)
            entry["report"] = verify(entry["doc"])
        except Exception as e:                  # noqa: BLE001 -- recorded, caller decides
            entry["load_error"] = f"{type(e).__name__}: {e}"
    return entry


# One snapshot per process: {"dir", "key", "reports"}. The board only moves
# forward within a process, so more slots would only retain memory (a
# 619-entry snapshot measured ~62 MB; see issue #966).
_BOARD_CACHE = {}


def board_reports(code_dir):
    """Verify every <code_dir>/*.json structurally, memoized on the bytes read.

    One process pays for the pass once, whoever asks: the site builder, the
    candidate validator and several tests each used to rescan and re-verify
    the whole board (~15-20 s per pass locally, two to three passes per pytest
    session, all producing identical reports).

    The memo key is a digest of the file names and the exact bytes the pass
    verifies, so a changed file re-verifies the board however it was written
    -- an edit that preserves size and mtime (cp -p, rsync -t, touch -r)
    cannot serve a stale report, and the key describes the content that was
    read rather than metadata sampled beside it. Hashing the board costs
    milliseconds against the tens of seconds the pass takes. Structural
    verification (refute=False) is deterministic, so the cached report is
    exactly what a fresh call would compute.

    Returns a tuple of dicts {path, slug, doc, report, size_error,
    load_error}: doc/report are None when size_error (file_size_error) or
    load_error (a parse or verify exception, recorded as text) is set. The
    entries are SHARED between callers: treat doc and report as read-only.
    """
    import hashlib
    code_dir = os.path.abspath(code_dir)
    raw, h = [], hashlib.sha256()
    for p in sorted(glob.glob(os.path.join(code_dir, "*.json"))):
        data = None
        if not file_size_error(p):              # never read an oversize file
            with open(p, "rb") as f:
                data = f.read()
        h.update(os.path.basename(p).encode())
        h.update(b"\0" + (data if data is not None else b"<oversize>") + b"\0")
        raw.append((p, data))
    key = h.hexdigest()
    if _BOARD_CACHE.get("dir") == code_dir and _BOARD_CACHE.get("key") == key:
        return _BOARD_CACHE["reports"]
    reports = tuple(_board_entry(p, data) for p, data in raw)
    _BOARD_CACHE.clear()
    _BOARD_CACHE.update(dir=code_dir, key=key, reports=reports)
    return reports


def main(path):
    ferr = file_size_error(path)
    if ferr:
        print(json.dumps({"name": None,
                          "checks": [{"check": "file_size_within_limit",
                                      "ok": False, "detail": ferr}],
                          "ok": False, "computed": {}, "earned_distance": {}},
                         indent=2))
        return 1
    try:
        with open(path) as f:
            doc = json.load(f)
    except FileNotFoundError:
        print(f"could not open {path}: file not found", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"could not parse {path}: not valid JSON ({e})", file=sys.stderr)
        return 2
    report = verify(doc, refute=True)   # the per-submission CLI runs the gate
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python qldpc_verify.py <submission.json>",
              file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
