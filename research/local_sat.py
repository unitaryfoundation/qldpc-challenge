"""Locality-constrained SAT-based CSS code discovery, scored for geometric
efficiency g = 4 k d^2 / (n rho^2 r^4) (TRACKS.md).

Extends sat_search.py: each check row g is anchored at a lattice site and may
only act on qubits within Euclidean radius ``radius`` of its anchor. Qubit
positions are fixed on a grid; check anchors are also SAT variables. This makes
the interaction radius bounded BY CONSTRUCTION, so any code found has an honest
2d-local layout -- the prerequisite for a nonzero g score.

Encoding per row g:
  anchor vars ax[g][i], az[g][i]  (one-hot over candidate sites)
  incidence xr[g][q] -> exists site i with ax[g][i] AND dist(site_i, qubit_q) <= radius

Any satisfying assignment decodes to CSS (HX, HZ) plus an explicit layout
(coordinates + anchors), so g is computable from the artifact itself.

Distance is NOT decided here -- yielded codes go through the normal witness +
validation-gate pipeline like everything else in this repo.

Usage:

    from local_sat import search_local_sat

    recs = search_local_sat(n_side=5, n_generators=6, max_weight=4, t=2,
                            radius=1.5, count=50, seed=7)

Requires ``python-sat`` (``uv run --with python-sat python ...``).
"""

import itertools
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "kit"))

try:
    from pysat.solvers import Minisat22, Cadical153, CryptoMinisat, Kissat404, Minicard

    _HAS_PYSAT = True
except ImportError:
    _HAS_PYSAT = False


def _grid_sites(side):
    return [(float(x), float(y)) for y in range(side) for x in range(side)]


