"""Rebuild the [[254,14,16]] generalized-bicycle candidate from its parameters.

Code: two-block generalized bicycle (arXiv:2111.03654 / arXiv:2306.16400)
over the cyclic group Z_127, H_X = [A | B], H_Z = [B^T | A^T], with the
trinomial supports recorded below. These are the supports recovered from the
staged matrix (the two-block form is ambiguous under the shift-direction
convention; the string in the earlier draft was the negated/other variant and
does not rebuild — see notes/254-14-16.md).

Run:  uv run python research/build_254_14_16.py
Writes: research/candidates/254-14-16-rebuilt.json (gitignored staging).
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "kit"))

from bb import build_bb  # noqa: E402
from css import compute_k, verify_css  # noqa: E402
from submit import make_submission, save_submission  # noqa: E402

# a(x) = x^11 + x^51 + x^63, b(x) = x^37 + x^93 + x^122 (exponents on x)
A = [(11, 0), (51, 0), (63, 0)]
B = [(37, 0), (93, 0), (122, 0)]

HX, HZ = build_bb(127, 1, A, B)
assert verify_css(HX, HZ), "CSS commutation failed"
k = compute_k(HX, HZ)
print(f"HX {HX.shape} HZ {HZ.shape}  k = {k}")

doc = make_submission(
    HX,
    HZ,
    name="[[254,14,16]] generalized bicycle on Z_127 (trinomial supports)",
    construction=(
        "Generalized bicycle (two-block) code on the cyclic group "
        "Z_127: H_X = [A|B], H_Z = [B^T|A^T] with trinomial "
        "supports a(x) = x^11+x^51+x^63, b(x) = x^37+x^93+x^122; "
        "check weight 6, k = 2*deg(gcd) <= 14 at w <= 6."
    ),
    authors=["@mathysrennela"],
    family="generalized-bicycle",
    references=["arXiv:2111.03654", "arXiv:2306.16400"],
    confidence="upper_bound",
    trials=8000,
    seed=7,
)
print("d =", doc["distance"]["d"], "| X:", doc["distance"]["X"]["value"], "| Z:", doc["distance"]["Z"]["value"])

out = os.path.join(_HERE, "candidates", "254-14-16-rebuilt.json")
errs = save_submission(doc, out)
print("schema errors:", errs or "none")
print("wrote:", out)
