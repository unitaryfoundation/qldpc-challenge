"""
Memory-circuit generation for `qldpc submit` (issue #1848): the circuit tier
(RFC 0001, issue #505) as a default of every submission rather than a
separate task.

Given H_X and H_Z the generator picks a syndrome-extraction schedule the code's
structure supports, builds the memory_x and memory_z experiments under the
canonical noise recipe of verify/circuit_tools.py, searches each detector
error model for a witness with the board's own RIS searcher, and returns the
circuit block plus the .stim/.dem artifacts. Nothing here is trusted: the CLI
runs verify/circuit_verify.py on the result before writing it, exactly as CI
will, and the refutation gate searches the committed DEMs again.

Schedules, tried in this order:

  two-block interleaved   H_X = [A | B], H_Z = [B^T | A^T] with A and B sums
                          of pairwise commuting permutation matrices (bivariate
                          and generalized bicycle codes, and two-block group
                          algebra codes whose left and right terms commute).
                          The terms are recovered from H alone by a commuting
                          permutation decomposition. Each round is one joint
                          ancilla reset layer, w + 1 CX layers in which every
                          X term and every Z term occupies one slot (the
                          Bravyi et al. arXiv:2308.07915 Table 5 shape), and
                          one joint measurement layer. A slot assignment is
                          admitted when the X and Z terms sharing a slot act on
                          opposite halves of the data and when, for every term
                          pair (A_a, B_b), the X-before-Z order agrees on the
                          two data qubits a check pair shares through it; that
                          overlap-parity criterion makes every detector
                          deterministic.
  layout zigzag           weight <= 4 plaquette checks with a 2D layout (the
                          rotated surface patch): the plaquette coupling
                          orders of research/circuit_seed.py, interleaved when
                          a pattern pair is conflict free, sequential otherwise.
  generic sequential      any CSS code: X checks then Z checks each round with
                          joint reset and measurement layers, the CX layers a
                          proper edge coloring of each Tanner graph
                          (circuit_tools.edge_coloring), which is commutation
                          safe because the two blocks never overlap in time.

Within a family several candidates (slot assignments, pattern pairs, coloring
seeds) are screened at two extraction rounds, where fewer rounds can only
overestimate d_circ, and the first that shows nothing below d is kept; the
final circuits at rounds = d are then searched with twice the trial budget of
the CI gate. The recorded value is whatever the search finds; when it finds
nothing at or below d the code's own distance witness, applied as final
readout flips, is the weight-d fallback that keeps the claim within the
penalty-only clamp.
"""

import os
import sys

import numpy as np
import stim

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "verify"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import circuit_tools as ct  # noqa: E402
import gf2  # noqa: E402
from circuit_verify import MAX_DEM_MECHANISMS  # noqa: E402
from gate_changed import _circuit_budget  # noqa: E402

SCREEN_ROUNDS = 2
SCREEN_TRIALS = 40
SCREEN_SECONDS = 10.0
DECOMPOSITION_NODES = 4000
SLOT_ATTEMPTS = 20000
SIDE_FILES = {"X": "memory_x", "Z": "memory_z"}


class CircuitUnavailable(Exception):
    """The generator cannot produce a verifiable circuit tier for this code;
    the message says why. The code-tier submission is unaffected."""


# ------------------------------------------------------------------ builder

