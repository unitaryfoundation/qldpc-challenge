"""Regression tests for the refutation gate.

GATE  An over-claimed distance (genuine but artificially heavy witnesses, so the
      cheap structural checks all pass) must be REJECTED by verify(refute=True),
      and -- to show why refutation is the thing that catches it -- ACCEPTED by
      verify(refute=False). refute=True is run by the per-PR gate (gate_changed)
      and the weekly whole-board job (refute_board).

F2    If the refuter cannot run, verify(refute=True) must FAIL CLOSED (ok False),
      never silently pass.

Run: uv run python verify/test_refute_gate.py  (or pytest)
"""
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import gf2
import qldpc_verify
import heuristic_distance

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_fail = []


def check(name, cond):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}")
    if not cond:
        _fail.append(name)


def _matrix(supports, n):
    H = np.zeros((len(supports), n), dtype=np.int8)
    for r, sup in enumerate(supports):
        for q in sup:
            H[r, q] = 1
    return H


def _heavy_logical(own_H, opp_H, n, target, seed):
    """A genuine nontrivial logical (in ker(opp_H), not in rowspace(own_H)) made
    heavy by XOR-ing in stabilizer rows -- same logical class, inflated weight."""
    rng = np.random.default_rng(seed)
    v = next(row.copy() % 2 for row in gf2.kernel_basis(opp_H)
             if not gf2.in_rowspace(row, own_H))
    stab = own_H % 2
    for _ in range(3000):
        if int(v.sum()) >= target:
            break
        v = (v + stab[rng.integers(len(stab))]) % 2
    return v, int(v.sum())


def _inflated_doc():
    """Real [[16,2,4]] checks, distance inflated with heavy genuine witnesses."""
    doc = json.load(open(os.path.join(ROOT, "codes", "16-2-4.json")))
    n = doc["n"]
    HX = _matrix(doc["checks"]["X"], n)
    HZ = _matrix(doc["checks"]["Z"], n)
    vx, wx = _heavy_logical(HX, HZ, n, target=8, seed=1)
    vz, wz = _heavy_logical(HZ, HX, n, target=8, seed=2)
    sup = lambda v: sorted(int(j) for j in np.nonzero(v)[0])
    over = copy.deepcopy(doc)
    over["distance"] = {
        "d": min(wx, wz),
        "X": {"value": wx, "confidence": "upper_bound", "witness": sup(vx)},
        "Z": {"value": wz, "confidence": "upper_bound", "witness": sup(vz)},
    }
    return over, doc["distance"]["d"]


def main():
    print("GATE: over-claim is rejected by refute=True, accepted by refute=False")
    over, true_d = _inflated_doc()
    claim = over["distance"]["d"]
    check(f"witness weights are genuine (claim {claim} > true {true_d})", claim > true_d)

    r_off = qldpc_verify.verify(over, refute=False)
    check("refute=False ACCEPTS the over-claim (the gap F1 closes)", r_off["ok"])

    r_on = qldpc_verify.verify(over, refute=True)
    nd = next((c for c in r_on["checks"] if c["check"] == "distance_not_refuted"), None)
    check("refute=True REJECTS the over-claim", not r_on["ok"])
    check("distance_not_refuted is the failing check", nd is not None and not nd["ok"])

    print("\nF2: a refuter error fails CLOSED")
    good = json.load(open(os.path.join(ROOT, "examples", "72-6-6.json")))
    orig = heuristic_distance.refute_check
    try:
        def boom(*a, **k):
            raise RuntimeError("simulated refuter failure")
        heuristic_distance.refute_check = boom
        r = qldpc_verify.verify(good, refute=True)
    finally:
        heuristic_distance.refute_check = orig
    nd = next((c for c in r["checks"] if c["check"] == "distance_not_refuted"), None)
    check("refuter error makes verify FAIL (not pass)", not r["ok"])
    check("distance_not_refuted failed closed with a clear message",
          nd is not None and not nd["ok"] and "failing closed" in nd["detail"])
    # sanity: the same code passes cleanly when the refuter works
    check("valid code still passes with a working refuter",
          qldpc_verify.verify(good, refute=True)["ok"])

    print(f"\n{'ALL PASS' if not _fail else 'FAILURES: ' + ', '.join(_fail)}")
    return 1 if _fail else 0


def test_refute_gate():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
