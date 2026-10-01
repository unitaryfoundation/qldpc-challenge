"""The gate's own use of the search cache, driven through main().

The module tests cover the cache; this covers the wiring, and the property
worth pinning is the one that would be a disaster to get wrong: a cached
refutation still fails the run, and it fails it without re-searching.

Also pinned here: a record whose witness does not survive re-validation is
discarded rather than believed. That is the whole reason a cache written by
the submitted tree is safe to read, so it is tested against main() and not
only against the module.
"""
import json
import os
import subprocess

import gate_changed as G
import heuristic_distance as H
import pytest
import refutation_cache as RC

# [[4,2,2]] claiming d=3. The weight-2 operator on qubits 0 and 1 is a
# genuine nontrivial logical, so it refutes the claim, and a cached record
# naming it is a record the verifier can confirm.
OVERCLAIMED = {
    "schema_version": "0.1",
    "name": "[[4,2,3]] synthetic over-claim",
    "code_type": "CSS",
    "n": 4, "k": 2,
    "checks": {"X": [[0, 1, 2, 3]], "Z": [[0, 1, 2, 3]]},
    "distance": {
        "d": 3,
        "X": {"value": 3, "confidence": "upper_bound", "witness": [0, 1, 2]},
        "Z": {"value": 3, "confidence": "upper_bound", "witness": [0, 1, 3]},
    },
    "provenance": {"authors": ["@tester"], "construction": "synthetic",
                   "date": "2026-10-01", "references": [], "notes": ""},
}
REAL_WITNESS = {"RIS#0": [2, [0, 1]]}
SLUG = "4-2-3"


def _git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True,
                   capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    """Build a one-entry repo whose base lacks the code: diff class new."""
    root = tmp_path / "repo"
    (root / "codes").mkdir(parents=True)
    _git(root.parent, "init", "-q", str(root))
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "README.md").write_text("base\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root,
                                   text=True).strip()
    with open(root / "codes" / f"{SLUG}.json", "w", encoding="utf-8") as f:
        json.dump(OVERCLAIMED, f)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "add the code")
    return root, base


def _run(repo_and_base, cache, monkeypatch, record=None, hits=None):
    """Drive main() over the one entry, counting searches."""
    repo, base = repo_and_base
    searched = []
    real = H.refute_check
    monkeypatch.setattr(H, "refute_check",
                        lambda *a, **k: (searched.append(1),
                                         real(*a, **k))[1])
    path = os.path.join("codes", f"{SLUG}.json")
    with open(repo / path, "rb") as f:
        doc_bytes = f.read()
    if record is not None:
        # The lone entry on this board is a record of its own cell, so the
        # gate takes the deep battery and the key has to say so. Derived
        # rather than hardcoded, since getting it wrong silently turns these
        # into tests of a cache miss.
        deep = SLUG in G.board_record_slugs(str(repo))
        assert deep, "expected the only entry to be a cell record"
        RC.store(cache, doc_bytes, record, hits or {}, deep=deep,
                 accelerated=G.GF is not None, head_sha="cafebabe" * 5)
    rc = G.main([base, path, "--code-root", str(repo),
                 "--search-cache", cache, "--seed", "7"])
    return rc, searched


def test_a_cached_refutation_still_fails_the_run(repo, tmp_path, monkeypatch,
                                                 capsys):
    """The property that would be a disaster to get wrong."""
    cache = str(tmp_path / "searchcache")
    rc, searched = _run(repo, cache, monkeypatch,
                        record={"refuted": True, "seed": 11, "trials": 900},
                        hits={k: tuple(v) for k, v in REAL_WITNESS.items()})
    out = capsys.readouterr().out
    assert rc == 1, "a reused refutation must fail the gate"
    assert "REFUTED" in out
    assert searched == [], "and must do it without re-searching"
    assert "refutation from cafebabe" in out, "the log must name its source"
    assert "witness re-checked" in out


def test_a_record_whose_witness_does_not_validate_is_discarded(
        repo, tmp_path, monkeypatch, capsys):
    """Why a cache the submitted tree can write is safe to read.

    The support here is a stabilizer, not a logical, so the pinned check
    refuses it and the gate searches instead of taking the record's word.
    """
    cache = str(tmp_path / "searchcache")
    rc, searched = _run(repo, cache, monkeypatch,
                        record={"refuted": True, "seed": 11, "trials": 900},
                        hits={"RIS#0": (2, [0, 1, 2, 3])})
    out = capsys.readouterr().out
    assert "did not re-validate" in out
    assert searched, "the gate must fall back to searching"
    assert "reused refutation" not in out
    assert rc in (0, 1)


def test_an_empty_cache_searches_and_stores_nothing_for_a_clean_run(
        repo, tmp_path, monkeypatch):
    """A clean verdict is never written, so there is nothing to forge."""
    cache = str(tmp_path / "searchcache")
    good = json.loads(json.dumps(OVERCLAIMED))
    good["distance"]["d"] = 2
    good["distance"]["X"]["value"] = 2
    good["distance"]["X"]["witness"] = [0, 1]
    good["distance"]["Z"]["value"] = 2
    good["distance"]["Z"]["witness"] = [0, 2]
    good["name"] = "[[4,2,2]] synthetic"
    root, _ = repo
    with open(root / "codes" / f"{SLUG}.json", "w", encoding="utf-8") as f:
        json.dump(good, f)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "honest claim")

    rc, searched = _run(repo, cache, monkeypatch)
    assert rc == 0 and searched, "an honest claim is searched and passes"
    stored = [f for _, _, fs in os.walk(cache) for f in fs]
    assert stored == [], "a clean result must leave no record behind"
