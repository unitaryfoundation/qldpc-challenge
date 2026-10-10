"""Half-infinite boundary gauge engine for open-boundary planar BB codes.

The general-purpose builder for the ``2d-local`` planar family: implements the
boundary construction of Liang-Yang-Iosue-Chen (arXiv:2410.11942) the way the
paper actually formulates it -- on a HALF-INFINITE plane, translation-invariant
along the boundary, so the boundary-parallel coordinate stays a Laurent-
polynomial variable t and commutation with the full semi-infinite bulk is
imposed EXACTLY (no finite-window artifacts). Unlike the fast greedy builder in
``planar.py`` (validated only for the flagship weight-6 family), this engine is
correct for generic (f, g), including the weight-8 families whose secondary
boundary generators are NOT truncations of bulk stabilizers.

Pipeline
--------
1. half_plane_generators(): for one boundary, candidates are Pauli operators
   supported on a strip of rows u in [0,w] with components in R = F2[t,1/t];
   commutation with every retained bulk stabilizer of the opposite type is an
   R-linear system; its kernel module (computed exactly over the PID F2[t] by
   unimodular column elimination) is the boundary gauge group, secondary
   operators included automatically.
2. build_planar(): finite Lx x Ly assembly = fully-supported bulk rows
   + all in-lattice translates of the gauge generators on each of the four
   boundaries (X-type top/bottom = m-condensed, Z-type left/right =
   e-condensed, the directional layout)
   + footnote-6 corner convention (an anticommuting X/Z pair near a corner
   -> include NEITHER)
   + corner topological-order completion: detect corner-local logical
   operators by exact finite linear algebra and promote them to stabilizers,
   preferring higher weight (Sec. III D step 3 of arXiv:2504.08887)
   + cleanup: eliminate weight-1 stabilizers (disentangled qubits) and
   decoupled qubits (Sec. III D step 4) -- this yields the qubit-removal
   layouts of the paper's Tables II-IV automatically.

Conventions (identical to planar.py)
------------------------------------
Cells (i,j), i in [0,Lx) rows, j in [0,Ly) cols; qubits A(i,j)=i*Ly+j and
B(i,j)=Lx*Ly+i*Ly+j. X-stabilizer generator = (f on A, g on B); Z-generator
= (gbar on A, fbar on B) with bar = joint negation of the SAME normalized
supports (independent monomial shifts of fbar and gbar break bulk CSS unless
the extents of f and g match). X stabilizers may hang off the row boundaries,
Z off the column boundaries.

STATUS (all measured in the source sandbox)
-------------------------------------------
* [[288,8,12]] family exact at L=6,8,10 (zero promotions); qubit-removal
  families reproduce k and d at every size tested (188-family 8x13 ->
  (191,8,9); 131-family 7x11 -> (134,7,7); 88-family 6x8 -> (90,6,6); etc.),
  n consistently +2..3 vs the paper (its corners are manually regularized;
  grafting closes most of the gap).
* On a 60-candidate MV==8 population at adaptive sizes within the validity
  domain, every candidate yields a sound code (k stable across two sizes).
* Weight-8 flagship family: 8x20 -> (294,12), d_rand=14 stable to 3000 trials
  (paper flagship [[292,12,14]]); the 2 secondary (non-truncation) boundary
  generators emerge automatically from the kernel.

VALIDITY DOMAIN: guaranteed completion for Lx >= extent_i + 3 and
Ly >= extent_j + 3 (two-sided extents of all four supports). Below the floor
the engine may leave residual short logicals; these are flagged by
d_rand <= 2, never silent.

GRAFTING: graft_r1 implements the paper's restricted r=1 pruning with an
explicit distance floor; graft_r1_safe adds per-step multi-seed confirmation
and block rollback (a fixed screening seed has a deterministic blind spot --
see the docstrings; this discipline is the difference between a real
qubit-removal and a silently distance-losing one).
"""
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, "..", "kit")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from css import rref, rank, kernel_basis  # noqa: E402
from surrogate import distance_rand  # noqa: E402


# =====================================================================
#  Recorded (S_f, S_g) pairs for the board's open-boundary planar family
# =====================================================================
#
# build_planar() takes the two supports as bare arguments, and they ARE the
# family: a different pair is a different code, not a variant of this one.
# Nothing in the signature said so, and the canonical pair was recoverable
# only by reading a board entry's free-text provenance, so a sweep could
# silently measure a different construction and still report well-formed
# numbers. Hence these names.
#
# SCOPE: build_planar() has produced 15 board entries, and their construction
# strings record THREE distinct (S_f, S_g) pairs. The A-support is NOT
# constant across them, so a single "the family's supports" is wrong:
#
#   B=4 weight-8 tile -- S_F_TILE4 / S_G_TILE4_MAIN
#     800-18-27 (20x20), 882-18-29 (21x21), 924-18-31 (21x22), 968-18-31 (22x22)
#     NOT the arXiv:2504.09171 tile -- see the correction note on S_G_TILE4_MAIN.
#   arXiv:2504.08887, square lattices -- S_F_08887 / S_G_08887
#     288-9-6 (12x12), 450-12-6 (15x15)
#   the "weight-8 tile" pair, non-square lattices -- S_F_W8 / S_G_W8
#     183-12-10 (7x17), 242-12-12 (8x19), 401-12-18 (10x24)
#
# Those are nine of the fifteen; the other six build_planar entries record no
# parameters at all and so attest nothing. The 08887 and W8 pairs are named
# here because they are the ones a reader is most likely to sweep by mistake:
# same function, same weight-4 or weight-8 bulk, and both reachable at a
# lattice that yields a perfectly well-formed code that is not the entry you
# meant. The pairs are different because their supports differ, not because
# the papers differ.
#
# Each pair below reproduces every entry listed for it exactly, check matrices
# included; see the calibration note in build_planar's docstring for the check
# that establishes it and for why (n, k, w) cannot.

