"""Verify every submission under codes/ and the verify/fixtures/ test inputs, and flag possible
duplicates by permutation-invariant signature. Used by CI. Exit 0 only if all
pass and no two codes/ entries share a signature."""

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from qldpc_verify import verify

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    code_paths = sorted(glob.glob(os.path.join(ROOT, "codes", "*.json")))
    paths = code_paths + sorted(glob.glob(os.path.join(ROOT, "verify", "fixtures", "*.json")))
    if not paths:
        print("no submissions found")
        sys.exit(0)
    failed = []
    sigs = {}
    fps = {}
    for p in paths:
        with open(p) as f:
            doc = json.load(f)
        rep = verify(doc)
        rel = os.path.relpath(p, ROOT)
        if rep["ok"]:
            ed = rep["earned_distance"].get("d", {})
            print(f"PASS  {rel}  -> d{ed.get('value','?')} "
                  f"({ed.get('tier','-')})")
            if rel.startswith("codes/"):
                if "signature" in rep:
                    sigs.setdefault(rep["signature"]["hash"], []).append(rel)
                if "fingerprint" in rep:
                    fps.setdefault(rep["fingerprint"], []).append(rel)
        else:
            failed.append(rel)
            bad = [c["check"] for c in rep["checks"] if not c["ok"]]
            print(f"FAIL  {rel}  -> {', '.join(bad)}")

    # identical codes (same stabilizer group, same labeling): a hard error.
    identical = {h: v for h, v in fps.items() if len(v) > 1}
    if identical:
        print("\nIDENTICAL CODES (same stabilizer group) -- reject:")
        for h, v in identical.items():
            print(f"  {', '.join(v)}")
    # same WL signature but not identical: likely permutation-equivalent, flag
    # for human review (WL is a strong necessary condition, not a proof).
    soft = {h: v for h, v in sigs.items()
            if len(v) > 1 and not any(set(v) <= set(iv)
                                      for iv in identical.values())}
    if soft:
        print("\nPOSSIBLE EQUIVALENT CODES (same Weisfeiler-Leman signature; "
              "review):")
        for h, v in soft.items():
            print(f"  {h}: {', '.join(v)}")

    print(f"\n{len(paths)-len(failed)}/{len(paths)} passed")
    sys.exit(1 if (failed or identical) else 0)
