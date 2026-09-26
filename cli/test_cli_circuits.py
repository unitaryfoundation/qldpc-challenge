"""End-to-end tests for the circuit tier in `qldpc submit` (issue #1848).

Nothing is mocked below the CLI: the board's [[12,4,2]] bivariate-bicycle
checks go in as an .npz, the code tier is searched and verified, the memory
circuits are generated, searched, and verified with verify/circuit_verify.py,
and the artifacts land under circuits/<slug>/ beside codes/. The board
loader is stubbed only because it re-verifies every entry (about 15 s) and
the frontier text is not what is under test.
"""

import json
import os
import shutil

import numpy as np
import pytest

import circuit_verify as cv
import qldpc
from qldpc_verify import _matrix, verify

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAST = ["--trials", "300", "--fast-trials", "0",
        "--circuit-seconds", "3", "--circuit-candidates", "2"]


@pytest.fixture(scope="module")
def npz(tmp_path_factory):
    doc = json.load(open(os.path.join(ROOT, "codes", "12-4-2.json")))
    n = doc["n"]
    path = tmp_path_factory.mktemp("in") / "bb12.npz"
    np.savez(path, hx=_matrix(doc["checks"]["X"], n),
             hz=_matrix(doc["checks"]["Z"], n))
    return str(path)


@pytest.fixture(autouse=True)
def _no_board(monkeypatch):
    monkeypatch.setattr(qldpc, "_load_board_entries", lambda: [])


def test_dry_run_generates_and_verifies_circuits(npz, capsys, tmp_path):
    out = str(tmp_path / "codes")
    rc = qldpc.main(["submit", npz, "--authors", "@me", "--dry-run",
                     "--out", out, *FAST])
    assert rc == 0
    text = capsys.readouterr().out
    assert "schedule family: two-block interleaved" in text
    assert "OK  circuit tier verified: d_circ <= 2 (X 2, Z 2)" in text
    assert "circuit      d_circ <= 2 (X 2, Z 2), rounds 2" in text
    assert f"would write {out}/12-4-2.json and" in text
    assert not os.path.exists(out)
    assert not os.path.exists(tmp_path / "circuits")


def test_submit_writes_circuits_beside_the_code(npz, capsys, tmp_path):
    out = str(tmp_path / "codes")
    rc = qldpc.main(["submit", npz, "--authors", "@me", "--out", out, *FAST])
    assert rc == 0
    text = capsys.readouterr().out
    doc = json.load(open(os.path.join(out, "12-4-2.json")))
    circuits_dir = str(tmp_path / "circuits" / "12-4-2")
    assert sorted(os.listdir(circuits_dir)) == [
        "memory_x.dem", "memory_x.stim", "memory_z.dem", "memory_z.stim"]
    assert doc["schema_version"] == "0.2"
    assert doc["circuit"]["rounds"] == 2
    # the written artifacts pass both verifiers, exactly as CI runs them
    assert verify(doc)["ok"]
    report = cv.verify_circuit(doc, circuits_dir)
    assert report["ok"], report
    assert report["earned_d_circ"]["d_circ"]["value"] == 2
    # the PR steps stage the circuits with the code
    assert f"git add {out}/12-4-2.json {circuits_dir}" in text
    # a second run refuses to overwrite either artifact
    rc = qldpc.main(["submit", npz, "--authors", "@me", "--out", out, *FAST])
    assert rc == 1


def test_no_circuit_opts_out(npz, capsys, tmp_path):
    out = str(tmp_path / "codes")
    rc = qldpc.main(["submit", npz, "--authors", "@me", "--out", out,
                     "--no-circuit", *FAST])
    assert rc == 0
    doc = json.load(open(os.path.join(out, "12-4-2.json")))
    assert "circuit" not in doc and doc["schema_version"] == "0.1"
    assert not os.path.exists(tmp_path / "circuits")
    assert "circuit tier" not in capsys.readouterr().out


def test_own_circuits_override_generation(npz, capsys, tmp_path):
    own = tmp_path / "own"
    own.mkdir()
    for side in ("x", "z"):
        shutil.copy(os.path.join(ROOT, "circuits", "12-4-2",
                                 f"memory_{side}.stim"), own)
    out = str(tmp_path / "codes")
    rc = qldpc.main(["submit", npz, "--authors", "@me", "--out", out,
                     "--circuits", str(own), *FAST])
    assert rc == 0
    text = capsys.readouterr().out
    assert "submitter-provided" in text
    doc = json.load(open(os.path.join(out, "12-4-2.json")))
    assert doc["circuit"]["notes"].startswith("submitter-provided")
    circuits_dir = str(tmp_path / "circuits" / "12-4-2")
    assert cv.verify_circuit(doc, circuits_dir)["ok"]
    assert (open(os.path.join(circuits_dir, "memory_x.stim")).read()
            == (own / "memory_x.stim").read_text())


def test_own_circuits_that_fail_are_a_hard_error(npz, tmp_path):
    own = tmp_path / "own"
    own.mkdir()
    for side in ("x", "z"):
        text = open(os.path.join(ROOT, "circuits", "12-4-2",
                                 f"memory_{side}.stim")).read()
        (own / f"memory_{side}.stim").write_text(
            text.replace("DEPOLARIZE2(0.001)", "DEPOLARIZE2(0.002)", 1))
    out = str(tmp_path / "codes")
    with pytest.raises(SystemExit, match="--circuits"):
        qldpc.main(["submit", npz, "--authors", "@me", "--out", out,
                    "--circuits", str(own), *FAST])
    assert not os.path.exists(out)


def test_pr_body_states_the_circuit_tier():
    doc = json.load(open(os.path.join(ROOT, "codes", "12-4-2.json")))
    report = {"computed": {"max_check_weight": 6,
                           "locality_class": "unrestricted",
                           "weight_class": "weight-6"},
              "earned_distance": {"d": {"value": 2, "tier": "upper_bound"}}}

    class A:
        family = "bivariate-bicycle"
        construction = ""
    body = qldpc.pr_body(doc, report, A(), "codes/12-4-2.json")
    assert "- Circuit tier: d_circ <= 2 (X 2, Z 2) at rounds 2" in body
    assert "`circuits/12-4-2/`" in body
    assert "- [x] `python verify/circuit_verify.py codes/12-4-2.json` " \
           "passes locally" in body