#: A-support of the B=4 weight-8 tile, as recorded by 800-18-27, 882-18-29,
#: 924-18-31 and 968-18-31. This one IS the arXiv:2504.09171 A-support: the
#: paper's X-tile horizontal edges are exactly {(0,0),(0,3),(2,2),(3,0)}
#: (main.tex, \def\horizontalqubits at lines 690 and 763).
S_F_TILE4 = ((0, 0), (0, 3), (2, 2), (3, 0))

#: Its matching B-support; the same one value in all four of those entries.
#:
#: CORRECTION (2026-10-10). This was previously documented as "the B-support of
#: the arXiv:2504.09171 B=4 tile". It is not. The paper's X-tile vertical edges
#: are {(0,1),(1,0),(1,1),(3,3)} (main.tex, \def\verticalqubits at lines 691 and
#: 764); this tuple differs from that in three of its four monomials. Measured
#: consequence, both sides witness-validated with verify/qldpc_verify.py's own
#: gf2 routines: S_G_TILE4_MAIN gives d <= 11 at 12x12 and d <= 18 at 16x16,
#: where the published tile gives d <= 13 and d <= 19 -- the paper's exact
#: [[288,18,13]] and [[512,18,19]]. So the four entries above are this repo's
#: own constructions at the published geometry, not the published code, and a
#: d <= 18 reading at 16x16 says nothing about the paper's d = 19.
S_G_TILE4_MAIN = ((0, 2), (1, 3), (2, 0), (3, 3))

#: The B-support the arXiv:2504.09171 B=4 weight-8 tile actually uses, paired
#: with S_F_TILE4. Not the board's S_G_TILE4_MAIN, and not the sibling support
#: that codes/566-18-20 and codes/578-18-20 record -- that one differs from this
#: in the single monomial (1,0) vs (2,0), which is the "one support swap" those
#: entries' provenance refers to. The published tile reproduces the paper's two
#: exact distances, d <= 13 at 12x12 and d <= 19 at 16x16.
S_G_TILE4_PUBLISHED = ((0, 1), (1, 0), (1, 1), (3, 3))

#: A-support of the arXiv:2504.08887 pair (codes/288-9-6, 450-12-6). Same
#: function and same weight-4 bulk as the tile, different paper and different
#: supports, so a sweep that pairs it with S_G_TILE4_MAIN measures neither code.
S_F_08887 = ((0, 0), (0, 1), (1, 0), (2, 1))

#: Its matching B-support.
S_G_08887 = ((0, 0), (1, 1), (2, 0), (2, 1))

#: A-support of the pair codes/183-12-10, 242-12-12 and 401-12-18 record as the
#: "weight-8 tile" family. Distinct from both pairs above despite the shared
#: weight, and reached only on non-square lattices.
S_F_W8 = ((0, 0), (1, 0), (2, 3), (2, -2))

#: Its matching B-support.
S_G_W8 = ((0, 0), (0, 1), (-1, -1), (-1, 3))

#: Every (S_f, S_g) pair the board records for this family, as of the entries
#: listed above. Each is verified against its own entries, not interchangeable
#: with another: mixing two of these pairs builds a code that is on no board.
#: S_G_TILE4_PUBLISHED is deliberately NOT here -- it is the published code, not
#: a pair this repo has filed, so it has no board entry to be verified against.
RECORDED_PAIRS = ((S_F_TILE4, S_G_TILE4_MAIN),
                  (S_F_08887, S_G_08887),
                  (S_F_W8, S_G_W8))

# CALIBRATE ON THE CHECK MATRICES, NOT ON (n, k). At a 21x22 lattice the
# triple (n, k, w) comes out (924, 18, 8) for S_G_TILE4_MAIN and for a wrong
# B-support alike: n and k are fixed by the lattice and w by the bulk weight,
# so none of them can see S_g at all. Only the rows can. The tile pair shares
# 475 of 475 X rows with codes/924-18-31; substituting the B-support
# ((0,0),(1,1),(2,2),(3,3)) leaves (n, k, w) untouched and drops that to 19 of
# 475. An assert on (n, k, w) therefore passes on the wrong code, which is the
# exact failure this note exists to catch.
#
# The same trap, one level up, is what the 2026-10-10 correction above records:
# S_G_TILE4_MAIN reproduces its four entries perfectly and is still not the
# published tile. Distance is the only axis that told the two apart -- 18 versus
# 19 at 16x16 -- so a generator calibrated on (n, k, w) or on check matrices
# alone will keep calling a non-published code the published one. Calibrate
# against a number the literature published, at a second size if you can.


# =====================================================================
#  F2[t] polynomial arithmetic (coefficients as Python int bitmasks)
# =====================================================================

def pmul(a: int, b: int) -> int:
    """Carry-less (GF(2)[t]) product."""
    r = 0
    while b:
        lsb = b & -b
        r ^= a << (lsb.bit_length() - 1)
        b ^= lsb
    return r


def pdivmod(a: int, b: int):
    """Polynomial division over F2: a = q*b + r, deg r < deg b."""
    assert b != 0
    db = b.bit_length() - 1
    q = 0
    while a and a.bit_length() - 1 >= db:
        sh = a.bit_length() - 1 - db
        q ^= 1 << sh
        a ^= b << sh
    return q, a


