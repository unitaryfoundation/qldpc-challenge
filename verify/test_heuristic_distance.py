"""Validation for heuristic_distance.

1. Corroboration: over a pinned PANEL of exact-certified codes, the heuristic must
   find exactly the certified distance -- lighter would mean a search bug or a bad
   cert, and failing to reach it would mean the search got weaker (the panel is
   sized so the budget reliably reaches d on both the python and gf2_fast engines).
2. Refutation: an inflated (over-claimed) distance must be refuted.

The panel is fixed and small instead of the whole board on purpose: this test
validates the heuristic's LOGIC, and the 30th board entry exercises no code path
the panel doesn't, so board growth must not grow CI time. Auditing the DATA (a bad
cert on any entry) is the weekly refute_board.py cron's job -- it re-checks every
entry with a fresh random seed each run. `--all` sweeps the full board the old way
(tolerant of inconclusive verdicts on large codes) for manual audits.
"""

import argparse
import copy
import glob
import json
import os
import sys

import gf2
import heuristic_distance as H
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Diverse in family, shape and code path: topological k=1 (smallest and larger),
# toric k=2, generalized-bicycle (low-k and the high-k [[126,28,8]]), and the BB
# gross code. Every member corroborates at trials=2500, seed=0 on BOTH engines
# (verified 2026-07-11); if one stops corroborating, the search regressed.
PANEL = ["7-1-3", "16-2-4", "24-6-4", "49-1-7", "72-6-6", "126-28-8"]


def check_code(slug, trials, require_corroboration):
    """Check one cert/code pair; returns (n_failures, report_line)."""
    codef = os.path.join(ROOT, "codes", slug + ".json")
    certf = os.path.join(ROOT, "certs", slug + ".json")
    if not (os.path.exists(codef) and os.path.exists(certf)):
        return 1, f"  {slug:16s} MISSING code or cert file (panel rot -- swap the member)"
    doc = json.load(open(codef))
    cert = json.load(open(certf))
    if not cert.get("d_exact"):
        return 1, f"  {slug:16s} cert is not d_exact (panel rot -- swap the member)"
    exact_d = int(doc["distance"]["d"])  # the cert certifies this as exact
    res = H.estimate(doc, trials=trials, seed=0)
    dh, verdict = res["d_heuristic"], res["verdict"]
    line = f"  {slug:16s} exact_d={exact_d:2d} d_heur={dh} verdict={verdict} method={res['method']}"
    if dh is not None and dh < exact_d:
        return 1, line + "  <<< FOUND LIGHTER THAN EXACT (bug/bad cert)"
    if require_corroboration and verdict != "corroborated":
        return 1, line + "  <<< PANEL MUST CORROBORATE (search regressed?)"
    return 0, line


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--all",
        action="store_true",
        help="sweep every exact cert on the board (manual audit; inconclusive tolerated) instead of the pinned panel",
    )
    ap.add_argument("--trials", type=int, default=2500)
    args = ap.parse_args(argv)

    if args.all:
        slugs = [
            os.path.basename(cf)[: -len(".json")]
            for cf in sorted(glob.glob(os.path.join(ROOT, "certs", "*.json")))
            if json.load(open(cf)).get("d_exact") and os.path.exists(os.path.join(ROOT, "codes", os.path.basename(cf)))
        ]
        mode = f"full board ({len(slugs)} exact certs)"
    else:
        slugs = PANEL
        mode = f"pinned panel ({len(slugs)} codes)"

    failures = 0
    print(f"=== corroboration over {mode}, trials={args.trials} ===")
    for slug in slugs:
        bad, line = check_code(slug, args.trials, require_corroboration=not args.all)
        failures += bad
        print(line)

    print("\n=== refutation: planted over-claim ===")
    doc = json.load(open(os.path.join(ROOT, "codes", "16-2-4.json")))
    true_d = doc["distance"]["d"]
    over = copy.deepcopy(doc)
    over["distance"]["d"] = true_d + 3
    res = H.estimate(over, trials=4000, seed=0)
    print(f"  16-2-4 claimed {true_d + 3} (true {true_d}) -> verdict={res['verdict']} d_heur={res['d_heuristic']}")
    ok = res["verdict"] == "refuted"
    print("  refutation", "OK" if ok else "FAILED")
    failures += 0 if ok else 1

    print("\n=== fast-path gating (issue #290) ===")
    import contextlib
    import io

    doc = json.load(open(os.path.join(ROOT, "codes", "16-2-4.json")))
    # explicit fast_trials=0 is the deterministic-gate opt-out: no accelerator,
    # and no warning (refute_check relies on this staying silent in CI logs)
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        res = H.estimate(doc, trials=200, seed=0, fast_trials=0)
    # the orbit-fold pass may annotate the method ("ris+orbit-fold(k)"); the
    # point here is that the accelerator did not run and nothing warned
    ok = "gf2_fast" not in res["method"] and err.getvalue() == ""
    print(
        f"  fast_trials=0: method={res['method']} warned={bool(err.getvalue())}",
        "OK" if ok else "  <<< explicit disable must stay silent",
    )
    failures += 0 if ok else 1
    if H._fast is not None:
        # accelerator importable but out-budgeted: must warn on stderr
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            res = H.estimate(doc, trials=200, seed=0, fast_trials=100)
        ok = "gf2_fast is available but skipped" in err.getvalue()
        print(f"  fast_trials<trials: warned={ok}", "OK" if ok else "  <<< silent skip is issue #290")
        failures += 0 if ok else 1
        # CLI default must scale the fast budget with --trials instead of
        # letting a deep --trials run silently drop to pure Python
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            H.main(os.path.join(ROOT, "codes", "16-2-4.json"), trials=200, seed=0)
        method = json.loads(out.getvalue())["method"]
        ok = method.endswith("+gf2_fast")
        print(f"  CLI default: method={method}", "OK" if ok else "  <<< CLI no longer engages the accelerator")
        failures += 0 if ok else 1
    else:
        print("  gf2_fast not importable here; accelerator cases skipped")

    print(f"\n{failures} failure(s)")
    sys.exit(1 if failures else 0)


