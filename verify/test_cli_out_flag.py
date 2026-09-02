"""Regression tests for --out validation (issue #638)."""

import pytest

import qldpc


def _fail_if_code_is_loaded(_path):
    raise AssertionError("--out must be checked before loading the code")


def test_submit_rejects_json_path_before_loading_code(monkeypatch):
    monkeypatch.setattr(qldpc, "load_checks", _fail_if_code_is_loaded)

    with pytest.raises(SystemExit, match=r"--out expects a directory"):
        qldpc.main([
            "submit", "must-not-be-loaded.npz",
            "--authors", "@vprusso", "--out", "/tmp/probe.json",
        ])


def test_submit_accepts_directory_out_and_reaches_code_loading(monkeypatch):
    reached = []

    def record_load(path):
        reached.append(path)
        raise RuntimeError("load reached")

    monkeypatch.setattr(qldpc, "load_checks", record_load)

    with pytest.raises(RuntimeError, match="load reached"):
        qldpc.main([
            "submit", "must-not-be-loaded.npz",
            "--authors", "@vprusso", "--out", "/tmp/some-output-dir",
        ])

    assert reached == ["must-not-be-loaded.npz"]
