"""Per-side distance intervals in the verifier report (issue #6812).

``computed.sector_distances`` carries, for each side and for d, the upper
bound the verified witness earns, lowered to the refuter's find on the side
the found logical belongs to, and the lower bound a certificate proves.
The codes here are built in the test (the toric code on a 4 x 4 torus and
the verifier's own [[5,1,3]] fixture), so no board file a refutation could
later remove is involved.

Run: uv run pytest verify/test_sector_distances.py
"""

import copy
import json
import os

import pytest

import check_certs
import heuristic_distance
import qldpc_verify as V

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
L = 4


def _h(i, j):
    return 2 * ((i % L) * L + (j % L))


def _v(i, j):
    return _h(i, j) + 1


def _sym(*sets):
    out = set()
    for s in sets:
        out ^= set(s)
    return sorted(out)


def toric_doc(claim):
    """The L x L toric code, [[32,2,4]], claiming distance ``claim`` in {4, 6}.

    X checks are the vertex stars, Z checks the plaquettes. The weight-4
    witnesses are a row of horizontal edges (Z) and a row of vertical edges
    (X); the weight-6 ones are those loops times an adjacent plaquette or
    star, so they are logicals of the same class and the claim of 6 is an
    over-claim the refuter can catch.
    """
    stars = [sorted({_h(i, j), _h(i, j - 1), _v(i, j), _v(i - 1, j)})
             for i in range(L) for j in range(L)]
    plaqs = [sorted({_h(i, j), _h(i + 1, j), _v(i, j), _v(i, j + 1)})
             for i in range(L) for j in range(L)]
    z4 = sorted(_h(0, j) for j in range(L))
    x4 = sorted(_v(0, j) for j in range(L))
    z6 = _sym(z4, plaqs[1])              # times plaquette (0, 1)
    x6 = _sym(x4, stars[L + 1])          # times star (1, 1)
    wx, wz = (x4, z4) if claim == 4 else (x6, z6)
    assert len(wx) == claim and len(wz) == claim
    return {
        "schema_version": "0.1",
        "name": f"toric {L}x{L} claiming d={claim}",
        "code_type": "CSS",
        "n": 2 * L * L, "k": 2,
        "checks": {"X": stars, "Z": plaqs},
        "distance": {"d": claim,
                     "X": {"value": claim, "confidence": "upper_bound", "witness": wx},
                     "Z": {"value": claim, "confidence": "upper_bound", "witness": wz}},
        "provenance": _provenance(),
    }, z4


def _provenance():
    """The fixture's provenance block, so the schema's required fields are met."""
    with open(os.path.join(ROOT, "verify", "fixtures", "72-6-6.json"), encoding="utf-8") as f:
        return json.load(f)["provenance"]


def test_witnesses_give_the_upper_bounds_and_nothing_proves_a_lower_one():
    doc, _ = toric_doc(4)
    rep = V.verify(doc, refute=False)
    assert rep["ok"], [c for c in rep["checks"] if not c["ok"]]
    sd = rep["computed"]["sector_distances"]
    assert set(sd) == {"X", "Z", "d"}
    for side in ("X", "Z"):
        assert sd[side] == {"upper": 4, "lower": None, "exact": False,
                            "witness_weight": 4, "refuted_to": None}
    assert sd["d"] == {"upper": 4, "lower": None, "exact": False}


def test_a_refuted_claim_lowers_the_side_the_found_logical_belongs_to(monkeypatch):
    doc, z4 = toric_doc(6)
    assert V.verify(doc, refute=False)["ok"]     # the weight-6 witnesses are real logicals

    def fake_refute(doc, seed=0, **kw):
        return True, 4, z4, 10                   # the refuter hands back a Z loop

    monkeypatch.setattr(heuristic_distance, "refute_check", fake_refute)
    rep = V.verify(doc, refute=True, seed=1)
    nd = next(c for c in rep["checks"] if c["check"] == "distance_not_refuted")
    assert not nd["ok"]
    sd = rep["computed"]["sector_distances"]
    assert sd["Z"]["upper"] == 4 and sd["Z"]["refuted_to"] == 4 and sd["Z"]["witness_weight"] == 6
    assert sd["X"]["upper"] == 6 and sd["X"]["refuted_to"] is None
    assert sd["d"]["upper"] == 4


