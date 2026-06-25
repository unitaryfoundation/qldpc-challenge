"""
Adversarial tests for the verifier: the trust anchor of the challenge must
ACCEPT a valid submission and REJECT every way a bad one can be wrong.

Run: uv run python verify/test_verifier.py   (or: pytest verify/test_verifier.py)

Each tamper takes the known-good examples/72-6-6.json, breaks exactly one
thing, and asserts the verifier flags it (report["ok"] is False, and ideally
the specific check fails). A green run means a hostile or mistaken submission
cannot slip a false claim onto the board.
"""

import copy
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qldpc_verify import verify

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOOD = json.load(open(os.path.join(ROOT, "examples", "72-6-6.json")))

_fail = []


def check(name, cond):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}")
    if not cond:
        _fail.append(name)


def rep(doc):
    return verify(doc)


def failed_checks(r):
    return {c["check"] for c in r["checks"] if not c["ok"]}


def main():
    print("ACCEPT the valid submission:")
    r = rep(GOOD)
    check("valid code passes", r["ok"])
    check("earns a distance tier", "d" in r["earned_distance"])

    print("\nREJECT tampered submissions:")

    # 1. fake (too-short) distance witness: claim d=6 but witness has weight 4
    d = copy.deepcopy(GOOD)
    d["distance"]["X"]["witness"] = d["distance"]["X"]["witness"][:4]
    r = rep(d)
    check("short witness rejected (weight != value)",
          not r["ok"] and "distance_X_witness" in failed_checks(r))

    # 2. witness that is a stabilizer (trivial): use an X-check row as the
    #    'logical' witness -- it commutes but is in rowspace(H_X), so trivial
    d = copy.deepcopy(GOOD)
    stab = d["checks"]["X"][0]
    d["distance"]["X"]["witness"] = stab
    d["distance"]["X"]["value"] = len(stab)
    d["distance"]["d"] = min(len(stab), d["distance"]["Z"]["value"])
    r = rep(d)
    check("trivial (stabilizer) witness rejected",
          not r["ok"] and "distance_X_witness" in failed_checks(r))

    # 3. broken CSS commutation: flip one bit into an X-check so H_X H_Z^T != 0
    d = copy.deepcopy(GOOD)
    q = (set(range(d["n"])) - set(d["checks"]["X"][0])).pop()
    d["checks"]["X"][0] = sorted(d["checks"]["X"][0] + [q])
    r = rep(d)
    check("broken CSS commutation rejected",
          not r["ok"] and "css_commutation" in failed_checks(r))

    # 4. inflated k claim
    d = copy.deepcopy(GOOD)
    d["k"] = d["k"] + 2
    r = rep(d)
    check("wrong k rejected",
          not r["ok"] and "k_matches_claim" in failed_checks(r))

    # 5. out-of-range qubit index
    d = copy.deepcopy(GOOD)
    d["checks"]["Z"][0] = sorted(set(d["checks"]["Z"][0] + [d["n"] + 5]))
    r = rep(d)
    check("out-of-range qubit index rejected",
          not r["ok"] and "qubit_indices_in_range" in failed_checks(r))

    # 6. inflated distance: claim d larger than the witness actually achieves
    d = copy.deepcopy(GOOD)
    d["distance"]["X"]["value"] += 3
    d["distance"]["d"] = min(d["distance"]["X"]["value"],
                             d["distance"]["Z"]["value"])
    r = rep(d)
    check("inflated distance value rejected",
          not r["ok"] and "distance_X_witness" in failed_checks(r))

    # 7. locality claim too tight (interaction radius understated)
    if "locality" in GOOD:
        d = copy.deepcopy(GOOD)
        d["locality"]["interaction_radius"] = 1.0
        r = rep(d)
        check("understated interaction radius rejected",
              not r["ok"]
              and "interaction_radius_within_claim" in failed_checks(r))

    # 7a. claims a 2d-local track but ships no layout: 2D-locality is unproven
    if any(t.startswith("2d-local") for t in GOOD.get("tracks", [])):
        d = copy.deepcopy(GOOD)
        d.pop("locality", None)
        r = rep(d)
        check("2d-local track without a locality block rejected",
              not r["ok"] and "locality_block_present" in failed_checks(r))

        # 7b. crammed layout: collapse qubits onto a sub-unit-spaced line so the
        #     radius looks tiny -- the spacing rule must catch the fake
        d = copy.deepcopy(GOOD)
        d["locality"]["coordinates"] = [[0.001 * i, 0.0] for i in range(d["n"])]
        d["locality"].pop("interaction_radius", None)
        r = rep(d)
        check("crammed (sub-unit spacing) layout rejected",
              not r["ok"]
              and any("no_qubit_cramming" in c for c in failed_checks(r)))

        # 7c. honest spacing but long range: spread qubits on a unit line so a
        #     check spans far beyond the track radius cap
        d = copy.deepcopy(GOOD)
        d["locality"]["coordinates"] = [[float(i), 0.0] for i in range(d["n"])]
        d["locality"]["layers"] = 1
        d["locality"].pop("interaction_radius", None)
        r = rep(d)
        check("over-radius (non-local) layout rejected",
              not r["ok"]
              and any("radius_within_cap" in c for c in failed_checks(r)))

    # 8. malformed: missing a required field, must not crash
    d = copy.deepcopy(GOOD)
    del d["checks"]
    try:
        r = rep(d)
        check("malformed (missing checks) rejected cleanly",
              not r["ok"] and "schema_valid" in failed_checks(r))
    except Exception as e:
        check(f"malformed rejected cleanly (raised {type(e).__name__})", False)

    # 9. not even a dict, must not crash
    try:
        r = rep([1, 2, 3])
        check("non-object submission rejected cleanly", not r["ok"])
    except Exception as e:
        check(f"non-object rejected cleanly (raised {type(e).__name__})", False)

    # 10. duplicate detection: a code shares signature AND fingerprint with
    #     itself, and is invariant to row reordering (same stabilizer group).
    r1 = rep(GOOD)
    d = copy.deepcopy(GOOD)
    d["checks"]["X"] = list(reversed(d["checks"]["X"]))  # reorder checks
    r2 = rep(d)
    check("identical codes share WL signature", r1["signature"]["hash"]
          == r2["signature"]["hash"])
    check("row-reordered code has same exact fingerprint",
          r1["fingerprint"] == r2["fingerprint"])

    # 11. a genuinely different code has a different WL signature. Pick any
    #     board code that is not the [[72,6,6]] used above.
    others = [p for p in glob.glob(os.path.join(ROOT, "codes", "*.json"))
              if os.path.basename(p) != "72-6-6.json"]
    other = json.load(open(others[0]))
    check("distinct codes have distinct WL signatures",
          rep(other)["signature"]["hash"] != r1["signature"]["hash"])

    # every shipped example/code still verifies
    print("\nshipped submissions still verify:")
    for p in (sorted(glob.glob(os.path.join(ROOT, "codes", "*.json")))
              + sorted(glob.glob(os.path.join(ROOT, "examples", "*.json")))):
        ok = verify(json.load(open(p)))["ok"]
        if not ok:
            check(f"{os.path.basename(p)} verifies", False)
    if not _fail:
        print("  ok    all shipped submissions verify")

    print(f"\n{'ALL PASS' if not _fail else 'FAILURES: ' + ', '.join(_fail)}")
    return 1 if _fail else 0


# pytest entry points
def test_adversarial():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
