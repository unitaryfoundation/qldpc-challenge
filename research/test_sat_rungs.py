"""Tests for the rung runner and the lazy exact detection (issue #2703).

The runner must tell a closure from a wall, and the lazy exact detection
must yield only codes that detect every error, as blocking does.
"""
import os
import sys

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "kit"))

pytest.importorskip("pysat")
import local_sat  # noqa: E402
import sat_rungs  # noqa: E402


def _codes(**kw):
    stats = {}
    out = [(HX.copy(), HZ.copy()) for _, HX, HZ in
           local_sat.enumerate_local_sat_codes(
               4, 5, 6, 2, 2.0, solver="cadical195", stream=True,
               shared_t3=True, max_codes=12, stats=stats, **kw)]
    return out, stats


def test_a_proved_empty_rung_is_unsat_not_walled():
    """4x4 G=4 w8 t=3 is the one proved UNSAT in this family."""
    rec = sat_rungs.run_rung(4, 4, 8, 3, 2.0, solver="cadical195",
                             conflicts=200_000, verbose=False)
    assert rec["status"] == "UNSAT" and rec["final"] == "UNSAT"
    assert rec["wall_hit"] is False


def test_a_budget_stop_is_walled_not_unsat():
    rec = sat_rungs.run_rung(5, 16, 6, 3, 2.0, solver="cadical195",
                             conflicts=50, verbose=False)
    assert rec["status"] == "walled" and rec["final"] == "budget"
    assert rec["conflict_cap"] == 50


def test_a_satisfiable_rung_reports_sat_with_k(tmp_path):
    rec = sat_rungs.run_rung(4, 5, 6, 2, 2.0, solver="cadical195",
                             conflicts=2_000_000, out_dir=str(tmp_path),
                             verbose=False)
    assert rec["status"] == "SAT" and rec["k"] >= 4
    assert os.path.exists(os.path.join(_HERE, "..", rec["model_path"]))


def test_nonempty_rows_leaves_no_zero_row():
    codes, stats = _codes(nonempty_rows=True)
    assert codes
    for HX, HZ in codes:
        assert (HX.sum(1) > 0).all() and (HZ.sum(1) > 0).all()
    assert stats["rejected"]["zero_row"] == 0


def test_exact_on_reject_yields_only_detecting_codes():
    """Yield only detecting codes under the lazy path.

    Every yielded code detects every weight <= t error either way; the lazy
    path only changes what the solver is told after a rejection.
    """
    codes, stats = _codes(exact_on_reject=True, nonempty_rows=True)
    assert codes and stats["final"] in ("max_codes", "UNSAT")
    cnf = local_sat.build_local_cnf(4, 5, 6, 2, 2.0, shared_t3=True)
    for HX, HZ in codes:
        for xe, ze in cnf["iter_errors"]():
            assert ((HX @ np.array(ze)) % 2).any() \
                or ((HZ @ np.array(xe)) % 2).any()


def test_detect_clauses_force_detection_of_one_error():
    """Adding the exact clauses for an error makes every later model detect it."""
    from pysat.solvers import Cadical195
    # t=0: no detection in the base formula, so the one clause added below
    # is the only thing asking for this error to be seen.
    cnf = local_sat.build_local_cnf(3, 2, 4, 0, 1.5)
    s = Cadical195(bootstrap_with=cnf["clauses"])
    n, G = cnf["n"], cnf["G"]
    # A Z error on qubit 4 (the center) and no X error.
    ze = tuple(1 if q == 4 else 0 for q in range(n))
    xe = tuple(0 for _ in range(n))
    nv = [cnf["n_vars"]]

    def fresh():
        nv[0] += 1
        return nv[0]
    for c in cnf["detect_clauses"](xe, ze, fresh):
        s.add_clause(c)
    assert s.solve()
    model = {abs(m) for m in s.get_model() if m > 0}
    HX = np.array([[1 if cnf["xr"][(g, q)] in model else 0 for q in range(n)]
                   for g in range(G)])
    assert ((HX @ np.array(ze)) % 2).any()
    s.delete()


def test_bilayer_sites_repeat_the_grid():
    cnf = local_sat.build_local_cnf(3, 2, 4, 1, 1.5, layers=2)
    assert cnf["n"] == 18
    assert cnf["sites"][:9] == cnf["sites"][9:]


def test_the_wall_clock_stops_a_run_cadical_cannot_be_interrupted_in():
    """python-sat cannot interrupt CaDiCaL, so the wall is checked between
    conflict chunks; a wall of zero hours stops after the first chunk."""
    sat_rungs_chunk = sat_rungs.CONF_CHUNK
    sat_rungs.CONF_CHUNK = 20
    try:
        rec = sat_rungs.run_rung(5, 16, 6, 3, 2.0, solver="cadical195",
                                 conflicts=10_000_000, wall_hours=1e-9,
                                 verbose=False)
    finally:
        sat_rungs.CONF_CHUNK = sat_rungs_chunk
    assert rec["status"] == "walled" and rec["wall_hit"] is True
    assert rec["conflicts_total"] is not None and rec["conflicts_total"] < 10_000