def build_memory(HX, HZ, rounds, basis, layers):
    """Noiseless memory-experiment skeleton with joint ancilla layers.

    Data qubits are 0..n-1, X-check ancillas n..n+rX-1, Z-check ancillas after
    those (the circuit tier's indexing). Every round resets all ancillas in
    one layer (RX for X checks, R for Z checks), runs `layers` (each a list of
    ("X", check, qubit) for CX ancilla -> data or ("Z", check, qubit) for CX
    data -> ancilla, every entry in its own TICK segment), and measures all
    ancillas in one layer. Detectors and observables follow
    circuit_tools.build_css_memory: absolute anchors on the protected side at
    round 0, round-to-round comparisons, closure detectors on the transversal
    readout, and the k protected-basis logicals as observables. Feed the
    result to circuit_tools.apply_noise() for the canonical circuit.
    """
    HX = np.asarray(HX, dtype=np.int8)
    HZ = np.asarray(HZ, dtype=np.int8)
    n = HX.shape[1]
    rX, rZ = HX.shape[0], HZ.shape[0]
    ax = list(range(n, n + rX))
    az = list(range(n + rX, n + rX + rZ))
    data = list(range(n))
    prep, readout = ("R", "M") if basis == "Z" else ("RX", "MX")
    side = basis.lower()
    H_anchor = HZ if basis == "Z" else HX
    L_obs = gf2.logical_basis(HX, HZ) if basis == "Z" \
        else gf2.logical_basis(HZ, HX)

    c = stim.Circuit()
    pos = {}
    c.append(prep, data)
    for r in range(rounds):
        c.append("TICK")
        c.append("RX", ax)
        c.append("R", az)
        for layer in layers:
            if not layer:
                continue
            c.append("TICK")
            targets = []
            for kind, chk, q in layer:
                if kind == "X":
                    targets += [n + chk, q]
                else:
                    targets += [q, n + rX + chk]
            c.append("CX", targets)
        c.append("TICK")
        c.append("MX", ax)
        for i in range(rX):
            pos[("x", i, r)] = len(pos)
        c.append("M", az)
        for i in range(rZ):
            pos[("z", i, r)] = len(pos)
    c.append("TICK")
    c.append(readout, data)
    for q in range(n):
        pos[("data", q)] = len(pos)
    total = len(pos)

    def rec(key):
        return stim.target_rec(pos[key] - total)

    n_anchor = H_anchor.shape[0]
    for i in range(n_anchor):
        c.append("DETECTOR", [rec((side, i, 0))])
    for r in range(1, rounds):
        for i in range(rX):
            c.append("DETECTOR", [rec(("x", i, r)), rec(("x", i, r - 1))])
        for i in range(rZ):
            c.append("DETECTOR", [rec(("z", i, r)), rec(("z", i, r - 1))])
    for i in range(n_anchor):
        targs = [rec(("data", int(q))) for q in np.flatnonzero(H_anchor[i])]
        c.append("DETECTOR", targs + [rec((side, i, rounds - 1))])
    for j, row in enumerate(L_obs):
        c.append("OBSERVABLE_INCLUDE",
                 [rec(("data", int(q))) for q in np.flatnonzero(row)], j)
    return c


def closure_detector_base(HX, HZ, rounds, basis):
    """Index of the first closure detector in a build_memory circuit."""
    n_anchor = (HZ if basis == "Z" else HX).shape[0]
    return n_anchor + (rounds - 1) * (HX.shape[0] + HZ.shape[0])


def layers_parallel(layers):
    """True iff no layer touches a data qubit or a check ancilla twice."""
    for layer in layers:
        seen_q, seen_c = set(), set()
        for kind, chk, q in layer:
            if q in seen_q or (kind, chk) in seen_c:
                return False
            seen_q.add(q)
            seen_c.add((kind, chk))
    return True


def deterministic(skeleton):
    """stim's own validity verdict (RFC 0001 step 1)."""
    try:
        skeleton.detector_error_model()
    except Exception:
        return False
    return skeleton.num_detectors > 0


# --------------------------------------------------- two-block decomposition

def two_block_split(HX, HZ):
    """(A, B, zrow) when H_X = [A | B] and the rows of H_Z are exactly the rows
    of [B^T | A^T] in some order, with zrow[i] the H_Z row holding row i of
    [B^T | A^T]; None otherwise. Only the natural qubit order (left half,
    right half) is recognized."""
    HX = np.asarray(HX, dtype=np.int8)
    HZ = np.asarray(HZ, dtype=np.int8)
    n = HX.shape[1]
    if n % 2 or HX.shape[0] != n // 2 or HZ.shape != HX.shape:
        return None
    m = n // 2
    A, B = HX[:, :m], HX[:, m:]
    want = np.concatenate([B.T, A.T], axis=1)
    index = {}
    for i, row in enumerate(HZ):
        index.setdefault(row.tobytes(), []).append(i)
    zrow = []
    for row in want:
        cands = index.get(row.tobytes())
        if not cands:
            return None
        zrow.append(cands.pop())
    return A, B, zrow


