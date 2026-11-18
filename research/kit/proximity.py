"""Proximity profile of a detector error model, as a schedule ranking (issue #6242, campaign 3).

Proxima (arXiv:2611.19715) ranks syndrome-extraction schedules without
decoding: the proximity of a fault u is the smallest number of additional
faults that complete u to a fault set no detector sees and that flips a
logical observable, so d_circ = 1 + min over u of prox(u), and restricting the
completion to a neighborhood Q of the DEM's fault graph (faults adjacent when
they share a detector) gives prox_Q(u) >= prox(u), still an upper bound on
d_circ - 1. Two schedules with the same d_circ differ in how many
near-minimal completions they admit, which the profile over a seed set reads:
P_min first (higher is better), then P_mean as the tie-break.

The seeds here are the mechanisms of the lightest undetected logical fault
sets that the board's own RIS search returns (verify/circuit_tools.ris_dem),
so every seed lies on a completion of that weight minus one and the profile
measures how crowded the lightest logical fault sets are around it. The
neighborhood of a seed is its witness set plus breadth-first layers of
detector-adjacent faults, up to ``size`` mechanisms; the minimum completion
inside it is found exactly by enumerating subsets in order of weight.

Nothing here is trusted: the ranking picks which schedule the deep RIS search
and the verifier (verify/circuit_verify.py) then evaluate, exactly as before.
"""
from __future__ import annotations

import itertools
from collections import defaultdict

import circuit_tools as ct
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

DEFAULT_SIZE = 16
DEFAULT_SEEDS = 2
DEFAULT_HOOD = 400          # mechanisms in a witness-centered neighborhood for the MILP search
DEFAULT_HOOK_LIMIT = 48     # hook-like seeds per basis
DEFAULT_MIN_DETECTORS = 4   # a seed is hook-like when it fires at least this many detectors
MILP_SECONDS = 20.0


def fault_adjacency(cols):
    """Detector -> mechanisms touching it, for the DEM columns of dem_columns()."""
    by_det = defaultdict(list)
    for j, (ds, _) in enumerate(cols):
        for d in ds:
            by_det[d].append(j)
    return by_det


def neighborhood(cols, by_det, seed, witness, size):
    """Up to ``size`` mechanisms around ``seed``.

    The witness set containing the seed comes first, then faults adjacent
    (sharing a detector) to what is already in, breadth first and in index
    order, so the same DEM always gives the same neighborhood.
    """
    Q = []
    seen = set()
    for j in [seed] + sorted(witness):
        if j not in seen:
            seen.add(j)
            Q.append(j)
    frontier = list(Q)
    while frontier and len(Q) < size:
        nxt = []
        for j in frontier:
            for d in cols[j][0]:
                for k in by_det[d]:
                    if k not in seen:
                        seen.add(k)
                        Q.append(k)
                        nxt.append(k)
                        if len(Q) >= size:
                            return Q
        frontier = nxt
    return Q


def _bits(cols, Q):
    """Compact bitmasks for the detectors and observables of the mechanisms in Q."""
    dets = sorted({d for j in Q for d in cols[j][0]})
    obs = sorted({o for j in Q for o in cols[j][1]})
    dpos = {d: i for i, d in enumerate(dets)}
    opos = {o: i for i, o in enumerate(obs)}
    dmask = {j: sum(1 << dpos[d] for d in cols[j][0]) for j in Q}
    omask = {j: sum(1 << opos[o] for o in cols[j][1]) for j in Q}
    return dmask, omask


def proximity(cols, seed, Q, cap):
    """Exact prox_Q(seed) inside the neighborhood Q, with its multiplicity.

    Returns (w, count): the smallest |f|, f a subset of Q without the seed,
    with the detectors of {seed} + f cancelling and their observables not, and
    how many such f of that weight Q holds; (None, 0) when no completion of at
    most ``cap`` faults exists inside Q. The count is the tie-break the paper's
    profile does not have: two schedules whose seeds all sit at the cap still
    differ in how many lightest completions surround each seed.
    """
    dmask, omask = _bits(cols, Q)
    others = [j for j in Q if j != seed]
    target_d = dmask[seed]
    seed_o = omask[seed]
    for w in range(0, min(cap, len(others)) + 1):
        count = 0
        for combo in itertools.combinations(others, w):
            dd = target_d
            oo = seed_o
            for j in combo:
                dd ^= dmask[j]
                oo ^= omask[j]
            if dd == 0 and oo != 0:
                count += 1
        if count:
            return w, count
    return None, 0


