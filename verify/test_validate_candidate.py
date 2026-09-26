"""Regression tests for validate_candidate -- the trusted autoresearch gate.

Each case isolates one gate so a failure points at the right place:

  1. a genuinely-new valid code PASSES (verifies, not refuted, not a dup);
  2. an OVER-CLAIM (same checks, witnesses inflated) is caught by the refutation,
     and is *not* a duplicate -- so the failure is unambiguously the distance gate;
  3. an exact BOARD DUPLICATE verifies but does not pass (the dedup gate);
  4. a SCHEMA-BROKEN candidate fails at verify and short-circuits;
  5. every verdict carries the validator's source-hash provenance stamp;
  6. a win whose only strict axis is d over a board peer equal in n, k and w is
     labelled as such, with the peer named for a re-measurement.

Fixtures are built from research/ (bb, submit) -- that is fine: the code UNDER TEST
(validate_candidate) imports only verify/, never research/. An explicit seed and a small,
off-board fixture keep the run deterministic and fast.

Run: uv run python verify/test_validate_candidate.py  (or pytest)
"""
import copy
import json
import os
import sys

import numpy as np
import gf2
from bb import build_bb
from submit import make_submission
import validate_candidate as V

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = 0
# a small, fast, off-board BB code: [[36,4,6]] on Z_6 x Z_3 (not on the board)
FRESH = (6, 3, [(0, 1), (0, 2), (5, 0)], [(4, 2), (3, 1), (0, 0)])

_fail = []


def check(name, cond):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}")
    if not cond:
        _fail.append(name)


def heavy_witness(own_H, opp_H, n, target, seed):
    """A genuine nontrivial logical (in ker(opp)\\rowspace(own)) padded with
    stabilizer rows until its weight reaches `target` -- same class, inflated weight."""
    rng = np.random.default_rng(seed)
    v = next(r.copy() % 2 for r in gf2.kernel_basis(opp_H) if not gf2.in_rowspace(r, own_H))
    stab = own_H % 2
    while int(v.sum()) < target:
        v = (v + stab[rng.integers(len(stab))]) % 2
    return v


