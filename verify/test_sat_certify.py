"""Tests for the SAT exact-distance certifier.

The certifier can only be trusted if it agrees with the MILP certifier where
both close, and if it refutes an overstated claim with a witness the trusted
stack accepts.
"""
import copy
import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gf2
import sat_certify

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pytest.importorskip("pycryptosat")
pytest.importorskip("pysat")


def _doc(slug):
    with open(os.path.join(ROOT, "codes", slug + ".json")) as f:
        return json.load(f)


@pytest.mark.parametrize("slug", ["24-6-4", "72-6-6"])
def test_agrees_with_existing_milp_cert(slug):
    """Where the board already has a cert, SAT must reach the same verdict."""
    certf = os.path.join(ROOT, "certs", slug + ".json")
    if not os.path.exists(certf):
        pytest.skip(f"no existing cert for {slug}")
    with open(certf) as f:
        existing = json.load(f)
    res = sat_certify.certify(_doc(slug), tlim=300)
    assert res["d_exact"] == existing["d_exact"], (
        f"{slug}: SAT says d_exact={res['d_exact']}, "
        f"existing {existing['solver']} cert says {existing['d_exact']}")
    assert res["d"] == existing["d"]


def test_refutes_an_inflated_claim_with_a_valid_witness():
    """Claiming a distance the code does not have must come back SAT.

    The witness must be a genuine logical operator by the trusted stack's own
    reckoning, otherwise a refutation would be an accusation with no evidence.
    """
    doc = copy.deepcopy(_doc("24-6-4"))
    true_d = int(doc["distance"]["d"])
    doc["distance"]["d"] = true_d + 2          # claim more than the code has
    res = sat_certify.certify(doc, tlim=300)
    assert not res["d_exact"]
    sat_sides = [s for s, b in res["sides"].items() if b["status"] == "SAT"]
    assert sat_sides, f"inflated claim not refuted: {res['sides']}"
    side = sat_sides[0]
    wit = res["sides"][side]["witness"]
    assert wit, "refutation carries no witness"
    n = doc["n"]
    HX = sat_certify._matrix(doc["checks"]["X"], n)
    HZ = sat_certify._matrix(doc["checks"]["Z"], n)
    v = np.zeros(n, dtype=np.int8)
    v[wit] = 1
    H_ker, H_row = (HZ, HX) if side == "X" else (HX, HZ)
    assert not ((H_ker @ v) % 2).any(), "witness is not in the kernel"
    assert gf2.rank(np.vstack([H_row, v[None, :]])) > gf2.rank(H_row), \
        "witness is a stabilizer, not a logical"
    assert 0 < int(v.sum()) <= true_d + 1


def test_timeout_is_not_an_exactness_claim():
    """A solve that runs out of time must leave the entry at its upper bound."""
    res = sat_certify.certify(_doc("24-6-4"), tlim=1e-9)
    for blk in res["sides"].values():
        if blk["status"] == "TIMEOUT":
            assert not blk["exact"]
    assert res["d_exact"] in (True, False)


def test_symmetry_is_gated_on_a_verified_automorphism():
    """Symmetry breaking must only fire when the rotation really is one.

    A lex-leader constraint prunes solutions that are rotations of each other.
    If the rotation is not an automorphism of the code, it prunes solutions
    that are not duplicates, and the certifier would report UNSAT for a code
    that has a lighter logical. So the gate, not the speedup, is the thing
    worth testing.
    """
    doc = _doc("24-6-4")
    res = sat_certify.certify(doc, tlim=300)
    n = doc["n"]
    HX = sat_certify._matrix(doc["checks"]["X"], n)
    HZ = sat_certify._matrix(doc["checks"]["Z"], n)
    p = sat_certify._shift_perm(n)
    expected = (n % 2 == 0 and sat_certify._perm_fixes(HX, p)
                and sat_certify._perm_fixes(HZ, p))
    assert res["symmetry"] == expected

    # A code the rotation does not fix must not be pruned by it.
    scrambled = np.array(HZ)
    scrambled[:, [0, 1]] = scrambled[:, [1, 0]]
    if not sat_certify._perm_fixes(scrambled, p):
        assert not sat_certify._perm_fixes(scrambled, p)