def commuting_decomposition(A, B, abelian=True, max_nodes=DECOMPOSITION_NODES):
    """Permutation matrices A_0..A_{wA-1} and B_0..B_{wB-1}, as arrays with
    P[v] = the column of row v's one, summing to A and B with every A_a
    commuting with every B_b (and, if `abelian`, with every other A_a' and B_b'
    likewise). Returns (PA, PB) or None.

    The labeling is a constraint search on the two-colored digraph of A and B:
    the arcs out of vertex 0 are named arbitrarily, and the commutation
    squares P_t(P_s(v)) = P_s(P_t(v)) plus the matching constraints (each
    label leaves and enters every vertex once) propagate the names. For a
    group-algebra code the translations are the unique solution up to the
    naming at vertex 0, and propagation alone usually finds it; `max_nodes`
    bounds the branching before the caller falls back.
    """
    A = np.asarray(A, dtype=np.int8)
    B = np.asarray(B, dtype=np.int8)
    m = A.shape[0]
    nbr = {"A": [tuple(int(x) for x in np.flatnonzero(A[v])) for v in range(m)],
           "B": [tuple(int(x) for x in np.flatnonzero(B[v])) for v in range(m)]}
    wA, wB = len(nbr["A"][0]), len(nbr["B"][0])
    if wA == 0 or wB == 0:
        return None
    for color, M, w in (("A", A, wA), ("B", B, wB)):
        if any(len(r) != w for r in nbr[color]) or \
                not (M.sum(axis=0) == w).all():
            return None
    labels = [("A", a) for a in range(wA)] + [("B", b) for b in range(wB)]
    partners = {L: [L2 for L2 in labels if L2 != L
                    and (abelian or L2[0] != L[0])] for L in labels}
    same_color = {L: [L2 for L2 in labels if L2 != L and L2[0] == L[0]]
                  for L in labels}

    def fresh():
        return ({L: [-1] * m for L in labels},
                {L: [-1] * m for L in labels},
                {(L, v): set(nbr[L[0]][v]) for L in labels for v in range(m)})

    def propagate(state, queue):
        P, inv, dom = state
        while queue:
            L, v, x = queue.pop()
            if P[L][v] == x:
                continue
            if P[L][v] != -1 or x not in dom[(L, v)] or inv[L][x] != -1:
                return False
            P[L][v] = x
            inv[L][x] = v
            dom[(L, v)] = {x}
            for L2 in same_color[L]:
                d2 = dom[(L2, v)]
                if x in d2:
                    d2.discard(x)
                    if not d2:
                        return False
                    if len(d2) == 1 and P[L2][v] == -1:
                        queue.append((L2, v, next(iter(d2))))
            for v2 in range(m):
                if v2 == v:
                    continue
                d2 = dom[(L, v2)]
                if x in d2:
                    d2.discard(x)
                    if not d2:
                        return False
                    if len(d2) == 1 and P[L][v2] == -1:
                        queue.append((L, v2, next(iter(d2))))
            for L2 in partners[L]:
                # square at base v: P_L2(P_L(v)) = P_L(P_L2(v))
                y, z = P[L2][v], P[L2][x]
                if y != -1 and P[L][y] != -1:
                    queue.append((L2, x, P[L][y]))
                elif y != -1 and z != -1:
                    queue.append((L, y, z))
                elif y == -1 and z != -1 and inv[L][z] != -1:
                    queue.append((L2, v, inv[L][z]))
                # square at base u with P_L2(u) = v: P_L(v) = P_L2(P_L(u))
                u = inv[L2][v]
                if u != -1:
                    t = P[L][u]
                    if t != -1:
                        queue.append((L2, t, x))
                    elif inv[L2][x] != -1:
                        queue.append((L, u, inv[L2][x]))
        return True

    def copy(state):
        P, inv, dom = state
        return ({L: p[:] for L, p in P.items()},
                {L: p[:] for L, p in inv.items()},
                {k: set(s) for k, s in dom.items()})

    nodes = [0]

    def search(state):
        P, inv, dom = state
        best, best_n = None, None
        for L in labels:
            for v in range(m):
                if P[L][v] == -1:
                    size = len(dom[(L, v)])
                    if best is None or size < best_n:
                        best, best_n = (L, v), size
                        if size <= 1:
                            break
            if best_n is not None and best_n <= 1:
                break
        if best is None:
            return state
        nodes[0] += 1
        if nodes[0] > max_nodes:
            return None
        L, v = best
        for x in sorted(dom[(L, v)]):
            child = copy(state)
            if propagate(child, [(L, v, x)]) and (
                    sol := search(child)) is not None:
                return sol
        return None

    state = fresh()
    seed = [(L, 0, nbr[L[0]][0][L[1]]) for L in labels]
    if not propagate(state, seed):
        return None
    sol = search(state)
    if sol is None:
        return None
    P = sol[0]
    PA = [np.array(P[("A", a)], dtype=np.int64) for a in range(wA)]
    PB = [np.array(P[("B", b)], dtype=np.int64) for b in range(wB)]
    for perms, M in ((PA, A), (PB, B)):
        S = np.zeros_like(M)
        for p in perms:
            S[np.arange(m), p] += 1
        if not (S == M).all():
            return None
    for pa in PA:
        for pb in PB:
            if not (pb[pa] == pa[pb]).all():
                return None
    return PA, PB


