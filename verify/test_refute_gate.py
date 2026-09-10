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


def _synthetic_gb_matrices(L=21, a=(0, 3, 6, 12), b=(0, 7)):
    """A circulant GB code from its symbols: H_X = [circ(a)|circ(b)],
    H_Z = [circ(b)^T|circ(a)^T]. Its lightest single-block logical is weight 3."""
    def circ(sym):
        M = np.zeros((L, L), dtype=np.int8)
        for i in range(L):
            for e in sym:
                M[i, (e + i) % L] = 1
        return M
    A, B = circ(a), circ(b)
    return np.hstack([A, B]).astype(np.int8), np.hstack([B.T, A.T]).astype(np.int8)


def _synthetic_gb_doc(claim):
    """A submittable circulant GB doc with genuine witnesses and a chosen claim.

    Synthetic ON PURPOSE. These tests previously asserted against live board
    entries that were over-stated at the time. Getting those entries corrected
    is precisely what this mechanism is for, so the fixtures were guaranteed to
    stop being over-stated -- and when the corrections merged they broke every
    open submission PR. A fixture for this mechanism must not be board data the
    mechanism is designed to change.

    `claim` drives which path the gate takes: above weight 3 the structural
    pass refutes it, at or below 1 nothing can, whatever else moves on the board.
    """
    HX, HZ = _synthetic_gb_matrices()
    n = HX.shape[1]
    sup = lambda M: [sorted(int(j) for j in np.nonzero(r)[0]) for r in M]
    vx, wx = _heavy_logical(HX, HZ, n, target=max(claim, 4), seed=1)
    vz, wz = _heavy_logical(HZ, HX, n, target=max(claim, 4), seed=2)
    one = lambda v: sorted(int(j) for j in np.nonzero(v)[0])
    return {
        "schema_version": "0.2",
        "name": f"[[{n},8,{claim}]] synthetic circulant GB test fixture",
        "code_type": "CSS",
        "n": n, "k": 8,
        "checks": {"X": sup(HX), "Z": sup(HZ)},
        "distance": {
            "d": claim,
            "X": {"value": claim, "confidence": "upper_bound", "witness": one(vx)},
            "Z": {"value": claim, "confidence": "upper_bound", "witness": one(vz)},
        },
        "provenance": {"authors": ["@test"], "construction": "test fixture",
                       "date": "2026-01-01"},
        "family": "generalized-bicycle",
    }


def test_structural_gb_pass():
    """The circulant-GB mechanism as the gate calls it (issue #942).

    Skipped when the optional accelerator is not built: without it the gate
    behaves exactly as it did before this mechanism existed, which is the whole
    safety argument -- the pass is strictly additive and never a prerequisite.
    """
    try:
        import gf2_fast                                     # noqa: F401
    except ImportError:
        import pytest
        pytest.skip("gf2_fast not built (run `make fast`); the structural pass "
                    "is strictly additive, so the gate is unchanged without it.")
    import gate_changed as G

    # A code that is not a circulant GB must be reported as NOT SEARCHED
    # (trials 0), so the caller leaves it out of the mechanism list entirely
    # rather than recording a meaningless null result against it.
    doc = json.load(open(os.path.join(ROOT, "verify", "fixtures", "72-6-6.json")))
    ref, found, wit, tr = G._structural_refute(doc, seed=11,
                                               trials=G.STRUCT_TRIALS_STD)
    check("non-circulant code is not searched",
          (ref, found, wit, tr) == (False, None, None, 0))

    # An over-claimed circulant GB entry is refuted, with a witness the pinned
    # python stack validated (_structural_refute returns None otherwise).
    over = _synthetic_gb_doc(claim=8)
    ref, found, wit, tr = G._structural_refute(over, seed=11,
                                               trials=G.STRUCT_TRIALS_STD)
    check("over-claimed circulant GB code is refuted",
          bool(ref and found is not None and found < 8 and wit))
    if wit:
        n = over["n"]
        v = np.zeros(n, dtype=np.int8)
        v[list(wit)] = 1
        HX, HZ = _synthetic_gb_matrices()
        in_ker = (not ((HX @ v) % 2).any()) or (not ((HZ @ v) % 2).any())
        check("the returned witness is a real kernel vector", in_ker)

    # And a claim nothing can beat is left alone.
    honest = _synthetic_gb_doc(claim=1)
    ref, found, wit, tr = G._structural_refute(honest, seed=11,
                                               trials=G.STRUCT_TRIALS_STD)
    check("un-beatable claim is not refuted", not ref and tr > 0)

    print(f"\n{'ALL PASS' if not _fail else 'FAILURES: ' + ', '.join(_fail)}")
    assert not _fail, _fail


