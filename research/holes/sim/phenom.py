"""Stage 0: phenomenological-noise memory experiments for CSS codes.

Noisy MPP stabilizer measurements (flip prob q) + data X/Z errors (p) per
round; no ancillas, no hooks. Memory-Z protects Z-logicals against X
errors (and symmetrically). Decoding: MWPM on the stim DEM (graphlike for
boundary-edge codes). Logical error rate reported per round per logical.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np
import stim
import pymatching


def memory_circuit(H_det, logicals, n, p, q, rounds, basis='Z'):
    """Phenomenological memory experiment.

    H_det: stabilizers of the type that DETECTS the errors (for memory-Z
    with X data errors: H_det = HZ, the Z-stabilizers). logicals: basis of
    the protected logical operators (Z-type), rows over data qubits.
    """
    err = 'X_ERROR' if basis == 'Z' else 'Z_ERROR'
    pauli = 'Z' if basis == 'Z' else 'X'
    m = H_det.shape[0]
    c = stim.Circuit()
    c.append('R' if basis == 'Z' else 'RX', range(n))
    supports = [np.nonzero(H_det[i])[0] for i in range(m)]

    def mpp_all(noise):
        for sup in supports:
            targets = []
            for j, qb in enumerate(sup):
                if j:
                    targets.append(stim.target_combiner())
                targets.append(stim.target_z(qb) if pauli == 'Z'
                               else stim.target_x(qb))
            c.append('MPP', targets, noise)

    # round 0: deterministic reference (noiseless projection)
    mpp_all(0.0)
    for i in range(m):
        c.append('DETECTOR', [stim.target_rec(-m + i)])
    for _ in range(rounds):
        c.append(err, range(n), p)
        mpp_all(q)
        for i in range(m):
            c.append('DETECTOR',
                     [stim.target_rec(-m + i), stim.target_rec(-2 * m + i)])
    # final data measurement (noiseless readout round)
    c.append('M' if basis == 'Z' else 'MX', range(n))
    for i in range(m):
        prev = -n - m + i
        recs = [stim.target_rec(prev)]
        recs += [stim.target_rec(-n + int(qb)) for qb in supports[i]]
        c.append('DETECTOR', recs)
    for li, L in enumerate(logicals):
        recs = [stim.target_rec(-n + int(qb)) for qb in np.nonzero(L)[0]]
        c.append('OBSERVABLE_INCLUDE', recs, li)
    return c


def run_memory(code, p, rounds=None, shots=20000, basis='Z'):
    """Returns (per-round per-logical logical error rate, k, shots)."""
    import distance as dst
    from packing import fast_logical_basis
    n = code['HX'].shape[1]
    if basis == 'Z':
        H_det, logicals = code['HZ'], fast_logical_basis(code['HX'], code['HZ'])
    else:
        H_det, logicals = code['HX'], fast_logical_basis(code['HZ'], code['HX'])
    k = len(logicals)
    rounds = rounds or 8
    circ = memory_circuit(H_det, logicals, n, p, p, rounds, basis)
    dem = circ.detector_error_model(decompose_errors=True)
    matcher = pymatching.Matching.from_detector_error_model(dem)
    sampler = circ.compile_detector_sampler()
    dets, obs = sampler.sample(shots, separate_observables=True)
    pred = matcher.decode_batch(dets)
    # per-logical failure counts
    fails = (pred != obs).sum(axis=0)
    p_shot = fails / shots                       # per-observable, whole run
    p_round = 1 - (1 - p_shot) ** (1.0 / rounds)  # per round
    return float(p_round.mean()), k, shots


if __name__ == '__main__':
    from holey import build_greedy
    # smoke test: rotated patches d=5 and d=7 — threshold behaviour sanity
    for L in (5, 7):
        c = build_greedy(L, L, 0, 1, 0, 0, 1)
        c['holes'] = []
        for p in (0.01, 0.02, 0.03, 0.04):
            r, k, s = run_memory(c, p, rounds=L, shots=20000)
            print(f'patch d={L} p={p}: per-round logical rate {r:.5f}',
                  flush=True)