def test_main():
    """Pytest entry point. main() takes argv and reports by calling sys.exit,
    including on success, so the exit status is what gets asserted.
    """
    import pytest

    with pytest.raises(SystemExit) as exc:
        main([])
    assert not exc.value.code, f"panel run exited {exc.value.code}"


if __name__ == "__main__":
    main(sys.argv[1:])


def test_accelerator_witness_is_recorded_and_valid():
    """Check that an accelerator find is recorded with a valid witness.

    When the accelerator finds a lighter logical, the verdict must carry a
    witness at that weight, and the witness must survive gf2 validation.
    """
    doc = json.load(open(os.path.join(ROOT, "codes", "144-12-12.json")))
    if H._fast is None:
        print("  gf2_fast unavailable; skipping")
        return
    res = H.estimate(doc, trials=200, seed=0, fast_trials=200_000)
    assert res["method"].endswith("+gf2_fast")  # the fold pass may prefix it
    d = res["d_heuristic"]
    assert d is not None
    backed = [s for s, blk in res["sides"].items() if blk.get("witness") and blk.get("lightest_found") == d]
    assert backed, f"no witness recorded at the reported weight {d}: {res['sides']}"
    n = doc["n"]
    HX = H._matrix(doc["checks"]["X"], n)
    HZ = H._matrix(doc["checks"]["Z"], n)
    for side in backed:
        v = np.zeros(n, dtype=np.int8)
        v[res["sides"][side]["witness"]] = 1
        H_ker, H_row = (HZ, HX) if side == "X" else (HX, HZ)
        assert H._valid_logical(v, H_ker, H_row), f"{side} witness invalid"
    print(f"  accelerator witness ok: d={d}, sides backed={backed}")


def test_valid_logical_rejects_stabilizer_and_nonkernel():
    """Reject a stabilizer row and a vector outside the kernel."""
    doc = json.load(open(os.path.join(ROOT, "codes", "144-12-12.json")))
    n = doc["n"]
    HX = H._matrix(doc["checks"]["X"], n)
    HZ = H._matrix(doc["checks"]["Z"], n)
    assert not H._valid_logical(HX[0].astype(np.int8), HZ, HX), "stabilizer accepted"
    bad = np.zeros(n, dtype=np.int8)
    bad[0] = 1
    if ((HZ @ bad) % 2).any():
        assert not H._valid_logical(bad, HZ, HX), "non-kernel vector accepted"
    assert not H._valid_logical(np.zeros(n, dtype=np.int8), HZ, HX), "zero accepted"


