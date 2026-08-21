"""
Circuit-tier substrate (RFC 0001, issue #505): the canonical noise recipe, DEM
matrices, the witness check, the RIS search over ker(H_dem), and the reference
memory-circuit builder.

The circuit tier records d_circ, the circuit-level distance of a submitted
syndrome-extraction memory experiment, with the same witness-backed `<=`
semantics the board already uses for d. Everything here is deliberately the
code-tier machinery transplanted: hyperedges of the detector error model are
simply columns of a parity-check matrix H_dem, so the RIS searcher, the GF(2)
witness check, and the refutation discipline all transfer unchanged.

Canonical noise recipe (RFC 0001). Noise placement is NOT a submitter degree
of freedom -- the schedule is. A submitted circuit conforms iff it equals
`apply_noise(strip_noise(circuit))` at the reference rate P_REF AND its TICK
layers are genuinely parallel:

  - DEPOLARIZE2(p) immediately after every two-qubit gate instruction;
  - X_ERROR(p) after every R, Z_ERROR(p) after every RX (reset flips);
  - measurement flip probability p on every M / MX;
  - DEPOLARIZE1(p) on every idle DATA qubit (index < n) at the end of each
    TICK-delimited layer that performs at least one operation;
  - within one TICK layer, no qubit is operated on more than once.

The last rule is what makes idle noise honest, and it is load-bearing for the
tier's penalty-only property (vprusso's #646 review): idle-data mechanisms
scale with the number of layers, so without it a submitter could delete TICKs
-- pure annotations -- to shed fault mechanisms and inflate d_circ. With it,
every layer is a set of operations a device could execute simultaneously:
merging layers is legal exactly when the merged operations touch disjoint
qubits, which is real pipelining that genuinely reduces idle exposure --
schedule optimization the tier exists to score -- while the coarsenings that
only exist on paper (an ancilla reset, coupled and measured "at once") are
rejected.

The allowed gate set is stim's unitary gates plus R, RX, M, MX and the
annotations (TICK, DETECTOR, OBSERVABLE_INCLUDE, QUBIT_COORDS, SHIFT_COORDS).
MPP / MR / heralded channels are excluded until the recipe defines them.
d_circ does not depend on the value of P_REF; the rate only has to be the
single reference one so the mechanism set is canonical.

Conformance is an exact-equality check through stim's own normalization
(consecutive same-gate instructions fuse on parse and append), so generate
circuits with apply_noise() -- the committed artifact is then a fixed point.
Hand-rolled circuits must keep one instruction per gate-name run per layer.
"""

import os
import sys

import numpy as np
import stim

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gf2

try:
    import gf2_fast as _GF        # optional C++ accelerator (make fast); the
except ImportError:               # search degrades to the python path without it
    _GF = None

P_REF = 0.001
RESET_FLIP = {"R": "X_ERROR", "RX": "Z_ERROR"}
MEASURES = ("M", "MX")
ANNOTATIONS = ("TICK", "DETECTOR", "OBSERVABLE_INCLUDE", "QUBIT_COORDS",
               "SHIFT_COORDS")


# ---------------------------------------------------------------- noise recipe

def _is_pure_noise(name):
    gd = stim.gate_data(name)
    return gd.is_noisy_gate and not gd.produces_measurements


def strip_noise(circuit):
    """The noiseless skeleton: noise channels removed, measurement flip
    arguments dropped. Measurement record indices are unchanged, so detector
    and observable references stay valid."""
    out = stim.Circuit()
    for inst in circuit.flattened():
        if _is_pure_noise(inst.name):
            continue
        if inst.name in MEASURES and inst.gate_args_copy():
            out.append(inst.name, inst.targets_copy(), [])
        else:
            out.append(inst)
    return out


