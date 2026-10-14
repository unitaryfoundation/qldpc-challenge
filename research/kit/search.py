"""A generic search funnel for *discovering* codes (the heart of autoresearch).

The constructors in this kit build one code at a time; this module sweeps a
*family* of them, screens each cheaply, and surfaces the best. The funnel is the
standard three stages:

    1. generate   candidate (HX, HZ) from a family (a sampler/enumerator)
    2. screen     skip k < min_k; estimate d with the surrogate; score by k*d^2/n
    3. rank       sort by efficiency and/or extract the Pareto frontier

The default path is pure numpy. ``surrogate.distance_rand`` also supports an
optional bit-packed C++ RIS backend (``backend="fast"`` or ``"auto"`` after
``make fast``). The screening distance is always an UPPER bound, so ``screen``
gives you ranked *candidates*, not certified codes. Confirm the finalists'
distance (``research/kit/distance.py``: exact MILP or decoder corroboration)
before claiming anything, then package the winner with ``submit.make_submission``.

``screen`` consumes any iterable of ``(label, HX, HZ)`` triples, so you can point
it at your own generator. Ready-made samplers ship for the BB family
(``sample_bb``) and the 2BGA families on dihedral, metacyclic, and affine
groups (``sample_dihedral``, ``sample_metacyclic``, ``sample_kasai_affine``);
a new one for any other family is the same shape.
"""
import hashlib
import json
import os

import numpy as np

from css import compute_k, verify_css, rref
from surrogate import distance_rand, prepare_distance_search
from bb import build_bb
from group_algebra import (alt, build_2bga, build_bbga, cyclic_product, dihedral,
                           metacyclic, sym)
import gf2poly
from products import (hypergraph_product, lifted_product, balanced_product,
                      sample_hypergraph_product, sample_lifted_product,
                      sample_balanced_product)


def efficiency(n, k, d):
    """The board's headline encoding-efficiency figure, k*d^2 / n."""
    return (k * d * d / n) if n else 0.0


def fingerprint(HX, HZ):
    """Exact-duplicate key: the reduced row echelon forms pin the stabilizer
    group. Equal fingerprint => identical code (same convention as the
    verifier's duplicate check). Used to dedup a sweep."""
    HX = np.asarray(HX, dtype=np.int8) % 2
    HZ = np.asarray(HZ, dtype=np.int8) % 2
    b = rref(HX)[0].tobytes() + b"|" + rref(HZ)[0].tobytes()
    return hashlib.sha256(b).hexdigest()[:16]


def _screen_one(job):
    """Score one candidate. Module level so a process pool can pickle it.

    The seed is derived from the code's own fingerprint, so a candidate gets
    the same trials wherever it runs and whatever order it arrives in.
    """
    spec, HX, HZ, min_k, min_d, trials, seed, backend, threads, distance, dkw = job
    if not verify_css(HX, HZ):
        return None
    k = compute_k(HX, HZ)
    if k < min_k:
        return None
    fp = fingerprint(HX, HZ)
    if distance is None:
        d = distance_rand(HX, HZ, trials=trials, seed=seed + int(fp, 16),
                          backend=backend, threads=threads)
    else:
        # An exact-distance backend has no restarts to seed, so seed/threads
        # are forwarded rather than re-derived; the callable owns that.
        d = distance(HX, HZ, trials=trials, seed=seed + int(fp, 16),
                     backend=backend, threads=threads, **(dkw or {}))
    if d == float("inf") or d < min_d:
        return None
    n = int(HX.shape[1])
    w = int(max(max((int(r.sum()) for r in HX), default=0),
                max((int(r.sum()) for r in HZ), default=0)))
    return {"spec": spec, "n": n, "k": int(k), "d": int(d), "w": w,
            "fingerprint": fp}