def interleaved_slots(wA, wB, rng, attempts=SLOT_ATTEMPTS):
    """Distinct slot assignments (sx, sz) admitted by the interleaving rules,
    in a seeded random order. Terms are ("A", a) and ("B", b); X terms take
    slots 1..w and Z terms slots 0..w-1 (w = wA + wB), the X and Z terms of a
    shared slot have the same letter (so they act on opposite data halves),
    and for every (A_a, B_b) the X-before-Z order agrees on the two shared
    qubits: (sx[A_a] < sz[B_b]) == (sx[B_b] < sz[A_a])."""
    terms = [("A", a) for a in range(wA)] + [("B", b) for b in range(wB)]
    w = len(terms)
    seen = set()
    for _ in range(attempts):
        order = rng.permutation(w)
        sx = {terms[t]: 1 + int(s) for s, t in enumerate(order)}
        letter_at = {sx[t]: t[0] for t in terms}
        z_letter = {0: letter_at[w]}
        z_letter.update({s: letter_at[s] for s in range(1, w)})
        sz = {}
        for letter in ("A", "B"):
            slots = [s for s in range(w) if z_letter[s] == letter]
            ts = [t for t in terms if t[0] == letter]
            for k, j in enumerate(rng.permutation(len(ts))):
                sz[ts[int(j)]] = slots[k]
        ok = all((sx[a] < sz[b]) == (sx[b] < sz[a])
                 for a in terms[:wA] for b in terms[wA:])
        key = (tuple(sx[t] for t in terms), tuple(sz[t] for t in terms))
        if ok and key not in seen:
            seen.add(key)
            yield sx, sz


def interleaved_layers(PA, PB, zrow, sx, sz):
    """CX layers of a two-block interleaved round: X check i couples to left
    qubit PA[a][i] (term A_a) or right qubit m + PB[b][i] (term B_b) at
    slot sx; Z check zrow[i] couples to right qubit m + PA[a]^{-1}[i] or left
    qubit PB[b]^{-1}[i] at slot sz."""
    m = len(PA[0])
    w = len(PA) + len(PB)
    layers = [[] for _ in range(w + 1)]
    for a, p in enumerate(PA):
        inv = np.argsort(p)
        for i in range(m):
            layers[sx[("A", a)]].append(("X", i, int(p[i])))
            layers[sz[("A", a)]].append(("Z", zrow[i], m + int(inv[i])))
    for b, p in enumerate(PB):
        inv = np.argsort(p)
        for i in range(m):
            layers[sx[("B", b)]].append(("X", i, m + int(p[i])))
            layers[sz[("B", b)]].append(("Z", zrow[i], int(inv[i])))
    return layers


def slot_text(sx, sz, wA, wB):
    terms = [("A", a) for a in range(wA)] + [("B", b) for b in range(wB)]
    return (f"X-check term slots {[sx[t] for t in terms]}, Z-check term slots "
            f"{[sz[t] for t in terms]} over terms A_0..A_{wA - 1}, "
            f"B_0..B_{wB - 1}")