def skeleton_errors(skeleton):
    """Gate-set conformance of a noiseless skeleton: [] iff every instruction
    is an allowed one (see module docstring)."""
    errs = []
    seen = set()
    for inst in skeleton.flattened():
        name = inst.name
        if name in seen:
            continue
        seen.add(name)
        if name in ANNOTATIONS or name in MEASURES or name in RESET_FLIP:
            continue
        gd = stim.gate_data(name)
        if gd.is_unitary:
            if any(not t.is_qubit_target for t in inst.targets_copy()):
                errs.append(f"{name} with a non-qubit target (classical "
                            f"control) is outside the circuit-tier gate set")
            continue
        errs.append(f"instruction {name} is outside the circuit-tier gate set "
                    f"(unitary gates, R, RX, M, MX, and annotations)")
    return errs


def _segments(flat_circuit):
    segs, cur = [], []
    for inst in flat_circuit:
        if inst.name == "TICK":
            segs.append(cur)
            cur = []
        else:
            cur.append(inst)
    segs.append(cur)
    return segs


def layer_conflict_errors(skeleton):
    """[] iff every TICK segment of the noiseless skeleton is a genuinely
    parallel layer: no qubit targeted by more than one operation atom
    (annotations do not count). See the module docstring for why this is
    load-bearing: layer count controls idle-data noise, so a layer structure
    that could not run on hardware would shed fault mechanisms for free."""
    errs = []
    for si, seg in enumerate(_segments(skeleton.flattened())):
        used = set()
        for inst in seg:
            if inst.name in ANNOTATIONS:
                continue
            for t in inst.targets_copy():
                q = t.qubit_value
                if q is None:
                    continue
                if q in used:
                    errs.append(
                        f"TICK layer {si} operates on qubit {q} more than "
                        f"once; a layer must be executable in parallel "
                        f"(sequential operations need a TICK between them)")
                    break
                used.add(q)
            if errs:
                break
        if len(errs) >= 3:
            break
    return errs


def apply_noise(skeleton, n_data, p=P_REF):
    """The canonical noisy circuit for a noiseless skeleton (see module
    docstring). This function IS the recipe: a submission conforms iff it
    equals apply_noise(strip_noise(submission), n, P_REF)."""
    out = stim.Circuit()
    segs = _segments(skeleton.flattened())
    for si, seg in enumerate(segs):
        if si:
            out.append("TICK")
        touched, active = set(), False
        for inst in seg:
            name = inst.name
            if name in ANNOTATIONS:
                out.append(inst)
                continue
            targets = inst.targets_copy()
            qubits = [t.qubit_value for t in targets
                      if t.qubit_value is not None]
            touched.update(qubits)
            active = True
            if name in MEASURES:
                out.append(name, targets, p)
            elif name in RESET_FLIP:
                out.append(inst)
                out.append(RESET_FLIP[name], qubits, p)
            else:
                out.append(inst)
                if stim.gate_data(name).is_two_qubit_gate:
                    out.append("DEPOLARIZE2", targets, p)
        if active:
            idle = [q for q in range(n_data) if q not in touched]
            if idle:
                out.append("DEPOLARIZE1", idle, p)
    return out


def noise_recipe_errors(circuit, n_data, p=P_REF):
    """[] iff the circuit is exactly the canonical noisy form of its own
    skeleton. Any deviation -- a missing or extra channel, a wrong rate, a
    disallowed instruction -- is reported with the first differing line."""
    skel = strip_noise(circuit)
    errs = skeleton_errors(skel) + layer_conflict_errors(skel)
    if errs:
        return errs
    want = str(apply_noise(skel, n_data, p))
    have = str(circuit.flattened())
    if want == have:
        return []
    wl, hl = want.splitlines(), have.splitlines()
    for i, (a, b) in enumerate(zip(wl, hl)):
        if a != b:
            return [f"noise placement deviates from the canonical recipe at "
                    f"instruction {i + 1}: expected '{a}', found '{b}'"]
    return [f"noise placement deviates from the canonical recipe: circuit has "
            f"{len(hl)} instructions, the canonical form has {len(wl)}"]


# --------------------------------------------------------------- DEM handling

