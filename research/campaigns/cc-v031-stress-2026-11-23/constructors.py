#!/usr/bin/env python3
"""Deterministic lead grids for the code-calculus v0.3.1 stress campaign.

Leads (from the 2026-11-22/23 fieldnotes):

1. `L-PAIR-PARTITION` at the p values the earlier grids did not try
   (p in {9, 11, 13}; the staged finds stopped at p=7).
2. `PP-SCALE` rung-3 SNF bundles whose slope pattern is not the unit-slope
   grid: base at P0=3 with slopes in {1, -1} (root r = P-1 of order 2),
   so the scaled code is not a plain CPM-PP tuple of the earlier grid.

Nothing here computes or asserts a distance; applicability is decided by
`machine.constructors.construct` and connectivity by the gate's own
`prescreen.block_structure` check.
"""

import itertools


def shifts(pattern, L):
    return {
        "all0": [0] * L,
        "identity": list(range(L)),
        "alternating": [i % 2 for i in range(L)],
        "pairwise": [i // 2 for i in range(L)],
        "reverse": list(reversed(range(L))),
    }[pattern]


PAIR_PATTERNS = ("all0", "identity", "alternating", "pairwise", "reverse")


def pair_partition_specs():
    """Lead 1: untried p values for the block-mixing pair-partition grid."""
    out = []
    for p in (9, 11, 13):
        for L in (4, 6):
            for px, pz in itertools.product(PAIR_PATTERNS, repeat=2):
                out.append(
                    (
                        f"pp-p{p}-L{L}-{px}-{pz}",
                        {
                            "constructor": "L-PAIR-PARTITION",
                            "p": p,
                            "blocks_x": [shifts(px, L)],
                            "blocks_z": [shifts(pz, L)],
                        },
                    )
                )
    return out


# Deterministic SNF-bundle subset: slope patterns via Q rows in {0,1}
# (slope 1 or -1 = P-1 at every lift size), shift patterns from the classic
# five, x and z independently, never identical (identical shifts give the
# p-block direct sum the gate refuses).
Q_PATTERNS = ((0, 0, 0, 0), (1, 1, 1, 1), (1, 0, 1, 0), (0, 1, 0, 1))


def pp_scale_specs():
    """Lead 2: PP-SCALE SNF bundles with non-unit relative slopes."""
    P0 = 3
    r0 = P0 - 1  # order 2 mod 3: reproduces slope patterns {1, 2 = -1}
    out = []
    for qx in Q_PATTERNS:
        for qz in Q_PATTERNS:
            for px, pz in itertools.product(PAIR_PATTERNS, repeat=2):
                sx, sz = shifts(px, 4), shifts(pz, 4)
                if sx == sz:
                    continue
                bx0 = [[(2 if qx[c] else 1, sx[c]) for c in range(4)]]
                bz0 = [[(2 if qz[c] else 1, sz[c]) for c in range(4)]]
                bundle = {
                    "P0": P0,
                    "orders_e": [2],
                    "roots_r0": [r0],
                    "shape_x": (1, 4),
                    "shape_z": (1, 4),
                    "Q_x": [[qx[c]] for c in range(4)],
                    "Q_z": [[qz[c]] for c in range(4)],
                    "G_x": [[sx[c]] for c in range(4)],
                    "G_z": [[sz[c]] for c in range(4)],
                    "theta_x": [1],
                    "theta_z": [1],
                    "blocks_x0": bx0,
                    "blocks_z0": bz0,
                }
                for P in (7, 11, 13):
                    b = dict(bundle)
                    b["roots_r"] = [P - 1]
                    out.append(
                        (f"ppscale-q{qx}{qz}-{px}-{pz}-P{P}", {"constructor": "PP-SCALE", "P0_bundle": bundle, "P": P})
                    )
    return out


def resolve_spec(label, spec):
    """Build the full spec: PP-SCALE needs its derived base state."""
    if spec["constructor"] != "PP-SCALE":
        return label, spec
    from machine.constructors import pair_partition_code

    bundle = spec["P0_bundle"]
    c0, _ = pair_partition_code(bundle["P0"], bundle["blocks_x0"], bundle["blocks_z0"])
    scaled = dict(bundle)
    scaled["roots_r"] = [spec["P"] - 1]
    return label, {"constructor": "PP-SCALE", "state": c0, "P": spec["P"], "bundle": scaled}


def jsonable_params(spec):
    out = {}
    for k, v in spec.items():
        if k == "state":
            continue
        if isinstance(v, tuple):
            out[k] = list(v)
        elif isinstance(v, list):
            out[k] = jsonable_list(v)
        else:
            out[k] = v
    return out


def jsonable_list(v):
    if isinstance(v, (list, tuple)):
        return [jsonable_list(x) for x in v]
    return v
