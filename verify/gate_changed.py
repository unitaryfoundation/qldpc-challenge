"""Distance-refutation gate for the codes changed in a PR (CI).

Runs two independent bounded, fixed-seed refutation searches -- RIS
(heuristic_distance) and the syndrome decoder (decode/distance, needs ldpc) --
only on the code/example submissions changed in this PR, and exits non-zero if
EITHER finds a logical lighter than the claimed distance (an over-claim). The
syndrome-decoder cross-check is skipped if ldpc is unavailable (RIS-only). Bulk
re-verification of the whole board stays cheap -- only new/changed files pay the
search cost (~10 s per method).

Usage:
  python verify/gate_changed.py [BASE] [files...]
    BASE     git ref to diff against (default origin/main); ignored if files given
    files    explicit code JSONs to gate (otherwise computed from the diff)
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import heuristic_distance as H

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_syndrome():
    """The syndrome-decoder cross-check (decode/distance.py); needs ldpc. Returns
    the module or None so the gate degrades to RIS-only without it."""
    try:
        sys.path.insert(0, os.path.join(ROOT, "decode"))
        import distance as sd
        return sd
    except Exception:
        return None


def changed_codes(base):
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", f"{base}...HEAD", "--", "codes", "verify/fixtures"],
            cwd=ROOT, text=True)
    except Exception as e:
        print(f"(could not compute diff vs {base}: {e}); gating nothing")
        return []
    return [f for f in out.split() if f.endswith(".json")]


def main(argv):
    files = [a for a in argv if a.endswith(".json")]
    base = next((a for a in argv if not a.endswith(".json")), "origin/main")
    if not files:
        files = changed_codes(base)
    if not files:
        print("no changed code submissions to gate")
        return 0

    SD = _load_syndrome()
    if SD is None:
        print("note: syndrome-decoder cross-check unavailable (ldpc missing); "
              "running RIS only\n")

    refuted = 0
    for f in files:
        p = f if os.path.isabs(f) else os.path.join(ROOT, f)
        if not os.path.exists(p):                 # deleted/renamed away
            continue
        doc = json.load(open(p))
        if "distance" not in doc or "d" not in doc.get("distance", {}):
            continue
        # two independent mechanisms; a hit from EITHER refutes the claim.
        results = {"RIS": H.refute_check(doc, seed=0)}
        if SD is not None:
            results["syndrome-decoder"] = SD.refute_check(doc, seed=0)
        hits = {m: (dh, wit) for m, (ref, dh, wit, _) in results.items() if ref}
        if hits:
            refuted += 1
            for m, (dh, wit) in hits.items():
                print(f"REFUTED  {f} [{m}]: weight-{dh} logical < claimed distance "
                      f"{doc['distance']['d']}\n         witness = {wit}")
        else:
            print(f"ok       {f}: no logical lighter than {doc['distance']['d']} "
                  f"({' + '.join(results)})")
    if refuted:
        print(f"\n{refuted} submission(s) refuted: claimed distance is not supported "
              f"by an independent search. See witnesses above.")
    return 1 if refuted else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