# ---------------------------------------------------------------------------
# Orbit-fold pass (audit of 2026-10-08).
#
# The fixtures are matrices built inline from their symbols, never board
# files: the refutation mechanism under test exists to change the board, so a
# test that read a board entry and asserted it over-stated would be scheduled
# to break the moment it did its job (verify/test_refute_gate.py tells the
# story). The [[350,20]] symbols below are a mathematical fact about those two
# polynomials -- a weight-40 X-logical constant on the cosets of 35Z/175 --
# and stay true whatever the board files say.
# ---------------------------------------------------------------------------


def _gb_from_symbols(L, a, b):
    """H_X = [circ(a) | circ(b)], H_Z = [circ(b)^T | circ(a)^T] over x^L - 1."""

    def circ(sym):
        M = np.zeros((L, L), dtype=np.int8)
        for i in range(L):
            for e in sym:
                M[i, (e + i) % L] = 1
        return M

    A, B = circ(a), circ(b)
    return np.hstack([A, B]).astype(np.int8), np.hstack([B.T, A.T]).astype(np.int8)


def _supports(M):
    return [sorted(int(j) for j in np.nonzero(r)[0]) for r in M]


# a(x), b(x) of a cyclic GB code on Z_175 filed at d = 44 whose lightest
# logicals have weight 40 and are constant on orbits of the order-5 shift.
_L175 = 175
_A175 = (6, 38, 42, 60, 65, 89, 120)
_B175 = (3, 11, 15, 29, 46, 60, 64, 79, 82, 90, 91)


def _doc175(claim):
    HX, HZ = _gb_from_symbols(_L175, _A175, _B175)
    n = HX.shape[1]
    # genuine witnesses of the claimed weight are not needed by the search
    # functions under test; estimate() only reads n, checks and distance.d
    return {
        "schema_version": "0.2",
        "name": f"[[{n},20,{claim}]] fixture",
        "code_type": "CSS",
        "n": n,
        "k": 20,
        "checks": {"X": _supports(HX), "Z": _supports(HZ)},
        "distance": {
            "d": claim,
            "X": {"value": claim, "confidence": "upper_bound", "witness": []},
            "Z": {"value": claim, "confidence": "upper_bound", "witness": []},
        },
    }