def poly_kernel(M):
    """Right-kernel basis of an m x n matrix over F2[t].

    M: list of m rows, each a list of n ints (bitmask polynomials).
    Returns a list of kernel vectors (each a list of n polys) that form a
    BASIS of {v in F2[t]^n : M v = 0} as an F2[t]-module (free, since F2[t]
    is a PID). Method: unimodular column elimination (Euclidean gcd steps on
    polynomial degrees) tracking the transformation U with M U = H in column
    echelon form; kernel = U-columns over the zero columns of H.
    """
    m = len(M)
    n = len(M[0]) if m else 0
    cols = [[M[r][c] for r in range(m)] for c in range(n)]
    U = [[1 if i == c else 0 for i in range(n)] for c in range(n)]
    used = [False] * n
    for r in range(m):
        while True:
            nz = [c for c in range(n) if not used[c] and cols[c][r]]
            if len(nz) <= 1:
                break
            # reduce all entries in row r modulo the minimal-degree one
            nz.sort(key=lambda c: cols[c][r].bit_length())
            c0 = nz[0]
            for c in nz[1:]:
                q, _ = pdivmod(cols[c][r], cols[c0][r])
                if q:
                    for rr in range(m):
                        cols[c][rr] ^= pmul(q, cols[c0][rr])
                    for k in range(n):
                        U[c][k] ^= pmul(q, U[c0][k])
            # loop again: remainders may have become new minima / zeros
        nz = [c for c in range(n) if not used[c] and cols[c][r]]
        if nz:
            used[nz[0]] = True
    kernel = []
    for c in range(n):
        if all(cols[c][r] == 0 for r in range(m)):
            if any(U[c][k] for k in range(n)):
                kernel.append(U[c])
    return kernel


# =====================================================================
#  Half-infinite boundary gauge generators
# =====================================================================

def _vec_span(vec):
    """j-extent of a strip vector (max bit_length over components)."""
    return max((p.bit_length() for p in vec), default=0)


def _vec_weight(vec):
    return sum(bin(p).count('1') for p in vec)


def _normalize(vec):
    """Right-shift all components so the minimum set bit is at j=0."""
    jmin = min((p & -p).bit_length() - 1 for p in vec if p)
    if jmin > 0:
        vec = [p >> jmin for p in vec]
    return vec


def _compactify(basis):
    """Reduce a kernel basis to compact (small j-span, then low weight)
    generators by pairwise translate-elimination. An arbitrary F2[t] kernel
    basis generates the module, but its vectors can be WIDE combinations of
    the natural compact generators; on a finite lattice, corner-adjacent
    translates of the compact generators are then not expressible by
    in-lattice translates of wide basis vectors (measured: rank deficit 4 on
    the [[288,8,12]] reference). Pairwise reduction restores compactness."""
    basis = [_normalize(list(v)) for v in basis if any(v)]
    improved = True
    while improved:
        improved = False
        for i in range(len(basis)):
            v = basis[i]
            key = (_vec_span(v), _vec_weight(v))
            for jdx in range(len(basis)):
                if jdx == i:
                    continue
                u = basis[jdx]
                for s in range(0, _vec_span(v) + _vec_span(u) + 1):
                    w = _normalize([a ^ (b << s) for a, b in zip(v, u)])
                    if any(w) and (_vec_span(w), _vec_weight(w)) < key:
                        basis[i] = w
                        v = w
                        key = (_vec_span(w), _vec_weight(w))
                        improved = True
    return basis


def _truncation_vectors(candA, candB, nA, w):
    """Strip vectors of all boundary-truncated bulk stabilizers of the
    CANDIDATE type (own supports candA on A, candB on B): center row c with
    c + p < 0 for some support row p; keep only in-half-plane Paulis."""
    ps = [p for p, _ in candA + candB]
    pminc, pmaxc = min(ps), max(ps)
    out = []
    for c in range(-pmaxc, -pminc):          # properly truncated centers
        vec = [0] * (2 * nA)
        ok = True
        for blk, supp in ((0, candA), (1, candB)):
            for (p, q) in supp:
                u = c + p
                if u < 0:
                    continue                  # truncated away
                if u >= nA:
                    ok = False
                    break
                vec[blk * nA + u] ^= 1 << (q + 64)   # offset to keep nonneg
            if not ok:
                break
        if ok and any(vec):
            out.append(_normalize(vec))
    return out