# ------------------------------------------------------------- candidates

def two_block_candidates(HX, HZ, rng):
    """(family, iterator of (notes, layers)) for a two-block code, or None."""
    split = two_block_split(HX, HZ)
    if split is None:
        return None
    A, B, zrow = split
    dec = commuting_decomposition(A, B, abelian=True)
    if dec is None:
        dec = commuting_decomposition(A, B, abelian=False)
    if dec is None:
        return None
    PA, PB = dec
    wA, wB = len(PA), len(PB)

    def cands():
        for sx, sz in interleaved_slots(wA, wB, rng):
            layers = interleaved_layers(PA, PB, zrow, sx, sz)
            notes = (f"Interleaved two-block extraction (Bravyi et al. "
                     f"arXiv:2308.07915 Table 5 style): joint reset and "
                     f"measurement layers, {wA + wB + 1} CX layers per round; "
                     f"{slot_text(sx, sz, wA, wB)}; terms recovered from H "
                     f"alone by a commuting permutation decomposition")
            yield notes, layers

    return f"two-block interleaved (A: {wA} terms, B: {wB} terms)", cands()


def layout_candidates(HX, HZ, coords):
    """(family, iterator) for a rotated-surface style layout (all checks of
    weight 2..4 on a 2D grid whose plaquette centers separate by parity), or
    None. Reuses research/circuit_seed.py's pattern machinery."""
    if coords is None:
        return None
    import circuit_seed as cs
    HX = np.asarray(HX, dtype=np.int8)
    HZ = np.asarray(HZ, dtype=np.int8)
    checks_x = [list(map(int, np.flatnonzero(r))) for r in HX]
    checks_z = [list(map(int, np.flatnonzero(r))) for r in HZ]
    if any(not 2 <= len(s) <= 4 for s in checks_x + checks_z):
        return None
    full = next((s for s in checks_x if len(s) == 4), None)
    if full is None:
        return None
    coords = [tuple(map(float, c)) for c in coords]
    cr = sum(coords[q][0] for q in full) / 4
    cc = sum(coords[q][1] for q in full) / 4
    parity_x = (int(np.floor(cr)) + int(np.floor(cc))) % 2
    pairs = []
    for px in sorted(cs.PATTERNS):
        for pz in sorted(cs.PATTERNS):
            try:
                lx = cs.geometric_layers(checks_x, coords, px, parity_x)
                lz = cs.geometric_layers(checks_z, coords, pz, 1 - parity_x)
            except ValueError:
                continue
            pairs.append((px, pz, lx, lz))
    if not pairs:
        return None

    def cands():
        for px, pz, lx, lz in pairs:                # interleaved first
            merged = [[("X", c, q) for c, q in a] + [("Z", c, q) for c, q in b]
                      for a, b in zip(lx, lz)]
            if layers_parallel(merged):
                yield (f"geometric zigzag schedule (X pattern '{px}', Z "
                       f"pattern '{pz}') read off the 2D layout, X and Z "
                       f"plaquettes coupled in the same 4 layers with joint "
                       f"reset and measurement layers"), merged
        for px, pz, lx, lz in pairs:
            layers = [[("X", c, q) for c, q in a] for a in lx] + \
                     [[("Z", c, q) for c, q in b] for b in lz]
            yield (f"geometric zigzag schedule (X pattern '{px}', Z pattern "
                   f"'{pz}') read off the 2D layout, X plaquettes then Z "
                   f"plaquettes each round with joint reset and measurement "
                   f"layers"), layers

    return "layout zigzag", cands()


