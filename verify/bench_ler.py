"""Measure decode cost per code that ships circuits.

Reports what the measured-LER budget can admit. Cost is fit from two probe sizes rather than one, because building the
decoder and sampling the DEM are fixed costs that a small probe charges to
the per-shot rate: a 120-shot probe on 25-1-5 reads 8.7 ms/shot against a
true marginal cost near 1 ms. Reported per code and basis: setup seconds,
marginal ms/shot, the shots the per-basis wall budget buys, and the
per-shot failure rate a code must exceed for that many shots to reach the
tier's failure floor.
"""

import glob
import os
import sys
import time

import numpy as np
import stim

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "verify"))
import ler_tools as lt
import ler_verify as lv

SMALL = int(sys.argv[1]) if len(sys.argv) > 1 else 60
LARGE = int(sys.argv[2]) if len(sys.argv) > 2 else 260

print(
    f"pinned decoder {lt.DECODER_ID}; probes {SMALL}/{LARGE} shots; "
    f"budget {lv.LER_SECONDS:.0f}s/basis; floor {lt.MIN_FAILURES} failures\n"
)
hdr = f"{'code':<10}{'basis':<7}{'DEM mech':<10}{'setup s':<9}{'ms/shot':<9}{'shots/budget':<14}{'p needed':<11}"
print(hdr)
print("-" * len(hdr))
for d in sorted(glob.glob(os.path.join(ROOT, "circuits", "*"))):
    slug = os.path.basename(d)
    for basis in ("x", "z"):
        f = os.path.join(d, f"memory_{basis}.stim")
        if not os.path.exists(f):
            continue
        dem = stim.Circuit.from_file(f).detector_error_model(decompose_errors=False)
        # Least squares over three probe sizes: a two-point fit put the same
        # DEM at 0.66 and 4.84 ms/shot on its two bases, which is scheduler
        # noise being read as a property of the code.
        sizes = [SMALL, (SMALL + LARGE) // 2, LARGE]
        ts = []
        for shots in sizes:
            t0 = time.time()
            lt.measure_failures(dem, shots, 1234)
            ts.append(time.time() - t0)
        per_shot, setup = np.polyfit(np.array(sizes, dtype=float), np.array(ts), 1)
        per_shot = max(float(per_shot), 1e-9)
        setup = max(float(setup), 0.0)
        usable = max(lv.LER_SECONDS - setup, 0.0)
        shots_budget = int(usable / per_shot) if per_shot > 0 else 0
        p_need = (lt.MIN_FAILURES / shots_budget) if shots_budget else float("inf")
        print(
            f"{slug:<10}{basis.upper():<7}{dem.num_errors:<10}{setup:<9.1f}"
            f"{per_shot * 1000:<9.2f}{shots_budget:<14}{p_need:<11.2e}",
            flush=True,
        )
print(
    "\nA code admits only when its true per-shot failure rate exceeds "
    "'p needed' on BOTH bases;\nthe tier fails closed otherwise. Lower is "
    "easier: a code with a low error rate needs\nmore shots to accumulate "
    "failures, which is why the budget binds hardest on the best codes."
)
