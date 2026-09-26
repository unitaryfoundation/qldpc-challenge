"""Tests for `qldpc reproduce` (issue #2220).

Only the cheap deterministic stages run here. Certification is a bounded solver
run and an LER re-measurement is Monte Carlo over 100k shots; both belong on a
developer's machine, not in every CI run, which is why they are opt-in flags in
the first place. What is pinned instead is the part that must not drift: which
stage statuses exist and what each one means, that a stage never silently
vanishes from the receipt, and that reproducing something is never reported as
proving it.

The fixture is `verify/fixtures/72-6-6.json`, copied into a throwaway tree, so
the tests do not depend on any particular board entry surviving a refutation.
"""
import json
import os
import shutil
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)

import qldpc  # noqa: E402


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """Build a throwaway repo holding one entry and nothing else."""
    (tmp_path / "codes").mkdir()
    shutil.copy(os.path.join(_ROOT, "verify", "fixtures", "72-6-6.json"),
                tmp_path / "codes" / "72-6-6.json")
    monkeypatch.setattr(qldpc, "_repro_root", lambda: str(tmp_path))
    return tmp_path


def _run(*argv):
    return qldpc.main(["reproduce", *argv])


def test_the_cheap_core_reproduces_and_writes_a_receipt(tree, capsys):
    out = tree / "receipt.json"
    assert _run("72-6-6", "--out", str(out)) == 0
    r = json.loads(out.read_text())
    assert r["receipt_version"] == "1" and r["receipt_kind"] == "reproduction"
    assert r["overall"] == "reproduced"
    assert r["stages"]["verify"]["status"] == qldpc.ST_VERIFIED
    computed = r["stages"]["verify"]["computed"]
    assert (computed["n"], computed["k"], computed["d"]) == (72, 6, 6)
    assert computed["fingerprint"] and computed["signature"]


def test_every_stage_appears_in_the_receipt(tree):
    """A stage that did not run says so; none may quietly go missing."""
    out = tree / "receipt.json"
    _run("72-6-6", "--out", str(out))
    r = json.loads(out.read_text())
    assert set(r["stages"]) == set(qldpc.REPRO_STAGES)
    for name in ("circuits", "ler", "certify", "construction"):
        assert r["stages"][name]["status"] == qldpc.ST_SKIPPED


def test_a_claim_the_entry_does_not_make_is_not_applicable(tree):
    """An entry with no circuit block has nothing to reproduce there.

    not_applicable and not_reproducible are different answers: the first says
    there is no claim, the second says there is one and nothing can re-derive
    it.
    """
    out = tree / "receipt.json"
    assert _run("72-6-6", "--circuits", "--ler", "--out", str(out)) == 0
    r = json.loads(out.read_text())
    assert r["stages"]["circuits"]["status"] == qldpc.ST_NOT_APPLICABLE
    assert r["stages"]["ler"]["status"] == qldpc.ST_NOT_APPLICABLE
    assert r["stages"]["certify"]["status"] == qldpc.ST_SKIPPED


def test_construction_without_a_recipe_is_not_reproducible(tree):
    """The honest status, and the default: the search is usually not committed."""
    out = tree / "receipt.json"
    assert _run("72-6-6", "--construction", "--out", str(out)) == 0
    stage = json.loads(out.read_text())["stages"]["construction"]
    assert stage["status"] == qldpc.ST_NOT_REPRODUCIBLE
    assert "no constructor recipe" in stage["detail"]


def test_a_manifest_reason_reaches_the_receipt(tree):
    """When an entry declares why it cannot be rebuilt, the receipt says so."""
    (tree / "repro").mkdir()
    (tree / "repro" / "72-6-6.json").write_text(json.dumps({
        "manifest_version": "1", "slug": "72-6-6",
        "stages": {"construction": {"status": "not_reproducible",
                                    "reason": "the sweep was never committed"}},
    }))
    out = tree / "receipt.json"
    assert _run("72-6-6", "--construction", "--out", str(out)) == 0
    r = json.loads(out.read_text())
    assert r["stages"]["construction"]["detail"] == "the sweep was never committed"
    assert r["artifact"]["manifest_sha256"]


def test_a_changed_entry_is_reported_not_hidden(tree, capsys):
    """A refutation may legitimately revise an entry after its manifest.

    Both digests go in the receipt so the difference is visible, and the run
    still proceeds: a stale manifest is not a reason to refuse to reproduce.
    """
    (tree / "repro").mkdir()
    (tree / "repro" / "72-6-6.json").write_text(json.dumps({
        "manifest_version": "1", "slug": "72-6-6",
        "artifact_sha256": "0" * 64, "stages": {},
    }))
    out = tree / "receipt.json"
    assert _run("72-6-6", "--out", str(out)) == 0
    assert "has changed since the manifest" in capsys.readouterr().out
    r = json.loads(out.read_text())
    assert r["artifact"]["manifest_artifact_sha256"] == "0" * 64
    assert r["artifact"]["sha256"] != "0" * 64


def test_the_receipt_says_it_is_not_authoritative(tree):
    """Reproducing an entry must never read as having proved it."""
    out = tree / "receipt.json"
    _run("72-6-6", "--out", str(out))
    assert "non-authoritative" in json.loads(out.read_text())["authority"]


def test_the_environment_is_recorded(tree):
    """A reproduction is only meaningful beside what it ran under."""
    out = tree / "receipt.json"
    _run("72-6-6", "--out", str(out))
    env = json.loads(out.read_text())["environment"]
    assert env["python"] and env["validator_source_sha256"]
    assert "stim" in env and "uv_lock_sha256" in env


def test_an_unknown_slug_exits_two_without_a_receipt(tree, capsys):
    out = tree / "receipt.json"
    assert _run("999-999-999", "--out", str(out)) == 2
    assert not out.exists()
    assert "no such board entry" in capsys.readouterr().err


def test_a_json_path_is_accepted_as_the_slug(tree):
    assert _run("codes/72-6-6.json") == 0
