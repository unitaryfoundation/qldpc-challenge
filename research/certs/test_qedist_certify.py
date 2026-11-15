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
    with open(os.path.join(_ROOT, "codes", "544-18-76.json"), encoding="utf-8") as f:
        doc = json.load(f)
    with pytest.raises(M.QEDistCertifyError):
        M.certify(doc, tlim=10.0, threads=1)