def half_plane_generators(conA, conB, candA=None, candB=None, w=None):
    """Gauge generators on the half-plane {rows >= 0} with boundary at row 0.

    conA, conB : supports (lists of (row_offset p, col_offset q)) of the
        A- and B-components of the CONSTRAINT stabilizer type (the opposite
        Pauli type to the candidates; for CSS, same-type operators commute
        automatically, so only the opposite type constrains).
    w : strip width (candidate rows u in [0, w]). Default: row-extent of the
        constraint supports + 1 (gauge generators live within one stabilizer
        range of the boundary; the +1 is a safety margin -- widening further
        only adds bulk-stabilizer duplicates).

    Candidates: components alpha_u(t) on A(u, .) and beta_u(t) on B(u, .).
    A constraint stabilizer centered at row c is RETAINED on the half-plane
    iff its entire support has row >= 0, i.e. c >= -p_min. Commutation with
    all its column-translates is one polynomial identity per retained c:

        sum_u  Gbar_{u-c}(t) alpha_u(t) + Fbar_{u-c}(t) beta_u(t) = 0,
        Gbar_v(t) = sum_{(p,q) in conA, p=v} t^{-q}   (cleared by t^{q_max}).

    Constraints with c outside [-p_min, w - p_min] cannot overlap the strip,
    so the system is the finite (w+1) x 2(w+1) matrix below -- EXACT, no
    window truncation anywhere.

    Returns a list of generators, each a pair (suppA, suppB) of (row, col)
    supports normalized so min col = 0 (translates are equivalent).
    """
    ps = [p for p, _ in conA + conB]
    qs = [q for _, q in conA + conB]
    pmin, pmax = min(ps), max(ps)
    qmax = max(qs)
    if w is None:
        w = (pmax - pmin) + 1

    nA = w + 1
    rows = []
    for c in range(-pmin, w - pmin + 1):
        row = [0] * (2 * nA)
        for u in range(nA):
            v = u - c
            ga = 0
            for (p, q) in conA:
                if p == v:
                    ga ^= 1 << (qmax - q)
            gb = 0
            for (p, q) in conB:
                if p == v:
                    gb ^= 1 << (qmax - q)
            row[u] = ga
            row[nA + u] = gb
        rows.append(row)

    gens = []
    seen = set()

    def emit(vec):
        suppA = [(u, j) for u in range(nA)
                 for j in range(vec[u].bit_length()) if (vec[u] >> j) & 1]
        suppB = [(u, j) for u in range(nA)
                 for j in range(vec[nA + u].bit_length()) if (vec[nA + u] >> j) & 1]
        if not suppA and not suppB:
            return
        gA = tuple(sorted(suppA))
        gB = tuple(sorted(suppB))
        if (gA, gB) not in seen:
            seen.add((gA, gB))
            gens.append((list(gA), list(gB)))

    # exact kernel basis, compactified to small-span generators
    for vec in _compactify(poly_kernel(rows)):
        emit(vec)

    # validated truncations of the candidate-type bulk stabilizer: these are
    # the paper's primary boundary operators whenever they commute; checking
    # them against the SAME exact constraint matrix guarantees the assembly
    # contains at least the truncation-complete construction.
    def commutes(vec):
        for row in rows:
            acc = 0
            for c in range(2 * nA):
                acc ^= pmul(row[c], vec[c])
            if acc:
                return False
        return True

    if candA is not None:
        for vec in _truncation_vectors(candA, candB, nA, w):
            if commutes(vec):
                emit(vec)
    return gens


def boundary_generators(S_f, S_g, w=None):
    """Gauge generators for all four boundaries of the directional layout.

    Returns dict side -> list of (suppA, suppB) generators in a canonical
    frame: 'top'/'bottom' are X-type with (u = depth into the lattice from
    that row boundary, j = column coordinate); 'left'/'right' are Z-type
    with (u = depth from that column boundary, j = row coordinate).
    Secondary operators (not truncations of bulk stabilizers) appear
    automatically as extra kernel generators -- nothing special-cases them.
    """
    S_fbar = [(-p, -q) for (p, q) in S_f]
    S_gbar = [(-p, -q) for (p, q) in S_g]
    refl = lambda S: [(-p, q) for (p, q) in S]
    trans = lambda S: [(q, p) for (p, q) in S]

    return {
        # X-type candidates (own supports f on A, g on B), constrained by
        # Z-bulk (gbar on A, fbar on B)
        'top':    half_plane_generators(S_gbar, S_fbar, S_f, S_g, w),
        'bottom': half_plane_generators(refl(S_gbar), refl(S_fbar),
                                        refl(S_f), refl(S_g), w),
        # Z-type candidates (own supports gbar on A, fbar on B), constrained
        # by X-bulk (f on A, g on B), in the transposed frame
        'left':   half_plane_generators(trans(S_f), trans(S_g),
                                        trans(S_gbar), trans(S_fbar), w),
        'right':  half_plane_generators(refl(trans(S_f)), refl(trans(S_g)),
                                        refl(trans(S_gbar)), refl(trans(S_fbar)), w),
    }


# =====================================================================
#  Finite-lattice assembly
# =====================================================================

def _place(gen, side, s, Lx, Ly):
    """Map a canonical-frame generator support to lattice (i, j) qubit
    coordinates for translate s along the boundary. Returns (qA, qB) lists
    of (i,j), or None if any coordinate falls outside the lattice."""
    suppA, suppB = gen
    out = ([], [])
    for k, supp in enumerate((suppA, suppB)):
        for (u, j) in supp:
            if side == 'top':
                i, c = u, j + s
            elif side == 'bottom':
                i, c = Lx - 1 - u, j + s
            elif side == 'left':
                i, c = j + s, u
            else:  # right
                i, c = j + s, Ly - 1 - u
            if not (0 <= i < Lx and 0 <= c < Ly):
                return None
            out[k].append((i, c))
    return out


