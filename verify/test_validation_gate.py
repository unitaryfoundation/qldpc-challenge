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
        assert r["ok"] and r["status"] in ("match", "match_entry_changed"), (slug, r)
    for slug in G.REPRODUCTIONS:
        with open(G._golden_path(slug), encoding="utf-8") as f:
            g = json.load(f)
        assert g["slug"] == slug and g["doc_sha256"] and g["report"]["ok"]
        # An identical verdict passes on changed bytes because the verdict
        # names the code it is a verdict on.
        assert g["report"]["fingerprint"], slug


@pytest.fixture
def one_reproduction(tmp_path, monkeypatch):
    """Point the gate at one synthetic entry with a freshly recorded golden.

    Nothing here reads the board: the entry is the gate's own Steane document,
    so no committed entry can move these tests.
    """
    codes = tmp_path / "codes"
    codes.mkdir()
    monkeypatch.setattr(G, "CODES", str(codes))
    monkeypatch.setattr(G, "GOLDEN_DIR", str(tmp_path / "golden"))
    monkeypatch.setattr(G, "REPRODUCTIONS", ("s-1-3",))
    entry = codes / "s-1-3.json"
    entry.write_text(json.dumps(G.steane(), indent=1), encoding="utf-8")
    assert G.run_reproductions(update=True) == [{"slug": "s-1-3", "status": "recorded", "ok": True}]
    return entry


def only_row():
    (row,) = G.run_reproductions()
    return row


def break_the_verifier(monkeypatch):
    """Make the verifier say something else about every document."""
    real = G.V.verify

    def changed(doc, **kw):
        rep = real(doc, **kw)
        rep["checks"][0] = dict(rep["checks"][0], detail="a changed verifier")
        return rep

    monkeypatch.setattr(G.V, "verify", changed)


def test_an_unchanged_entry_matches(one_reproduction):
    assert only_row() == {"slug": "s-1-3", "status": "match", "ok": True}


def test_changed_bytes_with_an_identical_verdict_still_pass(one_reproduction):
    """What #5929 did: the entry file moved, and nothing the verdict reports did."""
    doc = json.loads(one_reproduction.read_text(encoding="utf-8"))
    doc["provenance"]["construction"] += " (reworded)"
    one_reproduction.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    row = only_row()
    assert row["ok"] and row["status"] == "match_entry_changed", row
    assert G.ok({"solved": [], "broken": [], "reproductions": [row]})


def test_changed_bytes_with_a_changed_verdict_fail(one_reproduction):
    """A different code under the same name is not a reproduction of the golden."""
    one_reproduction.write_text(json.dumps(G.shor(), indent=1), encoding="utf-8")
    row = only_row()
    assert not row["ok"] and row["status"] == "entry_changed", row
    assert "rule out the verifier" in row["detail"]


def test_a_changed_verdict_on_the_recorded_bytes_is_drift(one_reproduction, monkeypatch):
    break_the_verifier(monkeypatch)
    row = only_row()
    assert not row["ok"] and row["status"] == "drift", row
    assert "schema_valid" in row["detail"]


def test_a_changed_verifier_is_not_excused_by_a_changed_entry(one_reproduction, monkeypatch):
    """Both moved: the verdict differs, so it fails, and the detail does not blame the entry alone."""
    doc = json.loads(one_reproduction.read_text(encoding="utf-8"))
    doc["provenance"]["construction"] += " (reworded)"
    one_reproduction.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    assert only_row()["status"] == "match_entry_changed"
    break_the_verifier(monkeypatch)
    row = only_row()
    assert not row["ok"] and row["status"] == "entry_changed", row
    assert "or a verifier change" in row["detail"] and "schema_valid" in row["detail"]


def test_re_recording_refreshes_the_recorded_hash(one_reproduction):
    one_reproduction.write_text(json.dumps(G.steane(), indent=3), encoding="utf-8")
    assert only_row()["status"] == "match_entry_changed"
    G.run_reproductions(update=True)
    assert only_row() == {"slug": "s-1-3", "status": "match", "ok": True}


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
