"""Stage-0 full sweep: phenomenological memory, holes vs patches, sinter."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import json
import numpy as np
import sinter
from holey import build_greedy
from sim.phenom import memory_circuit
import distance as dst
from packing import fast_logical_basis


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


def tasks():
    codes = {}
    for m in (2, 3, 4):
        W, holes = dual_grid(2, 10, 5, m, 10)
        c = build_greedy(W, W, 0, 1, 0, 0, 1, holes=holes)
        codes[f'dual_h2_m{m}'] = (c, 8)
    W, holes = dual_grid(4, 20, 10, 2, 18)
    c = build_greedy(W, W, 0, 1, 0, 0, 1, holes=holes)
    codes['dual_h4_m2'] = (c, 16)
    codes['patch_d8'] = (build_greedy(8, 8, 0, 1, 1, 0, 0), 8)
    codes['patch_d16'] = (build_greedy(16, 16, 0, 1, 1, 0, 0), 16)
    out = []
    for name, (c, d) in codes.items():
        n = c['HX'].shape[1]
        for basis in ('Z', 'X'):
            if basis == 'Z':
                H_det = c['HZ']
                logicals = fast_logical_basis(c['HX'], c['HZ'])
            else:
                H_det = c['HX']
                logicals = fast_logical_basis(c['HZ'], c['HX'])
            k = len(logicals)
            for p in (0.005, 0.0075, 0.01, 0.015, 0.02, 0.03):
                circ = memory_circuit(H_det, logicals, n, p, p, d, basis)
                out.append(sinter.Task(
                    circuit=circ,
                    json_metadata=dict(name=name, basis=basis, p=p, d=d,
                                       n=n, k=k, rounds=d)))
    return out


if __name__ == '__main__':
    results = sinter.collect(
        tasks=tasks(),
        decoders=['pymatching'],
        num_workers=8,
        max_shots=500_000,
        max_errors=150,
        print_progress=True,
    )
    rows = []
    for r in results:
        md = r.json_metadata
        shots, errs = r.shots, r.errors
        p_any = errs / shots if shots else None
        per_round_logical = None
        if p_any is not None and p_any < 1:
            per_round_logical = 1 - (1 - p_any) ** (1.0 / (md['rounds'] * md['k']))
        rows.append(dict(**md, shots=shots, errors=errs, p_any=p_any,
                         per_round_per_logical=per_round_logical))
        print(f"{md['name']} {md['basis']} p={md['p']}: "
              f"{errs}/{shots} p_any={p_any:.2e} "
              f"prpl={per_round_logical:.3e}" if p_any else f"{md} no data",
              flush=True)
    json.dump(rows, open(os.path.join(os.path.dirname(__file__),
                                      'stage0_results.json'), 'w'), indent=1)
    print('saved stage0_results.json')