def _batches(it, size):
    """Yield lists of at most ``size`` items, pulling lazily.

    Candidates are generated on demand and handed out in bounded batches, so a
    sweep of a million never materializes a million dense matrices.
    """
    batch = []
    for item in it:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def screen(candidates, *, min_k=1, min_d=1, trials=400, seed=0,
           metric=efficiency, keep=None, verbose=False, backend="numpy",
           threads=1, workers=1, threads_per_candidate=None, batch=64,
           distance=None, distance_kwargs=None):
    """Screen an iterable of ``(spec, HX, HZ)`` candidates.

    ``spec`` is any JSON-serializable description of how the code was built (a
    dict of construction parameters is ideal -- it lets you rebuild the winner
    without re-parsing a string). For each distinct code: require ``k >= min_k``,
    estimate ``d`` with ``distance_rand`` (upper bound; require ``d >= min_d``),
    and score with ``metric(n, k, d)``. Returns records
    ``{spec, n, k, d, efficiency, fingerprint}`` sorted by score (best first),
    deduplicated by fingerprint, truncated to ``keep`` if given. ``backend`` and
    ``threads`` control the optional accelerated distance screen.

    ``distance`` replaces the estimator with any callable of the shape
    ``(HX, HZ, *, trials, seed, backend, threads) -> d``, returning
    ``float("inf")`` for a code it cannot resolve (which drops the candidate).
    ``surrogate.distance_rand`` is the default and stays the upper bound it
    always was. ``distance.qubitserf_screen`` is an exact-distance backend that
    drops in unchanged -- useful because the default estimator inflates, and a
    rank computed on a loose bound ranks the wrong codes. An exact backend does
    not make the survivor's claim exact: that is still the gate's to say.
    ``distance_kwargs`` is forwarded verbatim to ``distance`` for the knobs it
    owns and ``screen`` does not (``tlim=`` for ``qubitserf_screen``).

    ``workers`` > 1 scores candidates in parallel processes. Candidates are
    independent, so this is the axis to scale for a broad sweep;
    ``threads_per_candidate`` (default 1 when parallel) is the other axis, for
    a few finalists rather than many candidates. Turning up both oversubscribes
    the machine, so passing both greater than 1 raises rather than quietly
    thrashing.

    The result does not depend on the worker count. Each candidate's trials are
    seeded from its own fingerprint, deduplication happens in the parent, and
    ties in score break on fingerprint, so a parallel run returns exactly what a
    serial one does. Candidates are pulled lazily in batches of ``batch``, so a
    long generator never has to be materialized.
    """
    if workers < 1:
        raise ValueError("workers must be at least 1")
    if threads_per_candidate is None:
        threads_per_candidate = 1 if workers > 1 else threads
    if workers > 1 and threads_per_candidate > 1:
        raise ValueError(
            "workers and threads_per_candidate both > 1 oversubscribes the "
            "machine; parallelize across candidates for a sweep, or across "
            "threads for a few finalists, not both")

    def _record(rec):
        rec["efficiency"] = round(float(metric(rec["n"], rec["k"], rec["d"])), 4)
        if verbose:
            print(f"  [[{rec['n']},{rec['k']},{rec['d']}]] "
                  f"eff={rec['efficiency']:.3f}  {rec['spec']}")
        return rec

    seen = {}
    jobs = ((spec, HX, HZ, min_k, min_d, trials, seed, backend,
             threads_per_candidate, distance, distance_kwargs)
            for spec, HX, HZ in candidates)

    if workers == 1:
        for job in jobs:
            rec = _screen_one(job)
            if rec is not None and rec["fingerprint"] not in seen:
                seen[rec["fingerprint"]] = _record(rec)
    else:
        import multiprocessing as mp
        try:
            ctx = mp.get_context("fork")
        except ValueError:
            ctx = mp.get_context("spawn")
        try:
            with ctx.Pool(processes=workers) as pool:
                for chunk in _batches(jobs, max(1, batch)):
                    for rec in pool.map(_screen_one, chunk):
                        if rec is not None and rec["fingerprint"] not in seen:
                            seen[rec["fingerprint"]] = _record(rec)
        except (OSError, RuntimeError, ValueError, ImportError):
            # An unguarded caller under spawn, or a sandbox without processes:
            # fall back rather than fail, since the serial path is the same
            # computation.
            for job in jobs:
                rec = _screen_one(job)
                if rec is not None and rec["fingerprint"] not in seen:
                    seen[rec["fingerprint"]] = _record(rec)

    # Fingerprint breaks ties so the order does not depend on arrival order,
    # which it otherwise would once candidates are scored out of sequence.
    out = sorted(seen.values(),
                 key=lambda r: (-r["efficiency"], r["fingerprint"]))
    return out[:keep] if keep else out


