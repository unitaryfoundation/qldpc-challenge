"""Build routing code submissions and stage for verification.

Routing codes from arXiv:2606.25330v1 (Zhang, Chen, Duan, Li, Wei, Hou, Kong,
Wu, Guo, 2026). Construction: weight-7 codes on torus Z_l x Z_m via
time-reversal symmetric routing vectors {v_t} = {w_t} with v_t = v_{T-t+1}.
The stabilizer of each syndrome qubit is computed from the palindromic
permutation composition (equation 3 of the paper), NOT the simplified
delta_t formula (equation S4).

Model: Mimo-V2.5 (Xiaomi MiMo-V2.5) via GitHub Copilot.

Usage:
    .venv/bin/python research/submit_routing_codes.py
"""
import sys
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "kit"))
sys.path.insert(0, os.path.join(_HERE, "..", "verify"))

from routing_codes import build_routing_code_v2
from submit import make_submission, save_submission

# Only codes that reproduce paper's n,k,CSS,weight exactly.
# v_sequence = w_sequence (time-reversed routing).
CODES = [
    {
        "name": "[[100,8,10]] routing code (arXiv:2606.25330)",
        "l": 20, "m": 10,
        "v": [(0,1),(1,0),(2,1),(0,1),(2,1),(1,0),(0,1)],
        "ref": "Table 1",
    },
    {
        "name": "[[200,8,18]] routing code (arXiv:2606.25330)",
        "l": 40, "m": 10,
        "v": [(0,1),(1,0),(2,1),(0,1),(2,1),(1,0),(0,1)],
        "ref": "Supplemental Table S1",
    },
]


def main():
    """Build both codes and save as schema-valid JSON in research/candidates/."""
    candidates_dir = os.path.join(_HERE, "candidates")
    os.makedirs(candidates_dir, exist_ok=True)

    for code_spec in CODES:
        l, m = code_spec["l"], code_spec["m"]
        v = code_spec["v"]
        w = list(reversed(v))
        name = code_spec["name"]

        print(f"\n{'='*60}")
        print(f"Building {name}")
        print(f"  Torus Z_{l} x Z_{m}, T={len(v)}, v={v}")
        print(f"{'='*60}")

        HX, HZ = build_routing_code_v2(l, m, v, w)
        n = HX.shape[1]
        print(f"  HX: {HX.shape}, HZ: {HZ.shape}")

        # Build full submission with witness search (trials=16000 for better
        # bounds; default 8000 may not find d for the larger code).
        doc = make_submission(
            HX, HZ,
            name=name,
            construction="Weight-7 routing code, time-reversal symmetric, "
                          f"torus Z_{l} x Z_{m}, routing v={v}",
            authors=["@mathysrennela"],
            family="other",
            references=["arXiv:2606.25330"],
            confidence="upper_bound",
            trials=16000,
            seed=42,
        )

        k = doc["k"]
        d = doc["distance"]["d"]
        wx = doc["distance"]["X"]["value"]
        wz = doc["distance"]["Z"]["value"]
        print(f"  n={n}, k={k}, d={d} (X-side={wx}, Z-side={wz})")

        # Save to research/candidates/ (NOT codes/ — that's the trusted dir).
        slug = f"{n}-{k}-{d}"
        path = os.path.join(candidates_dir, f"{slug}.json")
        errs = save_submission(doc, path)
        if errs:
            print(f"  SCHEMA ERRORS: {errs}")
            continue

        print(f"  Saved to {path}")
        print(f"  To validate:")
        print(f"    .venv/bin/python verify/validate_candidate.py {path}")

    print(f"\nDone. Review candidates in {candidates_dir}/")
    print("Nothing is a find until validate_candidate.py returns 'passed: true'.")


if __name__ == "__main__":
    main()
