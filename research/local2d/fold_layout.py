"""Generic 2D layout search: fold a periodic code into the plane.

Not research/foldbound.py, which folds a code onto an orbit-constant subspace to
bound its distance; the two share a verb and nothing else.

Given a CSS code's check supports, assign every qubit an integer grid site
(at most `layers` qubits per site; distinct integer sites are >= 1 apart by
construction) so as to minimise the interaction radius = max check diameter.
This is the "folding" step: a periodic code drawn naively has wraparound
checks that span the whole lattice; a good embedding of the quotient brings
them back together.

Simulated annealing over assignments with capacity `layers` per site, using an
incremental cost update (only the checks touching a moved qubit change).  The
reported radius is recomputed from scratch and is exactly the quantity
`verify/qldpc_verify.py` measures.
"""
import math
import random


def _diam(sup, site_of, sites):
    m = 0.0
    for i in range(len(sup)):
        xi, yi = sites[site_of[sup[i]]]
        for j in range(i + 1, len(sup)):
            xj, yj = sites[site_of[sup[j]]]
            dd = (xi - xj) ** 2 + (yi - yj) ** 2
            if dd > m:
                m = dd
    return math.sqrt(m)


def radius(checks, coords):
    """Max check diameter for an explicit coordinate list (verifier's rule)."""
    best = 0.0
    for s in checks:
        for i in range(len(s)):
            for j in range(i + 1, len(s)):
                d = math.dist(coords[s[i]], coords[s[j]])
                if d > best:
                    best = d
    return best


def anneal(checks, n, sites, layers=1, seed=0, iters=200000,
           t_hi=0.35, t_lo=0.004, init=None, power=6.0):
    """Return (coords, radius) for the best layout found."""
    rng = random.Random(seed)
    ns = len(sites)
    assert ns * layers >= n, f"not enough sites: {ns}*{layers} < {n}"
    touching = [[] for _ in range(n)]
    for ci, s in enumerate(checks):
        for q in s:
            touching[q].append(ci)
    touching = [sorted(set(t)) for t in touching]

    if init is not None:
        site_of = list(init)
    else:
        pool = [s for s in range(ns) for _ in range(layers)]
        rng.shuffle(pool)
        site_of = pool[:n]
    occ = [0] * ns
    for s in site_of:
        occ[s] += 1

    dia = [_diam(s, site_of, sites) for s in checks]
    cost = sum(d ** power for d in dia)
    best_r = max(dia)
    best = list(site_of)
    scale = max(cost / len(checks), 1e-9)

    for it in range(iters):
        T = t_hi * (t_lo / t_hi) ** (it / iters)
        q = rng.randrange(n)
        old = site_of[q]
        if rng.random() < 0.5:
            new = rng.randrange(ns)
            if new == old or occ[new] >= layers:
                continue
            undo = [(q, old)]
            site_of[q] = new
            occ[old] -= 1
            occ[new] += 1
            aff = touching[q]
        else:
            q2 = rng.randrange(n)
            s2 = site_of[q2]
            if q2 == q or s2 == old:
                continue
            undo = [(q, old), (q2, s2)]
            site_of[q] = s2
            site_of[q2] = old
            aff = sorted(set(touching[q]) | set(touching[q2]))

        newd = [_diam(checks[c], site_of, sites) for c in aff]
        delta = sum(d ** power for d in newd) - sum(dia[c] ** power for c in aff)
        if delta <= 0 or rng.random() < math.exp(-delta / max(T * scale, 1e-12)):
            cost += delta
            for c, d in zip(aff, newd):
                dia[c] = d
            r = max(dia)
            if r < best_r - 1e-12:
                best_r = r
                best = list(site_of)
        else:
            for qq, ss in undo:
                occ[site_of[qq]] -= 1
            for qq, ss in undo:
                site_of[qq] = ss
                occ[ss] += 1

    return [list(sites[s]) for s in best], best_r


def box_sites(w, h):
    return [(x, y) for x in range(w) for y in range(h)]


def search_layout(checks, n, layers, target, seed0=0, boxes=None, iters=150000,
                  restarts=4, verbose=False):
    """Try several bounding boxes / seeds; return the best (coords, radius)."""
    need = math.ceil(n / layers)
    if boxes is None:
        boxes = []
        side = math.ceil(math.sqrt(need))
        for extra in range(0, 4):
            for w in range(max(1, side - 2), side + extra + 2):
                h = math.ceil(need / w)
                if w * h >= need and (w, h + extra) not in boxes:
                    boxes.append((w, h + extra))
        boxes = sorted(set(boxes), key=lambda b: (b[0] * b[1], max(b)))[:8]
    bestc, bestr = None, float("inf")
    for (w, h) in boxes:
        if w * h * layers < n:
            continue
        for r in range(restarts):
            coords, rad = anneal(checks, n, box_sites(w, h), layers=layers,
                                 seed=seed0 + 1000 * r + w, iters=iters)
            if verbose:
                print(f"    box {w}x{h} seed{r}: r={rad:.4f}")
            if rad < bestr:
                bestc, bestr = coords, rad
            if bestr <= target:
                return bestc, bestr
    return bestc, bestr
