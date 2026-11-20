"""
Generate the circuit-tier seed artifact for a rotated-surface-code board entry
(RFC 0001 Phase A, issue #505): full-distance memory circuits for both bases,
and the circuit JSON block with RIS-found witnesses.

The schedule is the standard geometric one: every plaquette couples its data
qubits in a fixed zigzag order read off the layout coordinates. Each check's
virtual plaquette center is found from the code's own X/Z parity coloring of
the dual grid (a weight-2 boundary check keeps the slots it would occupy in
its full virtual plaquette, which is what makes the layers conflict-free).
The generator tries the 4x4 zigzag pattern pairs, keeps those whose quick RIS
bound realizes the full code distance in both bases, deep-checks the first,
and writes:

    circuits/<slug>/memory_{x,z}.stim   canonical-noise circuits
    codes/<slug>.json                   + circuit block (schema 0.2)

Usage: python research/circuit_seed.py codes/25-1-5.json [--rounds R]
"""

import argparse
import json
import os
import sys

import numpy as np
import stim

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "verify"))
import circuit_tools as ct
import circuit_verify as cv
from qldpc_verify import _matrix

# slot orders over plaquette offsets (dr, dc): NW, NE, SW, SE and friends
PATTERNS = {
    "z":  [(-1, -1), (-1, 1), (1, -1), (1, 1)],
    "n":  [(-1, -1), (1, -1), (-1, 1), (1, 1)],
}
PATTERNS.update({name + "_rev": offs[::-1] for name, offs in PATTERNS.items()})


def virtual_center(pts, parity):
    """Center of a check's (possibly virtual) full plaquette: for weight 4 the
    mean; for a weight-2 boundary pair the off-grid candidate whose dual-grid
    cell has the check type's parity ((floor r + floor c) % 2)."""
    pts = [tuple(map(float, p)) for p in pts]
    if len(pts) == 4:
        return (sum(p[0] for p in pts) / 4, sum(p[1] for p in pts) / 4)
    (r1, c1), (r2, c2) = pts
    mid = ((r1 + r2) / 2, (c1 + c2) / 2)
    perp = (0.5, 0.0) if r1 == r2 else (0.0, 0.5)
    for s in (1, -1):
        cr, cc = mid[0] + s * perp[0], mid[1] + s * perp[1]
        if (int(np.floor(cr)) + int(np.floor(cc))) % 2 == parity:
            return (cr, cc)
    raise ValueError(f"no center with parity {parity} for {pts}")


def geometric_layers(checks, coords, pattern, parity):
    """The 4 CX layers of a zigzag schedule: check ci couples the qubit at
    plaquette offset PATTERNS[pattern][l] in layer l. Raises if any layer
    reuses a qubit or check (the schedule would not be parallel)."""
    layers = [[] for _ in range(4)]
    for ci, sup in enumerate(checks):
        if not 2 <= len(sup) <= 4:
            raise ValueError(f"check {ci} has weight {len(sup)}: not a "
                             f"rotated-surface plaquette")
        cr, cc = virtual_center([coords[q] for q in sup], parity)
        for q in sup:
            off = (int(np.sign(coords[q][0] - cr)),
                   int(np.sign(coords[q][1] - cc)))
            layers[PATTERNS[pattern].index(off)].append((ci, int(q)))
    for l, layer in enumerate(layers):
        for pos in (0, 1):
            seen = [t[pos] for t in layer]
            if len(seen) != len(set(seen)):
                raise ValueError(f"layer {l} of pattern '{pattern}' is not "
                                 f"parallel")
    return layers


