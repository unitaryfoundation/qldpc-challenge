import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "kit"))
import numpy as np
from rs_tanner import gf_inv, gf_mul, make_tanner_code, rs_parity_check, tanner_css_from_hp, to_binary


def test_gf_inverse():
    for m in (2, 3, 4):
        for a in range(1, 1 << m):
            assert gf_mul(a, gf_inv(a, m), m) == 1


def test_tanner_shape():
    edges = [(u, v) for u in range(3) for v in range(3)]
    H = make_tanner_code(edges, 3, 3, [1, 2, 3], 2, 2)
    assert H.shape == (6, 9)


def test_binary_conversion():
    edges = [(u, v) for u in range(3) for v in range(3)]
    H = make_tanner_code(edges, 3, 3, [1, 2, 3], 2, 2)
    Hb = to_binary(H, 2)
    assert Hb.shape == (12, 18)
    assert Hb.dtype == np.int8


def test_css_hp():
    edges = [(u, v) for u in range(3) for v in range(3)]
    H = make_tanner_code(edges, 3, 3, [1, 2, 3], 2, 2)
    Hb = to_binary(H, 2)
    HX, HZ = tanner_css_from_hp(Hb)
    assert HX.shape[1] == 468


def test_rs_parity_check():
    S = [1, 2, 3]
    H = rs_parity_check(S, 2, 2)
    assert H.shape == (1, 3)