def main():
    HX, HZ = build_bb(*FRESH)
    n = HX.shape[1]
    good = make_submission(HX, HZ, name="fresh BB", construction="test fixture",
                           authors=["t"], family="bivariate-bicycle", trials=4000)

    print("1. a genuinely-new valid code PASSES:")
    vg = V.validate_candidate(good, seed=SEED)
    check("passes", vg["passed"])
    check("verifies", vg["gates"]["verify"]["ok"])
    check("not refuted", not vg["gates"]["refute"]["refuted"])
    check("not a board duplicate", vg["gates"]["dedup"]["exact_duplicate_of"] is None)
    check("computed cell is weight-6 x unrestricted",
          vg["gates"]["novelty"]["cell"] == ["weight-6", "unrestricted"])

    print("1b. a code compared against ITSELF reports no novelty verdict:")
    # Validating a doc already on the board makes the dedup gate fire. The
    # novelty verdict is withheld rather than reported as "does not advance its
    # board cell", which would read as a rejection on merit when none happened.
    import glob
    onboard = sorted(glob.glob(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "codes", "*.json")))
    if onboard:
        with open(onboard[0]) as f:
            dup = json.load(f)
        vd = V.validate_candidate(dup, seed=SEED)
        check("dedup fires", vd["gates"]["dedup"]["exact_duplicate_of"] is not None)
        check("novelty verdict withheld, not falsified",
              vd["gates"]["novelty"]["board_advancing"] is None)
        check("label names the duplicate, not a cell failure",
              any("already on the board" in x for x in vd["labels"])
              and not any("does not advance" in x for x in vd["labels"]))
        check("still fails the gate", not vd["passed"])

    print("2. an OVER-CLAIM (same checks, inflated witnesses) is rejected:")
    vx = heavy_witness(HX, HZ, n, 20, 1)
    vz = heavy_witness(HZ, HX, n, 20, 2)
    sup = lambda v: sorted(int(j) for j in np.nonzero(v)[0])
    over = copy.deepcopy(good)
    over["distance"] = {
        "d": min(int(vx.sum()), int(vz.sum())),
        "X": {"value": int(vx.sum()), "confidence": "upper_bound", "witness": sup(vx)},
        "Z": {"value": int(vz.sum()), "confidence": "upper_bound", "witness": sup(vz)},
    }
    vo = V.validate_candidate(over, seed=SEED)
    check("does not pass", not vo["passed"])
    check("caught by refute", vo["gates"]["refute"]["refuted"])
    check("verifier still accepts the structure (isolates the distance gate)",
          vo["gates"]["verify"]["ok"])
    check("NOT flagged a duplicate (isolates the distance gate)",
          vo["gates"]["dedup"]["exact_duplicate_of"] is None)

    print("3. an exact BOARD DUPLICATE verifies but does not pass:")
    dup = json.load(open(os.path.join(ROOT, "codes", "16-2-4.json")))
    vd = V.validate_candidate(dup, seed=SEED)
    check("verifies", vd["gates"]["verify"]["ok"])
    check("flagged exact duplicate of 16-2-4.json",
          vd["gates"]["dedup"]["exact_duplicate_of"] == "16-2-4.json")
    check("does not pass", not vd["passed"])

    print("4. a SCHEMA-BROKEN candidate fails at verify and short-circuits:")
    broken = copy.deepcopy(dup)
    broken["k"] = 999                                  # k will not match the recomputed value
    vb = V.validate_candidate(broken, seed=SEED)
    check("fails the verify gate", not vb["gates"]["verify"]["ok"])
    check("does not pass", not vb["passed"])

    print("5. provenance stamp:")
    check("verdict stamps this validator's source hash",
          vg["validator"]["source_sha256"] == V.source_sha256())
    check("source hash is 64 hex chars", len(vg["validator"]["source_sha256"]) == 64)

    print("6. a win whose ONLY strict axis is d is labelled as the suspect pattern:")
    # A construction fixes n, k and w, so the only axis left to gain on is d,
    # the axis that is an upper bound. The gate must name that case and hand
    # back the peer to re-measure, instead of a generic "advances".
    real_board = V._board_entries
    w6 = max(int(HX.sum(axis=1).max()), int(HZ.sum(axis=1).max()))

    def peer(k_peer, d_peer):
        return {"name": f"peer-{k_peer}-{d_peer}.json", "n": n, "k": k_peer,
                "d": d_peer, "fingerprint": "not-the-candidate", "sig": "neither",
                "weight_class": "weight-6", "w": w6, "locality_class": "unrestricted"}

    try:
        V._board_entries = lambda: [peer(4, 5)]            # ties n, k, w; loses on d only
        vd1 = V.validate_candidate(good, seed=SEED, refute=False)
        nov = vd1["gates"]["novelty"]
        check("flagged d_only_gain", nov["d_only_gain"] is True)
        check("advances_by is exactly ['d']", nov["advances_by"] == ["d"])
        check("peer named for the audit",
              nov["d_only_peers"] == [f"[[{n},{good['k']},5]] w={w6} peer-4-5.json"])
        check("label says ONLY on d and names the suspect axis",
              any("ONLY on d" in x and "suspect axis" in x for x in vd1["labels"]))
        check("still passes (the flag is a label, not a pass condition)",
              vd1["passed"])

        V._board_entries = lambda: [peer(3, 5)]            # wins on k as well as d
        vd2 = V.validate_candidate(good, seed=SEED, refute=False)
        check("a win on a structural axis too is NOT d-only",
              vd2["gates"]["novelty"]["d_only_gain"] is False
              and vd2["gates"]["novelty"]["advances_by"] == ["d", "k"])
        check("generic advance label",
              any(x == "advances the weight-6 x unrestricted board" for x in vd2["labels"]))

        # Two peers at once: one beaten on d alone, one on d and k. The whole
        # advance is no longer d-only, but the win over the first peer still
        # rests on a suspect axis alone, so the instruction must still print.
        V._board_entries = lambda: [peer(4, 5), peer(3, 5)]
        vd4 = V.validate_candidate(good, seed=SEED, refute=False)
        nov4 = vd4["gates"]["novelty"]
        check("a structural win elsewhere does NOT clear the d-only flag",
              nov4["d_only_gain"] is False
              and nov4["advances_by"] == ["d", "k"])
        check("the d-only peer is still listed",
              nov4["d_only_peers"] == [f"[[{n},{good['k']},5]] w={w6} peer-4-5.json"])
        label4 = next((x for x in vd4["labels"] if "advances the" in x), "")
        check("label still names the advance",
              label4.startswith("advances the weight-6 x unrestricted board on d, k"))
        check("label still hands back the peer to re-measure",
              "peer-4-5.json" in label4 and "suspect axis" in label4
              and "matched depth" in label4)
        check("still passes (the flag is a label, not a pass condition)",
              vd4["passed"])

        V._board_entries = lambda: [peer(4, 9)]            # board entry dominates
        vd3 = V.validate_candidate(good, seed=SEED, refute=False)
        check("dominated -> no advance, no d-only flag",
              vd3["gates"]["novelty"]["board_advancing"] is False
              and vd3["gates"]["novelty"]["d_only_gain"] is False
              and any("does not advance" in x for x in vd3["labels"]))
    finally:
        V._board_entries = real_board

    print(f"\n{'ALL PASS' if not _fail else 'FAILURES: ' + ', '.join(_fail)}")
    return 1 if _fail else 0


def test_validate_candidate():
    assert main() == 0


def test_main():
    """pytest entry point; the suite body lives in main()."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