def dem_pair(HX, HZ, rounds, basis, lay_x, lay_z, n):
    skel = ct.build_css_memory(HX, HZ, rounds, basis=basis,
                               layers_x=lay_x, layers_z=lay_z)
    noisy = ct.apply_noise(skel, n)
    dem = ct.derive_dem(noisy)
    return noisy, dem, ct.dem_matrices(dem)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("code_json")
    ap.add_argument("--rounds", type=int, default=None,
                    help="extraction rounds (default: the code distance d)")
    ap.add_argument("--quick-trials", type=int, default=60)
    ap.add_argument("--deep-trials", type=int, default=1500)
    ap.add_argument("--deep-seeds", type=int, default=3)
    ap.add_argument("--pattern-x", choices=sorted(PATTERNS), default=None,
                    help="pin the X-plaquette zigzag pattern (skip the scan); "
                         "the geometry is family-wide, so a pair that is "
                         "full-distance at one d transfers to the others")
    ap.add_argument("--pattern-z", choices=sorted(PATTERNS), default=None)
    args = ap.parse_args()

    doc = json.load(open(args.code_json))
    n, d = doc["n"], doc["distance"]["d"]
    rounds = args.rounds or d
    HX = _matrix(doc["checks"]["X"], n)
    HZ = _matrix(doc["checks"]["Z"], n)
    coords = doc["locality"]["coordinates"]
    # which dual-grid parity is X: read it off any weight-4 X plaquette
    full = next(s for s in doc["checks"]["X"] if len(s) == 4)
    cr = sum(coords[q][0] for q in full) / 4
    cc = sum(coords[q][1] for q in full) / 4
    parity_x = (int(np.floor(cr)) + int(np.floor(cc))) % 2

    print(f"{args.code_json}: n={n} d={d} rounds={rounds} "
          f"X-plaquette parity {parity_x}")
    candidates = []
    if args.pattern_x and args.pattern_z:
        lay_x = geometric_layers(doc["checks"]["X"], coords, args.pattern_x,
                                 parity_x)
        lay_z = geometric_layers(doc["checks"]["Z"], coords, args.pattern_z,
                                 1 - parity_x)
        candidates.append((args.pattern_x, args.pattern_z, lay_x, lay_z))
    for px in ([] if candidates else sorted(PATTERNS)):
        for pz in sorted(PATTERNS):
            lay_x = geometric_layers(doc["checks"]["X"], coords, px, parity_x)
            lay_z = geometric_layers(doc["checks"]["Z"], coords, pz,
                                     1 - parity_x)
            ok = True
            for basis in ("Z", "X"):
                _, _, (H, L) = dem_pair(HX, HZ, rounds, basis, lay_x, lay_z, n)
                w, _ = ct.ris_dem(H, L, trials=args.quick_trials, seed=11)
                if w != d:
                    ok = False
                    break
            print(f"  X:{px:6s} Z:{pz:6s} -> {'full distance' if ok else f'd_circ<{d} ({basis}={w})'}")
            if ok:
                candidates.append((px, pz, lay_x, lay_z))
        if candidates:
            break                      # deterministic: first surviving px

    if not candidates:
        sys.exit("no zigzag pattern pair realizes full distance; "
                 "this layout needs a bespoke schedule")
    px, pz, lay_x, lay_z = candidates[0]
    print(f"deep-checking X:{px} Z:{pz} "
          f"({args.deep_seeds} x {args.deep_trials} trials per basis)")

    block = {"d_circ": {}, "rounds": rounds, "stim_version": stim.__version__,
             "notes": f"standard geometric zigzag schedule (X pattern '{px}', "
                      f"Z pattern '{pz}') derived from the 2D layout; "
                      f"generated by research/circuit_seed.py"}
    slug = os.path.splitext(os.path.basename(args.code_json))[0]
    outdir = os.path.join(ROOT, "circuits", slug)
    os.makedirs(outdir, exist_ok=True)
    for basis in ("Z", "X"):
        noisy, dem, (H, L) = dem_pair(HX, HZ, rounds, basis, lay_x, lay_z, n)
        best, wit = None, None
        for s in range(args.deep_seeds):
            w, wt = ct.ris_dem(H, L, trials=args.deep_trials, seed=100 + s)
            if best is None or w < best:
                best, wit = w, wt
        print(f"  {basis}-memory: {dem.num_detectors} detectors, "
              f"{dem.num_errors} mechanisms, d_circ <= {best}")
        if best != d:
            sys.exit(f"deep search dropped below d ({best} < {d}); "
                     f"pattern pair is not full-distance after all")
        stem = os.path.join(outdir, f"memory_{basis.lower()}")
        open(stem + ".stim", "w").write(str(noisy) + "\n")
        # .dem is derived from the .stim; no longer committed (PR: drop derived DEMs)
        block["d_circ"][basis] = {"value": best, "confidence": "upper_bound",
                                  "witness": wit}

    doc["schema_version"] = "0.2"
    doc["circuit"] = block
    json.dump(doc, open(args.code_json, "w"), indent=1)
    open(args.code_json, "a").write("\n")
    print(f"wrote {outdir}/memory_{{x,z}}.{{stim,dem}} and updated "
          f"{args.code_json}")

    report = cv.verify_circuit(doc, outdir)
    print("circuit_verify:", "ok" if report["ok"] else
          json.dumps(report, indent=2))
    sys.exit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