def test_a_find_of_no_side_still_bounds_d():
    doc, _ = toric_doc(6)
    sd = V.sector_distances(doc, {"X": {"value": 6}, "Z": {"value": 6}},
                            {"side": None, "weight": 5, "witness": [0, 1, 2]})
    assert sd["X"]["upper"] == 6 and sd["Z"]["upper"] == 6 and sd["d"]["upper"] == 5


def test_a_side_without_a_witness_has_no_bound():
    doc, _ = toric_doc(4)
    sd = V.sector_distances(doc, {"X": {"value": 4}})
    assert sd["X"]["upper"] == 4 and sd["Z"]["upper"] is None and sd["d"]["upper"] is None


def test_an_exact_certificate_proves_every_side():
    doc, _ = toric_doc(4)
    rep = V.verify(doc, refute=False)
    cert = {"d": 4, "d_exact": True,
            "sides": {"X": {"value": 4, "exact": True}, "Z": {"value": 4, "exact": True}}}
    sd = V.apply_certificate(rep["computed"]["sector_distances"], doc, cert)
    for key in ("X", "Z", "d"):
        assert sd[key]["lower"] == 4 and sd[key]["exact"]
    # the same through verify(cert=...)
    assert V.verify(doc, refute=False, cert=cert)["computed"]["sector_distances"] == sd
    # a stale exact certificate (made against another distance) proves nothing
    stale = dict(cert, d=3)
    assert V.apply_certificate(rep["computed"]["sector_distances"], doc, stale) == \
        rep["computed"]["sector_distances"]


def test_a_partial_certificate_is_honored_by_its_binding_hash():
    doc, _ = toric_doc(4)
    rep = V.verify(doc, refute=False)
    base = rep["computed"]["sector_distances"]
    cert = {"d": 4, "d_exact": False, "d_lower": 3,
            "sides": {"X": {"proved_min": 3}, "Z": {"proved_min": 4}},
            "verification": {"checks_sha256": check_certs.checks_sha256(doc)}}
    sd = V.apply_certificate(base, doc, cert)
    assert sd["X"] == dict(base["X"], lower=3)
    assert sd["Z"] == dict(base["Z"], lower=4, exact=True)
    assert sd["d"] == {"upper": 4, "lower": 3, "exact": False}
    # bound to other matrices: ignored
    other = copy.deepcopy(cert)
    other["verification"]["checks_sha256"] = "0" * 64
    assert V.apply_certificate(base, doc, other) == base
    # a trivial bound, or sides that are not the entry's: ignored
    assert V.apply_certificate(base, doc, dict(cert, d_lower=1)) == base
    assert V.apply_certificate(base, doc, dict(cert, sides={"X": {"proved_min": 3}})) == base
    # a bound above the witness is a contradiction for check_certs, not a bound here
    high = copy.deepcopy(cert)
    high["sides"]["X"]["proved_min"] = 5
    assert V.apply_certificate(base, doc, high)["X"]["lower"] is None


def test_a_stabilizer_code_has_the_single_side_p():
    with open(os.path.join(ROOT, "verify", "fixtures", "5-1-3.json"), encoding="utf-8") as f:
        doc = json.load(f)
    rep = V.verify(doc, refute=False)
    sd = rep["computed"]["sector_distances"]
    assert set(sd) == {"P", "d"}
    assert sd["P"]["upper"] == 3 and sd["d"]["upper"] == 3
    cert = {"d": 3, "d_exact": True, "sides": {"P": {"value": 3, "exact": True}}}
    sd = V.apply_certificate(sd, doc, cert)
    assert sd["P"]["lower"] == 3 and sd["P"]["exact"] and sd["d"]["exact"]


def test_the_block_reaches_the_gate_verdict():
    """validate_candidate copies the block into candidate.sector_distances."""
    import validate_candidate as VC
    src = open(VC.__file__, encoding="utf-8").read()
    assert 'verdict["candidate"]["sector_distances"] = comp.get("sector_distances")' in src


if __name__ == "__main__":
    pytest.main([__file__])
