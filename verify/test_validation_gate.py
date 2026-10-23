"""The validation gate accepts the solved cases, diagnoses each broken artifact by class, and holds the goldens.

A verifier change that breaks a solved case, rejects a broken artifact for
the wrong reason, or changes a committed verdict fails here, and the re-pin
command refuses to run until it passes (issue #4030).
"""
import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import check_validator_integrity as CVI  # noqa: E402
import validation_gate as G  # noqa: E402


def test_solved_cases_verify_and_certify_at_their_known_parameters():
    for r in G.run_solved(tlim=60.0):
        assert r["ok"], r


@pytest.mark.parametrize("kind", [k for k, _, _ in G.BROKEN])
def test_each_broken_artifact_is_rejected_for_its_own_reason(kind):
    r = next(x for x in G.run_broken() if x["kind"] == kind)
    assert r["ok"], r
    assert kind in r["kinds"]


def test_the_direct_sum_and_the_clifford_image_are_diagnosed():
    cases = {r["case"]: r for r in G.run_solved(tlim=5.0)}
    assert cases["direct sum of two Steane codes is refused as disconnected"]["ok"]
    assert cases["Shor code under a local Hadamard is sent back as its CSS image"]["image_named"]


def test_every_reproduction_has_a_golden_that_matches():
    rows = {r["slug"]: r for r in G.run_reproductions()}
    assert set(rows) == set(G.REPRODUCTIONS)
    for slug, r in rows.items():
        assert r["status"] == "match", (slug, r)
    for slug in G.REPRODUCTIONS:
        with open(G._golden_path(slug), encoding="utf-8") as f:
            g = json.load(f)
        assert g["slug"] == slug and g["doc_sha256"] and g["report"]["ok"]


def test_the_golden_files_are_in_the_pinned_closure():
    files = CVI.trusted_files()
    assert "verify/validation_gate.py" in files
    for slug in G.REPRODUCTIONS:
        assert f"verify/fixtures/validation_gate/golden/{slug}.json" in files


def test_the_re_pin_refuses_when_the_gate_fails(tmp_path, capsys):
    assert CVI.update(gate=lambda: 1) == 1
    assert "validation gate did not pass" in capsys.readouterr().out
    assert CVI.check() == 0, "the refused re-pin wrote nothing"


def test_the_taxonomy_mirror_classifies_like_the_kit():
    assert G.kind_of("css_commutation") == "construction"
    assert G.kind_of("schema_valid", "checks/X/0 is too long") == "weight"
    assert G.kind_of("schema_valid", "'provenance' is a required property") == "packaging"
    assert G.kind_of("distance_X_witness") == "witness" and G.kind_of("d_matches_min_side") == "witness"
    assert G.kind_of("site_occupancy_within_layers") == "layout"