def seed_sets(H, L, trials, seeds=DEFAULT_SEEDS, max_seconds=None):
    """Distinct undetected logical fault sets of the lightest weight ``seeds`` RIS runs reach."""
    out = []
    for s in range(seeds):
        w, wit = ct.ris_dem(H, L, trials=trials, seed=s, max_seconds=max_seconds)
        if wit is None:
            continue
        wit = tuple(sorted(int(i) for i in wit))
        if wit not in out:
            out.append(wit)
    if not out:
        return out
    lightest = min(len(w) for w in out)
    return [w for w in out if len(w) == lightest]


def profile(cols, witness_sets, size=DEFAULT_SIZE, cap=None):
    """Proximity profile over the mechanisms of ``witness_sets``.

    Returns a dict with p_min, p_mean, the number of seeds attaining p_min, the
    number of seeds, and the per-seed values. The cap defaults to the witness
    weight minus one, which every seed attains inside its own witness set, so
    p_min equal to the cap means no lighter completion was found in any
    neighborhood and p_mean says how many seeds sit on one.
    """
    by_det = fault_adjacency(cols)
    if cap is None:
        cap = max((len(w) for w in witness_sets), default=1) - 1
    vals = {}
    counts = {}
    for wit in witness_sets:
        for u in wit:
            if u in vals:
                continue
            Q = neighborhood(cols, by_det, u, wit, size)
            p, c = proximity(cols, u, Q, cap)
            vals[u] = cap if p is None else p
            counts[u] = c
    if not vals:
        return {"p_min": None, "p_mean": None, "at_min": 0, "seeds": 0, "completions": None,
                "per_seed": {}}
    arr = np.array(list(vals.values()), dtype=float)
    cnt = np.array(list(counts.values()), dtype=float)
    return {"p_min": int(arr.min()), "p_mean": round(float(arr.mean()), 3),
            "at_min": int((arr == arr.min()).sum()), "seeds": int(arr.size),
            "completions": round(float(cnt.mean()), 3),
            "per_seed": {int(k): [int(v), int(counts[k])] for k, v in vals.items()}}



def neighborhood_layers(cols, by_det, witness, size):
    """Return the witness set plus whole breadth-first layers of detector-adjacent faults.

    Layers are added while the next one still fits under ``size`` (the first
    layer is added even when it does not, truncated in index order), so the
    hook faults next to the witness are always inside.
    """
    Q = sorted(set(int(j) for j in witness))
    seen = set(Q)
    frontier = list(Q)
    first = True
    while frontier:
        layer = []
        for j in frontier:
            for d in cols[j][0]:
                for k in by_det[d]:
                    if k not in seen:
                        seen.add(k)
                        layer.append(k)
        if not layer:
            break
        if len(Q) + len(layer) > size:
            if first:
                Q.extend(sorted(layer)[:max(0, size - len(Q))])
            break
        Q.extend(sorted(layer))
        frontier = layer
        first = False
    return Q


def hook_seeds(cols, Q, witness, limit=DEFAULT_HOOK_LIMIT, min_detectors=DEFAULT_MIN_DETECTORS):
    """Hook-like seeds of the neighborhood.

    The faults outside the witness that fire the most detectors (a propagated
    ancilla fault touches the checks of every data qubit it reached), most
    detectors first, index order on ties.
    """
    wit = set(int(j) for j in witness)
    cands = [j for j in Q if j not in wit and len(cols[j][0]) >= min_detectors]
    cands.sort(key=lambda j: (-len(cols[j][0]), j))
    return cands[:limit]