def build_local_cnf(n_side, n_generators, max_weight, t, radius, sink=None,
                    shared_t3=False):
    """Build the locality-constrained CNF and return its variable maps.

    Returns a dict with keys: ``sites``, ``n``, ``G``, ``xr``, ``zr``, ``ax``,
    ``az``, ``clauses``, ``incidence_vars``, ``iter_errors``. Separated from
    solving so benchmarks, symmetry breaking, and MaxSAT reuse can share one
    encoder definition.

    ``sink``: if given (any object with ``add_clause``), clauses are streamed
    into it and ``clauses`` is returned as None — keeps large t=3 formulas
    out of Python memory.
    """
    sites = _grid_sites(n_side)
    n = len(sites)
    G = n_generators

    aux = {}

    def A(name):
        return aux.setdefault(name, len(aux) + 1)

    clauses = [] if sink is None else None

    def emit(c):
        if sink is None:
            clauses.append(c)
        else:
            sink.add_clause(c)

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

    # variables
    xr = {(g, q): A(("xr", g, q)) for g in range(G) for q in range(n)}
    zr = {(g, q): A(("zr", g, q)) for g in range(G) for q in range(n)}
    ax = {(g, i): A(("ax", g, i)) for g in range(G) for i in range(n)}
    az = {(g, i): A(("az", g, i)) for g in range(G) for i in range(n)}

    # one-hot anchors: exactly one site per check row
    for side_vars in (ax, az):
        for g in range(G):
            lits = [side_vars[(g, i)] for i in range(n)]
            emit(lits)  # at least one
            for a, b in itertools.combinations(lits, 2):
                emit([-a, -b])  # at most one

    # locality: xr[g,q] -> OR_i (ax[g,i] & close(i,q)); encode as
    #   xr[g,q] -> OR of "anchor-at-i" literals restricted to close sites,
    # plus the converse direction via weight counting below. To keep it sound
    # we also forbid xr[g,q] when NO close site can be the anchor... that needs
    # the anchor choice fixed first, so instead we use the standard trick:
    # introduce p[g,q,i] <-> ax[g,i] & xr[g,q], require OR_i p[g,q,i] when
    # xr[g,q], and require p -> close(i,q).
    for g in range(G):
        for q in range(n):
            close = [
                i for i in range(n) if math.dist(sites[i], sites[q]) <= radius + 1e-9
            ]
            if not close:
                emit([-xr[(g, q)]])
                emit([-zr[(g, q)]])
                continue
            for side_anchor, side_row in ((ax, xr), (az, zr)):
                p_lits = []
                for i in close:
                    p = A(("p", id(side_anchor), g, q, i))
                    a_lit = side_anchor[(g, i)]
                    r_lit = side_row[(g, q)]
                    # p <-> a & r
                    emit([-p, a_lit])
                    emit([-p, r_lit])
                    emit([p, -a_lit, -r_lit])
                    p_lits.append(p)
                emit([-side_row[(g, q)]] + p_lits)

    # --- commutation: even overlap between every X-row g1 and Z-row g2
    def xor_chain(lits, tag):
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

    for g1 in range(G):
        for g2 in range(G):
            pair_lits = []
            for q in range(n):
                p = A(("ov", g1, g2, q))
                emit([-p, xr[(g1, q)]])
                emit([-p, zr[(g2, q)]])
                emit([p, -xr[(g1, q)], -zr[(g2, q)]])
                pair_lits.append(p)
            ch, out = xor_chain(pair_lits, ("par", g1, g2))
            for _c in ch:
                emit(_c)
            if out is not None:
                emit([-out])

    # --- detection: SOME X-row odd-overlaps ze OR SOME Z-row odd-overlaps xe
    #
    # shared_t3: factor detection into per-support aux. For each distinct ze
    # pattern build one aux t(ze) >= OR_g parity_g(ze) (implication clauses;
    # parity chains are built once per (row, ze) instead of per (row, error)),
    # likewise u(xe); then each error contributes only the 2-literal clause
    # [t(ze) | u(xe)]. Cuts the aux-variable count ~25x for t=3 (the 13 GB
    # memory wall) at the cost of possibly over-approximating t/u (sound:
    # the enumerator's post-check still rejects non-detecting configs).
    if shared_t3 and t >= 2:
        errors = list(iter_errors())
        zeats = sorted({ze for _, ze in errors})
        xeats = sorted({xe for xe, _ in errors})

        def side_det_aux(patterns, rowmap, tag):
            aux_of = {}
            for pat in patterns:
                if not any(pat):
                    continue  # empty pattern handled as a unit clause later
                tvar = A((tag, "det", pat))
                aux_of[pat] = tvar
                parities = []
                for g in range(G):
                    row_lits = [rowmap[(g, q)] for q in range(n) if pat[q]]
                    if not row_lits:
                        continue
                    if len(row_lits) == 1:
                        parities.append(row_lits[0])
                        emit([-row_lits[0], tvar])
                    else:
                        ch, out = xor_chain(row_lits, (tag, "par", pat, g))
                        for _c in ch:
                            emit(_c)
                        parities.append(out)
                        emit([-out, tvar])
                if parities:
                    # t -> OR(parities): blocks spurious satisfaction
                    emit([-tvar] + parities)
                else:
                    emit([-tvar])  # no row can detect this pattern
            return aux_of

        xdet = side_det_aux(zeats, xr, "x")
        zdet = side_det_aux(xeats, zr, "z")
        for xe, ze in errors:
            lits = []
            if not any(ze):
                lits.append(zdet[xe])
            elif not any(xe):
                lits.append(xdet[ze])
            else:
                lits.extend([xdet[ze], zdet[xe]])
            emit(list(lits))
    else:
        for e_idx, (xe, ze) in enumerate(iter_errors()):
            lits = []
            for g in range(G):
                row_lits = [xr[(g, q)] for q in range(n) if ze[q]]
                if row_lits:
                    if len(row_lits) == 1:
                        lits.append(row_lits[0])
                    else:
                        ch, out = xor_chain(row_lits, ("dx", g, e_idx))
                        for _c in ch:
                            emit(_c)
                        lits.append(out)
            for g in range(G):
                row_lits = [zr[(g, q)] for q in range(n) if xe[q]]
                if row_lits:
                    if len(row_lits) == 1:
                        lits.append(row_lits[0])
                    else:
                        ch, out = xor_chain(row_lits, ("dz", g, e_idx))
                        for _c in ch:
                            emit(_c)
                        lits.append(out)
            if lits:
                emit(list(lits))

    # --- weight bound per row (Sinz sequential counter over active qubits)
    def seq_counter(ls, bound, tag):
        m = len(ls)
        if bound >= m:
            return []
        s = [[A(("s", tag, i, j)) for j in range(bound)] for i in range(m)]
        c = []
        c.append([-ls[0], s[0][0]])
        c.append([-s[0][0], ls[0]])
        for j in range(1, bound):
            c.append([-s[0][j]])
        for i in range(1, m):
            c.append([s[i][0], -ls[i]])
            c.append([s[i][0], -s[i - 1][0]])
            c.append([-s[i][0], ls[i], s[i - 1][0]])
            for j in range(1, bound):
                c.append([s[i][j], -ls[i], -s[i - 1][j - 1]])
                c.append([s[i][j], -s[i - 1][j]])
                c.append([-s[i][j], s[i - 1][j], ls[i]])
                c.append([-s[i][j], s[i - 1][j], s[i - 1][j - 1]])
            c.append([-ls[i], -s[i - 1][bound - 1]])
        return c

    for side, varmap in ((0, xr), (1, zr)):
        for g in range(G):
            act = []
            for q in range(n):
                a = A(("act", side, g, q))
                v = varmap[(g, q)]
                emit([-a, v])
                emit([-v, a])
                act.append(a)
            for _c in seq_counter(act, max_weight, ("w", side, g)):
                emit(_c)

    own_vars = set(aux.values())
    # distinct-code blocking: freeze only the check-incidence pattern, so
    # anchor/counter re-derivations of the SAME code stay reachable and
    # genuinely different codes stay enumerable (blocking every aux var
    # made the solver go UNSAT after the first solution).
    incidence_vars = {v for (_, _), v in xr.items()} | {v for (_, _), v in zr.items()}
    return {
        "sites": sites,
        "n": n,
        "G": G,
        "xr": xr,
        "zr": zr,
        "ax": ax,
        "az": az,
        "clauses": clauses,
        "incidence_vars": incidence_vars,
        "iter_errors": iter_errors,
        "n_vars": len(aux),  # highest var allocated; static symmetry aux starts above this
    }


