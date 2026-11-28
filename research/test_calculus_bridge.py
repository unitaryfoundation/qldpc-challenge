"""The code-calculus bridge (issue #7444): the contract half runs everywhere, the smoke half needs the checkout.

The contract half pins where the bridge looks and how it refuses, with no
code-calculus present. The smoke half loads board entries into the consumer
and checks the four things the two repositories must agree on: the state's
parameters, its row spaces, the binding hash, and the witness ledger. It is
skipped when no checkout is found (set ``CODE_CALCULUS_PATH`` to run it).
"""

import json
import os
import subprocess
import sys

import calculus_bridge as CB
import pytest
import qldpc_verify

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _entry(slug):
    with open(os.path.join(ROOT, "codes", f"{slug}.json"), encoding="utf-8") as f:
        return json.load(f)


# --- the contract half: no dependency needed ----------------------------------


def test_candidates_are_the_env_vars_then_the_sibling_checkouts(tmp_path):
    env = {CB.ENV: str(tmp_path / "a"), CB.LEGACY_ENV: str(tmp_path / "b")}
    found = CB.candidates(environ=env, parent=str(tmp_path))
    assert [source for _, source in found] == [f"env:{CB.ENV}", f"env:{CB.LEGACY_ENV}", "sibling", "sibling"]
    assert [os.path.basename(path) for path, _ in found] == ["a", "b", "code-calculus", "code-calculus-dev"]
    assert CB.candidates(environ={}, parent=str(tmp_path))[0][0] == str(tmp_path / "code-calculus")


def test_locate_accepts_only_a_checkout_that_holds_the_consumer(tmp_path, monkeypatch):
    monkeypatch.setattr(CB, "_importable", lambda: False)
    fake = tmp_path / "cc"
    (fake / "machine").mkdir(parents=True)
    env = {CB.ENV: str(fake)}
    assert CB.locate(environ=env, parent=str(tmp_path)) is None
    (fake / "machine" / "priced_calculus.py").write_text("")
    loc = CB.locate(environ=env, parent=str(tmp_path))
    assert loc.source == f"env:{CB.ENV}" and loc.root == str(fake)
    sibling = tmp_path / "code-calculus-dev" / "machine"
    sibling.mkdir(parents=True)
    (sibling / "priced_calculus.py").write_text("")
    assert CB.locate(environ={}, parent=str(tmp_path)).source == "sibling"
    assert CB.locate(explicit=str(fake)).source == "explicit" and CB.locate(explicit=str(tmp_path)) is None


def test_load_names_every_place_searched_when_nothing_is_found(tmp_path, monkeypatch):
    monkeypatch.setattr(CB, "_importable", lambda: False)
    with pytest.raises(CB.CalculusUnavailable) as err:
        CB.load(environ={CB.LEGACY_ENV: str(tmp_path / "old")}, parent=str(tmp_path), refresh=True)
    message = str(err.value)
    assert f"env:{CB.LEGACY_ENV}" in message and "code-calculus-dev" in message and CB.ENV in message
    assert "machine/priced_calculus.py" in message


def test_css_document_takes_a_css_entry_and_refuses_a_stabilizer_one():
    pres = CB.css_document(_entry("12-4-2"))
    assert (pres["n"], pres["k"]) == (12, 4) and set(pres["checks"]) == {"X", "Z"}
    assert all(isinstance(q, int) for row in pres["checks"]["X"] for q in row)
    with pytest.raises(ValueError, match="not a CSS entry"):
        CB.css_document(_entry("10-2-4"))


def test_the_presentation_hashes_like_the_entry_on_our_side():
    doc = _entry("12-4-2")
    assert qldpc_verify.checks_sha256(CB.css_document(doc)) == qldpc_verify.checks_sha256(doc)


def test_version_note_names_another_consumer_line():
    loc = CB.Location(None, "importable")

    def calc(release):
        return CB.Calculus(loc, "/x", {"release": release, "git": None}, None, None, None, None, None, None)

    assert CB.version_note(calc("0.3.2")) is None
    assert "0.4.0" in CB.version_note(calc("0.4.0"))
    assert "could not be read" in CB.version_note(calc(None))


