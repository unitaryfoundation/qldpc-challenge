"""Regression tests for the refutation gate.

GATE  An over-claimed distance (genuine but artificially heavy witnesses, so the
      cheap structural checks all pass) must be REJECTED by verify(refute=True),
      and -- to show why refutation is the thing that catches it -- ACCEPTED by
      verify(refute=False). refute=True is run by the per-PR gate (gate_changed)
      and the weekly whole-board job (refute_board).

F2    If the refuter cannot run, verify(refute=True) must FAIL CLOSED (ok False),
      never silently pass.

SEED  The refutation seed is random by default (so an over-claim can't reliably
      evade one fixed search); the seed is reported for reproducibility, and an
      explicit seed makes a run deterministic. Tests pass seed=0 to stay stable.

Run: uv run python verify/test_refute_gate.py  (or pytest)
"""
import copy
import json
import os
import sys
import time

import gf2
import heuristic_distance
import numpy as np
import qldpc_verify

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

    # explicit seed -> deterministic test (the gate is random by default)
    r_on = qldpc_verify.verify(over, refute=True, seed=0)
    nd = next((c for c in r_on["checks"] if c["check"] == "distance_not_refuted"), None)
    check("refute=True REJECTS the over-claim", not r_on["ok"])
    check("distance_not_refuted is the failing check", nd is not None and not nd["ok"])
    check("the seed is reported (reproducible)", nd is not None and "seed 0" in nd["detail"])

    print("\nF2: a refuter error fails CLOSED")
    good = json.load(open(os.path.join(ROOT, "verify", "fixtures", "72-6-6.json")))
    orig = heuristic_distance.refute_check
    try:
        def boom(*a, **k):
            raise RuntimeError("simulated refuter failure")
        heuristic_distance.refute_check = boom
        r = qldpc_verify.verify(good, refute=True, seed=0)
    finally:
        heuristic_distance.refute_check = orig
    nd = next((c for c in r["checks"] if c["check"] == "distance_not_refuted"), None)
    check("refuter error makes verify FAIL (not pass)", not r["ok"])
    check("distance_not_refuted failed closed with a clear message",
          nd is not None and not nd["ok"] and "failing closed" in nd["detail"])
    # sanity: the same code passes cleanly when the refuter works
    check("valid code still passes with a working refuter",
          qldpc_verify.verify(good, refute=True, seed=0)["ok"])

    print("\nrandom-by-default: two no-seed runs draw different seeds")
    d1 = next(c for c in qldpc_verify.verify(good, refute=True)["checks"]
              if c["check"] == "distance_not_refuted")["detail"]
    d2 = next(c for c in qldpc_verify.verify(good, refute=True)["checks"]
              if c["check"] == "distance_not_refuted")["detail"]
    check("no-seed runs are non-deterministic (different seeds reported)", d1 != d2)

    print("\nCELL: deep-tier record detection is cell-aware, not global")
    # A 2D-local cell record that a nonlocal code dominates GLOBALLY must still
    # count as a record (and so face the deep refutation tier). Regression for
    # the locality-blind global frontier the gate used before.
    import tempfile

    import gate_changed

    with tempfile.TemporaryDirectory() as td:
        cd = os.path.join(td, "codes")
        os.makedirs(cd)
        docs = {
            # local-2d-single record: nothing in its cell dominates it
            "local-rec": {"n": 4, "k": 2, "distance": {"d": 2},
                          "checks": {"X": [[0, 1]], "Z": [[2, 3]]},
                          "locality": {"coordinates": [[0, 0], [1, 0],
                                                       [0, 1], [1, 1]],
                                       "layers": 1}},
            # nonlocal code that dominates local-rec on every (n,k,d,w) axis
            "global-dom": {"n": 2, "k": 9, "distance": {"d": 9},
                           "checks": {"X": [[0, 1]], "Z": [[0, 1]]}},
            # local code dominated INSIDE its own cell by local-rec
            "local-dominated": {"n": 6, "k": 1, "distance": {"d": 1},
                                "checks": {"X": [[0, 1]], "Z": [[4, 5]]},
                                "locality": {"coordinates": [[0, 0], [1, 0],
                                                             [2, 0], [0, 1],
                                                             [1, 1], [2, 1]],
                                             "layers": 1}},
        }
        for slug, doc in docs.items():
            json.dump(doc, open(os.path.join(cd, f"{slug}.json"), "w"))
        rec = gate_changed.board_record_slugs(td)
        check("locally-undominated code is a record despite global domination",
              "local-rec" in rec)
        check("globally-undominated code is still a record", "global-dom" in rec)
        check("code dominated within its own cell is not a record",
              "local-dominated" not in rec)

    print(f"\n{'ALL PASS' if not _fail else 'FAILURES: ' + ', '.join(_fail)}")
    return 1 if _fail else 0


def test_refute_gate():
    assert main() == 0


def test_main():
    """pytest entry point; the suite body lives in main()."""
    assert main() == 0


def _fake_syndrome_ok(doc, seed, max_seconds, out):
    out.put({"kind": "ok", "result": (True, 3, [1, 2, 3], 99)})


def _fake_syndrome_hangs(doc, seed, max_seconds, out):
    time.sleep(60)


def test_bounded_syndrome_decoder_returns_child_result():
    import gate_changed

    got = gate_changed._syndrome_refute_bounded(
        {}, seed=7, max_seconds=0.1, grace_seconds=0.1,
        worker=_fake_syndrome_ok,
    )
    assert got == (True, 3, [1, 2, 3], 99)


def test_bounded_syndrome_decoder_times_out():
    import gate_changed

    t0 = time.monotonic()
    got = gate_changed._syndrome_refute_bounded(
        {}, seed=7, max_seconds=0.05, grace_seconds=0.05,
        worker=_fake_syndrome_hangs,
    )
    assert got == (False, None, None, 0)
    assert time.monotonic() - t0 < 5


if __name__ == "__main__":
    sys.exit(main())