def build_planar(Lx, Ly, S_f, S_g, w=None, corner_pad=2, cleanup=True,
                 max_promotions=200, verbose=False):
    """Full boundary-engine construction of the open-boundary planar code.

    ``S_f`` and ``S_g`` are the family: they fix the code, and a different pair
    is a DIFFERENT code rather than a variant of this one. Use the named pairs
    above -- one of ``RECORDED_PAIRS``, or the ``S_F_TILE4``/``S_G_TILE4_MAIN``,
    ``S_F_08887``/``S_G_08887``, ``S_F_W8``/``S_G_W8`` spellings -- instead of
    inventing supports.

    Before sweeping, confirm the generator reproduces a board entry -- and
    compare the CHECK MATRICES, not ``(n, k, w)``, because those three cannot
    see ``S_g``: at 21x22 a wrong B-support still reports ``(924, 18, 8)``::

        >>> import json, numpy as np
        >>> HX, HZ, _ = build_planar(21, 22, S_F_TILE4, S_G_TILE4_MAIN)
        >>> board = json.load(open("codes/924-18-31.json"))
        >>> built = {tuple(np.nonzero(r)[0].tolist()) for r in np.asarray(HX, bool)}
        >>> assert built == {tuple(r) for r in board["checks"]["X"]}

    Each pair in ``RECORDED_PAIRS`` reproduces every entry listed beside it this
    way, X and Z check matrices both. Returns (HX, HZ, info). After cleanup,
    n = HX.shape[1] may be smaller than 2*Lx*Ly (qubit-removal layouts); info
    records counts and the kept qubit indices (into the original 2*Lx*Ly
    numbering)."""
    # Accept any sequence of pairs, so this module's named constants -- which
    # are tuples, and so cannot be mutated by a caller -- can be passed in
    # directly instead of being copied into a list at every call site.
    S_f = [tuple(p) for p in S_f]
    S_g = [tuple(p) for p in S_g]
    S_fbar = [(-p, -q) for (p, q) in S_f]
    S_gbar = [(-p, -q) for (p, q) in S_g]
    n2 = Lx * Ly
    n = 2 * n2
    A = lambda i, j: i * Ly + j
    B = lambda i, j: n2 + i * Ly + j

    xset, zset = {}, {}   # bytes -> row (dedup)

    def add(table, qA, qB):
        row = np.zeros(n, dtype=np.int8)
        for (i, j) in qA:
            row[A(i, j)] ^= 1
        for (i, j) in qB:
            row[B(i, j)] ^= 1
        if row.any():
            table[row.tobytes()] = row

    # ---- bulk rows (fully supported) ----
    def bulk(table, SA, SB):
        pis = [p for p, _ in SA + SB]
        pjs = [q for _, q in SA + SB]
        for ci in range(-min(pis), Lx - max(pis)):
            for cj in range(-min(pjs), Ly - max(pjs)):
                add(table,
                    [(ci + p, cj + q) for (p, q) in SA],
                    [(ci + p, cj + q) for (p, q) in SB])
    bulk(xset, S_f, S_g)
    bulk(zset, S_gbar, S_fbar)
    n_bulk_x, n_bulk_z = len(xset), len(zset)

    # ---- boundary gauge translates ----
    gens = boundary_generators(S_f, S_g, w)
    for side in ('top', 'bottom'):
        for gen in gens[side]:
            jmax = max(j for _, j in gen[0] + gen[1])
            for s in range(0, Ly - jmax):
                placed = _place(gen, side, s, Lx, Ly)
                if placed:
                    add(xset, *placed)
    for side in ('left', 'right'):
        for gen in gens[side]:
            jmax = max(j for _, j in gen[0] + gen[1])
            for s in range(0, Lx - jmax):
                placed = _place(gen, side, s, Lx, Ly)
                if placed:
                    add(zset, *placed)

    HX = np.array(list(xset.values()), dtype=np.int8)
    HZ = np.array(list(zset.values()), dtype=np.int8)

    # ---- footnote-6 corner convention: drop BOTH members of every
    #      anticommuting X/Z pair (conflicts are corner-localized; bulk rows
    #      provably commute with everything by the half-plane construction).
    C = (HX @ HZ.T) % 2
    xbad = C.any(axis=1)
    zbad = C.any(axis=0)
    n_dropped = int(xbad.sum() + zbad.sum())
    HX, HZ = HX[~xbad], HZ[~zbad]

    # ---- corner topological-order completion ----
    extent_i = (max(p for p, _ in S_f + S_g + S_fbar + S_gbar)
                - min(p for p, _ in S_f + S_g + S_fbar + S_gbar))
    extent_j = (max(q for _, q in S_f + S_g + S_fbar + S_gbar)
                - min(q for _, q in S_f + S_g + S_fbar + S_gbar))
    # one-sided extents (supports are shift-normalized nonneg)
    e1_i = max(p for p, _ in S_f + S_g)
    e1_j = max(q for _, q in S_f + S_g)
    # Corner regions must respect the same opposite-boundary safety margin
    # as the bands: a region reaching within one stabilizer range of the
    # OPPOSITE boundary can contain genuine logical pairs, and pair
    # promotion would then gauge-fix them (measured: k -> 0 at the validity
    # floor, where extent+3 ~ L and an L-2 cap lets corner regions span
    # nearly the whole lattice). Too-small regions only risk leaving
    # spurious pairs unpromoted -- an honest, flagged failure (k inflated /
    # unstable), never a silent one.
    ri = min(extent_i + corner_pad + 1, Lx - e1_i - 2)
    rj = min(extent_j + corner_pad + 1, Ly - e1_j - 2)
    n_promoted = 0
    for _ in range(max_promotions):
        cand = _best_corner_logical(HX, HZ, Lx, Ly, ri, rj, A, B,
                                     e1_i, e1_j)
        if cand is None:
            break
        vec, ptype = cand
        if ptype == 'X':
            HX = np.vstack([HX, vec.reshape(1, -1)])
        else:
            HZ = np.vstack([HZ, vec.reshape(1, -1)])
        n_promoted += 1

    info = dict(n_bulk_x=n_bulk_x, n_bulk_z=n_bulk_z,
                n_x_rows=HX.shape[0], n_z_rows=HZ.shape[0],
                n_corner_dropped=n_dropped, n_promoted=n_promoted,
                gens={s: len(gens[s]) for s in gens})

    # ---- cleanup: weight-1 stabilizers + decoupled qubits ----
    if cleanup:
        HX, HZ, kept = _cleanup(HX, HZ)
        info['kept_qubits'] = kept
        info['n_removed_qubits'] = n - len(kept)
    if verbose:
        print(info)
    return HX, HZ, info


def _corner_regions(Lx, Ly, ri, rj):
    return [(range(0, ri), range(0, rj)),
            (range(0, ri), range(Ly - rj, Ly)),
            (range(Lx - ri, Lx), range(0, rj)),
            (range(Lx - ri, Lx), range(Ly - rj, Ly))]


