"""Shared utilities for the literature-novelty checker.

Vendored from this project's `novelty` working repository so the method behind
research/provenance/derived.json is reviewable here rather than on trust. Only
the algorithm is committed; the literature index it reads is ~1.3 GB of
matrices and stays out of the repository.

Equivalence tested throughout this package (see REPORT.md for the discussion):

  Two CSS codes C = (H_X, H_Z) and C' = (H_X', H_Z') on n qubits are
  *permutation-equivalent* if there is a permutation pi of the n qubits with
      rowspace(H_X pi) = rowspace(H_X')  and  rowspace(H_Z pi) = rowspace(H_Z').
  They are *permutation-equivalent up to X/Z swap* if that holds after
  exchanging the roles of H_X' and H_Z' (a transversal Hadamard).

The test implemented here (`tanner_isomorphic`) is a *sufficient* condition:
it decides whether the typed Tanner graphs of the two generating sets (after
dropping zero and duplicate rows) are isomorphic. An isomorphism of typed
Tanner graphs is exactly a qubit permutation that maps the set of X-rows to
the set of X-rows and Z-rows to Z-rows, so it certifies permutation
equivalence of the codes. The converse fails in general: two different sparse
generating sets of the same stabilizer group need not have isomorphic Tanner
graphs. `rowspace_invariants` gives cheap basis-independent invariants
(ranks, and for small codes the exact low-weight enumerator of the row spaces)
that can *refute* equivalence independently of the generating set.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import networkx as nx
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
# The literature index is ~1.3 GB of matrices and is not committed here. Point
# LITERATURE_INDEX at it, or pass --index, to regenerate the derived table; the
# committed table and its --check path need neither the index nor this module.
DATA = os.environ.get("LITERATURE_INDEX") or os.path.join(HERE, "index")

sys.path.insert(0, os.path.join(REPO, "verify"))
import gf2  # noqa: E402  (repo GF(2) utilities, read-only)


# --------------------------------------------------------------------------
# GF(2) helpers
# --------------------------------------------------------------------------

def rows_to_ints(rows: Iterable[Iterable[int]]) -> list[int]:
    """Sparse supports -> Python ints (bit i set <=> qubit i in support)."""
    out = []
    for r in rows:
        v = 0
        for i in r:
            v |= 1 << int(i)
        out.append(v)
    return out


def ints_to_rows(ints: Iterable[int]) -> list[list[int]]:
    out = []
    for v in ints:
        r = []
        i = 0
        while v:
            if v & 1:
                r.append(i)
            v >>= 1
            i += 1
        out.append(r)
    return out


def rank_ints(vecs: Sequence[int]) -> int:
    """GF(2) rank of a list of bit-packed vectors (Gaussian elimination on
    Python ints; much faster than the int8 schoolbook for n <= 1000)."""
    basis: dict[int, int] = {}  # leading bit -> vector
    r = 0
    for v in vecs:
        while v:
            h = v.bit_length() - 1
            b = basis.get(h)
            if b is None:
                basis[h] = v
                r += 1
                break
            v ^= b
    return r


def dense(rows: Sequence[Sequence[int]], n: int) -> np.ndarray:
    M = np.zeros((len(rows), n), dtype=np.int8)
    for i, r in enumerate(rows):
        M[i, list(r)] = 1
    return M


def rank_rows(rows: Sequence[Sequence[int]], n: int) -> int:
    return rank_ints(rows_to_ints(rows))


def check_rank_agrees_with_repo(rows, n) -> bool:
    """Self-test hook: compare the bit-packed rank with verify/gf2.rank."""
    return rank_rows(rows, n) == gf2.rank(dense(rows, n))


# --------------------------------------------------------------------------
# Code container
# --------------------------------------------------------------------------

@dataclass
class Code:
    id: str
    n: int
    X: list[list[int]]
    Z: list[list[int]]
    meta: dict = field(default_factory=dict)

    @staticmethod
    def from_board_json(path: str) -> "Code":
        d = json.load(open(path))
        slug = os.path.splitext(os.path.basename(path))[0]
        meta = {
            "k": d.get("k"),
            "d": (d.get("distance") or {}).get("d"),
            "name": d.get("name"),
            "family": d.get("family"),
            "source": "board",
        }
        return Code(slug, int(d["n"]), d["checks"]["X"], d["checks"]["Z"], meta)

    @staticmethod
    def from_lit_json(d: dict) -> "Code":
        return Code(d["id"], int(d["n"]), d["checks"]["X"], d["checks"]["Z"],
                    {k: v for k, v in d.items() if k not in ("checks",)})

    def normalized(self) -> tuple[list[int], list[int]]:
        """Distinct nonzero rows of each side as sorted bit-packed ints."""
        X = sorted({v for v in rows_to_ints(self.X) if v})
        Z = sorted({v for v in rows_to_ints(self.Z) if v})
        return X, Z

    def ranks(self) -> tuple[int, int]:
        X, Z = self.normalized()
        return rank_ints(X), rank_ints(Z)

    def k(self) -> int:
        rx, rz = self.ranks()
        return self.n - rx - rz

    def max_weight(self) -> int:
        return max([len(r) for r in self.X] + [len(r) for r in self.Z] + [0])

    def is_css_commuting(self) -> bool:
        X, Z = self.normalized()
        return all((x & z).bit_count() % 2 == 0 for x in X for z in Z)

    def is_connected(self) -> bool:
        """Is the Tanner graph (qubits plus X- and Z-checks of the normalized
        generating sets) connected? A disconnected Tanner graph means the
        code is a direct sum of smaller codes on disjoint qubit sets (with
        any qubit touched by no check contributing a trivial [[1,1,1]]
        summand), so its distance is the minimum over the summands and it
        should not count as a single code of those parameters. Union-find on
        qubits: every row merges its support into one class."""
        parent = list(range(self.n))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        X, Z = self.normalized()
        for v in X + Z:
            root = None
            i = 0
            while v:
                if v & 1:
                    r = find(i)
                    if root is None:
                        root = r
                    elif r != root:
                        parent[r] = root
                v >>= 1
                i += 1
        return len({find(i) for i in range(self.n)}) == 1


# --------------------------------------------------------------------------
# Tanner graph, invariants, isomorphism
# --------------------------------------------------------------------------

def tanner_graph(code: Code, swap: bool = False) -> nx.Graph:
    """Typed Tanner graph on the normalized generating sets. Node attribute
    `t` is 'q' (qubit), 'x' (X-check) or 'z' (Z-check). With swap=True the
    X and Z rows exchange types (used to test equivalence up to X/Z swap)."""
    X, Z = code.normalized()
    if swap:
        X, Z = Z, X
    G = nx.Graph()
    for i in range(code.n):
        G.add_node(("q", i), t="q")
    for side, rows in (("x", X), ("z", Z)):
        for j, v in enumerate(rows):
            c = (side, j)
            G.add_node(c, t=side)
            i = 0
            while v:
                if v & 1:
                    G.add_edge(c, ("q", i))
                v >>= 1
                i += 1
    return G


def wl_hash(code: Code, swap: bool = False, iterations: int = 4) -> str:
    G = tanner_graph(code, swap)
    return nx.weisfeiler_lehman_graph_hash(G, node_attr="t", iterations=iterations)


def signature(code: Code) -> tuple:
    """Cheap permutation invariants of the *generating set*, X and Z ordered:
    (n, rank_X, rank_Z, sorted X row weights, sorted Z row weights,
     sorted qubit X-degrees, sorted qubit Z-degrees)."""
    X, Z = code.normalized()
    degx = [0] * code.n
    degz = [0] * code.n
    for v in X:
        for i in ints_to_rows([v])[0]:
            degx[i] += 1
    for v in Z:
        for i in ints_to_rows([v])[0]:
            degz[i] += 1
    return (code.n, rank_ints(X), rank_ints(Z),
            tuple(sorted(v.bit_count() for v in X)),
            tuple(sorted(v.bit_count() for v in Z)),
            tuple(sorted(degx)), tuple(sorted(degz)))


def signature_swapped(sig: tuple) -> tuple:
    n, rx, rz, wx, wz, dx, dz = sig
    return (n, rz, rx, wz, wx, dz, dx)


def sig_hash(sig: tuple) -> str:
    return hashlib.sha1(repr(sig).encode()).hexdigest()[:16]


def _nauty_graph(code: Code, swap: bool):
    import pynauty
    X, Z = code.normalized()
    if swap:
        X, Z = Z, X
    n = code.n
    nv = n + len(X) + len(Z)
    adj: dict[int, list[int]] = {}
    for j, v in enumerate(X + Z):
        c = n + j
        nb = []
        i = 0
        while v:
            if v & 1:
                nb.append(i)
            v >>= 1
            i += 1
        adj[c] = nb
    coloring = [set(range(n)), set(range(n, n + len(X))),
                set(range(n + len(X), nv))]
    coloring = [s for s in coloring if s]
    return pynauty.Graph(nv, directed=False, adjacency_dict=adj,
                         vertex_coloring=coloring), n


def nauty_certificate(code: Code, swap: bool = False) -> bytes:
    """Canonical form of the typed Tanner graph (nauty). Two codes have equal
    certificates iff their typed Tanner graphs are isomorphic, i.e. iff the
    given generating sets are permutation-equivalent row-set to row-set."""
    import pynauty
    g, _ = _nauty_graph(code, swap)
    return pynauty.certificate(g)


def nauty_permutation(a: Code, b: Code, swap: bool = False):
    """Qubit permutation a -> b from the canonical labelings, or None if the
    certificates differ."""
    import pynauty
    ga, n = _nauty_graph(a, False)
    gb, _ = _nauty_graph(b, swap)
    if pynauty.certificate(ga) != pynauty.certificate(gb):
        return None
    la = pynauty.canon_label(ga)  # la[i] = original vertex at canonical position i
    lb = pynauty.canon_label(gb)
    perm = {}
    for pos in range(len(la)):
        u, v = la[pos], lb[pos]
        if u < n:
            perm[u] = v
    return perm


def tanner_isomorphic(a: Code, b: Code, swap: bool = False):
    """Exact typed Tanner-graph isomorphism (VF2). Returns the qubit
    permutation as a dict a_qubit -> b_qubit, or None."""
    Ga = tanner_graph(a)
    Gb = tanner_graph(b, swap)
    nm = nx.algorithms.isomorphism.categorical_node_match("t", None)
    GM = nx.algorithms.isomorphism.GraphMatcher(Ga, Gb, node_match=nm)
    if not GM.is_isomorphic():
        return None
    m = GM.mapping
    return {u[1]: v[1] for u, v in m.items() if u[0] == "q"}


def verify_permutation(a: Code, b: Code, perm: dict, swap: bool = False) -> bool:
    """Independent check that perm maps rowspace(H_X(a)) onto rowspace(H_X(b))
    and likewise for Z (roles swapped if swap). This is the actual definition
    of equivalence; the Tanner isomorphism only supplies the candidate pi."""
    Xa, Za = a.normalized()
    Xb, Zb = b.normalized()
    if swap:
        Xb, Zb = Zb, Xb

    def apply(v):
        w = 0
        i = 0
        while v:
            if v & 1:
                w |= 1 << perm[i]
            v >>= 1
            i += 1
        return w

    for A, B in ((Xa, Xb), (Za, Zb)):
        A2 = [apply(v) for v in A]
        rA, rB = rank_ints(A2), rank_ints(B)
        if rA != rB or rank_ints(A2 + B) != rA:
            return False
    return True


def low_weight_enumerator(vecs: Sequence[int], wmax: int, limit: int = 2_000_000):
    """Exact count of rowspace vectors of weight <= wmax, by enumerating the
    whole rowspace. Only feasible for small rank; returns None when 2**rank >
    limit. Basis-independent, so it is a genuine invariant of the code."""
    basis = []
    piv = {}
    for v in vecs:
        w = v
        while w:
            h = w.bit_length() - 1
            if h in piv:
                w ^= piv[h]
            else:
                piv[h] = w
                basis.append(w)
                break
    r = len(basis)
    if 2 ** r > limit:
        return None
    counts = [0] * (wmax + 1)
    # Gray-code enumeration
    cur = 0
    for g in range(1, 2 ** r):
        cur ^= basis[(g & -g).bit_length() - 1]
        c = cur.bit_count()
        if c <= wmax:
            counts[c] += 1
    return tuple(counts)


def rowspace_invariants(code: Code, wmax: int | None = None):
    """Basis-independent invariants: (n, rank_X, rank_Z, lowX, lowZ) where
    lowX/lowZ are exact counts of rowspace vectors of weight <= wmax (None
    when the rank is too large to enumerate)."""
    X, Z = code.normalized()
    if wmax is None:
        wmax = code.max_weight()
    return (code.n, rank_ints(X), rank_ints(Z),
            low_weight_enumerator(X, wmax), low_weight_enumerator(Z, wmax))


# --------------------------------------------------------------------------
# Board and literature loading
# --------------------------------------------------------------------------

def board_code_path(slug: str) -> str:
    return os.path.join(REPO, "codes", slug + ".json")


def load_board_codes() -> dict[str, Code]:
    """Every CSS entry in codes/, read from the documents themselves.

    The working-repo version of this read a separate board ledger for the
    metadata. Reading codes/ directly keeps the vendored checker to one source
    of truth and lets it run against any checkout, which is the point of
    committing it here.
    """
    out = {}
    root = os.path.join(REPO, "codes")
    for fname in sorted(os.listdir(root)):
        if not fname.endswith(".json"):
            continue
        slug = fname[:-5]
        path = os.path.join(root, fname)
        try:
            doc = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if doc.get("code_type", "CSS") != "CSS":
            continue          # general stabilizer entries rank separately
        try:
            c = Code.from_board_json(path)
        except Exception:
            continue
        checks = doc.get("checks") or {}
        w = max((len(r) for side in ("X", "Z") for r in checks.get(side, [])),
                default=None)
        prov = doc.get("provenance") or {}
        c.meta.update({"k": doc.get("k"),
                       "d": (doc.get("distance") or {}).get("d"),
                       "w": w,
                       "family": doc.get("family") or prov.get("family"),
                       "novelty": doc.get("novelty") or prov.get("novelty"),
                       "on_frontier_now": None})
        out[slug] = c
    return out


def load_literature_params(path: str | None = None) -> list[dict]:
    path = path or os.path.join(DATA, "literature.jsonl")
    return [json.loads(l) for l in open(path)]


def iter_literature_matrices(path: str | None = None):
    path = path or os.path.join(DATA, "literature_matrices.jsonl")
    with open(path) as f:
        for line in f:
            yield Code.from_lit_json(json.loads(line))