def derive_dem(circuit):
    """The pinned DEM derivation (RFC 0001 step 5): no decomposition (hook
    mechanisms fire >2 detectors and must survive), loops flattened so error
    instructions are plain, absolutely-indexed lines. str() of the result is
    the committed .dem artifact; witness indices count its error instructions
    in file order. Verification compares a committed .dem against this with
    dem_matches, not byte equality -- see there for why."""
    return circuit.detector_error_model(decompose_errors=False,
                                        flatten_loops=True)


def dem_matches(derived, committed, rtol=1e-9, atol=1e-12):
    """Does the committed DEM match the pinned re-derivation? Everything
    d_circ depends on -- instruction count, types, detector/observable
    targets, and their file order (witness indices) -- must be EXACTLY equal.
    Probabilities are compared only to a tight tolerance: they are display
    metadata the distance tier never reads, and their last ulps are
    architecture-sensitive (e.g. FMA contraction on arm64 vs x86), so exact
    byte equality would reject an honest artifact generated on another
    machine while a real tamper still exceeds any plausible tolerance."""
    da = list(derived.flattened())
    ca = list(committed.flattened())
    if len(da) != len(ca):
        return False
    for x, y in zip(da, ca):
        if x.type != y.type:
            return False
        if [str(t) for t in x.targets_copy()] != \
           [str(t) for t in y.targets_copy()]:
            return False
        ax, ay = x.args_copy(), y.args_copy()
        if len(ax) != len(ay) or any(
                abs(a - b) > rtol * max(abs(a), abs(b)) + atol
                for a, b in zip(ax, ay)):
            return False
    return True


def dem_columns(dem):
    """One (detector_ids, observable_ids) pair per error instruction, in file
    order -- the sparse columns of H_dem / L, and the objects witness indices
    point at."""
    cols = []
    for inst in dem.flattened():
        if inst.type != "error":
            continue
        ds, ls = [], []
        for t in inst.targets_copy():
            if t.is_relative_detector_id():
                ds.append(int(t.val))
            elif t.is_logical_observable_id():
                ls.append(int(t.val))
        cols.append((ds, ls))
    return cols


def dem_matrices(dem):
    """Dense (H_dem, L): detectors x mechanisms and observables x mechanisms.
    The search substrate; the witness CHECK never needs it (witness_errors is
    sparse), so verification stays cheap even where these would be large."""
    cols = dem_columns(dem)
    H = np.zeros((dem.num_detectors, len(cols)), dtype=np.int8)
    L = np.zeros((dem.num_observables, len(cols)), dtype=np.int8)
    for j, (ds, ls) in enumerate(cols):
        for d in ds:
            H[d, j] = 1
        for l in ls:
            L[l, j] = 1
    return H, L


def witness_errors(dem, witness, value):
    """GF(2) check of a d_circ claim against a DEM: [] iff `witness` is a
    strictly increasing list of error-instruction indices whose detector sets
    XOR to nothing (undetected) and whose observable sets do not (flips a
    logical), with |witness| = value. Sparse and O(|witness| * degree)."""
    cols = dem_columns(dem)
    idx = [int(i) for i in witness]
    if idx != sorted(set(idx)):
        return ["witness indices must be strictly increasing and distinct"]
    if idx and idx[-1] >= len(cols):
        return [f"witness index {idx[-1]} out of range: the DEM has "
                f"{len(cols)} error mechanisms"]
    if len(idx) != value:
        return [f"witness has {len(idx)} mechanisms but claims value {value}"]
    det, obs = set(), set()
    for i in idx:
        det.symmetric_difference_update(cols[i][0])
        obs.symmetric_difference_update(cols[i][1])
    errs = []
    if det:
        errs.append(f"witness is detected: detectors {sorted(det)[:8]} fire")
    if not obs:
        errs.append("witness flips no logical observable")
    return errs


# --------------------------------------------------------------------- search

def _kernel_basis(H):
    return _GF.kernel_basis(H) if _GF else gf2.kernel_basis(H)


def _rref(M):
    if _GF:
        R, _ = _GF.gf2_rref(np.ascontiguousarray(M))
        return np.asarray(R, dtype=np.int8)
    return gf2.rref(np.ascontiguousarray(M))[0]


