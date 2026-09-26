"""
Server-side exact distance certification (the `d=` tier).

The trustless verifier (qldpc_verify.py) confirms a distance UPPER bound from
the submitter's witness. To upgrade a side to exact, we must prove no lighter
nontrivial logical exists. This is the NP-hard direction; we solve it with a
bounded integer program per logical generator (scipy/HiGHS, no commercial
solver). For each Z-logical generator tL we ask: does a v exist with
  H v = 0 (mod 2),  <v, tL> = 1 (mod 2),  weight(v) <= d-1 ?
If every generator (both sides) is infeasible, then d is exact.

This is deliberately the same construction proven out in the research repo;
here it is dependency-light (numpy + scipy only) and meant to run server-side
or by a maintainer, not in the cheap PR check. Large n may exceed a time
budget; the result then stays an upper bound (honest, never silently
upgraded).

Usage: python verify/certify.py codes/foo.json [--tlim 600]
"""

import argparse
import json
import os
import sys

import numpy as np
from scipy.optimize import milp, Bounds, LinearConstraint

sys.path.insert(0, os.path.dirname(__file__))
import gf2


def _matrix(support_list, n):
    H = np.zeros((len(support_list), n), dtype=np.int8)
    for r, sup in enumerate(support_list):
        for q in sup:
            H[r, q] ^= 1
    return H


def _exists_lighter(H, LZ, cap, tlim):
    """Is there a nontrivial logical (in ker(H), anticommuting with some LZ row)
    of weight <= cap? Returns True/False/None(timeout)."""
    n = H.shape[1]
    R, piv = gf2.rref(H)
    Hc = R[:len(piv)].astype(float)
    numC = Hc.shape[0]
    proved_all = True
    for tL in LZ:
        nv = n + numC + 1
        c = np.zeros(nv); c[:n] = 1.0
        lb = np.zeros(nv); ub = np.zeros(nv)
        ub[:n] = 1.0
        ub[n:n + numC] = np.sum(Hc, axis=1) // 2
        ub[-1] = int(tL.sum()) // 2
        A = np.zeros((numC + 2, nv))
        A[:numC, :n] = Hc
        A[:numC, n:n + numC] = -2 * np.eye(numC)
        A[numC, :n] = tL.astype(float)
        A[numC, -1] = -2
        A[numC + 1, :n] = 1.0
        blb = np.zeros(numC + 2); bub = np.zeros(numC + 2)
        blb[numC] = 1; bub[numC] = 1
        blb[numC + 1] = 1; bub[numC + 1] = cap
        opts = {'time_limit': tlim} if tlim else {}
        res = milp(c=c, constraints=LinearConstraint(A, blb, bub),
                   integrality=np.ones(nv), bounds=Bounds(lb, ub), options=opts)
        if res.success and res.fun is not None:
            return True  # found a lighter logical -> claim is refuted
        if res.status != 2:  # not proven infeasible (e.g. time limit)
            proved_all = False
    return False if proved_all else None


def certify(doc, tlim=600):
    if doc.get("code_type") == "stabilizer":
        # The MILP below minimizes Hamming weight in a kernel, which is the
        # per-side CSS distance. A stabilizer code's distance is a Pauli
        # weight (per-qubit indicator y_q >= x_q, y_q >= z_q, minimize sum
        # y_q over ker(B | A) with one anticommutation row); that
        # reformulation is not built yet. Until it lands an `exact`
        # claim on a stabilizer entry is accepted as upper_bound by the
        # verifier, exactly as CSS claims were before certification existed.
        return {"name": doc.get("name"), "d": doc["distance"]["d"],
                "solver": None, "sides": {}, "d_exact": False,
                "note": "stabilizer codes: Pauli-weight certification not "
                        "available yet; stays upper_bound"}
    n = doc["n"]
    HX = _matrix(doc["checks"]["X"], n)
    HZ = _matrix(doc["checks"]["Z"], n)
    d = doc["distance"]["d"]
    result = {"name": doc.get("name"), "d": d, "solver": "scipy/HiGHS MILP",
              "sides": {}}
    overall = True
    missing = [side for side in ("X", "Z") if side not in doc["distance"]]
    if missing:
        result["missing_sides"] = missing
        overall = False
    for side, H, LZ in (("X", HZ, gf2.logical_basis(HX, HZ)),
                        ("Z", HX, gf2.logical_basis(HZ, HX))):
        if side not in doc["distance"]:
            continue
        val = doc["distance"][side]["value"]
        lighter = _exists_lighter(H, LZ, val - 1, tlim)
        if lighter is True:
            result["sides"][side] = {"value": val, "exact": False,
                                     "note": "REFUTED: a lighter logical exists"}
            overall = False
        elif lighter is False:
            result["sides"][side] = {"value": val, "exact": True,
                                     "note": f"no logical < {val} exists"}
        else:
            result["sides"][side] = {"value": val, "exact": False,
                                     "note": "time limit; remains upper bound"}
            overall = False
    result["d_exact"] = overall and bool(result["sides"])
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--tlim", type=float, default=600)
    args = ap.parse_args()
    with open(args.path) as f:
        doc = json.load(f)
    print(json.dumps(certify(doc, args.tlim), indent=2))
