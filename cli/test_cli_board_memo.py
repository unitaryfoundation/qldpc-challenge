"""The CLI shares one board memo across checkouts (issue #7381).

The verifier's per-entry memo defaults to a directory inside the checkout, so
a fresh worktree paid the whole structural pass (about 44 s) before any
submission logic. The CLI points it at one per-user directory instead, and
only when nothing else has chosen: a caller's QLDPC_BOARD_CACHE wins, an empty
value keeps the memo off (the test suite's default), and CI is left alone.
"""

import os

import qldpc


def test_an_unset_environment_gets_the_shared_directory(monkeypatch, tmp_path):
    monkeypatch.delenv(qldpc.BOARD_MEMO_ENV, raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    path = qldpc._default_board_memo()
    assert path == os.path.join(str(tmp_path / "xdg"), "qldpc", "boardcache")
    assert os.environ[qldpc.BOARD_MEMO_ENV] == path
    # idempotent: a second call sees the value it set and leaves it
    assert qldpc._default_board_memo() is None and os.environ[qldpc.BOARD_MEMO_ENV] == path


def test_without_xdg_the_directory_is_under_the_home_cache(monkeypatch):
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setenv("HOME", "/tmp/qldpc-home")
    assert qldpc._shared_board_memo_dir() == os.path.join(os.path.expanduser("~"), ".cache", "qldpc", "boardcache")
    assert qldpc._shared_board_memo_dir().startswith("/tmp/qldpc-home")


def test_a_callers_choice_is_kept_including_off(monkeypatch, tmp_path):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv(qldpc.BOARD_MEMO_ENV, str(tmp_path / "mine"))
    assert qldpc._default_board_memo() is None and os.environ[qldpc.BOARD_MEMO_ENV] == str(tmp_path / "mine")
    monkeypatch.setenv(qldpc.BOARD_MEMO_ENV, "")
    assert qldpc._default_board_memo() is None and os.environ[qldpc.BOARD_MEMO_ENV] == ""


def test_ci_is_left_alone(monkeypatch):
    monkeypatch.delenv(qldpc.BOARD_MEMO_ENV, raising=False)
    monkeypatch.setenv("CI", "true")
    assert qldpc._default_board_memo() is None and qldpc.BOARD_MEMO_ENV not in os.environ


def test_the_verifier_reads_the_directory_the_cli_set(monkeypatch, tmp_path):
    import qldpc_verify as Q

    monkeypatch.delenv(qldpc.BOARD_MEMO_ENV, raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    path = qldpc._default_board_memo()
    assert Q.board_cache_dir() == path


def test_main_sets_the_default_before_parsing(monkeypatch, tmp_path, capsys):
    import pytest

    monkeypatch.delenv(qldpc.BOARD_MEMO_ENV, raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    with pytest.raises(SystemExit):
        qldpc.main(["--help"])
    assert os.environ[qldpc.BOARD_MEMO_ENV].endswith(os.path.join("qldpc", "boardcache"))
