"""Tests for verify/replay_formal.py (issue #2955, item 1).

The replay runs a certificate's recorded recipe verbatim, so the tests build
a small local git repository whose "build" is a shell command and drive the
four outcomes through it: the recipe replays, the commit is not reachable, the
build fails, the build exceeds the cap. No Lean is involved; what is under test
is the control flow and the reporting, which is all this script owns. One test
reads the board's real formal certificate and checks that its recipe is one
the script accepts.

Run: uv run pytest verify/test_replay_formal.py
"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay_formal as rf  # noqa: E402


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


@pytest.fixture
def repo(tmp_path):
    """A local repository with one commit holding `marker` and a lean-toolchain."""
    r = tmp_path / "upstream"
    r.mkdir()
    _git(r, "init", "-q")
    (r / "marker").write_text("ok\n")
    (r / "lean-toolchain").write_text("leanprover/lean4:v0.0.0\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "one")
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=r, check=True,
                         capture_output=True, text=True).stdout.strip()
    return r, sha


def _cert(repo_path, sha, build, toolchain="leanprover/lean4:v9.9.9"):
    return {"d": 6, "d_exact": True, "verification": {
        "level": "formal", "checker": "test",
        "replay": {"repo": f"file://{repo_path}", "commit": sha, "build": build,
                   "theorem": "T", "toolchain": toolchain}}}


def test_recipe_replays_and_the_recorded_toolchain_is_written(repo, tmp_path):
    r, sha = repo
    cert = _cert(r, sha, "test -f marker && grep -q v9.9.9 lean-toolchain")
    res = rf.replay("t", cert, timeout=60, keep=True, workdir=str(tmp_path / "w"))
    assert res["status"] == "ok", res
    assert res["theorem"] == "T" and res["commit"] == sha
    # the checkout carries the recorded toolchain, not the repository's
    assert (tmp_path / "w" / "src" / "lean-toolchain").read_text().strip() == "leanprover/lean4:v9.9.9"


def test_an_unreachable_commit_is_reported_not_guessed(repo, tmp_path):
    r, _ = repo
    cert = _cert(r, "0" * 40, "true")
    res = rf.replay("t", cert, timeout=60, workdir=str(tmp_path / "w"))
    assert res["status"] == "checkout_failed"
    assert "not reachable" in res["detail"]
    assert os.path.exists(res["log"])


def test_a_failing_build_is_a_failure_with_the_exit_code(repo, tmp_path):
    r, sha = repo
    res = rf.replay("t", _cert(r, sha, "exit 3"), timeout=60, workdir=str(tmp_path / "w"))
    assert res["status"] == "build_failed" and "exited 3" in res["detail"]


def test_the_wall_clock_cap_ends_a_hung_build(repo, tmp_path):
    r, sha = repo
    res = rf.replay("t", _cert(r, sha, "sleep 30"), timeout=3, workdir=str(tmp_path / "w"))
    assert res["status"] == "timeout"
    assert res["seconds"] < 20


def test_a_certificate_without_a_recipe_is_unreplayable():
    cert = {"verification": {"level": "formal", "replay": {"repo": "x"}}}
    res = rf.replay("t", cert, timeout=1)
    assert res["status"] == "unreplayable" and "lacks" in res["detail"]


def test_only_formal_certificates_are_selected_and_the_real_one_is_replayable():
    certs = rf.formal_certs()
    assert certs, "the board carries at least one formal certificate"
    for slug, cert in certs.items():
        assert cert["verification"]["level"] == "formal"
        assert rf.recipe_problems(cert["verification"]) == [], slug
    assert "72-12-6" in certs
    r = certs["72-12-6"]["verification"]["replay"]
    assert r["repo"] == "github.com/vprusso/Lean-QEC" and r["build"].startswith("git lfs pull")


def test_cli_list_and_json(repo, tmp_path, capsys, monkeypatch):
    r, sha = repo
    certdir = tmp_path / "certs"
    certdir.mkdir()
    (certdir / "9-1-3.json").write_text(json.dumps(_cert(r, sha, "test -f marker")))
    (certdir / "10-2-3.json").write_text(json.dumps({"verification": {"level": "proof_log"}}))
    monkeypatch.setattr(rf, "CERTS", str(certdir))
    assert rf.main(["--list"]) == 0
    out = capsys.readouterr().out
    assert "9-1-3" in out and "10-2-3" not in out
    outjson = tmp_path / "res.json"
    assert rf.main(["--all", "--timeout", "60", "--workdir", str(tmp_path / "w"), "--json", str(outjson)]) == 0
    res = json.load(open(outjson))
    assert [x["status"] for x in res] == ["ok"]
    assert rf.main(["nope"]) == 2