def ris_dem(H, L, trials, seed=0, pair_top=24, max_seconds=None, threads=4):
    """RIS upper-bound search for the lightest undetected logical fault set:
    min |e| with H e = 0, L e != 0. The code-tier searcher on the DEM's
    parity-check matrix -- hyperedge degree is irrelevant to it. Returns
    (weight, sorted column indices) or (None, None). Stops after `trials`
    permutations or `max_seconds` wall-clock, whichever comes first (the time
    cap keeps the CI gate bounded when the size estimate is off).

    When gf2_fast provides dem_rand_witness, the whole trial loop runs in
    C++ (kernel packed once, pivot-order permutation instead of physical
    column moves, `threads` workers), handed out in chunks. A chunk cannot
    be aborted, so the wall cap is enforced by PROJECTION, not just by
    checking between chunks (vprusso's #684 review: a blind 64-trial chunk
    overshot a 0.5 s cap by ~140x at m~12k): the loop opens with a small
    8-trial chunk to measure this machine's per-trial cost, then sizes every
    later chunk to what the remaining budget can pay for (floor `threads`,
    else stop), so the worst overshoot is one small chunk rather than one
    arbitrarily expensive one. An unconstrained run always uses the fixed
    (8, 64, 64, ...) sequence, so results stay deterministic given (seed,
    trials, threads) whenever the cap does not truncate. Finds are PROPOSALS
    either way -- callers validate with witness_errors. The numpy loop below
    is the fallback and the audited reference implementation."""
    import time
    H = np.ascontiguousarray(np.asarray(H, dtype=np.int8))
    L = np.ascontiguousarray(np.asarray(L, dtype=np.int8))
    if _GF is not None and hasattr(_GF, "dem_rand_witness"):
        deadline = (time.monotonic() + max_seconds) if max_seconds else None
        best, wit = None, None
        done, chunk_i = 0, 0
        per_trial = None            # measured; conservative running max
        while done < trials:
            t = min(8 if chunk_i == 0 else 64, trials - done)
            if deadline is not None and per_trial is not None:
                afford = int((deadline - time.monotonic()) / per_trial)
                if afford < max(threads, 1):
                    break
                t = min(t, afford)
            t0 = time.monotonic()
            w, sup = _GF.dem_rand_witness(H, L, trials=t,
                                          seed=seed + 7919 * chunk_i,
                                          pair_depth=pair_top,
                                          threads=threads)
            per_trial = max(per_trial or 0.0,
                            (time.monotonic() - t0) / t, 1e-9)
            if w is not None and (best is None or w < best):
                best, wit = int(w), [int(i) for i in sup]
            done += t
            chunk_i += 1
            if deadline and time.monotonic() > deadline:
                break
        return best, wit
    K = _kernel_basis(H)
    m = K.shape[1]
    if K.shape[0] == 0:
        return None, None
    LT = np.asarray(L, dtype=np.int8).T
    rng = np.random.default_rng(seed)
    best, best_v = m + 1, None
    deadline = (time.monotonic() + max_seconds) if max_seconds else None

    def consider(v, perm):
        nonlocal best, best_v
        w = int(v.sum())
        if 0 < w < best:
            inv = np.empty(m, dtype=np.int64)
            inv[perm] = np.arange(m)
            best, best_v = w, v[inv].copy()

    for _ in range(trials):
        if deadline and time.monotonic() > deadline:
            break
        perm = rng.permutation(m)
        R = _rref(K[:, perm])
        sig = (R @ LT[perm]) % 2
        live = np.flatnonzero(sig.any(axis=1))
        if not live.size:
            continue
        w = R[live].sum(axis=1)
        consider(R[live[int(np.argmin(w))]], perm)
        order = live[np.argsort(w)][:pair_top]
        for a in range(len(order)):
            for b in range(a + 1, len(order)):
                v = R[order[a]] ^ R[order[b]]
                if ((v @ LT[perm]) % 2).any():
                    consider(v, perm)
    if best_v is None:
        return None, None
    return best, sorted(int(i) for i in np.flatnonzero(best_v))