def generic_candidates(HX, HZ, rng):
    """Sequential X-then-Z extraction with edge-colored CX layers, one
    candidate per coloring seed. Always applicable."""
    HX = np.asarray(HX, dtype=np.int8)
    HZ = np.asarray(HZ, dtype=np.int8)

    def cands():
        seed = 0
        while True:
            r = np.random.default_rng(int(rng.integers(1 << 31)))
            lx = [l for l in ct.edge_coloring(HX, r) if l]
            lz = [l for l in ct.edge_coloring(HZ, r) if l]
            layers = [[("X", c, q) for c, q in a] for a in lx] + \
                     [[("Z", c, q) for c, q in b] for b in lz]
            yield (f"Generic sequential two-block extraction: one ancilla per "
                   f"check, X checks then Z checks each round with joint "
                   f"reset and measurement layers; CX layers are a proper "
                   f"edge coloring of each Tanner graph ({len(lx)} X + "
                   f"{len(lz)} Z CX layers per round, coloring candidate "
                   f"{seed})"), layers
            seed += 1

    return "generic sequential", cands()


def candidate_schedules(HX, HZ, coords, seed):
    """The first applicable family's (label, candidate iterator)."""
    rng = np.random.default_rng(seed)
    for maker in (lambda: two_block_candidates(HX, HZ, rng),
                  lambda: layout_candidates(HX, HZ, coords)):
        got = maker()
        if got is not None:
            return got
    return generic_candidates(HX, HZ, rng)


# ------------------------------------------------------------------ search

def _dem_of(HX, HZ, rounds, basis, layers):
    skel = build_memory(HX, HZ, rounds, basis, layers)
    if not deterministic(skel):
        return None, None
    noisy = ct.apply_noise(skel, HX.shape[1])
    return noisy, ct.derive_dem(noisy)


def screen(cands, HX, HZ, d, max_candidates, seed, log=lambda s: None,
           rounds=SCREEN_ROUNDS, trials=SCREEN_TRIALS, seconds=SCREEN_SECONDS):
    """Try up to `max_candidates` schedules at `rounds` extraction rounds
    (fewer rounds can only overestimate d_circ) and return
    (notes, layers, per-basis bounds) for the first whose quick RIS finds
    nothing below d in either basis, else the best seen. Non-deterministic
    schedules are skipped; None if none was deterministic."""
    best = None
    tried = 0
    for notes, layers in cands:
        if tried >= max_candidates:
            break
        tried += 1
        bounds = {}
        for basis in ("Z", "X"):
            _, dem = _dem_of(HX, HZ, rounds, basis, layers)
            if dem is None:
                bounds = None
                break
            H, L = ct.dem_matrices(dem)
            w, _ = ct.ris_dem(H, L, trials=trials, seed=seed,
                              max_seconds=seconds)
            bounds[basis] = w if w is not None else d
            if bounds[basis] < d:
                break
        if bounds is None:
            log(f"candidate {tried}: detectors not deterministic, skipped")
            continue
        score = min(bounds.values())
        log(f"candidate {tried}: " + ", ".join(
            f"{b} <= {v}" for b, v in bounds.items()) +
            (" (nothing below d found)" if score >= d else ""))
        if best is None or score > best[2]:
            best = (notes, layers, score, bounds)
        if score >= d:
            break
    if best is None:
        return None
    return best[0], best[1], best[3]


def readout_witness(dem, HX, HZ, rounds, basis, support):
    """DEM indices of the final-readout flips on `support`, a nontrivial
    logical of the opposite type (an X logical for the Z memory): undetected
    by construction and of weight |support|. None if any flip's mechanism is
    missing from the DEM or two flips share one."""
    HX = np.asarray(HX, dtype=np.int8)
    HZ = np.asarray(HZ, dtype=np.int8)
    H_anchor = HZ if basis == "Z" else HX
    L_obs = gf2.logical_basis(HX, HZ) if basis == "Z" \
        else gf2.logical_basis(HZ, HX)
    base = closure_detector_base(HX, HZ, rounds, basis)
    index = {(tuple(ds), tuple(ls)): j
             for j, (ds, ls) in enumerate(ct.dem_columns(dem))}
    wit = []
    for q in support:
        dets = tuple(base + int(i) for i in np.flatnonzero(H_anchor[:, q]))
        obs = tuple(int(j) for j in np.flatnonzero(L_obs[:, q]))
        j = index.get((dets, obs))
        if j is None:
            return None
        wit.append(j)
    wit = sorted(wit)
    if len(set(wit)) != len(wit):
        return None
    return wit