# --- the smoke half: skipped without the checkout -----------------------------

smoke = pytest.mark.skipif(not CB.available(), reason=f"code-calculus not found (set {CB.ENV} to a checkout)")


@smoke
def test_an_entry_loads_with_its_parameters_and_row_spaces():
    doc = _entry("12-4-2")
    calculus = CB.load()
    state = CB.state_from_entry(doc, calculus=calculus)
    assert (state.n(), state.k()) == (doc["n"], doc["k"])
    assert state.w() == max(len(row) for side in ("X", "Z") for row in doc["checks"][side])
    entry_fp, state_fp = CB.round_trip_fingerprints(doc, calculus=calculus)
    assert entry_fp == state_fp
    canonical = CB.state_from_entry(doc, canonical=True, calculus=calculus)
    a, b = CB.round_trip_fingerprints(doc, canonical=True, calculus=calculus)
    assert a == b and canonical.k() == state.k()
    HX, HZ = CB.matrices_from_state(state)
    assert HX.shape[1] == HZ.shape[1] == doc["n"] and len(state.sector_rows("X")) == HX.shape[0]


@smoke
def test_dependent_rows_are_dropped_and_a_wrong_k_is_malformed():
    doc = _entry("12-4-2")
    calculus = CB.load()
    doubled = json.loads(json.dumps(doc))
    doubled["checks"]["X"] = doc["checks"]["X"] + doc["checks"]["X"][:1]
    state = CB.state_from_entry(doubled, calculus=calculus)
    assert len(state.sector_rows("X")) == len(CB.state_from_entry(doc, calculus=calculus).sector_rows("X"))
    wrong = json.loads(json.dumps(doc))
    wrong["k"] += 1
    with pytest.raises(calculus.Malformed):
        CB.state_from_entry(wrong, calculus=calculus)


@smoke
def test_the_binding_hash_agrees_between_the_repositories():
    calculus = CB.load()
    slugs = ["12-4-2", "7-1-3", "15-7-3", "4-2-2"]
    for slug in slugs:
        doc = _entry(slug)
        assert CB.binding_hash(doc, calculus=calculus) == qldpc_verify.checks_sha256(doc)


@smoke
def test_the_ledger_reads_the_entry_witnesses_as_upper_endpoints():
    doc = _entry("12-4-2")
    calculus = CB.load()
    state = CB.state_from_entry(doc, calculus=calculus)
    ledger = CB.ledger_from_entry(state, doc, calculus=calculus)
    for side in ("X", "Z"):
        assert ledger.sector[side].upper == doc["distance"][side]["value"]
        assert ledger.sector[side].lower == 0
    assert ledger.full.upper == doc["distance"]["d"]


@smoke
def test_describe_reports_location_version_and_the_entry():
    record = CB.describe(_entry("12-4-2"))
    assert record["code_calculus"]["root"] and record["code_calculus"]["version"]["release"]
    entry = record["entry"]
    assert (entry["n"], entry["k"], entry["w"]) == (12, 4, 6) and entry["row_spaces_preserved"]
    assert entry["rows_kept"]["X"] <= entry["rows_listed"]["X"] and entry["binding_hash"]
    assert entry["ledger"]["sector"]["X"]["upper"] == 2


@smoke
def test_the_module_runs_as_a_script_on_an_entry():
    calculus = CB.load()
    env = dict(os.environ)
    env[CB.ENV] = calculus.root
    script = os.path.join(ROOT, "research", "kit", "calculus_bridge.py")
    entry = os.path.join(ROOT, "codes", "12-4-2.json")
    out = subprocess.run(
        [sys.executable, script, entry],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    record = json.loads(out.stdout)
    assert record["entry"]["binding_hash"] == qldpc_verify.checks_sha256(_entry("12-4-2"))
