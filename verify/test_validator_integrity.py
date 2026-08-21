"""Regression tests for the trusted validation-closure manifest."""

import json
import os
import shutil
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import check_validator_integrity as integrity
import check_submission_scope as submission_scope


def _copy_closure(root):
    for relative in integrity.trusted_files():
        source = os.path.join(integrity._ROOT, relative)
        destination = os.path.join(root, relative)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copyfile(source, destination)
    manifest = os.path.join("verify", "validator_manifest.json")
    os.makedirs(os.path.join(root, "verify"), exist_ok=True)
    shutil.copyfile(os.path.join(integrity._ROOT, manifest),
                    os.path.join(root, manifest))


def test_manifest_matches_declared_execution_closure():
    with open(integrity._manifest_path(integrity._ROOT)) as f:
        pinned = json.load(f)["files"]
    assert list(pinned) == list(integrity.trusted_files())
    assert integrity.check() == 0


def test_execution_closure_is_submission_critical():
    assert all(submission_scope.is_critical(path)
               for path in integrity.trusted_files())


@pytest.mark.parametrize("relative", integrity.trusted_files())
def test_each_trusted_file_is_checked(tmp_path, relative, capsys):
    root = str(tmp_path)
    _copy_closure(root)
    path = os.path.join(root, relative)
    with open(path, "ab") as f:
        f.write(b"\n# integrity-test tamper\n")

    assert integrity.check(root) == 1
    assert f"{relative}: changed" in capsys.readouterr().out


def test_missing_trusted_file_fails_closed(tmp_path, capsys):
    root = str(tmp_path)
    _copy_closure(root)
    missing = "verify/gate_changed.py"
    os.remove(os.path.join(root, missing))

    assert integrity.check(root) == 1
    assert f"{missing}: missing from tree" in capsys.readouterr().out


def test_new_verifier_fixture_requires_a_pin(tmp_path, capsys):
    root = str(tmp_path)
    _copy_closure(root)
    added = "verify/fixtures/new.json"
    with open(os.path.join(root, added), "w") as f:
        f.write("{}\n")

    assert integrity.check(root) == 1
    assert f"{added}: not pinned" in capsys.readouterr().out
