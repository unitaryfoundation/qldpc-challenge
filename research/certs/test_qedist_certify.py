"""QEDist certifier: solver-level exact distances for CSS entries."""

import importlib.util
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_ROOT, "verify"))
sys.path.insert(0, os.path.join(_ROOT, "research", "kit"))

import pytest


def _module():
    spec = importlib.util.spec_from_file_location("qedist_certify_mod",
                                                  os.path.join(_HERE, "qedist_certify.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _has_qedist():
    from qedist import find_qedist
    return find_qedist() is not None


def test_css_entry_certifies_exact():
    if not _has_qedist():
        pytest.skip("QEDist not installed")
    M = _module()
    with open(os.path.join(_ROOT, "codes", "10-2-3-b.json"), encoding="utf-8") as f:
        doc = json.load(f)
    cert = M.certify(doc, root=os.environ.get("QEDIST"), tlim=60.0, threads=1)
    assert cert["d"] == 3
    assert cert["d_exact"] is True
    assert cert["verification"]["level"] == "solver"
    assert all(s["status"] == "UNSAT" and s["exact"] for s in cert["sides"].values())


def test_stabilizer_entry_is_refused():
    M = _module()
    with open(os.path.join(_ROOT, "codes", "5-1-3.json"), encoding="utf-8") as f:
        doc = json.load(f)
    with pytest.raises(M.QEDistCertifyError):
        M.certify(doc, tlim=10.0, threads=1)


def test_high_distance_entry_is_refused():
    M = _module()
    with open(os.path.join(_ROOT, "codes", "544-18-70.json"), encoding="utf-8") as f:
        doc = json.load(f)
    with pytest.raises(M.QEDistCertifyError):
        M.certify(doc, tlim=10.0, threads=1)


def test_ladder_stops_on_timeout_and_keeps_previous_completed_rung(monkeypatch):
    M = _module()
    checks = [[0, 1, 2, 3], [0, 1, 4, 5], [0, 2, 4, 6]]
    doc = {
        "n": 7, "k": 1, "code_type": "CSS", "name": "steane",
        "checks": {"X": checks, "Z": checks},
        "distance": {"d": 6, "X": {"value": 6}, "Z": {"value": 6}},
    }
    seen = []

    def fake_certify(d, *, root=None, tlim=60.0, threads=1, cutoff=None, work_dir=None):
        seen.append((cutoff, work_dir))
        if cutoff in (1, 2):
            lb = cutoff + 1
            return {
                "d": 6, "d_exact": False, "d_lower": lb,
                "sides": {
                    "X": {"value": 6, "exact": False, "status": "TIMEOUT", "lower_bound": lb},
                    "Z": {"value": 6, "exact": False, "status": "TIMEOUT", "lower_bound": lb},
                },
                "solver": "QEDist", "verification": {"level": "solver", "checks_sha256": "0" * 64},
            }
        # cutoff 3 times out with a smaller lower_bound (2) on Z
        return {
            "d": 6, "d_exact": False, "d_lower": 2,
            "sides": {
                "X": {"value": 6, "exact": False, "status": "TIMEOUT", "lower_bound": 4},
                "Z": {"value": 6, "exact": False, "status": "TIMEOUT", "lower_bound": 2},
            },
            "solver": "QEDist", "verification": {"level": "solver", "checks_sha256": "0" * 64},
        }

    monkeypatch.setattr(M, "certify", fake_certify)
    cert = M.run_ladder(doc, budget=5.0, threads=1)
    # Stopped at cutoff=3; did not run 4 or 5; kept cutoff=2 (d_lower=3)
    assert [c for c, _ in seen] == [1, 2, 3]
    assert len({wd for _, wd in seen}) == 1 and seen[0][1] is not None
    assert cert["d_lower"] == 3
    assert cert["ladder"]["budget_per_side"] == 5.0


def test_partial_cert_satisfies_cert_schema(monkeypatch, tmp_path):
    import jsonschema
    import subprocess
    M = _module()
    checks = [[0, 1, 2, 3], [0, 1, 4, 5], [0, 2, 4, 6]]
    doc = {
        "n": 7, "k": 1, "code_type": "CSS", "name": "steane",
        "checks": {"X": checks, "Z": checks},
        "distance": {"d": 5, "X": {"value": 5}, "Z": {"value": 5}},
    }
    monkeypatch.setattr(M, "qedist_root", lambda root=None: ["fake-qedist"])

    def fake_run(cmd, capture_output=True, text=True):
        if cmd[1] == "certify":
            out_dir = cmd[cmd.index("--out") + 1]
            os.makedirs(out_dir, exist_ok=True)
            with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "sector_bounds": {
                        "X": {"lower": 3},
                        "Z": {"lower": 3},
                    }
                }, f)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(M.subprocess, "run", fake_run)
    cert = M.certify(doc, tlim=5.0, threads=1, cutoff=2, work_dir=tmp_path)
    assert cert["d_exact"] is False
    assert cert["d_lower"] == 3
    assert "checks_sha256" in cert["verification"]
    with open(os.path.join(_ROOT, "schema", "cert.schema.json"), encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.validate(cert, schema)
