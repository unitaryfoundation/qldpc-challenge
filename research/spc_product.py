"""Single-parity-check (SPC) D-fold product codes.

The [[512,174,8]] instance is the one printed as explicit Kronecker-product
parity-check matrices in arXiv:2505.06157 (Mostad, Lin, Rosnes, Lee, Lai),
Sec. III-C, which attributes it to that paper's Ref. 18. The matrices there are

    H_X = [ h^3 (x) I^6 ;  I^3 (x) h^3 (x) I^3 ;  I^6 (x) h^3 ]
    H_Z = [ h (x) I^2 (x) h (x) I^2 (x) h (x) I^2
          ; I (x) h (x) I^2 (x) h (x) I^2 (x) h (x) I
          ; I^2 (x) h (x) I^2 (x) h (x) I^2 (x) h ]

with h = (1 1) and I = I_2, so n = 2^9 = 512 and every row has uniform weight
2^3 = 8. Rebuilding from those matrices gives rank(H_X) = rank(H_Z) = 169 and
hence k = 512 - 169 - 169 = 174.

This module builds it. Nothing here decides a distance or a track;
`verify/validate_candidate.py` does.
"""

from __future__ import annotations

import numpy as np


def _kron_all(*factors: np.ndarray) -> np.ndarray:
    out = np.array([[1]], dtype=np.int64)
    for f in factors:
        out = np.kron(out, f)
    return out


def build_spc_512():
    """Return (HX, HZ) for the [[512,174,8]] SPC 3-fold product code."""
    h = np.array([[1, 1]], dtype=np.int64)
    I = np.eye(2, dtype=np.int64)
    HX = np.vstack(
        [
            _kron_all(h, h, h, I, I, I, I, I, I),
            _kron_all(I, I, I, h, h, h, I, I, I),
            _kron_all(I, I, I, I, I, I, h, h, h),
        ]
    )
    HZ = np.vstack(
        [
            _kron_all(h, I, I, h, I, I, h, I, I),
            _kron_all(I, h, I, I, h, I, I, h, I),
            _kron_all(I, I, h, I, I, h, I, I, h),
        ]
    )
    return HX, HZ


if __name__ == "__main__":
    import os
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "kit"))
    from css import compute_k, rank, verify_css

    HX, HZ = build_spc_512()
    print(
        f"n = {HX.shape[1]}  k = {compute_k(HX, HZ)}  "
        f"max weight = {int(HX.sum(1).max())}  "
        f"rank X = {rank(HX)}  rank Z = {rank(HZ)}  "
        f"commutes = {verify_css(HX, HZ)}"
    )
