"""Stage 1: circuit-level syndrome extraction with parametrized schedules.

Every check is assigned to a 2x2 cell; each of its qubits occupies a corner
role (SW, SE, NW, NE). A schedule is a pair of corner->layer bijections
(sigma_X, sigma_Z). Per round: reset ancillas, 4 CX layers (a check acts in
the layers of its surviving corners), measure ancillas. Truncated checks
inherit the full-cell layer assignment, so conflict-freeness is inherited
too -- but we verify it explicitly per instance and reject invalid pairs.

Noise: uniform depolarizing circuit noise at rate p (DEPOLARIZE2 after CX,
DEPOLARIZE1 on idle data, X_ERROR on reset/measurement).

Circuit distance of a candidate schedule is certified with stim's
shortest_graphlike_error (exact for graphlike DEMs; ours are, being
boundary-edge codes with weight<=2 error sensitivities after decomposition).
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np
import stim
from itertools import permutations

CORNERS = ('SW', 'SE', 'NW', 'NE')
OFF = {'SW': (0, 0), 'SE': (1, 0), 'NW': (0, 1), 'NE': (1, 1)}


def infer_cells(code):
    """Assign each check a cell (cx,cy) and corner roles for its qubits.

    Preference: the cell in which the check's absent corners are removed
    qubits or off-grid sites (i.e. the truncation's parent cell).
    """
    qubits = code['qubits']
    qidx = code['qidx']
    W = max(q[0] for q in qubits) + 1
    H = max(q[1] for q in qubits) + 1
    occupied = set(qubits)
    out = []  # (type, check_index_in_type, cell, {corner: data_qubit_index})
    for typ, checks in (('X', code['X_checks']), ('Z', code['Z_checks'])):
        for ci, ch in enumerate(checks):
            coords = [qubits[q] for q in ch]
            xs = [c[0] for c in coords]
            ys = [c[1] for c in coords]
            cands = []
            for cx in range(min(xs) - 1, min(xs) + 1):
                for cy in range(min(ys) - 1, min(ys) + 1):
                    roles = {}
                    ok = True
                    for q, co in zip(ch, coords):
                        d = (co[0] - cx, co[1] - cy)
                        role = next((r for r, o in OFF.items() if o == d), None)
                        if role is None:
                            ok = False
                            break
                        roles[role] = q
                    if not ok or len(roles) != len(ch):
                        continue
                    # score: absent corners should be non-existent qubits
                    absent = [r for r in CORNERS if r not in roles]
                    score = sum(1 for r in absent
                                if (cx + OFF[r][0], cy + OFF[r][1])
                                not in occupied)
                    cands.append((score, cx, cy, roles))
            if not cands:
                raise ValueError(f'no cell for check {typ}{ci}: {coords}')
            cands.sort(reverse=True)
            score, cx, cy, roles = cands[0]
            out.append((typ, ci, (cx, cy), roles))
    return out


def schedule_valid(code, cells, sx, sz):
    """Each data qubit and ancilla used at most once per layer."""
    use = {}
    for typ, ci, cell, roles in cells:
        s = sx if typ == 'X' else sz
        for role, q in roles.items():
            key = (s[role], q)
            if key in use:
                return False
            use[key] = True
    return True


def extraction_circuit(code, sx, sz, p, rounds, basis='Z', sched=None):
    """Full circuit-level memory experiment. Schedule: global (sx, sz), or
    per-check overrides via sched[(typ, ci)] = corner->layer dict."""
    cells = code['_cells']
    n = code['HX'].shape[1]
    nX = len(code['X_checks'])
    nZ = len(code['Z_checks'])
    aX = {ci: n + i for i, ci in
          enumerate(ci for t, ci, _, _ in cells if t == 'X')}
    aZ = {ci: n + nX + i for i, ci in
          enumerate(ci for t, ci, _, _ in cells if t == 'Z')}
    data = list(range(n))
    anc = list(range(n, n + nX + nZ))

    c = stim.Circuit()
    c.append('R' if basis == 'Z' else 'RX', data)

    def one_round(noisy):
        c.append('RX', [aX[ci] for t, ci, _, _ in cells if t == 'X'])
        c.append('R', [aZ[ci] for t, ci, _, _ in cells if t == 'Z'])
        if noisy:
            c.append('X_ERROR', anc, p)
        for layer in range(4):
            pairs = []
            busy = set()
            for typ, ci, cell, roles in cells:
                s = sched.get((typ, ci)) if sched else None
                if s is None:
                    s = sx if typ == 'X' else sz
                for role, q in roles.items():
                    if s[role] == layer:
                        if typ == 'X':
                            pairs += [aX[ci], q]
                        else:
                            pairs += [q, aZ[ci]]
                        busy.add(q)
            if pairs:
                c.append('CX', pairs)
                if noisy:
                    c.append('DEPOLARIZE2', pairs, p)
            idle = [q for q in data if q not in busy]
            if noisy and idle:
                c.append('DEPOLARIZE1', idle, p)
        if noisy:
            c.append('X_ERROR', anc, p)
        c.append('MX', [aX[ci] for t, ci, _, _ in cells if t == 'X'])
        c.append('M', [aZ[ci] for t, ci, _, _ in cells if t == 'Z'])

    mtot = nX + nZ
    # round 1: only the deterministic-type detectors
    one_round(True)
    det_type = 'Z' if basis == 'Z' else 'X'
    for i in range(mtot):
        is_z = i >= nX
        if (det_type == 'Z') == is_z:
            c.append('DETECTOR', [stim.target_rec(-mtot + i)])
    for _ in range(rounds - 1):
        one_round(True)
        for i in range(mtot):
            c.append('DETECTOR', [stim.target_rec(-mtot + i),
                                  stim.target_rec(-2 * mtot + i)])
    # final data measurement
    c.append('M' if basis == 'Z' else 'MX', data)
    H_det = code['HZ'] if basis == 'Z' else code['HX']
    checks = code['Z_checks'] if basis == 'Z' else code['X_checks']
    off0 = nX if basis == 'Z' else 0
    for i, ch in enumerate(checks):
        recs = [stim.target_rec(-n - mtot + off0 + i)]
        recs += [stim.target_rec(-n + q) for q in ch]
        c.append('DETECTOR', recs)
    for li, L in enumerate(code['_logicals_' + basis]):
        recs = [stim.target_rec(-n + int(q)) for q in np.nonzero(L)[0]]
        c.append('OBSERVABLE_INCLUDE', recs, li)
    return c


def prepare(code):
    from packing import fast_logical_basis
    code['_cells'] = infer_cells(code)
    code['_logicals_Z'] = fast_logical_basis(code['HX'], code['HZ'])
    code['_logicals_X'] = fast_logical_basis(code['HZ'], code['HX'])
    return code


def circuit_distance(code, sx, sz, rounds=3, p=1e-3, sched=None):
    """Certified graphlike circuit distance, min over both bases.

    Returns None if the schedule is invalid (non-deterministic detectors:
    the CX interleaving fails to measure the stabilizer group faithfully).
    """
    dmin = None
    for basis in ('Z', 'X'):
        circ = extraction_circuit(code, sx, sz, p, rounds, basis, sched)
        try:
            err = circ.shortest_graphlike_error(
                canonicalize_circuit_errors=True)
        except ValueError:
            return None
        d = len(err)
        dmin = d if dmin is None else min(dmin, d)
    return dmin


def all_valid_schedule_pairs():
    """All (sigma_X, sigma_Z) bijection pairs satisfying the rotated-lattice
    disjointness constraints (necessary for conflict-freeness in the bulk)."""
    perms = [dict(zip(CORNERS, p)) for p in permutations(range(4))]
    out = []
    for sx in perms:
        for sz in perms:
            if {sx['NE'], sx['SW']} & {sz['NW'], sz['SE']}:
                continue
            if {sx['NW'], sx['SE']} & {sz['NE'], sz['SW']}:
                continue
            out.append((sx, sz))
    return out