def screen_adaptive(candidates, *, stages=(400, 20_000, 200_000), target=None,
                    min_k=1, min_d=1, metric=efficiency, keep=None,
                    seed=0, backend="numpy", threads=1, audit=None,
                    verbose=False):
    """Screen in widening stages, dropping what cannot reach ``target``.

    ``screen`` spends its whole trial budget on every candidate, including the
    ones a hundred trials would have settled. This runs the cheapest stage on
    everything and promotes only what is still worth paying for.

    The rejection is sound rather than heuristic, and that rests on the
    direction of the error: ``distance_rand`` returns an UPPER bound on d. A
    candidate whose stage reading already scores below ``target`` therefore has
    true d at most that reading and true score at most that score, and no
    deeper stage can rescue it, since widening the search can only lower d.
    Nothing that could have beaten the target is dropped.

    ``target`` is a score in the units of ``metric`` (kd^2/n by default); with
    ``target=None`` nothing is dropped for score and the stages only refine the
    estimate. Candidates on the running Pareto frontier over (n, k, d) are
    promoted whether or not they clear the target, since the board rewards
    frontier membership separately from score.

    Pass ``audit`` as a dict to receive per-stage ``promoted`` and ``rejected``
    counts, plus ``trials_spent`` against ``trials_flat``, the budget a flat
    ``screen`` at the deepest stage would have spent.
    """
    tally = audit if audit is not None else {}
    tally.setdefault("promoted", [])
    tally.setdefault("rejected", [])
    tally.setdefault("trials_spent", 0)

    live, seen = [], set()
    for spec, HX, HZ in candidates:
        if not verify_css(HX, HZ):
            continue
        k = compute_k(HX, HZ)
        if k < min_k:
            continue
        fp = fingerprint(HX, HZ)
        if fp in seen:
            continue
        seen.add(fp)
        live.append({"spec": spec, "HX": HX, "HZ": HZ, "k": int(k),
                     "n": int(HX.shape[1]), "fp": fp, "d": None,
                     "prep": None})

    for si, trials in enumerate(stages):
        if not live:
            break
        for c in live:
            if c["prep"] is None and backend == "numpy":
                c["prep"] = prepare_distance_search(c["HX"], c["HZ"])
            got = int(distance_rand(
                c["HX"], c["HZ"], trials=trials,
                seed=seed + si * 7919 + int(c["fp"], 16),
                backend=backend, threads=threads, prepared=c["prep"]))
            # Every stage returns a valid upper bound, and the stages draw
            # independently, so a later one can come back worse. Keep the best
            # bound seen rather than the latest, or a deeper stage could report
            # a weaker result than the shallower one already proved.
            c["d"] = got if c["d"] is None else min(c["d"], got)
            tally["trials_spent"] += trials
        live = [c for c in live if c["d"] != float("inf") and c["d"] >= min_d]
        if target is not None and si < len(stages) - 1:
            scored = [{"n": c["n"], "k": c["k"], "d": c["d"], "_c": c}
                      for c in live]
            front_fps = {r["_c"]["fp"] for r in pareto_frontier(scored)}
            keepers, dropped = [], 0
            for c in live:
                if (metric(c["n"], c["k"], c["d"]) >= target
                        or c["fp"] in front_fps):
                    keepers.append(c)
                else:
                    dropped += 1
            tally["promoted"].append(len(keepers))
            tally["rejected"].append(dropped)
            live = keepers
            if verbose:
                print(f"  stage {si} ({trials} trials): {len(keepers)} kept, "
                      f"{dropped} rejected")

    tally["trials_flat"] = len(seen) * (stages[-1] if stages else 0)
    out = []
    for c in live:
        w = int(max(*(int(r.sum()) for r in c["HX"]),
                    *(int(r.sum()) for r in c["HZ"])))
        out.append({"spec": c["spec"], "n": c["n"], "k": c["k"], "d": c["d"],
                    "w": w, "fingerprint": c["fp"],
                    "efficiency": round(float(metric(c["n"], c["k"], c["d"])), 4)})
    out.sort(key=lambda r: r["efficiency"], reverse=True)
    return out[:keep] if keep else out


