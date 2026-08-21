"""Regression tests for submit-time author validation (issue #636)."""

import pytest

import check_authorship
import qldpc


def _fail_if_code_is_loaded(_path):
    raise AssertionError("author validation must run before loading the code")


def test_submit_rejects_bare_handle_before_loading_code(monkeypatch):
    monkeypatch.setattr(qldpc, "load_checks", _fail_if_code_is_loaded)

    with pytest.raises(SystemExit, match=r"Add @yourhandle.*--anonymous"):
        qldpc.main(["submit", "must-not-be-loaded.npz", "--authors", "vprusso"])


@pytest.mark.parametrize("author", ["@", "@bad!", "@two handles"])
def test_submit_rejects_malformed_at_handle_before_loading_code(monkeypatch, author):
    monkeypatch.setattr(qldpc, "load_checks", _fail_if_code_is_loaded)

    with pytest.raises(SystemExit, match=r"Invalid author.*@yourhandle"):
        qldpc.main(["submit", "must-not-be-loaded.npz", "--authors", author])


def test_submit_checks_every_author_value(monkeypatch):
    monkeypatch.setattr(qldpc, "load_checks", _fail_if_code_is_loaded)

    with pytest.raises(SystemExit, match=r"Invalid author.*@bad!"):
        qldpc.main([
            "submit", "must-not-be-loaded.npz",
            "--authors", "@vprusso", "@bad!",
        ])


def test_valid_handle_and_plain_name_reach_code_loading(monkeypatch):
    reached = []

    def record_load(path):
        reached.append(path)
        raise RuntimeError("load reached")

    monkeypatch.setattr(qldpc, "load_checks", record_load)

    with pytest.raises(RuntimeError, match="load reached"):
        qldpc.main([
            "submit", "must-not-be-loaded.npz",
            "--authors", "@vprusso", "Jane Roe",
        ])

    assert reached == ["must-not-be-loaded.npz"]


def test_anonymous_opt_in_warns_and_reaches_code_loading(monkeypatch, capsys):
    reached = []

    def record_load(path):
        reached.append(path)
        raise RuntimeError("load reached")

    monkeypatch.setattr(qldpc, "load_checks", record_load)

    with pytest.raises(RuntimeError, match="load reached"):
        qldpc.main([
            "submit", "must-not-be-loaded.npz",
            "--authors", "Jane Roe", "--anonymous",
        ])

    assert reached == ["must-not-be-loaded.npz"]
    warning = capsys.readouterr().out
    assert "recorded as anonymous" in warning
    assert "not be bound to a GitHub account" in warning


def test_anonymous_flag_rejects_conflicting_handle(monkeypatch):
    monkeypatch.setattr(qldpc, "load_checks", _fail_if_code_is_loaded)

    with pytest.raises(SystemExit, match=r"--anonymous cannot be combined"):
        qldpc.main([
            "submit", "must-not-be-loaded.npz",
            "--authors", "@vprusso", "--anonymous",
        ])


def test_cli_reuses_authorship_handle_pattern():
    assert qldpc.HANDLE is check_authorship.HANDLE
