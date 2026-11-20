"""Constrained variant: contract while keeping w <= 4 and diameter <= 4.

The unconstrained campaign (campaign.py) reaches n = 899 at k = 173 but blows
max check weight to 8 and max diameter to sqrt(20), so it lands in
weight-8 x local-2d-bilayer rather than the weight-4 x local-2d-single cell the
records live in. This enforces both caps as hard constraints and asks whether
anything survives: n < 923 at k = 173 would beat [[923,173,3]] on its own cell.
"""

import math
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE / "874-157-3")]
import campaign as C  # noqa: E402


def supports(H):
    return [list(np.flatnonzero(r)) for r in H]


def caps_ok(HX, HZ, coords, w_max=4, d_max=4.0):
    """Both hard caps: check weight and on-lattice diameter."""
    for H in (HX, HZ):
        for s in supports(H):
            if len(s) > w_max:
                return False
            if s:
                pts = [coords[q] for q in s]
                if max(math.dist(a, b) for a in pts for b in pts) > d_max:
                    return False
    return True


def run(HX, HZ, coords, originals, k0, seed, degree_max=1, verbose=False):
    """Same acceptance as campaign.graft_campaign, plus the two caps."""
    rng = np.random.default_rng(seed)
    orig = list(originals)
    removed = 0
    xmin, xmax = coords[:, 0].min(), coords[:, 0].max()
    ymin, ymax = coords[:, 1].min(), coords[:, 1].max()
    while True:
        wx = HX.sum(axis=0) if HX.size else np.zeros(HX.shape[1])
        wz = HZ.sum(axis=0) if HZ.size else np.zeros(HZ.shape[1])
        cands = [(t, int(q)) for t, w in (("X", wx), ("Z", wz)) for q in np.where((w >= 1) & (w <= degree_max))[0]]
        if not cands:
            break
        rng.shuffle(cands)
        cands.sort(key=lambda tc: -C._edge_distance(coords, int(tc[1]), xmin, xmax, ymin, ymax))
        accepted = False
        for t, q in cands:
            A = HX if t == "X" else HZ
            for r in np.nonzero(A[:, q])[0]:
                out = C._pivot_move(HX, HZ, q, t, int(r))
                if out is None:
                    continue
                HX2, HZ2 = out
                if not caps_ok(HX2, HZ2, coords):
                    continue
                if not C._admissible(HX2, HZ2, k0):
                    continue
                HX, HZ = HX2, HZ2
                coords = np.delete(coords, q, axis=0)
                xmin, xmax = coords[:, 0].min(), coords[:, 0].max()
                ymin, ymax = coords[:, 1].min(), coords[:, 1].max()
                orig.pop(q)
                removed += 1
                accepted = True
                if verbose:
                    print(f"  -{t} -> n={HX.shape[1]}", flush=True)
                break
            if accepted:
                break
        if not accepted:
            break
    return HX, HZ, coords, orig, removed


def main():
    bases = [(34, 29, 3, 1, 3, 173), (34, 29, 3, 1, 0, 172), (31, 31, 3, 1, 3, 169), (32, 31, 1, 4, 3, 173)]
    out = HERE / "out"
    out.mkdir(exist_ok=True)
    best = None
    t0 = time.time()
    for W, H, px, pz, order, expect in bases:
        try:
            st = C.base_state(W, H, px, pz, order)
        except ValueError as exc:
            print(f"{W}x{H} p=({px},{pz}) o={order}: {exc}; skip", flush=True)
            continue
        if st is None:
            print(f"{W}x{H} p=({px},{pz}) o={order}: incomplete; skip", flush=True)
            continue
        HX, HZ, coords, orig, k0 = st
        if k0 != expect:
            print(f"{W}x{H} p=({px},{pz}) o={order}: k={k0} != {expect}", flush=True)
            continue
        if not caps_ok(HX, HZ, coords):
            print(f"{W}x{H}: base violates caps", flush=True)
            continue
        n0 = HX.shape[1]
        for seed in (0, 1, 2, 3, 4, 5):
            a, b, c2, o2, rm = run(HX.copy(), HZ.copy(), coords.copy(), list(orig), k0, seed)
            n1 = a.shape[1]
            ok = C.one_connected(a, b)[0]
            print(
                f"{W}x{H} p=({px},{pz}) o={order} seed={seed}: "
                f"n {n0}->{n1} (-{rm}) k={k0} g={9 * k0 / n1:.4f} "
                f"connected={ok} {time.time() - t0:.0f}s",
                flush=True,
            )
            if ok and (best is None or n1 < best[0]):
                best = (n1, a, b, c2, o2, (W, H, px, pz, order, seed, n0, n1, k0))
                np.savez(out / f"constrained-{n1}-{k0}-3.npz", hx=a, hz=b, coords=c2)
                print(f"  -> saved constrained-{n1}-{k0}-3.npz", flush=True)
    if best:
        n1, _, _, _, _, meta = best
        print(
            f"BEST n={n1} k={meta[8]} "
            f"(base {meta[0]}x{meta[1]} p=({meta[2]},{meta[3]}) "
            f"o={meta[4]} seed={meta[5]}, n {meta[6]}->{meta[7]})",
            flush=True,
        )


if __name__ == "__main__":
    main()