# --- D4 orbit machinery for symmetry-aware enumeration ----------------------

def _d4_maps(side):
    """The 8 grid isometries of the square, each (x, y) -> (x', y')."""
    S = side - 1
    return [
        lambda x, y: (x, y),
        lambda x, y: (S - x, y),
        lambda x, y: (x, S - y),
        lambda x, y: (S - x, S - y),
        lambda x, y: (y, x),
        lambda x, y: (S - y, x),
        lambda x, y: (y, S - x),
        lambda x, y: (S - y, S - x),
    ]


def _site_permutations(side):
    """Qubit index permutations induced by the 8 grid isometries.

    sites are ordered [(x, y) for y in range(side) for x in range(side)], so
    index = y * side + x. perm[q] = index the qubit at q maps TO.
    """
    perms = []
    for f in _d4_maps(side):
        p = [0] * (side * side)
        for y in range(side):
            for x in range(side):
                x2, y2 = f(x, y)
                p[y * side + x] = y2 * side + x2
        perms.append(tuple(p))
    return perms


def _canon_key(M):
    """Row-order canonical form of an incidence matrix (tuple of row bytes)."""
    return tuple(sorted(bytes(int(b) for b in row) for row in M))


def orbit_canonical_key(side, G, HX, HZ, perms=None, xz_swap=True):
    """Minimum canonical key over the D4 orbit and (optionally) the X<->Z
    interchange of the stacked [HX; HZ] incidence matrix."""
    if perms is None:
        perms = _site_permutations(side)
    M = np.vstack([HX, HZ])
    best = None
    for p in perms:
        Mp = M[:, list(p)]
        for swapped in ((False, True) if xz_swap else (False,)):
            A = np.vstack([Mp[G:], Mp[:G]]) if swapped else Mp
            k = _canon_key(A)
            if best is None or k < best:
                best = k
    return best


