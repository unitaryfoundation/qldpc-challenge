"""Hinge-cost simulated annealing for honest 2D-local layouts.

Minimising the raw interaction radius (max check diameter) directly, as
``fold_layout.anneal`` does, works well when the target is within reach of a
good integer-grid embedding.  When the honest class cap is just below what the
plain radius objective can reach, the search condenses into a minsep-respecting
blob that jams one lattice step above the cap (sqrt(50) for the bilayer cap
7.0) and never escapes: every single-qubit repair either violates the 1.0
minimum site spacing or pushes its check out to the blob's boundary.

This searcher prices the cap as a hinge instead of the radius itself::

    cost = W * sum_c max(0, diam(c) - target)^2  +  sum_c diam(c)^2

with a large W (default 1e6) so that eliminating cap violations dominates the
spread term.  Moves are relocations (biased toward the sites around the worst
check's centroid, so repairs are proposed where they can land) and qubit swaps,
with Metropolis acceptance under a geometric temperature schedule.  Coordinates
lie on an integer or half/quarter-integer lattice; capacity is ``layers`` per
site with distinct occupied sites at least 1.0 apart, i.e. exactly the two
honesty checks ``verify/qldpc_verify.py`` applies (site occupancy and site
spacing).

Reproduce the layout contributed to ``codes/150-30-10.json``::

    uv run python research/local2d/hinge_anneal.py codes/150-30-10.json \
        --out /tmp/layout.json

The defaults (target 7.0, layers 2, seeds 0-3, lattices h in {1.0, 0.5, 0.25},
padded boxes, 900k iterations per job) are the search that produced it.  The
script is stochastic beyond the seed order: any run that prints a radius at or
below the target with the occupancy and spacing checks passing is a valid
layout; the verifier, not this script, is the authority on that.
"""

import argparse
import json
import math
import os
import random
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # noqa: E402
from fold_layout import anneal, box_sites, radius  # noqa: E402

TARGET = 7.0  # bilayer class cap (verify/qldpc_verify.py LOCALITY_CLASSES)
HINGE_W = 1_000_000.0
PAD = 6  # integer-init offset into the padded search box
SEEDS = (0, 1, 2, 3)
LATTICES = ((1.0, 24, 20), (0.5, 26, 22), (0.25, 26, 22))  # (step, box w, box h)
ITERS = 900_000


def load_checks(path):
    """Check supports and qubit count from a codes/ JSON entry (X rows then Z)."""
    doc = json.load(open(path))
    return doc["checks"]["X"] + doc["checks"]["Z"], doc["n"]


def integer_init(checks, n, seed=0, iters=200_000):
    """Embed the checks on an integer grid with fold_layout's layers-2 annealer."""
    coords, _ = anneal(checks, n, box_sites(16, 14), layers=2, seed=seed, iters=iters)
    return coords


def check_diameter(checks, ci, pts):
    """Measure one check the way the verifier does: max pairwise distance."""
    s = checks[ci]
    m = 0.0
    for a in range(len(s)):
        xa, ya = pts[s[a]]
        for b in range(a + 1, len(s)):
            dx = xa - pts[s[b]][0]
            dy = ya - pts[s[b]][1]
            d = math.sqrt(dx * dx + dy * dy)
            m = max(m, d)
    return m


def cost_of(dias, target, w):
    """Hinge-dominant objective: violations dominate, spread breaks ties."""
    c = 0.0
    for d in dias:
        if d > target:
            c += w * (d - target) ** 2
        c += d * d
    return c


