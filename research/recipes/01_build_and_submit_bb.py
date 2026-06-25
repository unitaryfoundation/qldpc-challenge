"""Recipe 01 -- the whole loop on the simplest family.

Build a known bivariate-bicycle code, read its (n, k), estimate its distance
(getting an explicit witness for free), package a schema-valid submission, and
run it through the real verifier in-process to prove it would pass CI.

Run:
    uv run python research/recipes/01_build_and_submit_bb.py

Then, for a real entry, write the doc into codes/ and verify from the CLI:
    uv run python verify/qldpc_verify.py codes/your-code.json
"""
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_RESEARCH = os.path.join(_HERE, "..")
_REPO = os.path.join(_RESEARCH, "..")
sys.path.insert(0, _RESEARCH)              # research/ modules
sys.path.insert(0, os.path.join(_REPO, "verify"))  # the verifier

from bb import build_bb, KNOWN
from css import compute_k, verify_css
from surrogate import distance_rand
from submit import make_submission, save_submission, validate
import qldpc_verify

# 1. Build a code. Start from a known BB code; change l, m, A, B to explore.
p = KNOWN["[[72,12,6]]"]
HX, HZ = build_bb(p["l"], p["m"], p["A"], p["B"])
n = HX.shape[1]
k = compute_k(HX, HZ)
assert verify_css(HX, HZ), "checks must commute"
print(f"1. built a CSS code:  n={n}  k={k}  css=ok")

# 2. Estimate the distance. This is an UPPER BOUND; raise trials until it stops
#    dropping, then trust it as d <= value. (For 72-12-6 the true d is 6.)
d = distance_rand(HX, HZ, trials=600, seed=0)
print(f"2. distance_rand upper bound:  d <= {d}")

# 3. Package a submission. The witnesses are extracted and pre-checked against
#    the verifier's own criteria, so this doc is built to pass.
doc = make_submission(
    HX, HZ,
    name=f"[[{n},{k},{d}]] gross-code BB (starter-kit demo)",
    construction=("Periodic bivariate-bicycle code on Z_6 x Z_6, "
                  "A = x^3 + y + y^2, B = y^3 + x + x^2 (Bravyi et al.)."),
    authors=["your-handle"],
    tracks=["bivariate bicycle (periodic)"],
    references=["arXiv:2308.07915"],
    confidence="upper_bound",
)
errs = validate(doc)
print(f"3. packaged submission:  schema_valid={not errs}  "
      f"claims [[{doc['n']},{doc['k']},{doc['distance']['d']}]]")
if errs:
    print("   schema errors:", errs[:3])

# 4. Run the actual verifier in-process (the same code CI runs).
report = qldpc_verify.verify(doc, refute=False)
failed = [c["check"] for c in report["checks"] if not c["ok"]]
print(f"4. verifier says ok={report['ok']}  earned_distance={report.get('earned_distance')}")
if failed:
    print("   FAILED checks:", failed)

# 5. Write it out (demo lands in a temp file; real entries go in codes/).
out = os.path.join(tempfile.gettempdir(), "demo_72-12-6.json")
save_submission(doc, out)
print(f"5. wrote demo submission to {out}")
print("   For a real entry: save into codes/ and open a PR (see CONTRIBUTING.md).")
