#!/usr/bin/env python3
r"""Cross-check the stabilizer certificates by means that share nothing with tropidist (issue #4939).

The only certifier of a stabilizer entry's Pauli-weight distance is the
sweep's tropidist backend (research/certs/tropidist_certify.py), whose
verdict is solver level: exhaustion inside the tool's kernel with no
artifact a third party can replay. This script checks each such certificate
three independent ways and writes a dated record:

  brute force   every Pauli operator of weight at most d - 1 is enumerated
                (when their number is within --brute-max) and none may be a
                nontrivial logical. Exact and independent of every solver;
                feasible for the small entries (n <= 17 at d <= 7).
  MILP          verify/certify.py's HiGHS integer program, the board's
                original certifier, asked on the same three-mechanisms-per-
                qubit encoding tropidist_certify.py builds (X_i, Z_i, Y_i as
                columns; a minimum never selects two on one qubit, so the
                mechanism count is the Pauli weight) whether a nontrivial
                logical of weight at most d - 1 exists. Exact when it
                finishes; a different solver on a different formulation.
  RIS           verify/heuristic_distance.py's random-information-set Pauli
                search at a stated trial budget. The lightest logical it finds
                must weigh at least d. A consistency check, not a proof: it
                catches an overclaim a search can reach, which is how the
                board's refutations are found.

A certificate is confirmed when brute force or the MILP finishes with no
lighter logical and the RIS search agrees; contradicted when any of the three
exhibits a logical lighter than d (the vector is recorded, re-verified with
verify/heuristic_distance.valid_pauli_logical); otherwise unconfirmed, with
whatever bounds were reached.

    uv run --extra certify python research/certs/stabilizer_crosscheck.py --all \\
        [--tlim 300] [--trials 200000] [--brute-max 2e7] [--out research/certs/stabilizer_crosscheck-<date>.json]
    uv run --extra certify python research/certs/stabilizer_crosscheck.py --slugs 5-1-3 40-9-6
"""
import argparse
import datetime
import itertools
import json
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "verify"))
sys.path.insert(0, HERE)
import gf2  # noqa: E402
import heuristic_distance as HD  # noqa: E402

CODES = os.path.join(ROOT, "codes")
CERTS = os.path.join(ROOT, "certs")
DEFAULT_BRUTE_MAX = 2e7


# ---------------------------------------------------------------------------- brute force
def pauli_count(n, max_weight):
    """Count the Pauli operators of weight 1 to max_weight on n qubits."""
    return sum(math.comb(n, w) * 3 ** w for w in range(1, max_weight + 1))


def _patterns(w):
    """Return the 3^w single-qubit Pauli assignments of a weight-w support, as (x, z) bit arrays."""
    codes = np.array(list(itertools.product((1, 2, 3), repeat=w)), dtype=np.int8)   # 1 = X, 2 = Z, 3 = Y
    return (codes != 2).astype(np.int8), (codes != 1).astype(np.int8)


def brute_force(A, B, max_weight, *, limit=DEFAULT_BRUTE_MAX):
    """Enumerate every Pauli of weight at most max_weight; return (checked, lighter_logicals).

    ``checked`` is False when the count exceeds ``limit`` and nothing was run.
    ``lighter_logicals`` lists the nontrivial logical Paulis found as (x | z)
    vectors (at most 8 kept), so a nonempty list refutes a distance above
    max_weight. A zero-syndrome Pauli that lies in the stabilizer group is a
    stabilizer, not a logical, and is not counted.
    """
    n = A.shape[1]
    if pauli_count(n, max_weight) > limit:
        return False, []
    S = np.concatenate([A, B], axis=1).astype(np.int8) % 2
    found = []
    for w in range(1, max_weight + 1):
        px, pz = _patterns(w)
        for support in itertools.combinations(range(n), w):
            X = np.zeros((px.shape[0], n), dtype=np.int8)
            Z = np.zeros_like(X)
            X[:, support] = px
            Z[:, support] = pz
            syndrome = (X @ B.T + Z @ A.T) % 2          # symplectic product with every generator
            for i in np.flatnonzero(~syndrome.any(axis=1)):
                v = np.concatenate([X[i], Z[i]])
                if not gf2.in_rowspace(v, S):
                    found.append(v.astype(np.int8))
                    if len(found) >= 8:
                        return True, found
    return True, found


# ---------------------------------------------------------------------------- the two other checks
def milp_check(doc, cap, tlim):
    """Ask verify/certify.py's integer program for a nontrivial logical of Pauli weight <= cap.

    Returns "confirmed" (none exists), "contradiction" (one exists), or
    "timeout". The problem is the three-mechanisms-per-qubit encoding of
    tropidist_certify.pauli_problem; the solver is scipy/HiGHS.
    """
    import certify as CE
    import tropidist_certify as TC
    (H, L), _ = TC.pauli_problem(doc)
    res = CE._exists_lighter(H, L, cap, tlim)
    return "confirmed" if res is False else "contradiction" if res else "timeout"


def ris_check(doc, trials, seed=4939):
    """Return (lightest Pauli weight found, verified) from the board's randomized Pauli search."""
    A, B = HD.stabilizer_matrices(doc)
    w, v = HD.ris_min_pauli_logical(A, B, trials, seed)
    if w is None or v is None:
        return None, False
    return int(w), bool(HD.valid_pauli_logical(np.asarray(v, dtype=np.int8), A, B))