def run_job(job):
    """One annealing job: (seed, lattice step, box w, box h, init, iters)."""
    seed, h, w, hh, init, iters, checks, n = job
    rng = random.Random(seed)
    pts = [[round((c[0] + PAD) / h) * h, round((c[1] + PAD) / h) * h] for c in init]
    sx = [x * h for x in range(int(w / h) + 1)]
    sy = [y * h for y in range(int(hh / h) + 1)]
    touch = [[] for _ in range(n)]
    for ci, s in enumerate(checks):
        for q in s:
            touch[q].append(ci)

    def occ_ok(q, x, y):
        cnt = 0
        for i in range(n):
            if i == q:
                continue
            d = math.hypot(x - pts[i][0], y - pts[i][1])
            if d <= 1e-9:
                cnt += 1
            elif d < 1.0 - 1e-9:
                return False
        return cnt <= 1

    dia = [check_diameter(checks, c, pts) for c in range(len(checks))]
    cost = cost_of(dia, TARGET, HINGE_W)
    best = (max(dia), [list(p) for p in pts])

    def accept(ncost):
        nonlocal cost
        delta = ncost - cost
        if delta <= 0 or rng.random() < math.exp(-delta / max(t_val, 1e-12)):
            cost = ncost
            return True
        return False

    for it in range(iters):
        t_val = 2000.0 * (0.5 / 2000.0) ** (it / iters)
        r = rng.random()
        mx = max(dia)
        worst = [c for c in range(len(dia)) if dia[c] >= mx - 1e-12]
        if 0.45 <= r < 0.62:
            # swap two qubits (either a worst-check qubit, or two random ones)
            if r < 0.55:
                ci0 = rng.choice(worst)
                q = rng.choice(checks[ci0])
            else:
                q = rng.randrange(n)
            q2 = rng.randrange(n)
            old, old2 = list(pts[q]), list(pts[q2])
            if q2 == q or old2 == old:
                continue
            pts[q], pts[q2] = old2, list(old)
            aff = sorted(set(touch[q]) | set(touch[q2]))
            old_d = [dia[c] for c in aff]
            for c in aff:
                dia[c] = check_diameter(checks, c, pts)
            if accept(cost_of(dia, TARGET, HINGE_W)):
                if max(dia) < best[0] - 1e-12:
                    best = (max(dia), [list(p) for p in pts])
                    if best[0] <= TARGET:
                        return best[0], best[1], it, seed, "feasible"
            else:
                pts[q], pts[q2] = list(old), list(old2)
                for c, d in zip(aff, old_d):
                    dia[c] = d
            continue
        if r < 0.45:
            # biased relocation: near the worst check's centroid, where a repair can land
            ci0 = rng.choice(worst)
            q = rng.choice(checks[ci0])
            cx = sum(pts[x][0] for x in checks[ci0]) / len(checks[ci0])
            cy = sum(pts[x][1] for x in checks[ci0]) / len(checks[ci0])
            x = round((cx + rng.uniform(-5, 5)) / h) * h
            y = round((cy + rng.uniform(-5, 5)) / h) * h
        else:
            q = rng.randrange(n)
            x = rng.choice(sx)
            y = rng.choice(sy)
        old = list(pts[q])
        if not (0 <= x <= w and 0 <= y <= hh) or (x, y) == (old[0], old[1]):
            continue
        if not occ_ok(q, x, y):
            continue
        pts[q] = [x, y]
        aff = touch[q]
        old_d = [dia[c] for c in aff]
        for c in aff:
            dia[c] = check_diameter(checks, c, pts)
        if accept(cost_of(dia, TARGET, HINGE_W)):
            if max(dia) < best[0] - 1e-12:
                best = (max(dia), [list(p) for p in pts])
                if best[0] <= TARGET:
                    return best[0], best[1], it, seed, "feasible"
        else:
            pts[q] = old
            for c, d in zip(aff, old_d):
                dia[c] = d
    return best[0], best[1], iters, seed, "limit"


def honesty(coords, layers):
    """(max qubits per site, min spacing between distinct sites): the verifier's checks."""
    mult = Counter(tuple(p) for p in coords)
    sites = sorted(mult)
    md = min(math.dist(a, b) for i, a in enumerate(sites) for b in sites[i + 1 :]) if len(sites) > 1 else float("inf")
    return max(mult.values()), md


def main(argv=None):
    """Search layers-2 layouts for a codes/ entry; --out receives the best one."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("doc", help="codes/<n>-<k>-<d>.json to build a layout for")
    ap.add_argument("--out", help="write the best qualifying layout here (JSON)")
    ap.add_argument("--target", type=float, default=TARGET, help="interaction-radius cap to hinge against")
    ap.add_argument("--iters", type=int, default=ITERS, help="annealing iterations per job")
    ap.add_argument("--seeds", type=int, default=len(SEEDS), help="number of seeds")
    args = ap.parse_args(argv)

    checks, n = load_checks(args.doc)
    init = integer_init(checks, n)
    jobs = [(seed, h, w, hh, init, args.iters, checks, n) for seed in range(args.seeds) for h, w, hh in LATTICES]
    best = None
    with ProcessPoolExecutor() as ex:
        for r, coords, it, seed, tag in ex.map(run_job, jobs):
            print(f"  seed {seed}: {tag} r={r:.6f} it={it}")
            if tag == "feasible" and (best is None or r < best[0]):
                best = (r, coords)
    if best is None:
        print(f"no layout <= {args.target} found; closest {r:.6f}")
        return 1
    mult, spacing = honesty(best[1], layers=2)
    measured = radius(checks, best[1])
    ok = measured <= args.target and mult <= 2 and spacing >= 1.0 - 1e-9
    print(f"radius {measured:.6f} | max/site {mult} | min spacing {spacing:.4f} -> {'valid' if ok else 'INVALID'}")
    if not ok:
        return 1
    if args.out:
        json.dump({"coordinates": best[1], "layers": 2, "interaction_radius": best[0]}, open(args.out, "w"), indent=1)
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
