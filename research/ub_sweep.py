#!/usr/bin/env python3
"""Univariate bicycle (UB) code sweep — arXiv:2605.14173v1 (Rabeti-Mahdavifar).

A UB code is a generalized bicycle GB(a, b) with the Frobenius coupling
b(x) = a(x)^t in R_n = F2[x]/(x^n - 1), t = 2^l.  By Lemma 2 of the paper,
b(x) = a(x^(2^l)) mod (x^n - 1): same weight as a when n is odd.

The paper's Table I rows are reconstructed exactly, packaged through
research/kit/submit.py (both side witnesses embedded), and sent through the
trusted validator.  Only validator-passing, board-advancing rows count.

Everything is persisted: per-row staged JSON + verdict under
research/candidates/, plus this script (committed) as the audit trail.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "research" / "kit"), str(ROOT / "verify")]

from css import compute_k, verify_css  # noqa: E402
from submit import make_submission, save_submission  # noqa: E402
from surrogate import distance_rand  # noqa: E402
from validate_candidate import validate_candidate  # noqa: E402

OUT = ROOT / "research" / "candidates"

# Table I of arXiv:2605.14173v1: (a-exponents, l, claimed [[N,k,d]], w)
TABLE = [
    ([0, 1, 4, 7], 3, (124, 14, 11), 8),
    ([0, 2, 9, 10], 4, (146, 20, 8), 8),
    ([0, 9, 10, 12], 5, (178, 24, 13), 8),
    ([0, 4, 8, 18], 6, (204, 36, 8), 8),
    ([0, 1, 5, 13], 5, (234, 26, 14), 8),
    ([0, 5, 6], 3, (252, 12, 14), 6),
    ([0, 4, 7], 3, (254, 14, 14), 6),
    ([0, 2, 7], 5, (372, 14, 12), 6),
    ([0, 1, 6], 9, (378, 12, 22), 6),
]


def circ(n: int, exponents) -> np.ndarray:
    """Circulant matrix Circ(a(x)) for a(x) = sum x^e over GF(2)."""
    M = np.zeros((n, n), dtype=np.int8)
    for e in exponents:
        e %= n
        for i in range(n):
            M[(i + e) % n, i] ^= 1
    return M


def build_ub(n: int, a_exp, ell: int):
    """UB(a, l): H_X=[A,B], H_Z=[B^T,A^T] with b = a(x^(2^l)) in R_n."""
    b_exp = sorted({(e * pow(2, ell, n)) % n for e in a_exp})
    A = circ(n, a_exp)
    B = circ(n, b_exp)
    HX = np.concatenate([A, B], axis=1).astype(np.int8)
    HZ = np.concatenate([B.T, A.T], axis=1).astype(np.int8)
    return HX, HZ


def main() -> None:
    results = []
    for row, (a_exp, ell, (N, k_claim, d_claim), w) in enumerate(TABLE, 1):
        n = N // 2
        hx, hz = build_ub(n, a_exp, ell)
        assert verify_css(hx, hz), f"row {row}: CSS failed"
        k = compute_k(hx, hz)
        assert hx.shape[1] == N, f"row {row}: n mismatch"
        trials = 4000 if N <= 300 else 12000
        seed = 260514173 + row
        d = distance_rand(hx, hz, trials=trials, seed=seed)
        doc = make_submission(
            hx, hz,
            name=f"[[{N},{k},d<={d}]] univariate bicycle UB(a,l={ell})",
            construction=(
                f"Univariate bicycle code over R_{n} = F2[x]/(x^{n}-1); "
                f"a(x) = {' + '.join(f'x^{e}' for e in a_exp)}; "
                f"b(x) = a(x^(2^{ell})) mod (x^{n}-1) "
                f"(Frobenius coupling, arXiv:2605.14173v1 Table I row {row}); "
                f"H_X=[A,B], H_Z=[B^T,A^T]."
            ),
            authors=["@mathysrennela"],
            family="generalized-bicycle",
            references=["arXiv:2605.14173"],
            notes=(
                f"Paper claims [[{N},{k_claim},{d_claim}]] (distance via "
                "codeDistance/QDistRnd-style search); this record is a "
                "witness-backed upper bound from the repository surrogate at "
                f"{trials} trials."
            ),
            confidence="upper_bound",
            trials=trials, seed=seed,
        )
        path = OUT / f"ub-{N}-{k}-{d}.json"
        errs = save_submission(doc, str(path))
        verdict = validate_candidate(doc, seed=seed + 777, refute=True)
        path.with_suffix(".verdict.json").write_text(
            json.dumps(verdict, indent=2) + "\n")
        nov = verdict.get("gates", {}).get("novelty", {})
        rec = {
            "row": row, "a": a_exp, "ell": ell,
            "paper": [N, k_claim, d_claim],
            "reconstructed_k": k, "witnessed_d": d,
            "k_matches_paper": k == k_claim,
            "passed": verdict.get("passed"),
            "board_advancing": nov.get("board_advancing"),
            "dominated_by": nov.get("dominated_by"),
            "path": str(path.relative_to(ROOT)),
        }
        results.append(rec)
        print(json.dumps(rec), flush=True)

    (OUT / "ub-sweep-summary.json").write_text(
        json.dumps(results, indent=2) + "\n")
    adv = [r for r in results if r["passed"] and r["board_advancing"]]
    print(f"\n{len(adv)} board-advancing validated rows")


if __name__ == "__main__":
    main()
