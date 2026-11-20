#!/usr/bin/env python
"""Export one multi-band config as the .npz pair `./qldpc submit` consumes.

`hx`/`hz` carry the parity checks and `coords` the per-qubit layout, so the
verifier derives the locality class itself (single layer here: the tilted
nearest-neighbour checks span sqrt(2) at unit qubit spacing). Everything is
rebuilt from ``research/multiband_surface.py``; nothing is hand-transcribed.

    uv run --frozen python research/geometric_grafts/export_multiband.py 5 7 7 6 /tmp/out
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in ("research", "research/kit", "verify"):
    _q = os.path.join(_ROOT, _p)
    if _q not in sys.path:
        sys.path.insert(0, _q)

import numpy as np  # noqa: E402
from multiband_surface import build, params  # noqa: E402


def export(d, rows, m, pitch, outdir):
    hx, hz, coords, _ = build(d, rows, m, pitch)
    p = params(d, rows, m, pitch)
    assert p["css"] and p["connected"] and not p["empty_rows"], p
    os.makedirs(outdir, exist_ok=True)
    tag = f"{p['n']}-{p['k']}-d{d}r{rows}m{m}p{pitch}"
    npz = os.path.join(outdir, tag + ".npz")
    np.savez_compressed(npz, hx=hx.astype(np.uint8), hz=hz.astype(np.uint8))
    cnpz = os.path.join(outdir, tag + "-coords.npz")
    np.savez_compressed(cnpz, coords=np.asarray(coords, dtype=float))
    print(f"{tag}: n={p['n']} k={p['k']} w={p['w']} css={p['css']} conn={p['connected']}")
    print(f"  {npz}")
    print(f"  {cnpz}")
    return npz, cnpz, tag


if __name__ == "__main__":
    d, rows, m, pitch = (int(x) for x in sys.argv[1:5])
    export(d, rows, m, pitch, sys.argv[5] if len(sys.argv) > 5 else "/tmp/opencode/npz")