def proximity_milp(cols, seed, Q, cap=None, seconds=MILP_SECONDS):
    """Exact prox_Q(seed) as a 0-1 integer program (HiGHS through scipy).

    Minimize |f| over f a subset of Q without the seed such that the detector
    sets of {seed} + f cancel (each detector row: A f - 2 y = s, y a
    non-negative integer) and at least one observable is flipped (each
    observable row: L f - t + 2 z = l, t binary, z an integer, with sum t >= 1).
    Returns the weight, or None when no completion exists inside Q or the
    solve hits ``cap`` or ``seconds``.
    """
    others = [j for j in Q if j != seed]
    if not others:
        return None
    dets = sorted({d for j in Q for d in cols[j][0]})
    obs = sorted({o for j in Q for o in cols[j][1]})
    dpos = {d: i for i, d in enumerate(dets)}
    opos = {o: i for i, o in enumerate(obs)}
    nf, nd, no = len(others), len(dets), len(obs)
    if no == 0:
        return None
    # variable layout: f (nf) | y (nd) | t (no) | z (no)
    nv = nf + nd + 2 * no
    A = np.zeros((nd + no + 1, nv))
    lo = np.zeros(nd + no + 1)
    hi = np.zeros(nd + no + 1)
    for col, j in enumerate(others):
        for d in cols[j][0]:
            A[dpos[d], col] = 1.0
        for o in cols[j][1]:
            A[nd + opos[o], col] = 1.0
    for i in range(nd):
        A[i, nf + i] = -2.0      # A f - 2 y = s: the count of faults on a detector has the seed's parity
    for o in range(no):
        A[nd + o, nf + nd + o] = -1.0
        A[nd + o, nf + nd + no + o] = 2.0
    s_seed = set(cols[seed][0])
    l_seed = set(cols[seed][1])
    for d in dets:
        lo[dpos[d]] = hi[dpos[d]] = 1.0 if d in s_seed else 0.0
    for o in obs:
        lo[nd + opos[o]] = hi[nd + opos[o]] = 1.0 if o in l_seed else 0.0
    A[nd + no, nf + nd:nf + nd + no] = 1.0
    lo[nd + no], hi[nd + no] = 1.0, no
    c = np.zeros(nv)
    c[:nf] = 1.0
    lb = np.concatenate([np.zeros(nf), np.zeros(nd), np.zeros(no), np.full(no, -np.inf)])
    ub = np.concatenate([np.ones(nf), np.full(nd, np.inf), np.ones(no), np.full(no, np.inf)])
    res = milp(c=c, constraints=LinearConstraint(A, lo, hi), integrality=np.ones(nv),
               bounds=Bounds(lb, ub), options={"time_limit": float(seconds), "disp": False})
    if res.status != 0 or res.x is None:
        return None
    w = int(round(float(res.fun)))
    if cap is not None and w > cap:
        return None
    return w


def profile_hooks(cols, witness, size=DEFAULT_HOOD, limit=DEFAULT_HOOK_LIMIT,
                  min_detectors=DEFAULT_MIN_DETECTORS, cap=None, seconds=MILP_SECONDS):
    """Proximity profile over hook-like seeds in a witness-centered neighborhood.

    The witness (an undetected logical fault set of weight d_circ) anchors the
    neighborhood; its own faults have proximity d_circ - 1 by construction and
    are not seeds. A hook-like fault that stands in for two of the witness's
    data faults has proximity d_circ - 2 inside the neighborhood, three gives
    d_circ - 3, so P_min and P_mean over the hooks say how much the schedule's
    propagated faults shorten the lightest logical fault sets. The cap is
    d_circ - 1; a seed with no completion inside the neighborhood counts at the
    cap.
    """
    by_det = fault_adjacency(cols)
    Q = neighborhood_layers(cols, by_det, witness, size)
    seeds = hook_seeds(cols, Q, witness, limit=limit, min_detectors=min_detectors)
    if cap is None:
        cap = len(witness) - 1
    vals = {}
    for u in seeds:
        p = proximity_milp(cols, u, Q, cap=cap, seconds=seconds)
        vals[u] = cap if p is None else p
    out = {"p_min": None, "p_mean": None, "at_min": 0, "seeds": len(vals), "completions": None,
           "neighborhood": len(Q), "cap": cap, "per_seed": {int(k): int(v) for k, v in vals.items()}}
    if vals:
        arr = np.array(list(vals.values()), dtype=float)
        out.update(p_min=int(arr.min()), p_mean=round(float(arr.mean()), 3),
                   at_min=int((arr == arr.min()).sum()))
    return out



