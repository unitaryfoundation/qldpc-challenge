"""Stage 2: circuit-level Monte Carlo, dual-grid (region schedule, d_circ=6)
vs rotated patch (optimal schedule, d_circ=8), uniform depolarizing noise."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import json
import sinter
from holey import build_greedy
from sim.circuits import prepare, extraction_circuit
from sim.schedule_search import dual_grid, classify_cells, assemble, CANDS


def tasks():
    out = []
    # dual-grid m=2 and m=3, best known region schedule (bulk=P2, rest P1)
    for m in (2, 3):
        W, holes = dual_grid(2, 10, 5, m, 10)
        code = prepare(build_greedy(W, W, 0, 1, 0, 0, 1, holes=holes))
        code['holes'] = holes
        cls = classify_cells(code, holes, 2, 10, 10, m)
        assign = {c: (1 if c == 'bulk' else 0) for c in set(cls.values())}
        sched = assemble(code, cls, assign)
        sx, sz = CANDS[1]
        n = code['HX'].shape[1]
        nanc = len(code['X_checks']) + len(code['Z_checks'])
        k = len(code['_logicals_Z'])
        for basis in ('Z', 'X'):
            for p in (0.001, 0.002, 0.003, 0.005, 0.01):
                circ = extraction_circuit(code, sx, sz, p, 8, basis, sched)
                out.append(sinter.Task(circuit=circ, json_metadata=dict(
                    name=f'dual_m{m}', basis=basis, p=p, d=8, dcirc=6,
                    n=n, nanc=nanc, k=k, rounds=8)))
    # patch d=8 baseline, certified-optimal schedule
    pc = prepare(build_greedy(8, 8, 0, 1, 1, 0, 0))
    pc['holes'] = []
    sxp = {'SW': 0, 'SE': 2, 'NW': 1, 'NE': 3}
    szp = {'SW': 0, 'SE': 1, 'NW': 2, 'NE': 3}
    n = pc['HX'].shape[1]
    nanc = len(pc['X_checks']) + len(pc['Z_checks'])
    for basis in ('Z', 'X'):
        for p in (0.001, 0.002, 0.003, 0.005, 0.01):
            circ = extraction_circuit(pc, sxp, szp, p, 8, basis)
            out.append(sinter.Task(circuit=circ, json_metadata=dict(
                name='patch_d8', basis=basis, p=p, d=8, dcirc=8,
                n=n, nanc=nanc, k=1, rounds=8)))
    return out


if __name__ == '__main__':
    results = sinter.collect(
        tasks=tasks(), decoders=['pymatching'], num_workers=8,
        max_shots=2_000_000, max_errors=200, print_progress=True)
    rows = []
    for r in results:
        md = r.json_metadata
        p_any = r.errors / r.shots if r.shots else None
        prpl = None
        if p_any is not None and 0 <= p_any < 1:
            prpl = 1 - (1 - p_any) ** (1.0 / (md['rounds'] * md['k']))
        rows.append(dict(**md, shots=r.shots, errors=r.errors,
                         p_any=p_any, per_round_per_logical=prpl))
        print(f"{md['name']} {md['basis']} p={md['p']}: {r.errors}/{r.shots}"
              f" prpl={prpl if prpl is None else f'{prpl:.3e}'}", flush=True)
    json.dump(rows, open(os.path.join(os.path.dirname(__file__),
                                      'stage2_results.json'), 'w'), indent=1)
    print('saved stage2_results.json')