def pareto_frontier(records):
    """The Pareto-optimal records over (n smaller, k larger, d larger): those
    not dominated by any other (no other has n' <= n, k' >= k, d' >= d with at
    least one strict). This is the board's frontier view -- there can be many
    co-leaders, none collapsed to a single rank."""
    front = []
    for r in records:
        dominated = any(
            s is not r
            and s["n"] <= r["n"] and s["k"] >= r["k"] and s["d"] >= r["d"]
            and (s["n"] < r["n"] or s["k"] > r["k"] or s["d"] > r["d"])
            for s in records
        )
        if not dominated:
            front.append(r)
    return sorted(front, key=lambda r: (r["n"], -r["k"], -r["d"]))


# ---------------------------------------------------------------------------
#  Persistence: append-and-resume a leaderboard across sweeps
# ---------------------------------------------------------------------------
def load_leaderboard(path):
    """Load a saved leaderboard (list of records), or [] if none exists."""
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return []


def update_leaderboard(path, records):
    """Merge ``records`` into the leaderboard at ``path`` (keyed by fingerprint,
    so re-screening the same code just refreshes it), write it back sorted by
    efficiency, and return the merged list. Lets a long search pause and resume."""
    board = {r["fingerprint"]: r for r in load_leaderboard(path)}
    for r in records:
        board[r["fingerprint"]] = r
    out = sorted(board.values(), key=lambda r: r["efficiency"], reverse=True)
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    return out


# ---------------------------------------------------------------------------
#  Ready-made samplers (all yield (spec, HX, HZ); point ``screen`` at any)
# ---------------------------------------------------------------------------
def bb_shape(l, m, A, B):  # noqa: E741
    """Return (n, w) for a bivariate-bicycle candidate without building it.

    Both are exact rather than bounds: n = 2lm by construction, and every check
    row is one A monomial block beside one B block, so the max row weight is
    |A| + |B| whenever the supports are distinct (which the samplers ensure).
    Cheap enough to run on every candidate before the dense build.
    """
    return 2 * l * m, len(A) + len(B)


def sample_bb(num, *, l_range=(4, 12), m_range=(3, 10), weight=3, seed=0,
              n_range=None, max_weight=None, audit=None):
    """Yield ``num`` random bivariate-bicycle candidates ``(spec, HX, HZ)``.

    Each picks a random torus Z_l x Z_m and two sets of ``weight`` distinct
    monomials (distinct so the supports do not cancel mod 2). ``spec`` is a dict
    ``{"family": "bb", "l", "m", "A", "B"}`` -- pass it straight to ``build_bb``
    to rebuild the code.

    ``n_range`` and ``max_weight`` reject a candidate before ``build_bb`` runs,
    using the exact (n, w) that ``bb_shape`` reads off the parameters. Both are
    facts about the construction rather than estimates, so nothing that could
    have passed is discarded. Pass ``audit`` as a dict to receive counts under
    ``sampled``, ``rejected_n``, ``rejected_w`` and ``built``.

    Reach at the defaults: n = 2lm, so l <= 12 and m <= 10 cap n at 240, and
    weight=3 caps the check weight at 6. Raise ``l_range``/``m_range`` for
    larger codes. The cap that matters for the board is the weight: every one of
    the 25 most efficient entries on it has a check weight of at least 12, so
    this sampler at its defaults explores the low-weight cells rather than
    competing at the efficiency frontier.

    Deliberately absent: a k prefilter via ``surrogate.mixed_volume``. That is
    a heuristic here, not a bound. Measured against recomputed k on random
    candidates whose supports contain (0,0), true k exceeds it in about 2.6% of
    cases on small tori (l, m in [3,5]; worst observed k = 12 against a bound
    of 0 at l = m = 3), 0.1% for l, m in [6,9], and in none of 700 samples at
    [10,14]. Rejecting on it would silently drop real codes, so it is left to
    callers who want a lossy filter and know the rate.
    """
    rng = np.random.default_rng(seed)
    tally = audit if audit is not None else {}
    for key in ("sampled", "rejected_n", "rejected_w", "built"):
        tally.setdefault(key, 0)

    def distinct_monomials(l, m):  # noqa: E741
        grid = [(a, b) for a in range(l) for b in range(m)]
        idx = rng.choice(len(grid), size=min(weight, len(grid)), replace=False)
        return [grid[i] for i in idx]

    for _ in range(num):
        l = int(rng.integers(l_range[0], l_range[1] + 1))  # noqa: E741
        m = int(rng.integers(m_range[0], m_range[1] + 1))
        if l * m < weight:
            continue
        A = distinct_monomials(l, m)
        B = distinct_monomials(l, m)
        tally["sampled"] += 1
        n, w = bb_shape(l, m, A, B)
        if n_range is not None and not (n_range[0] <= n <= n_range[1]):
            tally["rejected_n"] += 1
            continue
        if max_weight is not None and w > max_weight:
            tally["rejected_w"] += 1
            continue
        tally["built"] += 1
        HX, HZ = build_bb(l, m, A, B)
        yield ({"family": "bb", "l": l, "m": m, "A": A, "B": B}, HX, HZ)


