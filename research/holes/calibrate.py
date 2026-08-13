"""Calibration sweep: inter-hole string metric + lasso law."""
import json
import time
import numpy as np
from holey import build_greedy
from graphdist import graph_distance

results = []


def run(name, W, H, holes):
    t0 = time.time()
    c = build_greedy(W, H, 0, 1, 0, 0, 1, holes=holes)
    c['holes'] = holes
    dX, sX = graph_distance(c, 'X')
    dZ, sZ = graph_distance(c, 'Z')
    rec = dict(name=name, n=c['n'], k=c['k'], comm=bool(c['comm']),
               dX=dX, dZ=dZ, t=round(time.time() - t0, 1),
               supX=sorted(tuple(c['qubits'][q]) for q in (sX or [])),
               supZ=sorted(tuple(c['qubits'][q]) for q in (sZ or [])))
    results.append(rec)
    print(f"{name}: [[{rec['n']},{rec['k']}]] dX={dX} dZ={dZ} ({rec['t']}s)",
          flush=True)


h = 2
pad = 12  # boundary gap: boundary strings cost >= pad, keep > inter-hole values

# --- two X-holes, varying offset vector (corner-to-corner) ---
for (ox, oy) in [(6, 0), (8, 0), (10, 0), (6, 6), (8, 8), (10, 10),
                 (6, 3), (8, 4), (4, 4), (5, 5)]:
    x0, y0 = pad, pad
    x1, y1 = x0 + ox, y0 + oy
    W = x1 + h + pad
    H = max(y1, y0) + h + pad
    if W % 2 == 0:
        W += 1
    if H % 2 == 0:
        H += 1
    holes = [(x0, y0, x0 + h, y0 + h, 'X'), (x1, y1, x1 + h, y1 + h, 'X')]
    run(f'XX off=({ox},{oy})', W, H, holes)

# --- X-hole + Z-hole (lasso law), varying offset ---
for (ox, oy) in [(4, 0), (6, 0), (8, 0), (4, 4), (6, 6), (3, 3), (3, 0)]:
    x0, y0 = pad, pad
    x1, y1 = x0 + ox, y0 + oy
    W = x1 + h + pad
    H = max(y1, y0) + h + pad
    if W % 2 == 0:
        W += 1
    if H % 2 == 0:
        H += 1
    holes = [(x0, y0, x0 + h, y0 + h, 'X'), (x1, y1, x1 + h, y1 + h, 'Z')]
    run(f'XZ off=({ox},{oy})', W, H, holes)

# --- larger same-type holes at diagonal offset (h-dependence of diag metric) ---
for h2, off in [(3, 8), (4, 10)]:
    x0 = y0 = pad
    x1 = y1 = x0 + off
    W = H = x1 + h2 + pad + (1 - (x1 + h2 + pad) % 2)
    holes = [(x0, y0, x0 + h2, y0 + h2, 'X'), (x1, y1, x1 + h2, y1 + h2, 'X')]
    run(f'XX h={h2} diag off=({off},{off})', W, H, holes)

json.dump(results, open('calibration.json', 'w'), indent=1)
print('saved calibration.json')
