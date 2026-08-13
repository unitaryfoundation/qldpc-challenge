"""Schedule search v3: parallel evaluations, triage filter, basis short-circuit.

Speedups over v2 (all algorithmic; the per-evaluation core is stim's C++):
- pool of workers evaluates candidate moves concurrently;
- rounds=3 triage is a valid upper bound on d_circ (monotone in rounds),
  so candidates triaging <= best skip the full rounds=d evaluation;
- the Z basis (historically binding) is evaluated first and short-circuits.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import json
import time
import random
import itertools
from multiprocessing import Pool

A = {'SW': 0, 'SE': 1, 'NW': 2, 'NE': 3}
B = {'SW': 0, 'SE': 2, 'NW': 1, 'NE': 3}
SIGMAS = [A, B]

_CTX = {}


def _init(h, mX):
    from holey import build_greedy
    from sim.circuits import prepare
    from sim.schedule_search import dual_grid, classify_cells
    R, off, pad = 5 * h, 5 * h // 2, 5 * h
    W, holes = dual_grid(h, R, off, mX, pad)
    code = prepare(build_greedy(W, W, 0, 1, 0, 0, 1, holes=holes))
    code['holes'] = holes
    _CTX['code'] = code
    _CTX['cls'] = classify_cells(code, holes, h, R, pad, mX)
    _CTX['d'] = 4 * h


def _dcirc(assign_items, rounds, best):
    """Upper-bounded circuit distance with basis short-circuit."""
    import stim
    from sim.circuits import extraction_circuit
    assign = dict(assign_items)
    code, cls = _CTX['code'], _CTX['cls']
    sched = {}
    for key, c in cls.items():
        ix, iz = assign[c]
        sched[key] = SIGMAS[ix] if key[0] == 'X' else SIGMAS[iz]
    bx, bz = assign['bulk']
    dmin = None
    for basis in ('Z', 'X'):
        circ = extraction_circuit(code, SIGMAS[bx], SIGMAS[bz], 1e-3,
                                  rounds, basis, sched)
        try:
            err = circ.shortest_graphlike_error(
                canonicalize_circuit_errors=True)
        except ValueError:
            return None
        d = len(err)
        dmin = d if dmin is None else min(dmin, d)
        if dmin <= best:
            return dmin        # short-circuit: cannot beat best
    return dmin


def _worker(args):
    assign_items, best, d_code = args
    tri = _dcirc(assign_items, 3, best)
    if tri is None or tri <= best:
        return assign_items, tri, False       # triaged out (or invalid)
    full = _dcirc(assign_items, d_code, best)
    return assign_items, full, True


def search(h=2, mX=2, budget_hours=8.0, workers=7, seed=20260814):
    random.seed(seed)
    _init(h, mX)                              # parent context for classes
    cls = _CTX['cls']
    d_code = _CTX['d']
    classes = sorted(set(cls.values()))
    combos = [(i, j) for i in range(2) for j in range(2)]
    ckpt = os.path.join(os.path.dirname(__file__),
                        f'schedule3_h{h}_m{mX}.json')
    print(f'classes: {classes}, workers={workers}', flush=True)

    pool = Pool(workers, initializer=_init, initargs=(h, mX))
    visited = set()
    t_end = time.time() + budget_hours * 3600
    best, best_assign = 0, None
    restart = 0
    while time.time() < t_end and best < d_code:
        restart += 1
        assign = {c: random.choice(combos) for c in classes}
        cur_items = tuple(sorted(assign.items()))
        r = pool.apply(_worker, ((cur_items, 0, d_code),))
        cur = r[1] or 0
        print(f'restart {restart}: start d<={cur}', flush=True)
        stall = 0
        while time.time() < t_end and best < d_code and stall < 2:
            # batch: all unvisited single- and sampled two-class moves
            trials = []
            for c in classes:
                for cand in combos:
                    t2 = dict(assign)
                    t2[c] = cand
                    it = tuple(sorted(t2.items()))
                    if it not in visited:
                        trials.append(it)
            pairs = [(c1, c2) for i, c1 in enumerate(classes)
                     for c2 in classes[i + 1:]]
            random.shuffle(pairs)
            for c1, c2 in pairs[:6]:
                for k1, k2 in itertools.product(combos, combos):
                    t2 = dict(assign)
                    t2[c1], t2[c2] = k1, k2
                    it = tuple(sorted(t2.items()))
                    if it not in visited:
                        trials.append(it)
            random.shuffle(trials)
            trials = trials[:workers * 6]
            visited.update(trials)
            if not trials:
                stall += 1
                continue
            args = [(it, max(best, cur - 1), d_code) for it in trials]
            results = pool.map(_worker, args)
            improved = False
            for it, d, was_full in results:
                if d is None:
                    continue
                if was_full and d > cur:
                    assign, cur, improved = dict(it), d, True
                    if d > best:
                        best, best_assign = d, dict(it)
                        print(f'  NEW BEST {d}: {dict(it)}', flush=True)
                        json.dump(dict(best=d, assign={k: list(v) for k, v
                                                       in dict(it).items()}),
                                  open(ckpt, 'w'), indent=1)
            if not improved:
                stall += 1
            print(f'  sweep: {len(trials)} candidates, cur={cur}, '
                  f'best={best}, visited={len(visited)}', flush=True)
        print(f'restart {restart} done: best={best}', flush=True)
    pool.close()
    print(f'FINAL best={best} assign={best_assign} '
          f'({len(visited)} states)', flush=True)


if __name__ == '__main__':
    search()


def exhaustive(h=2, mX=2, workers=7):
    """Certify the optimum over ALL class assignments (4^|classes|)."""
    _init(h, mX)
    cls = _CTX['cls']
    d_code = _CTX['d']
    classes = sorted(set(cls.values()))
    combos = [(i, j) for i in range(2) for j in range(2)]
    ckpt = os.path.join(os.path.dirname(__file__),
                        f'schedule3_exhaustive_h{h}_m{mX}.json')
    space = [tuple(sorted(zip(classes, choice)))
             for choice in itertools.product(combos, repeat=len(classes))]
    print(f'exhaustive: {len(space)} assignments, workers={workers}',
          flush=True)
    pool = Pool(workers, initializer=_init, initargs=(h, mX))
    best, best_assign, done = 0, None, 0
    t0 = time.time()
    CH = workers * 8
    for i in range(0, len(space), CH):
        batch = space[i:i + CH]
        args = [(it, best, d_code) for it in batch]
        for it, d, was_full in pool.map(_worker, args):
            done += 1
            if d is not None and was_full and d > best:
                best, best_assign = d, dict(it)
                print(f'  NEW BEST {d}: {best_assign}', flush=True)
                json.dump(dict(best=d, done=done,
                               assign={k: list(v) for k, v
                                       in best_assign.items()}),
                          open(ckpt, 'w'), indent=1)
        if (i // CH) % 10 == 0:
            rate = done / (time.time() - t0)
            eta = (len(space) - done) / rate / 60
            print(f'  {done}/{len(space)} best={best} '
                  f'({rate:.1f}/s, eta {eta:.0f} min)', flush=True)
    pool.close()
    json.dump(dict(best=best, done=done, exhaustive=True,
                   assign={k: list(v) for k, v in (best_assign or {}).items()}),
              open(ckpt, 'w'), indent=1)
    print(f'EXHAUSTIVE RESULT: best={best} over {done} assignments',
          flush=True)