def sample_cyclic_gb(num, *, m_range=(300, 345), weight=(12, 16),
                     k_band=(120, 200), seed=0, trials_per_ideal=200,
                     audit=None):
    """Yield ``num`` cyclic generalized-bicycle candidates with k designed.

    H_X = [circ(a) | circ(b)] over Z_m, the family every one of the board's 25
    most efficient entries belongs to (issue #2778). For it
    k = 2 deg gcd(a, b, x^m - 1), so a random pair of supports encodes k = 2
    almost always: at check weight 12 on Z_315, Z_330, and Z_341, 150 of 180
    random draws had k = 2 and none had k above 12, and the 2026-08-15
    field note records the same at prime orders 251 to 347 and weights 8 to
    14. The frontier entries fix a divisor g of x^m - 1 first and draw a and
    b as sparse multiples of it, so this sampler does the same: an odd m from
    ``m_range``, a divisor whose degree puts 2 deg g inside ``k_band``, and a
    and b from the sparse multiples found by ``trials_per_ideal`` rounds of
    the kit's Prange search. ``weight`` is the band for each of a and b, so
    the check weight is their sum.

    Reach: n = 2m, so the defaults cover n = 600 to 690 at check weight 24 to
    32, which is where the frontier sits. A pair whose gcd is larger than g
    (k above the band) is discarded, since that degeneracy is what makes a
    random pair with large k have a tiny distance. Pass ``audit`` as a dict
    to receive counts under ``sampled``, ``no_divisor``, ``no_words``,
    ``k_outside`` and ``built``.

    What this does not do is make the family cheap to win in: the entries at
    the frontier came from long searches over many ideals and words per
    ideal (``research/cyclic_gb.py`` is that stack, with sympy), and
    ``research/literature/README.md`` is where the rest of the story is.
    """
    import random
    rng = np.random.default_rng(seed)
    prng = random.Random(seed)
    tally = audit if audit is not None else {}
    tally.update(sampled=0, no_divisor=0, no_words=0, k_outside=0, built=0)
    odd = [m for m in range(m_range[0], m_range[1] + 1) if m % 2]
    factors = {}
    built = 0
    while built < num:
        tally["sampled"] += 1
        m = int(rng.choice(odd))
        if m not in factors:
            factors[m] = gf2poly.factor_squarefree(gf2poly.x_pow_m_minus_1(m),
                                                   prng)
        g = gf2poly.designed_divisor(
            factors[m], (k_band[0] // 2, k_band[1] // 2), prng)
        if g is None:
            tally["no_divisor"] += 1
            continue
        words = gf2poly.sparse_multiples(m, g, weight, rng,
                                         trials=trials_per_ideal)
        if len(words) < 2:
            tally["no_words"] += 1
            continue
        i, j = rng.choice(len(words), size=2, replace=False)
        a, b = list(words[i]), list(words[j])
        k = gf2poly.designed_k(m, a, b)
        if not k_band[0] <= k <= k_band[1]:
            tally["k_outside"] += 1
            continue
        HX, HZ = gf2poly.cyclic_gb(m, a, b)
        tally["built"] += 1
        built += 1
        yield ({"family": "cyclic-gb", "m": m, "g": hex(g), "a": a, "b": b,
                "k": k}, HX, HZ)


def sample_dihedral(num, *, m_range=(30, 80), weight=4, seed=0):
    """Yield ``num`` random 2BGA candidates on dihedral groups D_m
    (order 2m, so n = 4m). Random supports of ``weight`` distinct elements.

    Reach at the defaults: m <= 80 caps n at 320, and weight=4 caps the check
    weight at 8. See ``sample_bb`` on why the weight cap is the binding one.
    """
    rng = np.random.default_rng(seed)
    for _ in range(num):
        m = int(rng.integers(m_range[0], m_range[1] + 1))
        order = 2 * m
        mul, _elems = dihedral(m)
        a = [int(x) for x in rng.choice(order, size=weight, replace=False)]
        b = [int(x) for x in rng.choice(order, size=weight, replace=False)]
        HX, HZ = build_2bga(mul, a, b)
        yield ({"family": "2bga-dihedral", "m": m, "a": a, "b": b}, HX, HZ)


def _tanner_connected(HX, HZ):
    """Is the qubit/check Tanner graph of (HX, HZ) connected? A direct sum is not, and the verifier rejects it."""
    H = np.concatenate([HX, HZ], axis=0).astype(bool)
    reached = np.zeros(H.shape[1], dtype=bool)
    reached[0] = True
    while True:
        checks = H[:, reached].any(axis=1)
        grown = H[checks].any(axis=0) | reached
        if grown.sum() == reached.sum():
            return bool(reached.all())
        reached = grown


def bbga_groups(max_order=24):
    """Return the default seed-group menu for ``sample_bbga``: ``(label, mul)`` pairs of order <= ``max_order``."""
    menu = [(f"C{m}", cyclic_product(m)[0]) for m in range(2, 13)]
    menu += [(f"D{m}", dihedral(m)[0]) for m in range(3, 7)]
    menu += [("A4", alt(4)[0]), ("S4", sym(4)[0]),
             ("C7x|C3", metacyclic(7, 3, 2)[0]), ("C5x|C4", metacyclic(5, 4, 2)[0])]
    return [(lab, mul) for lab, mul in menu if mul.shape[0] <= max_order]


def sample_bbga(num, *, groups=None, p_range=(1, 4), q_range=(1, 4), seed_terms=2,
                terms=(2, 4), max_weight=8, max_n=320, seed=0, audit=None):
    """Yield ``num`` random weighted-shift BBGA candidates (arXiv:2609.36213).

    Rebuild a winner with ``group_algebra.build_bbga`` from the ``spec``:
    ``{"family": "bbga", "group", "a", "b", "A", "B"}``. ``groups`` is a list
    of ``(label, mul)`` Cayley tables (default ``bbga_groups()``). Each shift
    seed is a random sum of 1..``seed_terms`` group elements, with at least
    one multi-element seed per candidate: when every seed is a single element
    and <P, Q> is transitive the code is permutation-equivalent to an abelian
    2BGA (the paper's Prop. 3.1), which ``sample_bb`` already covers. A and B
    get ``terms`` random distinct monomials P^u Q^v with u < 2p, v < 2q.

    Candidates whose heaviest check exceeds ``max_weight``, whose n exceeds
    ``max_n``, or whose Tanner graph is disconnected (a direct sum, which the
    verifier rejects) are skipped and do not count toward ``num``; pass
    ``audit`` as a dict to receive the skip counts.
    """
    rng = np.random.default_rng(seed)
    groups = groups or bbga_groups()
    tally = audit if audit is not None else {}
    for key in ("sampled", "rejected_n", "rejected_w", "rejected_disconnected", "built"):
        tally.setdefault(key, 0)
    built = 0
    while built < num:
        tally["sampled"] += 1
        label, mul = groups[int(rng.integers(len(groups)))]
        order = int(mul.shape[0])
        p = int(rng.integers(p_range[0], p_range[1] + 1))
        q = int(rng.integers(q_range[0], q_range[1] + 1))
        if 2 * p * q * order > max_n:
            tally["rejected_n"] += 1
            continue

        def seed_elem():
            w = int(rng.integers(1, seed_terms + 1))
            return sorted(int(x) for x in rng.choice(order, size=w, replace=False))

        a = [seed_elem() for _ in range(p)]
        b = [seed_elem() for _ in range(q)]
        if all(len(s) == 1 for s in a + b):
            idx = int(rng.integers(p + q))
            (a + b)[idx][:] = sorted(int(x) for x in rng.choice(order, size=2, replace=False))

        def monomials():
            t = int(rng.integers(terms[0], terms[1] + 1))
            pool = [(u, v) for u in range(2 * p) for v in range(2 * q)]
            pick = rng.choice(len(pool), size=min(t, len(pool)), replace=False)
            return sorted(pool[i] for i in pick)

        A, B = monomials(), monomials()
        HX, HZ = build_bbga(mul, a, b, A, B)
        w = int(max(HX.sum(1).max(), HZ.sum(1).max()))
        if w > max_weight:
            tally["rejected_w"] += 1
            continue
        if not _tanner_connected(HX, HZ):
            tally["rejected_disconnected"] += 1
            continue
        tally["built"] += 1
        built += 1
        yield ({"family": "bbga", "group": label, "a": a, "b": b, "A": A, "B": B}, HX, HZ)


def sample_metacyclic(num, *, order_range=(60, 160), weight=4, seed=0):
    """Yield ``num`` random 2BGA candidates on metacyclic groups
    Z_n x| Z_k with r^k = 1 mod n (order n*k). This is the family line that
    produced the board's [[294,8,19]].

    Reach at the defaults: order <= 160 caps n at 320, and weight=4 caps the
    check weight at 8. See ``sample_bb`` on why the weight cap is the binding one.
    """
    rng = np.random.default_rng(seed)
    valid_params = [(n, k, r)
                    for n in range(5, 60)
                    for k in range(2, 20)
                    if order_range[0] <= n * k <= order_range[1]
                    for r in range(2, n)
                    if pow(r, k, n) == 1]
    for _ in range(num):
        if not valid_params:
            break
        n, k, r = valid_params[rng.choice(len(valid_params))]
        order = n * k
        mul, _elems = metacyclic(n, k, r)
        a = [int(x) for x in rng.choice(order, size=weight, replace=False)]
        b = [int(x) for x in rng.choice(order, size=weight, replace=False)]
        HX, HZ = build_2bga(mul, a, b)
        yield ({"family": "2bga-metacyclic", "n": int(n), "k_m": int(k),
                "r": int(r), "a": a, "b": b}, HX, HZ)


def _primitive_root(q):
    """A generator of (Z/qZ)* for prime q, or None."""
    for r in range(2, q):
        if all(pow(r, k, q) != 1 for k in range(1, q - 1)):
            return r
    return None


def sample_kasai_affine(num, *, q_range=(7, 19), weight=4, seed=0):
    """Yield ``num`` random generalized-bicycle candidates on affine groups
    Aff(F_q) for prime q (the structure of Kasai's affine-coset construction).
    Group order N = q(q-1), realized as the metacyclic group Z_q x| Z_{q-1}
    with a primitive root acting; block size n = 2N.

    Reach at the defaults: q <= 19 gives N <= 342 and so n <= 684, which is the
    only sampler here whose n reaches the band the efficiency frontier sits in.
    weight=4 still caps the check weight at 8, against a frontier that is at
    least 12 throughout, so raise ``weight`` to compete. See ``sample_bb``.
    """
    rng = np.random.default_rng(seed)
    affine_groups = []
    for q in range(q_range[0], q_range[1] + 1):
        if all(q % i for i in range(2, int(q ** 0.5) + 1)) and q > 1:
            r = _primitive_root(q)
            if r is not None:
                affine_groups.append((q, q - 1, r))
    for _ in range(num):
        if not affine_groups:
            break
        q, k, r = affine_groups[rng.choice(len(affine_groups))]
        order = q * k
        mul, _elems = metacyclic(q, k, r)
        a = [int(x) for x in rng.choice(order, size=weight, replace=False)]
        b = [int(x) for x in rng.choice(order, size=weight, replace=False)]
        HX, HZ = build_2bga(mul, a, b)
        yield ({"family": "2bga-affine", "q": int(q), "a": a, "b": b}, HX, HZ)


if __name__ == "__main__":
    # Sweep a few hundred random BB codes and show the best + the frontier.
    recs = screen(sample_bb(300, seed=1), min_k=4, min_d=4, trials=200)
    print(f"screened -> {len(recs)} distinct codes with k>=4, d>=4")
    print("top 5 by efficiency k*d^2/n:")
    for r in recs[:5]:
        print(f"  [[{r['n']},{r['k']},{r['d']}]]  eff={r['efficiency']:.3f}")
    front = pareto_frontier(recs)
    params = sorted({(r["n"], r["k"], r["d"]) for r in front})   # dedup for display
    print(f"Pareto frontier ({len(front)} codes, {len(params)} distinct params): "
          + ", ".join(f"[[{n},{k},{d}]]" for n, k, d in params[:8]))
