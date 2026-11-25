"""Sisyphus as a proposer for the circuit-tier refutation gate (RFC 0001 step 6).

Usage:
    python verify/sisyphus_propose.py MEMORY.stim --below CLAIM --seconds S --seed N

Searches the detector error model of one memory circuit for an undetected
logical fault set lighter than CLAIM and prints one line,

    SISYPHUS_RESULT {"lightest": w, "witness": [...], ...}

where `witness` holds error-instruction indices of the flattened DEM in file
order, the same indexing circuit_tools.witness_errors reads. `lightest` is
null when the search found no fault set at all.

This file decides nothing. It is run as a subprocess by
gate_changed._circuit_refute, which re-derives the DEM itself and accepts a
proposal only after circuit_tools.witness_errors confirms it, the same
layering the gf2_fast accelerator sits under. A wrong answer from here
costs a missed refutation and can never produce a false one.

Why a subprocess: Sisyphus (sisyphus-qec, pinned in pyproject.toml) is a
Numba program that starts its own worker processes. Keeping it out of the
gate's interpreter means a crash or a hang in it is a non-zero exit or a
killed process group, and the gate's wall-clock cap holds whatever the
search does.

The search is information-set decoding with learned column scores over
round-aligned detector windows; see https://github.com/varunmenon1310/sisyphus.
`--seconds` bounds the search only: building the matrices and loading the
compiled kernels happen before Sisyphus starts its timer. The seed fixes
the random stream but not the outcome, since the stop is wall-clock.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Steps are never the binding budget: the wall-clock limit is. Sisyphus
# counted about 5e4 steps per second on the largest board DEMs.
MAX_STEPS = 10**9
# Sisyphus honours a wall-clock limit only with a worker pool (two or more
# processes). Four matches the threads ris_dem uses and the CI runner's cores.
WORKERS = 4
MARKER = "SISYPHUS_RESULT "


def propose(stim_path, below, seconds, seed, workers=WORKERS):
    """Return the result record for one memory circuit; see the module docstring."""
    from importlib.metadata import version

    import circuit_tools as ct
    import stim
    from sisyphus_qec import dem_to_matrices, lift_columns, side_distance

    t0 = time.monotonic()
    dem = ct.derive_dem(stim.Circuit(open(stim_path).read()))
    rec = {
        "lightest": None,
        "witness": None,
        "below": int(below),
        "mechanisms": int(dem.num_errors),
        "detectors": int(dem.num_detectors),
        "seed": int(seed),
        "workers": int(workers),
        "version": version("sisyphus-qec"),
    }
    if dem.num_errors == 0 or dem.num_observables == 0 or below <= 1:
        rec.update(steps=0, search_seconds=0.0, total_seconds=round(time.monotonic() - t0, 3))
        return rec
    H, L, columns = dem_to_matrices(dem)
    res = side_distance(
        H,
        None,
        pair_rows=L,
        num_trials=MAX_STEPS,
        num_workers=max(2, int(workers)),
        time_limit=float(seconds),
        cutoff=int(below) - 1,
        seed=int(seed),
    )
    if res.distance > 0 and res.witness is not None:
        rec["lightest"] = int(res.distance)
        rec["witness"] = sorted(int(i) for i in lift_columns(res.witness, columns))
    rec.update(
        steps=int(res.shots),
        search_seconds=round(float(res.wall_time), 3),
        total_seconds=round(time.monotonic() - t0, 3),
    )
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("stim_path")
    ap.add_argument("--below", type=int, required=True, help="the claimed d_circ; the search stops below it")
    ap.add_argument("--seconds", type=float, required=True, help="wall-clock limit of the search")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=WORKERS)
    a = ap.parse_args(argv)
    rec = propose(a.stim_path, a.below, a.seconds, a.seed, a.workers)
    print(MARKER + json.dumps(rec), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