def orbit_selftest(side=6, G=4, seed=0):
    """Invariance sanity check: the canonical key is constant over the whole
    transform group applied to random matrices. Raises on failure."""
    rng = np.random.default_rng(seed)
    n = side * side
    perms = _site_permutations(side)
    for _ in range(20):
        HX = rng.integers(0, 2, size=(G, n)).astype(np.int8)
        HZ = rng.integers(0, 2, size=(G, n)).astype(np.int8)
        ref = orbit_canonical_key(side, G, HX, HZ, perms=perms)
        M = np.vstack([HX, HZ])
        for p in perms:
            Mp = M[:, list(p)]
            A = np.vstack([Mp[G:], Mp[:G]])
            if orbit_canonical_key(side, G, Mp[:G], Mp[G:], perms=perms) != ref:
                raise AssertionError("orbit key not invariant under D4+XZ")
    return True


def _full_symmetry_group(side):
    """All 16 transforms (site perm, xz_swap) of D4 x C2, identity first."""
    out = []
    for p in _site_permutations(side):
        for xz in (False, True):
            out.append((p, xz))
    return out


def _sym_image(side, G, n, p, xz, side_idx, g, q):
    """Image of incidence variable (side_idx, g, q) under (site perm p, xz swap)."""
    return (1 - side_idx if xz else side_idx, g, p[q])


def add_static_symmetry_clauses(cnf, emit):
    """Static (in-CNF) lex-leader symmetry breaking over the incidence vars.

    For every non-identity transform sigma in D4 x C2 (site isometries plus
    the X<->Z interchange), add lex-leader constraints lex(v, sigma(v)) over
    the canonical variable ordering (side, g, q). Sound because
    build_local_cnf is invariant under the group: each orbit keeps exactly
    one representative, so enumeration still yields every distinct code —
    just once. ``emit(c)`` receives each clause (list append for in-memory
    builds, solver.add_clause for streamed builds).

    Returns the number of auxiliary variables introduced.
    """
    side = int(round(max(s[0] for s in cnf["sites"]))) + 1
    n = cnf["n"]
    G = cnf["G"]
    rowmaps = (cnf["xr"], cnf["zr"])

    # aux vars must number ABOVE everything build_local_cnf allocated
    # (colliding with incidence vars silently corrupts the CNF — found by
    # the 2x2 brute-force test, 2026-09-08)
    aux_count = cnf.get("n_vars") or max(
        max(m.values()) for m in (cnf["xr"], cnf["zr"], cnf["ax"], cnf["az"])
    )
    # canonical variable order and the per-transform image list
    order = [
        (s, g, q) for s in range(2) for g in range(G) for q in range(n)
    ]
    var_of = {(s, g, q): rowmaps[s][(g, q)] for s, g, q in order}

    for p, xz in _full_symmetry_group(side):
        if p == tuple(range(n)) and not xz:
            continue  # identity
        # vector v in canonical order; w = sigma(v)
        v = [var_of[key] for key in order]
        w = []
        for s, g, q in order:
            s2, g2, q2 = _sym_image(side, G, n, p, xz, s, g, q)
            w.append(var_of[(s2, g2, q2)])
        # e_i <-> (prefix of length i+1 equal); e_{i} chain with skip on
        # positions where v[i] is w[i] (fixed by the transform).
        e = None  # None = prefix equal so far (length 0)
        for vi, wi in zip(v, w):
            if vi == wi:
                continue  # trivially equal position, chain unaffected
            if e is None:
                # first differing-capable position: prefix of length i equal
                # is vacuously true, so the lex constraint binds directly
                emit([-vi, wi])  # ¬v_i ∨ w_i  (v_i ≤ w_i)
            else:
                emit([-e, -vi, wi])  # e_{i-1} -> (¬v_i ∨ w_i)
            # chain: e_i <-> e_{i-1} & (v_i <-> w_i)
            ei = aux_count + 1
            aux_count += 1
            if e is None:
                emit([-ei, vi, -wi])
                emit([-ei, -vi, wi])
                emit([ei, vi, wi])
                emit([ei, -vi, -wi])
            else:
                emit([-ei, e])
                emit([-ei, vi, -wi])
                emit([-ei, -vi, wi])
                emit([ei, -e, vi, wi])
                emit([-e, -vi, -wi, ei])
            e = ei
    return aux_count