def test_structural_automorphisms_from_matrices():
    """Symmetries are read from H, never from a family tag: a circulant GB
    code yields its block shift (order L) in both the contiguous and the
    interleaved qubit layouts, a 2-D (l x m) layout yields both shifts, and a
    code with none of these yields nothing (so the fold pass is skipped).
    """
    HX, HZ = _gb_from_symbols(21, (0, 3, 6, 12), (0, 7))
    n = HX.shape[1]
    gens = H.structural_automorphisms([HX, HZ], n)
    assert gens and H._perm_order(gens[0]) == 21
    inv = H._RowInvariance([HX, HZ], n)
    assert all(inv(g) for g in gens)

    # interleaved layout: qubit (block, pos) -> pos*2 + block
    perm = np.array([(j % 21) * 2 + (j // 21) for j in range(n)])
    inv_perm = np.argsort(perm)
    HXi, HZi = HX[:, inv_perm], HZ[:, inv_perm]
    gens_i = H.structural_automorphisms([HXi, HZi], n)
    assert gens_i and H._perm_order(gens_i[0]) == 21

    # a hypergraph product fixture has no block-circulant layout
    doc = json.load(open(os.path.join(ROOT, "verify", "fixtures", "72-6-6.json")))
    HX72 = H._matrix(doc["checks"]["X"], 72)
    HZ72 = H._matrix(doc["checks"]["Z"], 72)
    assert H.structural_automorphisms([HX72, HZ72], 72) == []
    assert H.orbit_fold_refute(doc, seed=0, trials=50, max_seconds=5) == (False, None, None, 0)


def test_structural_automorphisms_survive_dropped_rows():
    """Several board GB entries list only an independent subset of the shifts
    of their templates, so the permuted ROW SET is not the row set; the row
    SPACE still is, and the shift must still be found (the span fallback).
    """
    HX, HZ = _gb_from_symbols(21, (0, 3, 6, 12), (0, 7))
    n = HX.shape[1]
    HXr, _ = gf2.rref(HX)  # a basis of the row space, not shifts
    assert HXr.shape[0] < HX.shape[0]
    inv = H._RowInvariance([HXr, HZ], n)
    shift = np.array([(j // 21) * 21 + (j % 21 + 1) % 21 for j in range(n)])
    assert not inv.rows(shift) and inv.span(shift)
    gens = H.structural_automorphisms([HXr.astype(np.int8), HZ], n)
    assert gens and H._perm_order(gens[0]) == 21


def test_orbit_fold_finds_symmetric_logical():
    """The failure mode of the audit: a lightest logical constant on the orbits
    of an order-5 shift, weight 40 on a code filed at 44. The fold finds it
    within a few trials; every witness is re-validated on the full matrices.
    """
    HX, HZ = _gb_from_symbols(_L175, _A175, _B175)
    n = HX.shape[1]
    res = H.orbit_fold_min_logical(HX, HZ, trials=100, seed=0, max_seconds=30)
    assert res["partitions"] > 0
    for side, H_ker, H_row in (("X", HZ, HX), ("Z", HX, HZ)):
        assert res[side] is not None, side
        w, v = res[side]
        assert w <= 40 and int(v.sum()) == w
        assert H._valid_logical(v, H_ker, H_row)
        # the witness is orbit-constant: invariant under the order-5 shift
        shift = np.array([(j // _L175) * _L175 + (j % _L175 + 35) % _L175 for j in range(n)])
        assert (v[shift] == v).all()

    ref, found, wit, searched = H.orbit_fold_refute(_doc175(44), seed=0, trials=100, max_seconds=30)
    assert ref and found <= 40 and searched > 0
    assert isinstance(wit, list) and len(wit) == found
    # an honest claim at or below what the fold reaches is left alone
    ref, found, wit, searched = H.orbit_fold_refute(_doc175(40), seed=0, trials=100, max_seconds=30)
    assert not ref and wit is None and searched > 0


def test_estimate_merges_fold_and_can_disable_it():
    """estimate() runs the fold first and takes the lighter of fold and RIS
    per side; fold_trials=0 restores the pure RIS verdict and method string.
    """
    doc = _doc175(44)
    res = H.estimate(doc, trials=20, seed=0, fast_trials=0, max_seconds=20)
    assert res["verdict"] == "refuted" and res["d_heuristic"] <= 40
    assert res["method"].startswith("ris+orbit-fold(") and res["fold_partitions"] > 0
    for side in ("X", "Z"):
        v = np.zeros(doc["n"], dtype=np.int8)
        v[res["sides"][side]["witness"]] = 1
        assert int(v.sum()) == res["sides"][side]["lightest_found"]
    off = H.estimate(doc, trials=20, seed=0, fast_trials=0, max_seconds=20, fold_trials=0)
    assert off["method"] == "ris" and off["fold_partitions"] == 0
    assert off["d_heuristic"] >= res["d_heuristic"]
    # refute_check (the gate's and the weekly sweep's entry point) inherits it
    ref, dh, wit, _ = H.refute_check(doc, seed=0, max_seconds=20, trials=20)
    assert ref and dh <= 40 and len(wit) == dh


def test_orbit_fold_stabilizer_path():
    """Non-CSS: Pauli folds on the labelled Tanner structure plus random
    single-qubit frames; the witness is a validated Pauli operator. The cyclic
    five-qubit and [[17,1,7]] fixtures expose the shift and reach their exact
    distances; an inflated claim on them is refuted.
    """
    for slug in ("5-1-3", "17-1-7"):
        doc = json.load(open(os.path.join(ROOT, "verify", "fixtures", slug + ".json")))
        A, B = H.stabilizer_matrices(doc)
        res = H.orbit_fold_min_pauli_logical(A, B, trials=60, seed=0, max_seconds=20)
        assert res["partitions"] + res["frames"] > 0
        assert res["P"] is not None
        w, v = res["P"]
        assert w == doc["distance"]["d"]
        assert H.valid_pauli_logical(v, A, B)
        over = copy.deepcopy(doc)
        over["distance"]["d"] += 2
        ref, found, wit, searched = H.orbit_fold_refute(over, seed=0, trials=60, max_seconds=20)
        assert ref and found == doc["distance"]["d"] and set(wit) == {"X", "Z"}
        res = H.estimate(over, trials=20, seed=0, fast_trials=0, max_seconds=20)
        assert res["verdict"] == "refuted" and "orbit-fold" in res["method"]
