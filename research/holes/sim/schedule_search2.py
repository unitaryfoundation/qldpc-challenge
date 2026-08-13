"""Overnight schedule search v2: decoupled per-class sigmas, visited-set
plateau walks, coordinated two-class moves, random restarts, time budget."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import json
import time
import random
from holey import build_greedy
from sim.circuits import prepare, circuit_distance
from sim.schedule_search import dual_grid, classify_cells

A = {'SW': 0, 'SE': 1, 'NW': 2, 'NE': 3}   # hook pair horizontal (top edge)
B = {'SW': 0, 'SE': 2, 'NW': 1, 'NE': 3}   # hook pair vertical (right edge)
SIGMAS = [A, B]
random.seed(20260814)


def main(h=2, mX=2, budget_hours=8.0):
    R, off, pad = 5 * h, 5 * h // 2, 5 * h
    W, holes = dual_grid(h, R, off, mX, pad)
    code = prepare(build_greedy(W, W, 0, 1, 0, 0, 1, holes=holes))
    code['holes'] = holes
    d_code = 4 * h
    cls = classify_cells(code, holes, h, R, pad, mX)
    classes = sorted(set(cls.values()))
    print(f'classes: {classes}', flush=True)

    def key(a):
        return tuple(sorted(a.items()))

    def evaluate(a):
        sched = {}
        for k2, c in cls.items():
            ix, iz = a[c]
            sched[k2] = SIGMAS[ix] if k2[0] == 'X' else SIGMAS[iz]
        bx, bz = a['bulk']
        return circuit_distance(code, SIGMAS[bx], SIGMAS[bz],
                                rounds=d_code, sched=sched)

    t_end = time.time() + budget_hours * 3600
    visited = {}
    best_global, best_assign = 0, None

    def score(a):
        k2 = key(a)
        if k2 in visited:
            return visited[k2]
        d = evaluate(a)
        visited[k2] = d
        return d

    combos = [(i, j) for i in range(2) for j in range(2)]
    restart = 0
    while time.time() < t_end:
        restart += 1
        assign = {c: random.choice(combos) for c in classes}
        cur = score(assign) or 0
        print(f'restart {restart}: start d={cur} {assign}', flush=True)
        stall = 0
        while time.time() < t_end and cur < d_code and stall < 3:
            moved = False
            # single-class moves, then sampled two-class moves
            moves = [(c,) for c in classes]
            pairs = [(c1, c2) for i, c1 in enumerate(classes)
                     for c2 in classes[i + 1:]]
            random.shuffle(pairs)
            moves += pairs[:10]
            random.shuffle(moves)
            for mv in moves:
                options = [combos] * len(mv)
                import itertools
                for choice in itertools.product(*options):
                    trial = dict(assign)
                    changed = False
                    for c, ch in zip(mv, choice):
                        if trial[c] != ch:
                            trial[c] = ch
                            changed = True
                    if not changed or key(trial) in visited:
                        continue
                    d = score(trial)
                    dd = d or 0
                    if dd > cur or (dd == cur and random.random() < 0.5):
                        if dd >= cur:
                            assign, cur = trial, dd
                            moved = True
                            if dd > (best_global or 0):
                                best_global, best_assign = dd, dict(trial)
                                print(f'  NEW BEST {dd}: {trial}', flush=True)
                                json.dump(
                                    dict(best=dd, assign={k: list(v) for k, v
                                                          in trial.items()}),
                                    open(os.path.join(
                                        os.path.dirname(__file__),
                                        f'schedule2_h{h}_m{mX}.json'), 'w'),
                                    indent=1)
                            break
                if moved:
                    break
            if not moved:
                stall += 1
        print(f'restart {restart} done: cur={cur} best={best_global} '
              f'({len(visited)} states)', flush=True)
        if best_global >= d_code:
            break
    print(f'FINAL best={best_global} assign={best_assign} '
          f'({len(visited)} states explored)', flush=True)


if __name__ == '__main__':
    main()