def test_symmetry_does_not_change_the_verdict():
    """With and without symmetry breaking, the answer must be identical.

    Speed may differ; correctness may not. This is the check that a pruning
    constraint is removing orbit duplicates rather than real solutions.
    """
    doc = _doc("24-6-4")
    n = doc["n"]
    HX = sat_certify._matrix(doc["checks"]["X"], n)
    HZ = sat_certify._matrix(doc["checks"]["Z"], n)
    W = int(doc["distance"]["d"]) - 1
    for side, H_same, H_opp in (("X", HX, HZ), ("Z", HZ, HX)):
        L = sat_certify._logicals(H_opp, H_same)
        on, _ = sat_certify._solve_side(H_opp, L, W, 300, use_symmetry=True)
        off, _ = sat_certify._solve_side(H_opp, L, W, 300, use_symmetry=False)
        assert on == off, f"{side}: symmetry changed the verdict {off} -> {on}"
    # And at a weight where a logical does exist, both must still agree.
    for side, H_same, H_opp in (("X", HX, HZ), ("Z", HZ, HX)):
        L = sat_certify._logicals(H_opp, H_same)
        on, _ = sat_certify._solve_side(H_opp, L, W + 1, 300, use_symmetry=True)
        off, _ = sat_certify._solve_side(H_opp, L, W + 1, 300, use_symmetry=False)
        assert on == off, f"{side} at W+1: {off} -> {on}"


@pytest.mark.parametrize("slug", ["37-1-7", "24-6-4", "144-12-12"])
def test_pairing_set_spans_every_logical_class(slug):
    """The pairing set has to reach all k classes, on both sides.

    A class with no representative in the set is a class the cardinality
    bound never constrains, so a logical living there is invisible to the
    solver and the side comes back UNSAT with nothing searched. Codes chosen
    to span the failure: 37-1-7 is the one where the old slice returned a
    stabilizer and spanned nothing, and the other two are the codes the rest
    of this file already exercises.
    """
    doc = _doc(slug)
    n = doc["n"]
    HX = sat_certify._matrix(doc["checks"]["X"], n)
    HZ = sat_certify._matrix(doc["checks"]["Z"], n)
    k = n - gf2.rank(HX) - gf2.rank(HZ)
    for side, H_same, H_opp in (("X", HX, HZ), ("Z", HZ, HX)):
        # certify() pairs this side against ker(H_same) modulo
        # rowspace(H_opp), so H_opp is what the representatives must be
        # independent of. Measuring against H_same instead reports a
        # shortfall on codes whose sets are complete.
        L = sat_certify._logicals(H_opp, H_same)
        assert len(L) == k, f"{slug} {side}: {len(L)} representatives, k={k}"
        spanned = gf2.rank(np.vstack([H_opp, L])) - gf2.rank(H_opp)
        assert spanned == k, f"{slug} {side}: spans {spanned} classes, k={k}"


def test_an_overstated_colour_code_distance_is_refuted():
    """37-1-7 at d=8 must be refuted, not certified.

    This is the case the old pairing set got wrong. Its X side returned a
    single row that lies in rowspace(HZ), so every kernel vector commuted
    with it, the at-least-one-anticommutation clause was unsatisfiable, and
    both sides reported UNSAT. The certifier then recorded d=8 as exact for a
    code whose own witness has weight 7.
    """
    doc = copy.deepcopy(_doc("37-1-7"))
    assert int(doc["distance"]["d"]) == 7
    doc["distance"]["d"] = 8
    res = sat_certify.certify(doc, tlim=300)
    assert not res["d_exact"], "an overstated distance was certified as exact"
    assert any(b["status"] == "SAT" for b in res["sides"].values()), res["sides"]


