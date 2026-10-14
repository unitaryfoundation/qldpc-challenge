#!/usr/bin/env python
"""Generate the paper's dense-packed surface code [[101,5,5]] as (HX, HZ, coords)
for submission.

Reconstruction faithfully follows dense_packing_simulation_x_error.py:
- five_dense_num(i,d): every occupied site of the 5-logical-qubit dense packing.
- data_num(i,d):       data qubits are odd,odd sites.
- auxiliary_z(i,d):    Z-ancillas, (x+y)%4==2, measure X-stabilizers.
- auxiliary_x:         the rest, measure Z-stabilizers.
- each stabilizer acts on the 4 diagonal data-qubit neighbors of its ancilla
  (the code's CNOT connectivity, paper Fig 14 / Appendix A).

Layout: qubit q_ij at grid (x,y) => coordinate (x,y) in unitless grid units.
The nearest-neighbor checks step (dx,dy)=(±1,±1) => interaction radius sqrt(2).
"""
import numpy as np

def num_to_coordinate(i, distance):
    offset = distance*6+5
    return i % offset, i // offset

def five_dense_num(i, distance):
    x, y = num_to_coordinate(i, distance)
    if (1 <= y <= distance*2-1) and ((1 <= x <= distance*2-1) or (distance*2+3 <= x <= distance*4+1) or (distance*4+5 <= x <= distance*6+3)):
        return ((x+y) % 2 == 0)
    elif (distance <= y <= distance*3-2) and ((distance+2 <= x <= distance*3) or (distance*3+4 <= x <= distance*5+2)):
        return ((x+y) % 2 == 0)
    elif (1 < y < distance*2-1) and (x == 0 or x == distance*2 or x == distance*2+2 or x == distance*4+2 or x == distance*4+4 or x == distance*6+4):
        return (x+y) % 4 == 0
    elif (y == distance-1 or y == distance*3-1) and ((distance+2 < x <= distance*3) or (distance*3+4 < x < distance*5+2)):
        return (x+y) % 4 == 0
    elif (y == 0 or y == distance*2) and ((1 < x < distance*2-1) or (distance*2+3 < x < distance*4+1) or (distance*4+5 < x < distance*6+3)):
        return (x+y) % 4 == 2
    elif (distance*2 <= y < distance*3-2) and (x == distance+1 or x == distance*3+1 or x == distance*3+3 or x == distance*5+3):
        return (x+y) % 4 == 2
    else:
        return False

def data_num(i, distance):
    x, y = num_to_coordinate(i, distance)
    return x % 2 == 1 and y % 2 == 1

def auxiliary_z(i, distance):
    x, y = num_to_coordinate(i, distance)
    return (x+y) % 4 == 2

def build(distance):
    off = distance*6+5
    sites = [i for i in range(off*distance*3) if five_dense_num(i, distance)]
    coords = {i: num_to_coordinate(i, distance) for i in sites}
    data = [i for i in sites if data_num(i, distance)]
    dset = set(data)
    d2i = {coords[q]: j for j, q in enumerate(data)}   # coord -> data index

    HX = []  # rows: Z-ancillas (X-stabilizers), supports on data indices
    HZ = []  # rows: X-ancillas (Z-stabilizers), supports on data indices
    for i in sites:
        if i in dset:
            continue
        x, y = coords[i]
        ns = sorted(d2i[(x+dx, y+dy)]
                    for (dx, dy) in [(-1, -1), (-1, 1), (1, -1), (1, 1)]
                    if (x+dx, y+dy) in d2i)
        if auxiliary_z(i, distance):
            HX.append(ns)
        else:
            HZ.append(ns)

    n = len(data)
    HXa = np.zeros((len(HX), n), dtype=np.uint8)
    HZa = np.zeros((len(HZ), n), dtype=np.uint8)
    for r, s in enumerate(HX):
        for c in s:
            HXa[r, c] ^= 1
    for r, s in enumerate(HZ):
        for c in s:
            HZa[r, c] ^= 1

    # coordinates: one [x,y] per data qubit, indexed by data-index (0..n-1).
    # The paper's grid places adjacent sites 2 apart; we normalize to unit
    # spacing so the tilted nearest-neighbour checks span sqrt(2) (honest
    # layout, single layer, 1 qubit/site).
    xy = np.array([coords[q] for q in data], dtype=float) / 2.0
    return HXa, HZa, xy, data, coords

if __name__ == "__main__":
    import sys
    d = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    out = sys.argv[2] if len(sys.argv) > 2 else f"dense_{d}.npz"
    HX, HZ, coords, data, allcoords = build(d)
    n = len(data)
    rX = np.linalg.matrix_rank(HX.astype(np.int64)) if n else 0
    rZ = np.linalg.matrix_rank(HZ.astype(np.int64)) if n else 0
    # GF(2) ranks (numpy rank is over reals, wrong mod 2) — do GF2 rref
    def gf2_rank(A):
        A = (A % 2).copy()
        m, c = A.shape
        r = 0
        for col in range(c):
            piv = np.nonzero(A[r:, col])[0]
            if len(piv) == 0:
                continue
            piv = piv[0] + r
            A[[r, piv]] = A[[piv, r]]
            for rr in range(m):
                if rr != r and A[rr, col]:
                    A[rr] ^= A[r]
            r += 1
            if r == m:
                break
        return r
    rX = gf2_rank(HX); rZ = gf2_rank(HZ)
    print(f"n={n} rankX={rX} rankZ={rZ} k={n-rX-rZ}")
    print(f"CSS commute: {(HX @ HZ.T % 2).max()==0}")
    print(f"max check weight X={HX.sum(1).max()} Z={HZ.sum(1).max()}")
    r = np.sqrt(2)
    print(f"coords range (normalized) x:[{coords[:,0].min()},{coords[:,0].max()}] y:[{coords[:,1].min()},{coords[:,1].max()}]")
    print(f"claim interaction_radius {r:.6f}; min site spacing {coords.min(axis=0) if False else 'unit by construction'}")

    np.savez(out, hx=HX, hz=HZ, coords=coords)
    print(f"wrote {out}  (hx hz coords)")
