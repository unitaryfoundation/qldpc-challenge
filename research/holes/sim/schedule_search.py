"""Greedy region-schedule search: recover circuit distance on hole codes.

Classes: bulk (fixed to a patch-optimal pair), ringX/ringZ (cells within
Chebyshev distance 1 of a hole bbox, by hole type), corrH/corrV (cells in
the hole row/column bands between holes). Candidates per class: the four
patch-optimal global pairs (both hook orientations). Coordinate-ascent with
the certified circuit distance (rounds = d, both bases) as objective.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import json
import time
from holey import build_greedy
from sim.circuits import prepare, circuit_distance

# the four patch-optimal (sigma_X, sigma_Z) pairs found by the d=5/d=8 scans
P1 = ({'SW': 0, 'SE': 2, 'NW': 1, 'NE': 3}, {'SW': 0, 'SE': 1, 'NW': 2, 'NE': 3})
P2 = ({'SW': 0, 'SE': 1, 'NW': 2, 'NE': 3}, {'SW': 0, 'SE': 2, 'NW': 1, 'NE': 3})
P3 = ({'SW': 3, 'SE': 1, 'NW': 2, 'NE': 0}, {'SW': 3, 'SE': 2, 'NW': 1, 'NE': 0})
P4 = ({'SW': 3, 'SE': 2, 'NW': 1, 'NE': 0}, {'SW': 3, 'SE': 1, 'NW': 2, 'NE': 0})
CANDS = [P1, P2, P3, P4]


def dual_grid(h, R, off, mX, pad):
    holes = []
    for i in range(mX):
        for j in range(mX):
            x0, y0 = pad + i * R, pad + j * R
            holes.append((x0, y0, x0 + h, y0 + h, 'X'))
    for i in range(mX - 1):
        for j in range(mX - 1):
            x0, y0 = pad + i * R + off, pad + j * R + off
            holes.append((x0, y0, x0 + h, y0 + h, 'Z'))
    span = (mX - 1) * R + h
    W = span + 2 * pad
    if W % 2 == 0:
        W += 1
    return W, holes


def classify_cells(code, holes, h, R, pad, mX):
    """cell -> class name for every check."""
    cls = {}
    xrow = [pad + i * R for i in range(mX)]        # X-hole origins
    zrow = [pad + i * R + R // 2 for i in range(mX - 1)]
    for typ, ci, (cx, cy), roles in code['_cells']:
        c = 'bulk'
        for (x0, y0, x1, y1, T) in holes:
            if x0 - 2 <= cx <= x1 and y0 - 2 <= cy <= y1:
                c = 'ring' + T
                break
        if c == 'bulk':
            in_xrow = any(y0 <= cy < y0 + h for y0 in xrow) or \
                      any(y0 <= cy < y0 + h for y0 in zrow)
            in_xcol = any(x0 <= cx < x0 + h for x0 in xrow) or \
                      any(x0 <= cx < x0 + h for x0 in zrow)
            if in_xrow and not in_xcol:
                c = 'corrH'
            elif in_xcol and not in_xrow:
                c = 'corrV'
        cls[(typ, ci)] = c
    return cls


def assemble(code, cls, assign):
    """assign: class -> (sx, sz) pair index into CANDS. Returns sched dict."""
    sched = {}
    for key, c in cls.items():
        sx, sz = CANDS[assign[c]]
        typ = key[0]
        sched[key] = sx if typ == 'X' else sz
    return sched


def search(h=2, mX=2, rounds=None):
    R, off, pad = 5 * h, 5 * h // 2, 5 * h
    W, holes = dual_grid(h, R, off, mX, pad)
    code = prepare(build_greedy(W, W, 0, 1, 0, 0, 1, holes=holes))
    code['holes'] = holes
    d_code = 4 * h
    rounds = rounds or d_code
    cls = classify_cells(code, holes, h, R, pad, mX)
    classes = sorted(set(cls.values()))
    print(f'classes: {classes}', flush=True)
    assign = {c: 0 for c in classes}   # start: everything P1

    def evaluate(a):
        sched = assemble(code, cls, a)
        sx, sz = CANDS[a['bulk']]
        return circuit_distance(code, sx, sz, rounds=rounds, sched=sched)

    best = evaluate(assign)
    print(f'start: d_circ={best} (code d={d_code}) assign={assign}', flush=True)
    improved = True
    while improved and best < d_code:
        improved = False
        for c in classes:
            for cand in range(len(CANDS)):
                if cand == assign[c]:
                    continue
                trial = dict(assign)
                trial[c] = cand
                t0 = time.time()
                d = evaluate(trial)
                print(f'  {c}<-P{cand+1}: d_circ={d} ({time.time()-t0:.0f}s)',
                      flush=True)
                if d is not None and d > best:
                    best, assign, improved = d, trial, True
                    print(f'  IMPROVED: {best} {assign}', flush=True)
                    break
            if improved:
                break
    print(f'FINAL: d_circ={best} / code d={d_code}, assign={assign}',
          flush=True)
    json.dump(dict(best=best, assign=assign),
              open(os.path.join(os.path.dirname(__file__),
                                f'schedule_h{h}_m{mX}.json'), 'w'), indent=1)
    return best, assign


if __name__ == '__main__':
    search(h=2, mX=2)