def enumerate_local_sat_codes(
    n_side,
    n_generators,
    max_weight,
    t,
    radius,
    *,
    seed=0,
    max_codes=None,
    solver="minisat",
    layers=1,
    conf_budget=None,
    time_budget=None,
    interrupt_handle=None,
    stream=False,
    symmetry="none",
    max_rounds=None,
    shared_t3=False,
):
    """Yield ``(spec, HX, HZ, coordinates, anchors_x, anchors_z)`` for distinct
    CSS codes whose checks are all local under the returned layout.

    Parameters
    ----------
    n_side       : qubits live on an n_side x n_side grid (n = n_side**2)
    n_generators : rows sought in EACH of HX and HZ
    max_weight   : per-row weight bound (active qubits <= max_weight)
    t            : code must detect every Pauli error of weight <= t
    radius       : max distance from a check's anchor to a qubit it acts on
                   (this bounds the interaction radius by construction)
    solver       : backend key (minisat | cadical | cryptominisat | kissat |
                   minicard)
    layers       : recorded in spec for the locality block (rho in g)
    conf_budget  : per-solve conflict budget (None = unlimited). Budgeted
                   solves use solve_limited, so a hard instance cannot eat
                   the whole run (SIGALRM cannot interrupt Minisat22 C code).
                   Note: kissat404 in pysat 1.9.dev13 does not forward
                   conflict limits, so pair kissat with time_budget instead.
    time_budget  : per-solve wall-clock budget in seconds, honored by the
                   backends that expose time_budget (cryptominisat, kissat,
                   minicard). CryptoMinisat requires one, so it defaults to
                   3600 s there when only conf_budget is given; minisat and
                   cadical ignore it (use conf_budget for those).
    interrupt_handle : if a list is passed, the solver object is appended to
                   it so a driver thread can call .interrupt() on timeout.
    stream       : build the CNF directly into the solver via add_clause
                    instead of materializing the Python clause list (needed
                    for large t=3 formulas).
    symmetry     : "none" | "orbit" | "lex". "orbit" = dynamic filter (a model
                    is only yielded when it IS its D4+X/Z orbit canonical
                    representative; non-canonical models are blocked — 22x
                    slower on 2026-09-05, do not use). "lex" = static in-CNF
                    lex-leader constraints added BEFORE solving (untested
                    until 2026-09-08; see sym_bench). Each orbit yields
                    exactly one representative under "lex"; the dynamic
                    canon check is unnecessary and skipped for it.
    max_rounds   : hard cap on solve/block iterations. Without it a config
                   that yields mostly-rejected models can loop for hours:
                   each round is bounded by conf/time budgets, but the
                   ROUND count is what was unbounded (the 2026-09-05
                   overnight overrun: 500+ rounds on t3_5x5 with minisat).

    Each spec is rebuildable: {"family": "local-sat-css", ...}.
    """
    if not _HAS_PYSAT:
        raise ImportError("local_sat needs python-sat")

    solver_map = {
        "minisat": Minisat22,
        "cadical": Cadical153,
        "cryptominisat": CryptoMinisat,
        "kissat": Kissat404,
        "minicard": Minicard,
    }
    if solver not in solver_map:
        raise ValueError(f"unknown solver {solver!r}; choose from {sorted(solver_map)}")
    if solver == "kissat" and max_codes != 1:
        # pysat's kissat wrapper aborts the whole process (fatal C-level
        # error, not an exception) if add_clause is called after a solve,
        # which the enumeration's blocking clauses always do. Verified
        # overnight 2026-09-05: first SAT model kills the run.
        raise ValueError("kissat cannot enumerate: no incremental add_clause "
                         "(process aborts, not raises); use cadical/cryptominisat")
    if symmetry not in ("none", "orbit", "lex"):
        raise ValueError(f"unknown symmetry {symmetry!r}; choose none|orbit|lex")

    perms = _site_permutations(n_side) if symmetry == "orbit" else None

    if stream:
        solver_obj = solver_map[solver](bootstrap_with=[])
        cnf = build_local_cnf(
            n_side, n_generators, max_weight, t, radius, sink=solver_obj,
            shared_t3=shared_t3,
        )
        if symmetry == "lex":
            add_static_symmetry_clauses(cnf, solver_obj.add_clause)
    else:
        cnf = build_local_cnf(n_side, n_generators, max_weight, t, radius,
                              shared_t3=shared_t3)
        if symmetry == "lex":
            add_static_symmetry_clauses(cnf, cnf["clauses"].append)
        solver_obj = solver_map[solver](bootstrap_with=cnf["clauses"])
    sites = cnf["sites"]
    n = cnf["n"]
    G = cnf["G"]
    xr = cnf["xr"]
    zr = cnf["zr"]
    ax = cnf["ax"]
    az = cnf["az"]
    incidence_vars = cnf["incidence_vars"]
    iter_errors = cnf["iter_errors"]
    if interrupt_handle is not None:
        interrupt_handle.append(solver_obj)
    if solver == "cryptominisat":
        # pysat's cryptosat.solve() requires BOTH limits set (None is an error)
        if time_budget is None:
            time_budget = 3600.0
        if conf_budget is None:
            conf_budget = 10**12
    limited = conf_budget is not None or time_budget is not None
    try:
        count = 0
        rounds = 0
        while max_codes is None or count < max_codes:
            if max_rounds is not None and rounds >= max_rounds:
                break
            rounds += 1
            if limited:
                if conf_budget is not None:
                    solver_obj.conf_budget(conf_budget)
                if time_budget is not None and hasattr(solver_obj, "time_budget"):
                    solver_obj.time_budget(time_budget)
            res = solver_obj.solve_limited(expect_interrupt=limited)
            if limited:
                try:
                    solver_obj.clear_interrupt()
                except Exception:
                    pass
            if not res:  # UNSAT or budget/interrupt exhausted
                break
            model = {abs(m) for m in solver_obj.get_model() if m > 0}
            HX = np.zeros((G, n), dtype=np.int8)
            HZ = np.zeros((G, n), dtype=np.int8)
            anchors_x = anchors_z = None
            for g in range(G):
                for q in range(n):
                    HX[g, q] = 1 if xr[(g, q)] in model else 0
                    HZ[g, q] = 1 if zr[(g, q)] in model else 0
            anchors_x = [
                next(i for i in range(n) if ax[(g, i)] in model) for g in range(G)
            ]
            anchors_z = [
                next(i for i in range(n) if az[(g, i)] in model) for g in range(G)
            ]
            block = [-v for v in incidence_vars if v in model]

            if symmetry == "orbit":
                # yield only the canonical representative of each orbit
                if _canon_key(np.vstack([HX, HZ])) != orbit_canonical_key(
                    n_side, G, HX, HZ, perms=perms
                ):
                    solver_obj.add_clause(block)
                    continue

            if (HX.sum(axis=1) == 0).any() or (HZ.sum(axis=1) == 0).any():
                solver_obj.add_clause(block)
                continue

            ok = True
            for xe, ze in iter_errors():
                xev = np.array(xe, dtype=np.int8)
                zev = np.array(ze, dtype=np.int8)
                if not ((HX @ zev) % 2).any() and not ((HZ @ xev) % 2).any():
                    ok = False
                    break
            if not ok:
                solver_obj.add_clause(block)
                continue

            spec = {
                "family": "local-sat-css",
                "n_side": n_side,
                "n_generators": G,
                "max_weight": max_weight,
                "t": t,
                "radius": radius,
                "layers": layers,
                "seed": seed,
                "index": count,
            }
            yield (spec, HX, HZ, list(sites), anchors_x, anchors_z)
            count += 1
            solver_obj.add_clause(block)
    finally:
        solver_obj.delete()