def test_structural_stage_ordering():
    """Stage 1 (circulant-GB) runs first and short-circuits ONLY on a hit.

    Three paths, and the middle one matters most:
      * circulant and over-claimed -> stage 1 refutes and the general battery
        is skipped, because a validated refutation cannot be undone by more
        searching (and the battery is where the wall-clock goes);
      * circulant and not beatable -> stage 1 clears it and the FULL battery
        still runs, because a structural miss proves nothing: that search only
        sees single-block logicals, and most real witnesses are mixed-support;
      * not circulant -> stage 1 is a no-op and the battery runs as before.
    """
    try:
        import gf2_fast                                     # noqa: F401
    except ImportError:
        import pytest
        pytest.skip("gf2_fast not built (run `make fast`); without it stage 1 "
                    "never runs and the gate is unchanged.")
    import shutil
    import subprocess
    import tempfile

    def gate_receipt(doc=None, src=None):
        """Run the gate on a temp code file and return its receipt gate block."""
        dst = os.path.join(ROOT, "codes", "zz-stage-probe.json")
        if doc is not None:
            with open(dst, "w") as f:
                json.dump(doc, f)
        else:
            shutil.copy(os.path.join(ROOT, src), dst)
        try:
            with tempfile.TemporaryDirectory() as rd:
                subprocess.run(
                    [sys.executable, os.path.join(ROOT, "verify", "gate_changed.py"),
                     "--seed", "0", "--receipt-dir", rd, dst],
                    cwd=ROOT, capture_output=True, text=True)
                rp = os.path.join(rd, "zz-stage-probe.json")
                if not os.path.exists(rp):
                    return None
                return json.load(open(rp))["trusted_validation"]["distance_gate"]
        finally:
            if os.path.exists(dst):
                os.remove(dst)

    g = gate_receipt(doc=_synthetic_gb_doc(claim=8))
    if g is not None:
        check("over-claimed circulant refutes at stage 1", bool(g["refuted"]))
        check("stage 1 hit short-circuits the battery",
              g.get("short_circuited_by") == "circulant-GB")
        check("only the structural mechanism ran",
              list(g["methods"]) == ["circulant-GB"])
        check("no general trials were spent", g["trials"] == 0 and not g["seeds"])

    g = gate_receipt(doc=_synthetic_gb_doc(claim=1))
    if g is not None:
        check("un-beatable circulant is not refuted", not g["refuted"])
        check("stage 1 runs on it", "circulant-GB" in g["methods"])
        check("a stage 1 MISS still pays the full battery",
              any(m.startswith("RIS#") for m in g["methods"]))
        check("no short circuit on a miss", g.get("short_circuited_by") is None)
        check("general trials were spent", g["trials"] > 0)

    g = gate_receipt(src=os.path.join("verify", "fixtures", "72-6-6.json"))
    if g is not None:
        check("non-circulant code never reaches the structural search",
              "circulant-GB" not in g["methods"])
        check("non-circulant code runs the battery immediately",
              any(m.startswith("RIS#") for m in g["methods"]))
        check("structural trials are zero for it", g["structural_trials"] == 0)

    print(f"\n{'ALL PASS' if not _fail else 'FAILURES: ' + ', '.join(_fail)}")
    assert not _fail, _fail


def test_refute_gate():
    assert main() == 0


def test_main():
    """pytest entry point; the suite body lives in main()."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
