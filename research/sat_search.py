"""SAT-based CSS code discovery (DalFavero et al., arXiv:2608.23460, Sec. VI),
with the group-membership slack handled the CSS way.

This is the unconstrained base. A find carries no layout, so it cannot enter the
2d-local tracks; for those use research/local_sat.py, which extends this file
with a locality constraint on every check.

Formulates "find an [[n, k]] CSS code whose checks all have weight <= w and
which detects every Pauli error of weight <= t" as CNF:

  variables
    xr[g][q] -- X-check row g acts with X on qubit q
    zr[g][q] -- Z-check row g acts with Z on qubit q

  commutation: HX HZ^T = 0, i.e. every (X-row, Z-row) pair overlaps on an even
    number of qubits (per-pair XOR parity chains).

  detection of error e=(xe|ze): e must have nonzero syndrome OR lie in the
    stabilizer group. For CSS codes "in the stabilizer" means xe in rowspace(HZ)
    ... more precisely e is undetected iff xe is in rowspace(HZ) AND ze in
    rowspace(HX). Encoding rowspace membership directly needs slack variables
    over GF(2) products; instead we use the equivalent *distance* form:
    e is detected iff (HX ze != 0) or (HZ xe != 0), where HX ze != 0 means some
    X-row has odd overlap with ze. We encode "odd overlap" per row with XOR
    parity chains and require at least one odd row overall -- but we do NOT
    require it for errors that are stabilizer elements. Since enumerating
    stabilizer membership is complex, we take the paper's route: require
    detection for all errors EXCEPT allow each error an "absorbed" escape hatch
    via slack literals s[g] marking that error as a product of rows. To keep
    the encoding sound and simple, we instead only enumerate errors up to
    weight t and require nonzero syndrome for all of them; this is exactly
    right whenever the resulting code has no weight-<=t stabilizers, which we
    CHECK after decoding (rejecting any assignment where some weight-<=t error
    has zero syndrome -- those are precisely the absorbed ones).

  weight bound: Sinz sequential counter over active qubits per row.

Any satisfying assignment decodes to CSS (HX, HZ); assignments where a
weight-<=t error lands in the stabilizer group are rejected post-hoc (they
would be valid codes too, just not certified by this clause set). Distinct
solutions are enumerated with blocking clauses.

Distance is NOT decided here -- yielded codes go through the normal witness +
validation-gate pipeline like everything else in this repo.

Usage:

    from sat_search import enumerate_sat_codes, search_sat_codes

    recs = search_sat_codes(n=10, n_generators=5, max_weight=4, t=2,
                            count=200, seed=7, min_k=4, min_d=4)

Requires ``python-sat`` (``uv run --with python-sat python ...``).
"""
import itertools
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "kit"))

try:
    from pysat.solvers import Minisat22
    _HAS_PYSAT = True
except ImportError:
    _HAS_PYSAT = False


def _seq_counter(lits, bound, A, tag):
    """Sinz sequential counter: at most ``bound`` of ``lits`` may be true.
    ``tag`` must be unique per call (aux-variable namespace)."""
    n = len(lits)
    if bound >= n:
        return []
    s = [[A(("s", tag, i, j)) for j in range(bound)] for i in range(n)]
    cls = []
    cls.append([-lits[0], s[0][0]])
    cls.append([-s[0][0], lits[0]])
    for j in range(1, bound):
        cls.append([-s[0][j]])
    for i in range(1, n):
        cls.append([s[i][0], -lits[i]])
        cls.append([s[i][0], -s[i - 1][0]])
        cls.append([-s[i][0], lits[i], s[i - 1][0]])
        for j in range(1, bound):
            cls.append([s[i][j], -lits[i], -s[i - 1][j - 1]])
            cls.append([s[i][j], -s[i - 1][j]])
            cls.append([-s[i][j], s[i - 1][j], lits[i]])
            cls.append([-s[i][j], s[i - 1][j], s[i - 1][j - 1]])
        cls.append([-lits[i], -s[i - 1][bound - 1]])
    return cls


def _xor_chain(lits, A, tag):
    """CNF for a literal equal to the XOR of ``lits``; returns (clauses, out)."""
    cls = []
    prev = None
    for i, lit in enumerate(lits):
        cur = A((tag, i))
        if prev is None:
            cls.append([-cur, lit])
            cls.append([cur, -lit])
        else:
            cls.append([-cur, prev, lit])
            cls.append([-cur, -prev, -lit])
            cls.append([cur, -prev, lit])
            cls.append([cur, prev, -lit])
        prev = cur
    return cls, prev