def geometric_efficiency(n, k, d, interaction_radius, layers):
    """g = 4 k d^2 / (n rho^2 r^4); surface code (r=sqrt2, rho=1) scores 1."""
    if n == 0 or interaction_radius <= 0:
        return 0.0
    return 4.0 * k * d * d / (n * (layers**2) * (interaction_radius**4))


def calibrate_local_cnf(n_side, n_generators, max_weight, t, radius,
                        shared_t3=True):
    """Build the CNF (streamed, no solver) and report its budget: aux vars,
    clause count, and build time. Reject configs whose CNF would blow up
    memory before spending solver time."""
    import time as _time
    t0 = _time.time()
    counter = {"clauses": 0}

    class _Sink:
        def add_clause(self, c):
            counter["clauses"] += 1

    cnf = build_local_cnf(n_side, n_generators, max_weight, t, radius,
                          sink=_Sink(), shared_t3=shared_t3)
    dt = _time.time() - t0
    print(f"calibrate n_side={n_side} (n={cnf['n']}) G={n_generators} "
          f"w={max_weight} t={t}: {cnf['n_vars']:,} aux, "
          f"{counter['clauses']:,} clauses, {dt:.1f}s build")
    return cnf["n_vars"], counter["clauses"]


def search_local_sat(
    n_side,
    n_generators,
    max_weight,
    t,
    radius,
    *,
    count=100,
    seed=0,
    min_k=2,
    min_d=3,
    trials=400,
    keep=25,
    verbose=True,
    layers=1,
):
    """Generate up to ``count`` locality-constrained SAT codes, screen them
    with the kit's funnel, and rank by geometric efficiency g."""
    from search import screen

    gen = enumerate_local_sat_codes(
        n_side,
        n_generators,
        max_weight,
        t,
        radius,
        seed=seed,
        max_codes=count,
        layers=layers,
    )
    recs = screen(gen, min_k=min_k, min_d=min_d, trials=trials)
    if verbose:
        print(
            f"local-SAT-CSS sweep {n_side}x{n_side} gens={n_generators} "
            f"w<={max_weight} t={t} r={radius}: {len(recs)} survivors "
            f"(k>={min_k}, d_ub>={min_d})"
        )
    return recs[:keep]