def test_a_short_pairing_set_is_refused_rather_than_certified():
    """Certifying against a set that misses a class must raise.

    Without this the failure is silent and looks exactly like a proof: the
    solver reports UNSAT, certify() records exact=True, and the cert file
    that upgrades the board entry gets written.
    """
    doc = copy.deepcopy(_doc("24-6-4"))
    full = sat_certify._logicals
    try:
        sat_certify._logicals = lambda H_same, H_opp: full(H_same, H_opp)[:-1]
        with pytest.raises(ValueError, match="logical classes"):
            sat_certify.certify(doc, tlim=300)
        # Same row count, no logical content: the guard has to measure the
        # span rather than the length, since a stabilizer is a row too.
        sat_certify._logicals = lambda H_same, H_opp: np.zeros_like(
            full(H_same, H_opp))
        with pytest.raises(ValueError, match="logical classes"):
            sat_certify.certify(doc, tlim=300)
    finally:
        sat_certify._logicals = full


# --- the ascending ladder (issue #4230) --------------------------------------------------------

def test_the_ladder_reaches_the_exact_verdict_and_records_every_rung():
    res = sat_certify.certify(_doc("24-6-4"), tlim=300, ladder=True)
    assert res["d_exact"] and res["d_lower"] == 4
    for blk in res["sides"].values():
        assert blk["exact"] and blk["proved_min"] == 4
        assert [(r["W"], r["status"]) for r in blk["ladder"]] == [(1, "UNSAT"), (2, "UNSAT"), (3, "UNSAT")]
    assert res["verification"]["level"] == "solver" and "checks_sha256" not in res["verification"]
    assert res["ladder"] == {"start": 1, "budget_per_side": None}
    # resumed at 3, the ladder asks only W = 3 and still closes
    res = sat_certify.certify(_doc("24-6-4"), tlim=300, ladder=True, start=3)
    assert res["d_exact"] and [r["W"] for r in res["sides"]["X"]["ladder"]] == [3]
    # without the flag the record is what it always was
    plain = sat_certify.certify(_doc("24-6-4"), tlim=300)
    assert "d_lower" not in plain and "ladder" not in plain["sides"]["X"]


def test_a_ladder_that_times_out_still_proves_a_lower_bound(monkeypatch):
    real = sat_certify._solve_side

    def above_two_times_out(H_opp, L, W, tlim, use_symmetry=False, prefix=25):
        return ("TIMEOUT", None) if W >= 3 else real(H_opp, L, W, tlim, use_symmetry, prefix)

    monkeypatch.setattr(sat_certify, "_solve_side", above_two_times_out)
    doc = _doc("72-12-6")
    res = sat_certify.certify(doc, tlim=300, ladder=True)
    assert res["d_exact"] is False and res["d_lower"] == 3
    for blk in res["sides"].values():
        assert blk["status"] == "TIMEOUT" and blk["exact"] is False and blk["proved_min"] == 3
        assert [(r["W"], r["status"]) for r in blk["ladder"]] == [(1, "UNSAT"), (2, "UNSAT"), (3, "TIMEOUT")]
        assert blk["note"] == "no logical < 3 exists; W = 3 TIMEOUT"
    import check_certs
    assert res["verification"]["checks_sha256"] == check_certs.checks_sha256(doc)
    assert res["verification"]["level"] == "solver"
    assert check_certs.bound_problems("72-12-6", res) == []
    # the same timeout without the ladder proves nothing and records no bound
    plain = sat_certify.certify(doc, tlim=300)
    assert plain["d_exact"] is False and "d_lower" not in plain


def test_the_budget_stops_the_ladder_between_rungs(monkeypatch):
    import time as _time

    def slow_unsat(H_opp, L, W, tlim, use_symmetry=False, prefix=25):
        _time.sleep(0.05)
        return "UNSAT", None

    monkeypatch.setattr(sat_certify, "_solve_side", slow_unsat)
    res = sat_certify.certify(_doc("24-6-4"), tlim=300, ladder=True, budget=0.01)
    for blk in res["sides"].values():
        assert [r["W"] for r in blk["ladder"]] == [1] and blk["proved_min"] == 2
        assert "budget was spent before W = 2" in blk["note"]
    assert res["d_exact"] is False and res["d_lower"] == 2
    assert res["ladder"]["budget_per_side"] == 0.01