def _local_logicals(Hsame, Hother, mask):
    """Nontrivial logicals of one Pauli type supported inside `mask`:
    reps of ker(Hother|_mask) / (rowspace(Hsame) restricted to mask).
    Exact: P in rowspace(Hsame) with supp(P) in mask  <=>  P = a.Hsame with
    a in the left-kernel of Hsame[:, ~mask]."""
    R = np.where(mask)[0]
    if R.size == 0 or Hother.shape[0] == 0:
        return []
    K = kernel_basis(Hother[:, R])            # rows: length |R|
    if K.size == 0:
        return []
    if Hsame.shape[0] > 0:
        LK = kernel_basis(Hsame[:, ~mask].T)  # combos a
        W = (LK @ Hsame[:, R]) % 2 if LK.size else np.zeros((0, R.size), np.int8)
    else:
        W = np.zeros((0, R.size), np.int8)
    Wr, piv = rref(W)
    out = []
    for v in K:
        v = v.copy()
        for irow, p in enumerate(piv):
            if v[p]:
                v = (v + Wr[irow]) % 2
        if v.any():
            full = np.zeros(Hsame.shape[1], dtype=np.int8)
            full[R] = v
            out.append(full)
            # extend the reduction basis so later reps are independent
            Wr = np.vstack([Wr, v.reshape(1, -1)]) % 2
            Wr, piv = rref(Wr)
            piv = list(piv)
    return out


def _best_corner_logical(HX, HZ, Lx, Ly, ri, rj, A, B, extent_i=0, extent_j=0):
    """Next operator to promote, or None. Two passes:

    PASS 1 -- type-restricted full-length BANDS (lone promotion, provably
    safe): in a top/bottom band of height h_i <= Lx - extent_i - 2 (so the
    band stays more than one stabilizer range away from the opposite
    m-boundary), any X-type local logical is spurious: a genuine X-logical
    must terminate on BOTH m-condensed boundaries, and every Z-logical class
    has a representative supported below the band (class anticommutation is
    representative-independent because the candidate commutes with all
    stabilizers), so a band-local X commuting with everything pairs with no
    genuine Z-logical. Symmetrically, Z-type in left/right bands. This
    catches mid-edge and corner spurious operators of the matching type.

    PASS 2 -- corner LOCAL CONJUGATE PAIRS: promote the higher-weight member
    of an anticommuting (X,Z) candidate pair supported in the same corner
    region (the parent paper's corner completion). A lone candidate pairing
    only with extended operators is a genuine logical and is never promoted
    (a lone-candidate rule drives k to 0 on tight lattices)."""
    n = HX.shape[1]
    best = None

    def consider(vec, ptype):
        nonlocal best
        wgt = int(vec.sum())
        if best is None or wgt > best[2]:
            best = (vec, ptype, wgt)

    # ---- pass 1: bands ----
    h_i = min(extent_i + 2, Lx - extent_i - 2)
    h_j = min(extent_j + 2, Ly - extent_j - 2)
    bands = []
    if h_i >= 1:
        bands.append((range(0, h_i), range(0, Ly), 'X'))
        bands.append((range(Lx - h_i, Lx), range(0, Ly), 'X'))
    if h_j >= 1:
        bands.append((range(0, Lx), range(0, h_j), 'Z'))
        bands.append((range(0, Lx), range(Ly - h_j, Ly), 'Z'))
    for (ris_, rjs_, ptype) in bands:
        mask = np.zeros(n, dtype=bool)
        for i in ris_:
            for j in rjs_:
                mask[A(i, j)] = True
                mask[B(i, j)] = True
        if ptype == 'X':
            for vec in _local_logicals(HX, HZ, mask):
                consider(vec, 'X')
        else:
            for vec in _local_logicals(HZ, HX, mask):
                consider(vec, 'Z')
    if best is not None:
        return (best[0], best[1])

    # ---- pass 2: corner pairs ----
    for (ris_, rjs_) in _corner_regions(Lx, Ly, ri, rj):
        mask = np.zeros(n, dtype=bool)
        for i in ris_:
            for j in rjs_:
                mask[A(i, j)] = True
                mask[B(i, j)] = True
        xc = _local_logicals(HX, HZ, mask)
        if not xc:
            continue
        zc = _local_logicals(HZ, HX, mask)
        if not zc:
            continue
        XC = np.array(xc, dtype=np.int8)
        ZC = np.array(zc, dtype=np.int8)
        P = (XC @ ZC.T) % 2
        for i in range(P.shape[0]):
            for j in range(P.shape[1]):
                if P[i, j]:
                    consider(XC[i], 'X')
                    consider(ZC[j], 'Z')
    return (best[0], best[1]) if best else None


def _cleanup(HX, HZ):
    """Sec. III D step 4: iteratively eliminate weight-1 stabilizers
    (multiply them into other same-type rows, then drop the fixed qubit)
    and decoupled qubits (zero columns). Returns (HX, HZ, kept_indices)."""
    n = HX.shape[1]
    kept = np.ones(n, dtype=bool)
    HX, HZ = HX.copy(), HZ.copy()
    while True:
        changed = False
        HX = HX[HX.sum(axis=1) > 0] if HX.size else HX
        HZ = HZ[HZ.sum(axis=1) > 0] if HZ.size else HZ
        for name in ('X', 'Z'):
            H = HX if name == 'X' else HZ
            if not H.size:
                continue
            wts = H.sum(axis=1)
            ones = np.where(wts == 1)[0]
            if ones.size:
                r = ones[0]
                q = int(np.argmax(H[r]))
                # other same-type rows containing q: multiply by this stab
                touch = np.where(H[:, q] == 1)[0]
                for rr in touch:
                    if rr != r:
                        H[rr] ^= H[r]
                # opposite-type rows cannot touch q in a commuting group
                Hopp = HZ if name == 'X' else HX
                assert not (Hopp.size and Hopp[:, q].any()), \
                    "weight-1 stabilizer conflicts with opposite type"
                H = np.delete(H, r, axis=0)
                # remove the column entirely (qubit disentangled)
                if name == 'X':
                    HX = np.delete(H, q, axis=1)
                    HZ = np.delete(HZ, q, axis=1) if HZ.size else HZ
                else:
                    HZ = np.delete(H, q, axis=1)
                    HX = np.delete(HX, q, axis=1) if HX.size else HX
                live = np.where(kept)[0]
                kept[live[q]] = False
                changed = True
                break
        if changed:
            continue
        # decoupled qubits: zero columns in both
        colw = (HX.sum(axis=0) if HX.size else 0) + (HZ.sum(axis=0) if HZ.size else 0)
        dead = np.where(colw == 0)[0]
        if dead.size:
            HX = np.delete(HX, dead, axis=1) if HX.size else HX
            HZ = np.delete(HZ, dead, axis=1) if HZ.size else HZ
            live = np.where(kept)[0]
            kept[live[dead]] = False
            changed = True
        if not changed:
            break
    return HX, HZ, np.where(kept)[0]