# ---------------------------------------------------------------------------- one entry
def crosscheck(slug, doc, d, *, tlim, trials, brute_max, skip_milp=False):
    """Run the three checks on one entry against the certified distance d; return the record."""
    A, B = HD.stabilizer_matrices(doc)
    n = doc["n"]
    out = {"slug": slug, "n": n, "k": doc["k"], "d": int(d)}
    t0 = time.time()
    checked, lighter = brute_force(A, B, d - 1, limit=brute_max)
    out["brute_force"] = {"checked": checked, "paulis": pauli_count(n, d - 1), "secs": round(time.time() - t0, 1)}
    if checked:
        out["brute_force"]["lighter_logicals"] = len(lighter)
        if lighter:
            v = lighter[0]
            out["brute_force"]["example"] = {"X": [int(i) for i in np.flatnonzero(v[:n])],
                                             "Z": [int(i) for i in np.flatnonzero(v[n:])],
                                             "weight": int((v[:n] | v[n:]).sum()),
                                             "valid": bool(HD.valid_pauli_logical(v, A, B))}
    if skip_milp:
        out["milp"] = {"verdict": "skipped"}
    else:
        t0 = time.time()
        out["milp"] = {"verdict": milp_check(doc, d - 1, tlim), "tlim_per_solve": tlim,
                       "secs": round(time.time() - t0, 1)}
    t0 = time.time()
    w, ok = ris_check(doc, trials)
    out["ris"] = {"trials": trials, "lightest": w, "witness_valid": ok, "agrees": w is None or w >= d,
                  "secs": round(time.time() - t0, 1)}
    exact_ok = (checked and not lighter) or out["milp"]["verdict"] == "confirmed"
    refuted = (checked and bool(lighter)) or out["milp"]["verdict"] == "contradiction" or (w is not None and w < d)
    out["verdict"] = "contradiction" if refuted else "confirmed" if exact_ok and out["ris"]["agrees"] else "unconfirmed"
    return out


def certified_stabilizer_slugs():
    """Every slug whose certificate has the single Pauli side P and whose entry is on the board."""
    out = []
    for name in sorted(os.listdir(CERTS)):
        if not name.endswith(".json"):
            continue
        slug = name[:-5]
        if not os.path.exists(os.path.join(CODES, slug + ".json")):
            continue
        with open(os.path.join(CERTS, name), encoding="utf-8") as f:
            cert = json.load(f)
        if "P" in (cert.get("sides") or {}):
            out.append(slug)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--slugs", nargs="*", default=None, help="entries to check (default with --all: every certified "
                                                               "stabilizer entry)")
    ap.add_argument("--all", action="store_true", help="check every stabilizer entry that has a certificate")
    ap.add_argument("--tlim", type=float, default=300.0, help="seconds per MILP solve (default 300)")
    ap.add_argument("--trials", type=int, default=200_000, help="RIS trials (default 200000)")
    ap.add_argument("--brute-max", type=float, default=DEFAULT_BRUTE_MAX,
                    help="enumerate only when the Pauli count is at most this (default 2e7)")
    ap.add_argument("--skip-milp", action="store_true")
    ap.add_argument("--out", default=None,
                    help="record path (default research/certs/stabilizer_crosscheck-<date>.json)")
    a = ap.parse_args(argv)
    slugs = list(a.slugs or [])
    if a.all:
        slugs = certified_stabilizer_slugs()
    if not slugs:
        print("nothing to check: pass --slugs or --all", file=sys.stderr)
        return 2
    today = datetime.date.today().isoformat()
    out_path = a.out or os.path.join(HERE, f"stabilizer_crosscheck-{today}.json")
    record = {"date": today, "tlim_per_solve": a.tlim, "ris_trials": a.trials, "brute_max": a.brute_max,
              "entries": []}
    rc = 0
    for slug in slugs:
        with open(os.path.join(CODES, slug + ".json"), encoding="utf-8") as f:
            doc = json.load(f)
        cert_path = os.path.join(CERTS, slug + ".json")
        d = doc["distance"]["d"]
        if os.path.exists(cert_path):
            with open(cert_path, encoding="utf-8") as f:
                d = json.load(f)["d"]
        rec = crosscheck(slug, doc, d, tlim=a.tlim, trials=a.trials, brute_max=a.brute_max, skip_milp=a.skip_milp)
        record["entries"].append(rec)
        print(f"{slug}: {rec['verdict']} (brute force {'checked' if rec['brute_force']['checked'] else 'skipped'}, "
              f"MILP {rec['milp']['verdict']}, RIS lightest {rec['ris']['lightest']} in {rec['ris']['secs']} s)",
              flush=True)
        if rec["verdict"] == "contradiction":
            rc = 3
        record["summary"] = {v: sum(1 for e in record["entries"] if e["verdict"] == v)
                             for v in ("confirmed", "unconfirmed", "contradiction")}
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=1, sort_keys=True)
            f.write("\n")
    print(json.dumps(record["summary"]))
    return rc


if __name__ == "__main__":
    sys.exit(main())
