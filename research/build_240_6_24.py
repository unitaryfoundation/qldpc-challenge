"""Rebuild the [[240,6,24]] metacyclic 2BGA code from its construction parameters.

Two-block group-algebra (2BGA) on the metacyclic group Z_15 x| Z_8 with
action r=4 (order 120, n=240). Weight-4 supports per block (check weight 8).
Found by a random metacyclic sweep (`sample_metacyclic`); distance is a
witness-backed upper bound (screen d<=26 collapsed to d<=24 under packaging).

Run:  uv run python research/build_240_6_24.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "kit"))

from css import compute_k, verify_css  # noqa: E402
from group_algebra import build_2bga, metacyclic  # noqa: E402
from submit import make_submission, save_submission  # noqa: E402

# Metacyclic Z_n x| Z_{k_m} with r^{k_m} = 1 (mod n).
N, K_M, R = 15, 8, 4
A = [83, 21, 107, 116]
B = [17, 20, 105, 97]


def main():
    mul, _elems = metacyclic(N, K_M, R)
    HX, HZ = build_2bga(mul, A, B)
    assert verify_css(HX, HZ), "CSS commutation failed"
    k = compute_k(HX, HZ)
    print(f"HX {HX.shape} HZ {HZ.shape}  k = {k}")
    assert k == 6, f"expected k=6, got {k}"

    doc = make_submission(
        HX, HZ,
        name="[[240,6,24]] metacyclic 2BGA (Z_15 x| Z_8, r=4)",
        construction=(
            "2BGA on metacyclic Z_15 x| Z_8 with r=4; "
            f"supports a={A}, b={B}."
        ),
        authors=["@simsaidan"],
        family="generalized-bicycle",
        references=["arXiv:2306.16400"],
        confidence="upper_bound",
        trials=12000,
        seed=0,
    )
    print("d =", doc["distance"]["d"],
          "| X:", doc["distance"]["X"]["value"],
          "| Z:", doc["distance"]["Z"]["value"])

    out = os.path.join(_HERE, "candidates", "240-6-24-rebuilt.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    errs = save_submission(doc, out)
    print("schema errors:", errs or "none")
    print("wrote:", out)


if __name__ == "__main__":
    main()