def compute_k(HX, HZ):
    """k = n - rank(HX) - rank(HZ), tolerant of empty check matrices (which
    the cleanup and grafting loops can produce)."""
    nq = HX.shape[1] if HX.ndim == 2 else HZ.shape[1]
    rx = rank(HX) if HX.size else 0
    rz = rank(HZ) if HZ.size else 0
    return nq - rx - rz


# =====================================================================
#  Lattice grafting (qubit removal) and weight reduction
# =====================================================================

def graft_r1(HX, HZ, max_removals=10**9, trials=200, seed=0, d_floor=None,
             verbose=False):
    """Restricted (r=1) lattice grafting, arXiv:2504.08887 Sec. III E.

    Repeatedly remove a qubit q that participates in EXACTLY ONE stabilizer
    of some Pauli type O, together with that O-stabilizer. Commutation is
    preserved automatically: opposite-type stabilizers containing q only
    overlapped q against the removed row (no other O-row touches q), so
    truncating them keeps all overlaps even. Each removal is accepted only
    if k is unchanged and the randomized distance bound (fixed trials/seed,
    so comparisons are consistent) does not decrease; otherwise it is
    reverted. Candidate order is randomized (`seed`); run several seeds and
    keep the best, as in the paper.

    Returns (HX, HZ, n_removed)."""
    rng = np.random.default_rng(seed)
    k0 = compute_k(HX, HZ)
    # d_floor: explicit acceptance floor for the distance. Without it the
    # floor is the measured d_rand of the input -- but d_rand is an UPPER
    # bound, so an under-converged baseline (estimate below the true d)
    # silently licenses distance-losing removals (measured: a [[292,12,14]]
    # graft dropped to d=13 with a trials=120 baseline). When the target d
    # is known, pass it.
    d0 = d_floor if d_floor is not None else distance_rand(HX, HZ,
                                                           trials=trials, seed=1)
    removed = 0
    while removed < max_removals:
        wx = HX.sum(axis=0) if HX.size else np.zeros(HX.shape[1])
        wz = HZ.sum(axis=0) if HZ.size else np.zeros(HZ.shape[1])
        cands = ([('X', int(q)) for q in np.where(wx == 1)[0]] +
                 [('Z', int(q)) for q in np.where(wz == 1)[0]])
        if not cands:
            break
        rng.shuffle(cands)
        accepted = False
        for (t, q) in cands:
            H = HX if t == 'X' else HZ
            r = int(np.where(H[:, q] == 1)[0][0])
            HX2 = np.delete(HX, r, axis=0) if t == 'X' else HX
            HZ2 = np.delete(HZ, r, axis=0) if t == 'Z' else HZ
            HX2 = np.delete(HX2, q, axis=1)
            HZ2 = np.delete(HZ2, q, axis=1)
            if compute_k(HX2, HZ2) != k0:
                continue
            d2 = distance_rand(HX2, HZ2, trials=trials, seed=1)
            if d2 >= d0:
                HX, HZ = HX2, HZ2
                removed += 1
                accepted = True
                if verbose:
                    print(f"  graft: removed qubit (type {t}), n={HX.shape[1]}, "
                          f"d_rand={d2}", flush=True)
                break
        if not accepted:
            break
    return HX, HZ, removed


