"""A completed search is reused only where reusing it means the same thing.

Issue #2633. The gate re-ran its full search on byte-identical code whenever a
push touched only prose, because `changed_codes` diffs against the base
branch: 6 of 7 PR branches with more than one run, 293.2 minutes in one day.

The reuse has to be narrow or it is worse than the cost it removes, so each
condition is pinned separately: the key covers the pinned closure and not just
the candidate, a refutation is never replaced by a clean result, and a reused
record carries the seed of the run that searched rather than the seed of the
run serving it.
"""
import json
import os

import pytest
import refutation_cache as RC

DOC = b'{"n": 72, "k": 6, "distance": {"d": 6}}'
OTHER = b'{"n": 72, "k": 6, "distance": {"d": 7}}'
CLEAN = {"refuted": False, "seed": 11, "trials": 4580, "methods": ["RIS#0"]}
REFUTED = {"refuted": True, "seed": 13, "trials": 900, "methods": ["RIS#0"]}
HITS = {"RIS#0": (5, [1, 2, 3])}


@pytest.fixture
def manifest(tmp_path):
    p = tmp_path / "validator_manifest.json"
    p.write_text(json.dumps({"files": {"verify/gate_changed.py": "aa",
                                       "verify/heuristic_distance.py": "bb"}}))
    return str(p)


@pytest.fixture
def cache(tmp_path):
    return str(tmp_path / "searchcache")


def test_a_clean_result_is_never_stored(cache, manifest):
    """Refuse the record a contributor's own run could have forged.

    A clean result carries nothing a reader can re-check.
    """
    assert RC.store(cache, DOC, CLEAN, {}, deep=False, accelerated=False,
                    head_sha="abc1234", manifest_path=manifest) is None
    assert RC.load(cache, DOC, deep=False, accelerated=False,
                   manifest_path=manifest) is None


def test_a_stored_refutation_comes_back(cache, manifest):
    RC.store(cache, DOC, REFUTED, HITS, deep=False, accelerated=False,
             head_sha="abc1234", manifest_path=manifest)
    rec = RC.load(cache, DOC, deep=False, accelerated=False,
                  manifest_path=manifest)
    assert rec["gate"]["refuted"] is True and rec["hits"]


def test_different_bytes_do_not_share_a_search(cache, manifest):
    RC.store(cache, DOC, REFUTED, HITS, deep=False, accelerated=False, manifest_path=manifest)
    assert RC.load(cache, OTHER, deep=False, accelerated=False, manifest_path=manifest) is None


def test_a_standard_run_does_not_answer_for_a_deep_one(cache, manifest):
    """The deep flag selects the trial budget: two different searches."""
    RC.store(cache, DOC, REFUTED, HITS, deep=False, accelerated=False, manifest_path=manifest)
    assert RC.load(cache, DOC, deep=True, accelerated=False, manifest_path=manifest) is None


def test_a_changed_closure_retires_the_search(cache, tmp_path, manifest):
    """The candidate can be byte-identical while the search is not.

    gate_changed.py, heuristic_distance.py, gf2_fast.cpp and decode/distance.py
    are all pinned in the manifest, so any change to how the search works
    moves the key without anyone maintaining a list of what matters.
    """
    RC.store(cache, DOC, REFUTED, HITS, deep=False, accelerated=False, manifest_path=manifest)
    other = tmp_path / "other_manifest.json"
    other.write_text(json.dumps({"files": {"verify/gate_changed.py": "CHANGED",
                                           "verify/heuristic_distance.py": "bb"}}))
    assert RC.load(cache, DOC, deep=False, accelerated=False, manifest_path=str(other)) is None


def test_a_missing_manifest_is_its_own_namespace(tmp_path):
    assert RC.closure_digest(str(tmp_path / "gone.json")) == "no-manifest"
    assert len(RC.closure_digest(None)) == 64, "the committed manifest digests"