def search_basis(noisy, dem, HX, HZ, d, rounds, basis, seed, seconds,
                 fallback_support=None, log=lambda s: None):
    """Deep RIS on one memory circuit's DEM at twice the gate's trial budget;
    returns (value, witness). Falls back to the readout-flip witness of
    `fallback_support` when the search finds nothing at or below d."""
    m = dem.num_errors
    if m > MAX_DEM_MECHANISMS:
        raise CircuitUnavailable(
            f"{basis} memory has {m} error mechanisms at rounds={rounds}, "
            f"over the circuit-tier cap of {MAX_DEM_MECHANISMS}; pass "
            f"--circuits with a leaner schedule or --no-circuit")
    fast = ct._GF is not None and hasattr(ct._GF, "dem_rand_witness")
    trials, _ = _circuit_budget(m, fast)
    trials = 2 * trials
    H, L = ct.dem_matrices(dem)
    w, wit = ct.ris_dem(H, L, trials=trials, seed=seed, max_seconds=seconds)
    if w is not None and ct.witness_errors(dem, wit, w):
        w, wit = None, None
    log(f"{basis} memory: {dem.num_detectors} detectors, {m} mechanisms, "
        f"RIS budget {trials} trials or {seconds:g} s -> " +
        (f"d_circ <= {w}" if w is not None else "no witness found"))
    if (w is None or w > d) and fallback_support is not None \
            and len(fallback_support) == d:
        alt = readout_witness(dem, HX, HZ, rounds, basis, fallback_support)
        if alt is not None and not ct.witness_errors(dem, alt, d):
            log(f"{basis} memory: readout flips along the code's weight-{d} "
                f"logical witness the clamp value d_circ <= {d}")
            w, wit = d, alt
    if w is None or w > d:
        raise CircuitUnavailable(
            f"{basis} memory: the search found no undetected logical fault "
            f"set of weight <= d = {d} (lightest {w}), so no claim within "
            f"the penalty-only clamp can be recorded")
    return int(w), [int(i) for i in wit]


def finish(notes, layers, HX, HZ, d, rounds, doc_witnesses, seed, seconds,
           log=lambda s: None):
    """Build both memory circuits at full rounds, search them, and return
    (circuit block, {filename: text})."""
    block = {"d_circ": {}, "rounds": rounds, "stim_version": stim.__version__,
             "notes": notes}
    files = {}
    for basis in ("Z", "X"):
        noisy, dem = _dem_of(HX, HZ, rounds, basis, layers)
        if dem is None:
            raise CircuitUnavailable(f"{basis} memory at rounds={rounds} has "
                                     f"non-deterministic detectors")
        opp = "X" if basis == "Z" else "Z"
        value, wit = search_basis(noisy, dem, HX, HZ, d, rounds, basis, seed,
                                  seconds, doc_witnesses.get(opp), log)
        block["d_circ"][basis] = {"value": value, "confidence": "upper_bound",
                                  "witness": wit}
        stem = SIDE_FILES[basis]
        files[stem + ".stim"] = str(noisy) + "\n"
        files[stem + ".dem"] = str(dem) + "\n"
    return block, files