def graft_r1_safe(HX, HZ, max_removals=10**9, trials=1200, confirm_trials=2500,
                  seed=0, d_floor=None, verbose=False, block=3):
    """Self-correcting restricted (r=1) grafting.

    Same move set as graft_r1, but each removal that passes the cheap
    fixed-seed screen (trials, seed=1) must then be CONFIRMED at
    confirm_trials with a fresh rotating seed before it is kept; on
    confirmation failure the removal is undone and that qubit is
    blacklisted (by original identity, stable under deletions).

    Motivation (measured): a fixed screening seed has a deterministic blind
    spot -- on a [[294,12,14]] graft, seed-1 screens at 1200 trials missed
    a weight-13 logical in 6/6 chains that seed-5 verification at 2500
    trials caught 6/6, wasting every chain. Confirm-per-step converts
    end-of-chain rejection into per-step backtracking.

    Returns (HX, HZ, n_removed)."""
    rng = np.random.default_rng(seed)
    k0 = compute_k(HX, HZ)
    assert d_floor is not None, "graft_r1_safe requires an explicit d_floor"
    orig = list(range(HX.shape[1]))      # stable qubit identities
    blacklist = set()
    confirm_seed = 5
    removed = 0
    since_block = []                     # orig-ids removed since last good snapshot
    snap_HX, snap_HZ, snap_orig = HX.copy(), HZ.copy(), list(orig)
    while removed < max_removals:
        wx = HX.sum(axis=0) if HX.size else np.zeros(HX.shape[1])
        wz = HZ.sum(axis=0) if HZ.size else np.zeros(HZ.shape[1])
        cands = [(t, int(q)) for t, w in (('X', wx), ('Z', wz))
                 for q in np.where(w == 1)[0] if orig[int(q)] not in blacklist]
        if not cands:
            break
        rng.shuffle(cands)
        accepted = False
        for (t, q) in cands:
            H = HX if t == 'X' else HZ
            r = int(np.where(H[:, q] == 1)[0][0])
            HX2 = np.delete(HX, r, axis=0) if t == 'X' else HX
            HZ2 = np.delete(HZ, r, axis=0) if t == 'Z' else HZ
            HX2 = np.delete(HX2, q, axis=1)
            HZ2 = np.delete(HZ2, q, axis=1)
            if compute_k(HX2, HZ2) != k0:
                continue
            if distance_rand(HX2, HZ2, trials=trials, seed=1) < d_floor:
                continue
            # confirmation at TWO fresh seeds: the step is kept only if
            # independent high-trial checks both meet the floor. (Measured:
            # single-seed confirms at 2500 trials pass distance-losing
            # removals ~40% of the time; two seeds cut the per-step
            # slip-through to ~15%, with a 3-seed block gate behind it.)
            dC = distance_rand(HX2, HZ2, trials=confirm_trials,
                               seed=confirm_seed)
            if dC >= d_floor:
                dC = min(dC, distance_rand(HX2, HZ2, trials=confirm_trials,
                                           seed=confirm_seed + 1))
            confirm_seed += 4
            orig_removed_last = orig[q]
            if dC < d_floor:
                blacklist.add(orig[q])
                if verbose:
                    print(f"  graft-safe: UNDO qubit (type {t}) -- confirm "
                          f"d_rand({confirm_trials})={dC} < {d_floor}; "
                          f"blacklisted", flush=True)
                continue
            del orig[q]
            HX, HZ = HX2, HZ2
            removed += 1
            since_block.append(orig_removed_last)
            accepted = True
            if verbose:
                print(f"  graft-safe: removed qubit (type {t}), "
                      f"n={HX.shape[1]}, confirmed d_rand={dC}", flush=True)
            # block verification: every `block` accepted removals, run the
            # full multi-seed gate; on failure roll back to the last good
            # snapshot and blacklist the block's qubits. Rationale
            # (measured): at n~560 a single 2500-trial check detects a
            # marginal short logical only ~25-35% of the time, so 2-seed
            # per-step confirms leak ~40-50% of bad removals and 13-26-step
            # chains die at end-verification. Early block gates bound the
            # damage to `block` steps instead of the whole chain.
            if len(since_block) >= block:
                dB = min(distance_rand(HX, HZ, trials=confirm_trials,
                                       seed=s2) for s2 in (701, 809, 911))
                if dB < d_floor:
                    HX, HZ, orig = snap_HX.copy(), snap_HZ.copy(), list(snap_orig)
                    removed -= len(since_block)
                    blacklist.update(since_block)
                    if verbose:
                        print(f"  graft-safe: BLOCK ROLLBACK ({len(since_block)} "
                              f"removals; gate d_rand={dB} < {d_floor}); "
                              f"qubits blacklisted", flush=True)
                else:
                    snap_HX, snap_HZ, snap_orig = HX.copy(), HZ.copy(), list(orig)
                    if verbose:
                        print(f"  graft-safe: block gate PASSED at n={HX.shape[1]} "
                              f"(d_rand={dB})", flush=True)
                since_block = []
            break
        if not accepted:
            break
    return HX, HZ, removed


def reduce_weights(H, passes=10):
    """Greedy generating-set weight minimization (vectorized).

    Repeatedly replaces a row by its sum with another row when that lowers
    its weight. Row operations preserve the rowspace, hence the stabilizer
    group, k, d, and CSS structure; only the GENERATING SET changes. The
    engine's raw kernel/completion output is not weight-minimal (measured:
    the [[288,8,12]] family builds with a weight-7 Z-generator that reduces
    to 6, matching the paper). A code's weight class is a property of the
    best generating set, so this pass is part of construction, not
    cosmetics."""
    H = H.copy() % 2
    for _ in range(passes):
        changed = False
        for i in np.argsort(-H.sum(axis=1)):
            wi = H[i].sum()
            if wi <= 0:
                continue
            wn = (H ^ H[i]).sum(axis=1)
            wn[i] = wi
            j = int(np.argmin(wn))
            if wn[j] < wi:
                H[i] ^= H[j]
                changed = True
        if not changed:
            break
    return H


if __name__ == "__main__":
    # unit test: poly kernel of [t, t^2+t] -> basis {(t+1, 1)}
    ker = poly_kernel([[0b10, 0b110]])
    assert ker == [[0b11, 0b1]], ker
    print("poly_kernel unit test: ok")

    # flagship family through the full engine at 6x6: n=72, k=8; the raw
    # generating set weight-reduces to the advertised weight-6 class.
    Sf = [(1, 0), (2, 0), (0, 2)]
    Sg = [(0, 0), (2, 1), (2, 2)]
    HX, HZ, info = build_planar(6, 6, Sf, Sg)
    from css import verify_css
    k = compute_k(HX, HZ)
    wmax = max(reduce_weights(HX).sum(axis=1).max(),
               reduce_weights(HZ).sum(axis=1).max())
    d = distance_rand(HX, HZ, trials=400, seed=0)
    print(f"build_planar 6x6 flagship: n={HX.shape[1]} k={k} "
          f"CSS={verify_css(HX, HZ)} max_weight={wmax} d_rand<= {d}")
    print(f"  (expect n=72, k=8, CSS=True, max_weight=6, d<=4)")