def profile_decoder(dem, witness, limit=DEFAULT_HOOK_LIMIT, min_detectors=DEFAULT_MIN_DETECTORS,
                    size=DEFAULT_HOOD, cap=None, decoder_factory=None, targets="parity"):
    """Proximity profile over hook-like seeds, completions found by the pinned decoder.

    The exact local search does not scale (HiGHS hits its time limit on a
    250-fault neighborhood), so the completion of a seed u is found the way a
    decoder would: decode the syndrome of u on the model with the observables
    appended as perfect checks, asking for each logical in turn to come out
    flipped. Every correction f returned satisfies H f = H u and flips that
    logical, so u + f is an undetected logical fault set and |f| is an upper
    bound on prox(u); the lightest over the logicals is the seed's value,
    clipped at the cap (d_circ - 1, the witness weight minus one). A
    correction that uses u itself completes nothing and is skipped. The
    decoder is verify/ler_tools.make_decoder with a flat prior, so it
    minimizes weight rather than likelihood. With ``targets="parity"`` one
    row, the sum of the observables, is appended and asked to flip (one
    decode per seed, an odd number of logicals flipped); ``"each"`` appends
    every observable and asks for each in turn (k decodes per seed).
    """
    import ler_tools as lt

    cols = ct.dem_columns(dem)
    H, L = ct.dem_matrices(dem)
    by_det = fault_adjacency(cols)
    Q = neighborhood_layers(cols, by_det, witness, size)
    seeds = hook_seeds(cols, Q, witness, limit=limit, min_detectors=min_detectors)
    if cap is None:
        cap = len(witness) - 1
    Lrows = L if targets == "each" else (L.sum(axis=0) % 2).reshape(1, -1)
    Hp = np.vstack([H, Lrows]).astype(np.uint8)
    k = Lrows.shape[0]
    make = decoder_factory or lt.make_decoder
    dec = make(Hp, np.full(Hp.shape[1], 1e-3))
    vals = {}
    for u in seeds:
        s = Hp[:, u].copy()
        best = None
        for o in range(k):
            t = s.copy()
            t[H.shape[0] + o] ^= 1
            f = np.asarray(dec.decode(t.astype(np.uint8)), dtype=np.uint8)
            if f[u]:
                continue
            if np.any((Hp @ f) % 2 != t):
                continue
            w = int(f.sum())
            if best is None or w < best:
                best = w
        vals[u] = cap if best is None or best > cap else best
    out = {"p_min": None, "p_mean": None, "at_min": 0, "seeds": len(vals), "completions": None,
           "neighborhood": len(Q), "cap": cap, "method": f"decoder/{targets}",
           "per_seed": {int(a): int(b) for a, b in vals.items()}}
    if vals:
        arr = np.array(list(vals.values()), dtype=float)
        out.update(p_min=int(arr.min()), p_mean=round(float(arr.mean()), 3),
                   at_min=int((arr == arr.min()).sum()))
    return out


def dem_profile(dem, trials, size=DEFAULT_SIZE, seeds=DEFAULT_SEEDS, max_seconds=None,
                extra_witnesses=(), hook_limit=DEFAULT_HOOK_LIMIT):
    """Profile of one memory circuit's DEM.

    The seeds are the lightest RIS witness sets plus ``extra_witnesses``, undetected
    logical fault sets the caller already holds (the final-readout flips along the
    code's own logical, which every schedule of one code shares, so candidates are
    compared on the same seeds and not on what a short search happened to find).
    """
    cols = ct.dem_columns(dem)
    if not seeds and extra_witnesses:
        # the bake-off path: the readout witness anchors a large neighborhood
        # and hook-like faults are the seeds, solved exactly by MILP
        prof = profile_decoder(dem, list(extra_witnesses)[0], size=max(size, DEFAULT_HOOD), limit=hook_limit)
        prof["witness_weights"] = [len(list(extra_witnesses)[0])]
        return prof
    wits = []
    if seeds:
        # the dense matrices and the RIS kernel are the expensive part: a
        # 100,000-mechanism memory DEM takes minutes here, so callers that
        # seed from the readout witness alone pass seeds=0 and skip them
        H, L = ct.dem_matrices(dem)
        wits = seed_sets(H, L, trials, seeds=seeds, max_seconds=max_seconds)
    for extra in extra_witnesses:
        key = tuple(sorted(int(i) for i in extra))
        if key and key not in wits:
            wits.append(key)
    prof = profile(cols, wits, size=size)
    prof["witness_weights"] = sorted(len(w) for w in wits)
    return prof


def schedule_key(profiles):
    """Sort key over both bases; higher wins.

    The lower P_min first, then the lower P_mean, then the negated larger mean
    number of lightest completions per seed (fewer is better).
    """
    pmins = [p["p_min"] for p in profiles.values() if p["p_min"] is not None]
    pmeans = [p["p_mean"] for p in profiles.values() if p["p_mean"] is not None]
    comps = [p["completions"] for p in profiles.values() if p.get("completions") is not None]
    atmin = [p.get("at_min", 0) for p in profiles.values()]
    if not pmins:
        return (-1, -1.0, 0.0)
    third = -max(comps) if comps else -float(max(atmin))
    return (min(pmins), min(pmeans), third)