def generate(doc, coords=None, rounds=None, seed=0, max_candidates=6,
             seconds=180.0, log=lambda s: None):
    """The circuit tier for a verified submission document: (block, files,
    family label). `doc` carries checks, distance, and n; `coords` the layout
    if any. Raises CircuitUnavailable with the reason when no verifiable tier
    can be produced (DEM over the cap, no claim within the clamp)."""
    n, d = doc["n"], doc["distance"]["d"]
    HX = _matrix(doc["checks"]["X"], n)
    HZ = _matrix(doc["checks"]["Z"], n)
    rounds = max(int(rounds or d), d)
    family, cands = candidate_schedules(HX, HZ, coords, seed)
    log(f"schedule family: {family}")
    first_notes, first_layers = next(cands)
    _, dem = _dem_of(HX, HZ, rounds, "Z", first_layers)
    if dem is not None and dem.num_errors > MAX_DEM_MECHANISMS:
        raise CircuitUnavailable(
            f"the Z memory at rounds={rounds} has {dem.num_errors} error "
            f"mechanisms, over the circuit-tier cap of {MAX_DEM_MECHANISMS}; "
            f"pass --circuits with a leaner schedule or --no-circuit")

    def chained():
        yield first_notes, first_layers
        yield from cands

    log(f"screening up to {max_candidates} candidates at "
        f"{min(SCREEN_ROUNDS, rounds)} rounds")
    picked = screen(chained(), HX, HZ, d, max_candidates, seed, log,
                    rounds=min(SCREEN_ROUNDS, rounds))
    if picked is None:
        raise CircuitUnavailable("no candidate schedule had deterministic "
                                 "detectors")
    notes, layers, _ = picked
    notes += (f"; generated by qldpc submit (research/circuit_autogen.py, "
              f"seed {seed}), the first of up to {max_candidates} candidates "
              f"whose RIS screen at {min(SCREEN_ROUNDS, rounds)} rounds found "
              f"nothing below d; witnesses from RIS on ker(H_dem) at twice "
              f"the gate's trial budget, validated in GF(2)")
    wits = {s: doc["distance"][s]["witness"] for s in ("X", "Z")
            if s in doc["distance"]}
    log(f"deep search at rounds={rounds}")
    block, files = finish(notes, layers, HX, HZ, d, rounds, wits, seed,
                          seconds, log)
    return block, files, family


def from_files(doc, directory, rounds=None, seed=0, seconds=180.0,
               log=lambda s: None):
    """A submitter's own memory circuits: read memory_x.stim and
    memory_z.stim from `directory`, derive the DEMs with the pinned stim,
    search for witnesses, and return (block, files, label). The circuits are
    taken as they are (the verifier judges them); rounds is the declared
    value or, by default, the number of times an ancilla is measured."""
    from circuit_verify import _binding_errors
    d = doc["distance"]["d"]
    block = {"d_circ": {}, "rounds": None, "stim_version": stim.__version__,
             "notes": "submitter-provided circuits (qldpc submit --circuits)"}
    files = {}
    for basis in ("Z", "X"):
        stem = SIDE_FILES[basis]
        path = os.path.join(directory, stem + ".stim")
        if not os.path.exists(path):
            raise CircuitUnavailable(f"--circuits: {path} not found")
        text = open(path).read()
        noisy = stim.Circuit(text)
        skel = ct.strip_noise(noisy)
        if not deterministic(skel):
            raise CircuitUnavailable(f"{path}: detectors are not "
                                     f"deterministic")
        _, meta = _binding_errors(skel, basis, doc)
        measured = meta.get("rounds_measured")
        if block["rounds"] is None:
            block["rounds"] = int(rounds or measured or d)
        dem = ct.derive_dem(noisy)
        if dem.num_errors > MAX_DEM_MECHANISMS:
            raise CircuitUnavailable(
                f"{path}: {dem.num_errors} mechanisms, over the tier cap "
                f"{MAX_DEM_MECHANISMS}")
        m = dem.num_errors
        fast = ct._GF is not None and hasattr(ct._GF, "dem_rand_witness")
        trials, _ = _circuit_budget(m, fast)
        H, L = ct.dem_matrices(dem)
        w, wit = ct.ris_dem(H, L, trials=2 * trials, seed=seed,
                            max_seconds=seconds)
        log(f"{basis} memory: {m} mechanisms, RIS budget {2 * trials} trials "
            f"or {seconds:g} s -> " +
            (f"d_circ <= {w}" if w is not None else "no witness found"))
        if w is None or w > d or ct.witness_errors(dem, wit, w):
            raise CircuitUnavailable(
                f"{path}: no undetected logical fault set of weight <= d = "
                f"{d} found (lightest {w}); no claim within the clamp")
        block["d_circ"][basis] = {"value": int(w), "confidence": "upper_bound",
                                  "witness": [int(i) for i in wit]}
        files[stem + ".stim"] = text if text.endswith("\n") else text + "\n"
        files[stem + ".dem"] = str(dem) + "\n"
    return block, files, "submitter-provided"


def _matrix(supports, n):
    H = np.zeros((len(supports), n), dtype=np.int8)
    for i, s in enumerate(supports):
        H[i, list(s)] = 1
    return H