def lex_symmetry_selftest(side=4, G=5, t=1, radius=1.5, weight=4):
    """Soundness check for symmetry="lex": over a small cell, the lex
    enumeration must yield exactly one representative per D4+XZ orbit of the
    unconstrained enumeration — same orbit-canonical-key set, no duplicates.

    Default cell 4x4 G=5 w=4 t=1 yields ~40 models in 39 orbits (2026-09-08).
    """
    def orbit_keys(sym):
        keys = []
        for spec, HX, HZ, *_ in enumerate_local_sat_codes(
            side, G, weight, t, radius, max_codes=60, solver="cadical",
            symmetry=sym, shared_t3=True, conf_budget=100_000,
            time_budget=20.0, max_rounds=300,
        ):
            keys.append(orbit_canonical_key(side, G, HX, HZ))
        return keys

    keys_none = orbit_keys("none")
    keys_lex = orbit_keys("lex")
    # the unconstrained run may legitimately visit two models of the same
    # orbit; the lex run must yield exactly one representative per DISTINCT
    # orbit — same key set, and no lex duplicates.
    assert len(set(keys_lex)) == len(keys_lex), "lex run yielded a duplicate orbit"
    assert set(keys_lex) == set(keys_none), (
        f"lex orbit set mismatch: {len(keys_lex)} vs {len(set(keys_none))}"
    )
    return {"none_orbits": len(set(keys_none)), "lex_yields": len(keys_lex)}


if __name__ == "__main__":
    print("selftest:", lex_symmetry_selftest())
    search_local_sat(
        n_side=4, n_generators=4, max_weight=3, t=1, radius=1.5, count=20, seed=11
    )
