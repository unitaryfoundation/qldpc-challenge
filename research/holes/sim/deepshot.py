"""Deep-shot X-basis verification at low p, certified m=2 config vs patch."""
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
    W, holes = dual_grid(2, 10, 5, 2, 10)
    code = prepare(build_greedy(W, W, 0, 1, 0, 0, 1, holes=holes))
    code['holes'] = holes
    cls = classify_cells(code, holes, 2, 10, 10, 2)
    assign = {c: (1 if c == 'bulk' else 0) for c in set(cls.values())}
    sched = assemble(code, cls, assign)
    sx, sz = CANDS[1]
    for p in (0.001, 0.0015):
        circ = extraction_circuit(code, sx, sz, p, 8, 'X', sched)
        out.append(sinter.Task(circuit=circ, json_metadata=dict(
            name='dual_m2', basis='X', p=p, k=6, rounds=8)))
    pc = prepare(build_greedy(8, 8, 0, 1, 1, 0, 0))
    pc['holes'] = []
    sxp = {'SW': 0, 'SE': 2, 'NW': 1, 'NE': 3}
    szp = {'SW': 0, 'SE': 1, 'NW': 2, 'NE': 3}
    for p in (0.001, 0.0015):
        circ = extraction_circuit(pc, sxp, szp, p, 8, 'X')
        out.append(sinter.Task(circuit=circ, json_metadata=dict(
            name='patch_d8', basis='X', p=p, k=1, rounds=8)))
    return out


if __name__ == '__main__':
    results = sinter.collect(tasks=tasks(), decoders=['pymatching'],
                             num_workers=7, max_shots=100_000_000,
                             max_errors=300)
    rows = []
    for r in results:
        md = r.json_metadata
        p_any = r.errors / r.shots if r.shots else None
        prpl = (1 - (1 - p_any) ** (1.0 / (8 * md['k'])))\
            if p_any is not None and p_any < 1 else None
        rows.append(dict(**md, shots=r.shots, errors=r.errors, prpl=prpl))
        print(f"{md['name']} X p={md['p']}: {r.errors}/{r.shots} "
              f"prpl={'%.3e' % prpl if prpl is not None else '?'}", flush=True)
    json.dump(rows, open(os.path.join(os.path.dirname(__file__),
                                      'deepshot_results.json'), 'w'), indent=1)
    print('saved', flush=True)