# -------------------------------------------------------------------- builder

def edge_coloring(H, rng=None):
    """Greedy proper coloring of check-qubit edges -> list of parallel CX
    layers. A rng shuffles the edge insertion order, yielding a different
    valid schedule per seed (the schedule-search knob)."""
    edges = [(c, int(q)) for c in range(H.shape[0])
             for q in np.flatnonzero(H[c])]
    if rng is not None:
        rng.shuffle(edges)
    layers, used_q, used_c = [], {}, {}
    for c, q in edges:
        col = 0
        while col in used_q.get(q, set()) or col in used_c.get(c, set()):
            col += 1
        used_q.setdefault(q, set()).add(col)
        used_c.setdefault(c, set()).add(col)
        while len(layers) <= col:
            layers.append([])
        layers[col].append((c, q))
    return layers


def build_css_memory(HX, HZ, rounds, basis="Z", sched_seed=None,
                     layers_x=None, layers_z=None):
    """Reference noiseless memory-experiment skeleton for a CSS code: the
    implementation submitters copy, and the generator of the seed artifacts.

    Data qubits are 0..n-1 (the board's qubit indexing), X-check ancillas
    n..n+rX-1, Z-check ancillas after those. Each round extracts the X checks
    (RX ancilla, CX ancilla->data in edge-colored layers, MX) then the Z
    checks (R ancilla, CX data->ancilla, M), every gate layer in its own TICK
    segment. Basis S prepares and reads out data in S, anchors the S-side
    checks with absolute round-0 and final-closure detectors, compares
    everything else round-to-round, and includes the k S-type logicals as
    observables. Feed the result to apply_noise() for the canonical circuit.

    The schedule -- the thing the tier scores -- is the CX layer structure:
    pass layers_x/layers_z as lists of [(check, qubit), ...] layers (e.g. a
    geometric plaquette order), or let a greedy edge coloring pick one
    (sched_seed shuffles it). Explicit layers must cover each check's support
    exactly; empty layers are skipped.
    """
    HX = np.asarray(HX, dtype=np.int8)
    HZ = np.asarray(HZ, dtype=np.int8)
    n = HX.shape[1]
    rX, rZ = HX.shape[0], HZ.shape[0]
    ax = list(range(n, n + rX))
    az = list(range(n + rX, n + rX + rZ))
    data = list(range(n))
    rng = None if sched_seed is None else np.random.default_rng(sched_seed)
    lay_x = [l for l in (layers_x if layers_x is not None
                         else edge_coloring(HX, rng)) if l]
    lay_z = [l for l in (layers_z if layers_z is not None
                         else edge_coloring(HZ, rng)) if l]
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
        for layer in lay_x:
            c.append("TICK")
            c.append("CX", [t for chk, q in layer for t in (n + chk, q)])
        c.append("TICK")
        c.append("MX", ax)
        for i in range(rX):
            pos[("x", i, r)] = len(pos)
        c.append("TICK")
        c.append("R", az)
        for layer in lay_z:
            c.append("TICK")
            c.append("CX", [t for chk, q in layer for t in (q, n + rX + chk)])
        c.append("TICK")
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
    for i in range(n_anchor):                       # deterministic at prep
        c.append("DETECTOR", [rec((side, i, 0))])
    for r in range(1, rounds):
        for i in range(rX):
            c.append("DETECTOR", [rec(("x", i, r)), rec(("x", i, r - 1))])
        for i in range(rZ):
            c.append("DETECTOR", [rec(("z", i, r)), rec(("z", i, r - 1))])
    for i in range(n_anchor):                       # closure on data readout
        targs = [rec(("data", int(q))) for q in np.flatnonzero(H_anchor[i])]
        c.append("DETECTOR", targs + [rec((side, i, rounds - 1))])
    for j, row in enumerate(L_obs):
        c.append("OBSERVABLE_INCLUDE",
                 [rec(("data", int(q))) for q in np.flatnonzero(row)], j)
    return c