def enumerate_sat_codes(n, n_generators, max_weight, t, *, seed=0,
                        max_codes=None):
    """Yield ``(spec, HX, HZ)`` for distinct CSS codes found by SAT.

    Parameters
    ----------
    n            : number of physical qubits
    n_generators : rows sought in EACH of HX and HZ
    max_weight   : per-row weight bound (active qubits <= max_weight)
    t            : code must detect every Pauli error of weight <= t
                   (errors that would be stabilizer elements cause rejection)
    seed         : reserved for reproducibility bookkeeping in spec
    max_codes    : stop after this many codes

    Each spec is rebuildable:
    {"family": "sat-css", "n", "n_generators", "max_weight", "t", "seed",
     "index"}.
    """
    if not _HAS_PYSAT:
        raise ImportError("sat_search needs python-sat")

    aux = {}

    def A(name):
        return aux.setdefault(name, len(aux) + 1)

    # --- errors: all nontrivial Paulis of weight 1..t as (xe_bits, ze_bits)
    def iter_errors():
        for w in range(1, t + 1):
            for support in itertools.combinations(range(n), w):
                for comps in itertools.product((1, 2, 3), repeat=w):
                    xe = np.zeros(n, dtype=np.int8)
                    ze = np.zeros(n, dtype=np.int8)
                    for q, c in zip(support, comps):
                        if c in (1, 3):
                            xe[q] = 1
                        if c in (2, 3):
                            ze[q] = 1
                    yield tuple(xe), tuple(ze)

    G = n_generators
    xr = {(g, q): A(("xr", g, q)) for g in range(G) for q in range(n)}
    zr = {(g, q): A(("zr", g, q)) for g in range(G) for q in range(n)}

    clauses = []

    # --- commutation: even overlap between every X-row g1 and Z-row g2
    for g1 in range(G):
        for g2 in range(G):
            pair_lits = []
            for q in range(n):
                p = A(("ov", g1, g2, q))          # p <-> xr[g1,q] & zr[g2,q]
                clauses.append([-p, xr[(g1, q)]])
                clauses.append([-p, zr[(g2, q)]])
                clauses.append([p, -xr[(g1, q)], -zr[(g2, q)]])
                pair_lits.append(p)
            ch, out = _xor_chain(pair_lits, A, ("par", g1, g2))
            clauses.extend(ch)
            if out is not None:
                clauses.append([-out])             # final parity must be 0

    # --- detection: for each error, SOME X-row has odd overlap with ze OR
    #     SOME Z-row has odd overlap with xe.
    #     Per X-row g: odd overlap with ze <=> XOR_q (xr[g,q] & ze[q]) = 1.
    #     Conjoin the fixed ze bits into per-(g,q) literals, then XOR-chain.
    for e_idx, (xe, ze) in enumerate(iter_errors()):
        lits = []
        for g in range(G):
            row_lits = []
            for q in range(n):
                if ze[q]:
                    row_lits.append(xr[(g, q)])
            if row_lits:
                if len(row_lits) == 1:
                    lits.append(row_lits[0])
                else:
                    ch, out = _xor_chain(row_lits, A, ("dx", g, e_idx))
                    clauses.extend(ch)
                    lits.append(out)
        for g in range(G):
            row_lits = []
            for q in range(n):
                if xe[q]:
                    row_lits.append(zr[(g, q)])
            if row_lits:
                if len(row_lits) == 1:
                    lits.append(row_lits[0])
                else:
                    ch, out = _xor_chain(row_lits, A, ("dz", g, e_idx))
                    clauses.extend(ch)
                    lits.append(out)
        if lits:
            clauses.append(list(lits))

    # --- weight bound per row
    for side, varmap in enumerate((xr, zr)):
        for g in range(G):
            act = []
            for q in range(n):
                a = A(("act", side, g, q))
                v = varmap[(g, q)]
                clauses.append([-a, v])          # a -> v
                clauses.append([-v, a])          # v -> a
                act.append(a)
            clauses.extend(_seq_counter(act, max_weight, A,
                                        tag=("w", side, g)))

    # --- symmetry breaking: first X-row starts with an X on qubit 0
    clauses.append([xr[(0, 0)]])

    own_vars = set(aux.values())
    solver = Minisat22(bootstrap_with=clauses)
    try:
        count = 0
        while max_codes is None or count < max_codes:
            if not solver.solve():
                break
            model = {abs(m) for m in solver.get_model() if m > 0}
            HX = np.zeros((G, n), dtype=np.int8)
            HZ = np.zeros((G, n), dtype=np.int8)
            for g in range(G):
                for q in range(n):
                    HX[g, q] = 1 if xr[(g, q)] in model else 0
                    HZ[g, q] = 1 if zr[(g, q)] in model else 0
            block = [-v for v in own_vars if v in model]

            # reject degenerate rows (schema requires non-empty checks)
            if (HX.sum(axis=1) == 0).any() or (HZ.sum(axis=1) == 0).any():
                solver.add_clause(block)
                continue

            # reject assignments where some weight-<=t error has zero syndrome
            # (that error would be a stabilizer element, not "detected")
            ok = True
            for xe, ze in iter_errors():
                xev = np.array(xe, dtype=np.int8)
                zev = np.array(ze, dtype=np.int8)
                if not ((HX @ zev) % 2).any() and not ((HZ @ xev) % 2).any():
                    ok = False
                    break
            if not ok:
                solver.add_clause(block)
                continue

            spec = {"family": "sat-css", "n": n, "n_generators": G,
                    "max_weight": max_weight, "t": t, "seed": seed,
                    "index": count}
            yield (spec, HX, HZ)
            count += 1
            solver.add_clause(block)
    finally:
        solver.delete()


def search_sat_codes(n, n_generators, max_weight, t, *, count=100, seed=0,
                     min_k=4, min_d=4, trials=400, keep=25, verbose=True):
    """Generate up to ``count`` SAT-found codes and screen them with the kit's
    standard funnel (``search.screen``). Returns ranked records."""
    from search import screen
    gen = enumerate_sat_codes(n, n_generators, max_weight, t, seed=seed,
                              max_codes=count)
    recs = screen(gen, min_k=min_k, min_d=min_d, trials=trials)
    if verbose:
        print(f"SAT-CSS sweep n={n} gens={n_generators} w<={max_weight} t={t}: "
              f"{len(recs)} survivors (k>={min_k}, d_ub>={min_d})")
        for r in recs[:keep]:
            print(f"  [[{r['n']},{r['k']},{r['d']}]] eff={r['efficiency']} {r['spec']}")
    return recs[:keep]


if __name__ == "__main__":
    search_sat_codes(n=8, n_generators=4, max_weight=3, t=1, count=30, seed=11)
