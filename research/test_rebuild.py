"""Tests for the construction recipe (issue #2955, item 3): rebuild.py replays
a `{constructor, params}` recipe to the verifier's fingerprint, and
submit.write_repro_manifest emits the manifest `qldpc reproduce` reads.
"""
import json
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "kit"))
sys.path.insert(0, os.path.join(ROOT, "verify"))

import rebuild  # noqa: E402
from submit import recipe_from_spec, write_repro_manifest  # noqa: E402

GROSS = {"constructor": "bb.build_bb",
         "params": {"l": 12, "m": 6, "A_terms": [[3, 0], [0, 2], [0, 1]], "B_terms": [[2, 0], [1, 0], [0, 3]]}}


def test_the_gross_code_rebuilds_to_the_board_entry_fingerprint():
    HX, HZ = rebuild.rebuild(GROSS["constructor"], GROSS["params"])
    assert HX.shape == (72, 144) and HZ.shape == (72, 144)
    from qldpc_verify import verify
    doc = json.load(open(os.path.join(ROOT, "codes", "144-12-12.json")))
    assert rebuild.fingerprint_of(HX, HZ) == verify(doc)["fingerprint"]


def test_the_script_prints_the_fingerprint_line_reproduce_reads():
    out = subprocess.run([sys.executable, os.path.join(HERE, "kit", "rebuild.py"),
                          "--constructor", GROSS["constructor"], "--params", json.dumps(GROSS["params"])],
                         capture_output=True, text=True, check=True).stdout
    lines = [l for l in out.splitlines() if l.startswith("fingerprint=")]
    assert len(lines) == 1 and len(lines[0].split("=", 1)[1]) == 16


def test_bad_recipes_are_refused():
    import pytest
    with pytest.raises(ValueError):
        rebuild.rebuild("build_bb", {})                       # no module
    with pytest.raises(ValueError):
        rebuild.rebuild("bb.no_such_function", {})
    with pytest.raises(ValueError):
        rebuild.rebuild("os.system", {})                       # not a kit module
    # a constructor that returns non-commuting checks is refused
    import types
    fake = types.ModuleType("fakector")
    fake.build = lambda: (np.array([[1, 1, 0]], dtype=np.int8), np.array([[1, 0, 0]], dtype=np.int8))
    sys.modules["fakector"] = fake
    try:
        with pytest.raises(ValueError):
            rebuild.rebuild("fakector.build", {})
    finally:
        del sys.modules["fakector"]


def test_recipe_from_spec_requires_both_keys():
    assert recipe_from_spec(GROSS) == GROSS
    assert recipe_from_spec({**GROSS, "family": "bivariate-bicycle"}) == GROSS
    assert recipe_from_spec({"constructor": "bb.build_bb"}) is None
    assert recipe_from_spec({"params": {}}) is None
    assert recipe_from_spec("bb(12,6)") is None


def test_write_repro_manifest_emits_a_runnable_construction_stage(tmp_path):
    doc = json.load(open(os.path.join(ROOT, "codes", "144-12-12.json")))
    path = write_repro_manifest(doc, "144-12-12", {**GROSS, "family": "bivariate-bicycle"},
                                repro_dir=str(tmp_path), artifact_path=os.path.join(ROOT, "codes", "144-12-12.json"))
    m = json.load(open(path))
    c = m["stages"]["construction"]
    assert c["status"] == "applicable" and c["script"] == "research/kit/rebuild.py"
    assert c["args"][:2] == ["--constructor", "bb.build_bb"]
    assert json.loads(c["args"][3]) == GROSS["params"]
    assert m["spec_context"] == {"family": "bivariate-bicycle"}
    assert len(m["artifact_sha256"]) == 64
    assert m["stages"]["verify"] == {"status": "applicable"}
    # running the declared command reproduces the entry's fingerprint
    out = subprocess.run([sys.executable, os.path.join(ROOT, c["script"]), *c["args"]],
                         capture_output=True, text=True, check=True).stdout
    from qldpc_verify import verify
    assert f"fingerprint={verify(doc)['fingerprint']}" in out


def test_write_repro_manifest_without_a_recipe_is_honest(tmp_path):
    doc = {"n": 7, "k": 1, "checks": {"X": [[0, 2, 4, 6]], "Z": [[0, 2, 4, 6]]}, "distance": {"d": 3}}
    path = write_repro_manifest(doc, "7-1-3", {"note": "hand-built"}, repro_dir=str(tmp_path))
    m = json.load(open(path))
    assert m["stages"]["construction"]["status"] == "not_reproducible"
    assert "recipe" in m["stages"]["construction"]["reason"]
    assert m["stages"]["circuits"]["status"] == "not_applicable"
