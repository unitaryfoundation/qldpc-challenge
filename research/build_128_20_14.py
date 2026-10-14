"""Rebuild the [[128,20,14]] 2BGA candidate from its construction parameters.

Code: two-block group-algebra (2BGA, arXiv:2306.16400) over the non-abelian
order-64 group GAP SmallGroup(64, 61), structure description
((C4 x C2) : C4) : C2, with element-index supports a and b below. Found by
the GAP-enhanced autoresearch sweep; distance confirmed flat across
400 -> 1M RIS trials; trusted gate passed 2026-08-15 (fresh seed).

The Cayley table is the committed research/kit/groups/smallgroup_64_61.json
(GAP 4.15.1, Elements(G) order), so no GAP install is needed. The sweep's
GAP bridge was never committed, and the structure description alone does not
pin the group: SmallGroup(64, i) prints as ((C4 x C2) : C4) : C2 for i in
{61, 62, 69, 74, 80}. The catalog id does.

Run:  uv run python research/build_128_20_14.py
Writes: research/candidates/128-20-14-rebuilt.json (gitignored staging).
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "kit"))

from css import compute_k, verify_css  # noqa: E402
from group_algebra import build_2bga, small_group  # noqa: E402
from submit import make_submission, save_submission  # noqa: E402

A = [7, 9, 11, 30, 32, 34, 47, 59]
B = [3, 6, 23, 27, 41, 46, 47, 56]


def load_group():
    """Order-64 Cayley table of GAP SmallGroup(64, 61), from the committed export."""
    return small_group(64, 61)


def main():
    mul = load_group()
    HX, HZ = build_2bga(mul, A, B)
    assert verify_css(HX, HZ), "CSS commutation failed"
    k = compute_k(HX, HZ)
    print(f"HX {HX.shape} HZ {HZ.shape}  k = {k}")

    doc = make_submission(
        HX, HZ,
        name="[[128,20,14]] 2BGA on ((C4xC2):C4):C2 (order 64)",
        construction=("2BGA (arXiv:2306.16400) on GAP SmallGroup(64, 61), "
                      "((C4 x C2) : C4) : C2, "
                      "weight-8 supports a=[7,9,11,30,32,34,47,59] "
                      "b=[3,6,23,27,41,46,47,56]."),
        authors=["@mathysrennela"],
        family="generalized-bicycle",
        references=["arXiv:2306.16400"],
        confidence="upper_bound",
        trials=8000, seed=7,
    )
    print("d =", doc["distance"]["d"],
          "| X:", doc["distance"]["X"]["value"],
          "| Z:", doc["distance"]["Z"]["value"])

    out = os.path.join(_HERE, "candidates", "128-20-14-rebuilt.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    errs = save_submission(doc, out)
    print("schema errors:", errs or "none")
    print("wrote:", out)


if __name__ == "__main__":
    main()
