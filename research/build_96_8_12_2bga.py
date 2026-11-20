"""Rebuild the [[96,8,12]] two-block group-algebra code on D_4 x Z_6.

The code is a transcription, not a search result: the supports of `a` and `b`
are the ones printed for this code in Appendix J of arXiv:2610.05307v1 (the
`[[96,8,12]]` row of Table 1), and the parity checks follow that paper's
Eq. 1-2, `H_X = [L(a) | R(b)]` and `H_Z = [R(b)^T | L(a)^T]` on `G u G`.

Run it and it writes `codes`-shaped arrays to an .npz:

    uv run --extra research python research/build_96_8_12_2bga.py out.npz

`[[96,8,12]]` is the published parameter set; what the board gains is the
weight-8 placement (8 logical qubits at d = 12 in 96 qubits, where the board
held `[[104,8,12]]`). No search is involved, so the script has no seeds.
"""

import sys

import numpy as np

sys.path[:0] = ["research/kit", "verify"]

from group_algebra import build_2bga, cyclic_product, dihedral, direct_product


def build():
    """Return (HX, HZ) for the [[96,8,12]] code on D_4 x Z_6, and (a, b, mul)."""
    # arXiv:2610.05307 S2.3: D_n acts on Z_n as r: i -> i+1 and s_j: i -> j-i;
    # Z_m = <y>. dihedral(4) is exactly that convention, with s_0 = s.
    mul_d4, el_d4 = dihedral(4)
    mul_z6, _ = cyclic_product(6)
    mul, _ = direct_product(mul_d4, mul_z6)  # G = D_4 x Z_6, |G| = 48

    idx = {tuple(g): i for i, g in enumerate(el_d4)}
    e = idx[(0, 1, 2, 3)]  # identity
    r1 = idx[(1, 2, 3, 0)]  # r
    r2 = idx[(2, 3, 0, 1)]  # r^2
    r3 = idx[(3, 0, 1, 2)]  # r^3
    s0 = idx[(0, 3, 2, 1)]  # s_0 : i -> -i

    def g(d, j):  # direct_product index
        return d * 6 + j % 6

    # Appendix J, [[96,8,12]] row. |supp a| = |supp b| = 4, so every check has
    # weight 8 and the code has n = 2|G| = 96 qubits.
    a = [g(e, 0), g(e, 1), g(r1, 0), g(r3, 0)]  # {(e,e), (e,y), (r,e), (r^3,e)}
    b = [g(e, 0), g(r1, 2), g(s0, 0), g(r2, 4)]  # {(e,e), (r,y^2), (s_0,e), (r^2,y^4)}

    HX, HZ = build_2bga(mul, a, b)
    return HX, HZ, (a, b, mul)


if __name__ == "__main__":
    from css import compute_k, verify_css

    out = sys.argv[1] if len(sys.argv) > 1 else "96-8-12.npz"
    HX, HZ, (a, b, mul) = build()
    w = max(int(HX.sum(axis=1).max()), int(HZ.sum(axis=1).max()))
    print(f"a={a} b={b}  |G|={mul.shape[0]}")
    print(f"n={HX.shape[1]} k={compute_k(HX, HZ)} w={w} css={verify_css(HX, HZ)}")
    assert (HX.shape[1], compute_k(HX, HZ), w) == (96, 8, 8), "not [[96,8,8]]"
    assert verify_css(HX, HZ), "checks do not commute"
    np.savez_compressed(out, hx=HX, hz=HZ)
    print(f"wrote {out}")