def test_a_refutation_is_never_replaced_by_a_clean_result(cache, manifest):
    """The search is one-sided, so the witness is the fact and silence is not."""
    RC.store(cache, DOC, REFUTED, HITS, deep=False, accelerated=False, manifest_path=manifest)
    assert RC.store(cache, DOC, CLEAN, {}, deep=False, accelerated=False,
                    manifest_path=manifest) is None
    rec = RC.load(cache, DOC, deep=False, accelerated=False, manifest_path=manifest)
    assert rec["gate"]["refuted"] is True
    gate, hits = RC.restored(rec)
    assert hits == {"RIS#0": (5, [1, 2, 3])}


def test_a_shallow_record_does_not_answer_for_an_accelerated_run(cache, manifest):
    """Keep a shallow battery from answering for an accelerated one.

    `make fast` is continue-on-error, so a flaky build must not leave a
    three-python-seed record for a healthy run to reuse in place of the
    150x pass.
    """
    RC.store(cache, DOC, REFUTED, HITS, deep=True, accelerated=False,
             manifest_path=manifest)
    assert RC.load(cache, DOC, deep=True, accelerated=True,
                   manifest_path=manifest) is None
    assert RC.load(cache, DOC, deep=True, accelerated=False,
                   manifest_path=manifest)


def test_a_reused_record_carries_the_searching_run_s_seed(cache, manifest):
    """So the printed seed still reproduces the verdict it belongs to."""
    RC.store(cache, DOC, dict(REFUTED, seed=11), HITS, deep=False,
             accelerated=False, head_sha="deadbeefcafe", manifest_path=manifest)
    gate, _ = RC.restored(RC.load(cache, DOC, deep=False, accelerated=False,
                                  manifest_path=manifest))
    assert gate["seed"] == 11
    assert gate["reused_from"]["head_sha"] == "deadbeefcafe"
    assert gate["reused_from"]["seed"] == 11


def test_the_circuit_block_is_not_reused(cache, manifest):
    """Recompute the circuit tier every run.

    It decides whether to search by diffing against the base branch, which
    moves, so its result is not a function of the candidate's bytes.
    """
    RC.store(cache, DOC, dict(REFUTED, circuit={"searched": True}), HITS,
             deep=False, accelerated=False, manifest_path=manifest)
    rec = RC.load(cache, DOC, deep=False, accelerated=False, manifest_path=manifest)
    assert "circuit" not in rec["gate"]


def test_no_cache_directory_means_every_run_searches(manifest):
    """Absent the flag, this module is inert and the gate behaves as before."""
    assert RC.load(None, DOC, deep=False, accelerated=False, manifest_path=manifest) is None
    assert RC.store(None, DOC, REFUTED, HITS, deep=False, accelerated=False,
                    manifest_path=manifest) is None


def test_a_torn_entry_is_a_miss_and_not_a_crash(cache, manifest):
    RC.store(cache, DOC, REFUTED, HITS, deep=False, accelerated=False, manifest_path=manifest)
    key = RC.key_for(DOC, deep=False, accelerated=False, manifest_path=manifest)
    with open(os.path.join(cache, key[:2], key[2:] + ".json"), "w") as f:
        f.write('{"entry_version": 1, "ga')
    assert RC.load(cache, DOC, deep=False, accelerated=False, manifest_path=manifest) is None


def test_an_entry_from_a_future_version_is_a_miss(cache, manifest):
    RC.store(cache, DOC, REFUTED, HITS, deep=False, accelerated=False, manifest_path=manifest)
    key = RC.key_for(DOC, deep=False, accelerated=False, manifest_path=manifest)
    p = os.path.join(cache, key[:2], key[2:] + ".json")
    rec = json.load(open(p))
    rec["entry_version"] = RC.ENTRY_VERSION + 1
    json.dump(rec, open(p, "w"))
    assert RC.load(cache, DOC, deep=False, accelerated=False, manifest_path=manifest) is None
