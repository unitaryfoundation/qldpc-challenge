"""Tests for the coordination primitives (issue #2314).

Two properties are worth more than the rest and are tested hardest, because
both are about not losing something expensive. A staging write never destroys
another session's witness, and the verdict cache never serves an answer the
gate would not give right now: not after the validator changed, and not for a
document that would fail the schema. A cache that can produce a pass the gate
did not is worse than no cache at all, so the conditions that keep the reuse
subtractive are pinned here one at a time.

The board is deliberately not one of them. Only the refutation is cached;
``dedup`` and ``novelty`` are recomputed on every call, which is what a hit
is tested to do.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "kit"))

from coordination import (  # noqa: E402
    PREFLIGHT_SUFFIX,
    REJECTED_DIRNAME,
    RUN_ID_ENV,
    SESSION_ENV,
    CandidateCollision,
    PreflightFailure,
    VerdictCache,
    _parse,
    cell_slug,
    claim,
    content_digest,
    gate_and_record,
    holds_same_candidate,
    live_claims,
    preflight_path,
    prune_claims,
    read_claim,
    rejected_path,
    release,
    run_id,
    seed_cache_from_record,
    session_id,
    staging_dir,
    unique_path,
    validate_cached,
    validator_sha256,
    verdict_path,
)
from submit import save_submission  # noqa: E402


def candidate(**over):
    """A schema-valid [[4,2,2]] document: the smallest thing the gate accepts."""
    doc = {
        "schema_version": "0.1",
        "name": "[[4,2,2]] coordination test code",
        "code_type": "CSS",
        "n": 4,
        "k": 2,
        "checks": {"X": [[0, 1, 2, 3]], "Z": [[0, 1, 2, 3]]},
        "distance": {
            "d": 2,
            "X": {"value": 2, "confidence": "upper_bound", "witness": [0, 1]},
            "Z": {"value": 2, "confidence": "upper_bound", "witness": [0, 2]},
        },
        "provenance": {"authors": ["@tester"], "construction": "a test fixture",
                       "date": "2026-09-28", "references": [], "notes": ""},
    }
    doc.update(over)
    return doc


def variant(witness):
    """``candidate()`` with another X witness: a different candidate the gate accepts.

    Any weight-2 operator commutes with the one Z check and is outside the
    one X row, so the document stays valid and only its digest changes.
    """
    doc = candidate()
    doc["distance"]["X"]["witness"] = list(witness)
    return doc


def direct_sum_candidate():
    """Two [[4,2,2]] blocks on disjoint qubits: valid witnesses, not one code.

    The shape of 15 of the 41 refusals in issue #3616. The gate's verify step
    fails it on ``tanner_connected`` and ``stabilizer_group_connected`` and
    then still spends the random search on it, because the witnesses on the
    first block verify and earn a distance to refute.
    """
    return candidate(n=8, k=4, checks={"X": [[0, 1, 2, 3], [4, 5, 6, 7]],
                                       "Z": [[0, 1, 2, 3], [4, 5, 6, 7]]})


REFUTE_OK = {"refuted": False, "seed": 7, "detail": "no lighter operator"}
REFUTED = {"refuted": True, "seed": 9, "detail": "found weight 1 < 2"}


def stamped(passed=True, refute=None, **over):
    """A verdict shaped like the gate's, carrying the real source stamp."""
    v = {"passed": passed,
         "candidate": {"n": 4, "k": 2, "d": 2, "fingerprint": "abc123"},
         "gates": {"refute": dict(REFUTE_OK if refute is None else refute),
                   "dedup": {"exact_duplicate_of": None},
                   "novelty": {"board_advancing": False}},
         "labels": [],
         "validator": {"source_sha256": validator_sha256(), "seed": 7}}
    v.update(over)
    return v


def cache_at(tmp_path, board=None):
    return VerdictCache(root=str(tmp_path / "verdicts"))


# -- run identity and staging ---------------------------------------------

def test_a_run_id_is_a_usable_directory_name(monkeypatch):
    monkeypatch.delenv(RUN_ID_ENV, raising=False)
    rid = run_id()
    assert str(os.getpid()) in rid
    assert os.sep not in rid and "/" not in rid and rid == rid.strip()


def test_a_run_id_can_be_pinned_by_the_harness(monkeypatch):
    monkeypatch.setenv(RUN_ID_ENV, "pod 3/session:1")
    assert run_id() == "pod-3-session-1"


def test_a_session_id_can_be_pinned_by_the_harness(monkeypatch):
    monkeypatch.setenv(SESSION_ENV, "pod 3/session:1")
    assert session_id() == "pod-3-session-1"
    # One id pins both: a harness that sets QLDPC_RUN_ID gets claims to agree
    # with it too, without a second variable to remember.
    monkeypatch.delenv(SESSION_ENV)
    monkeypatch.setenv(RUN_ID_ENV, "pod 4/run:2")
    assert session_id() == "pod-4-run-2"


def test_a_session_id_is_one_terminal_and_run_id_is_one_process(monkeypatch):
    """The claim/release sequence is two ./qldpc processes, one shell.

    What has to agree across them is the session; what must not is the run, or
    two ladders started from one shell would share a staging directory.
    """
    monkeypatch.delenv(SESSION_ENV, raising=False)
    monkeypatch.delenv(RUN_ID_ENV, raising=False)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [os.path.join(_HERE, "kit"), env.get("PYTHONPATH", "")])
    out = subprocess.run(
        [sys.executable, "-c",
         "import coordination; print(coordination.session_id()); "
         "print(coordination.run_id())"],
        env=env, capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stderr
    their_session, their_run = out.stdout.split()
    assert their_session == session_id()      # another process, the same terminal
    assert their_run != run_id()              # another process, another run


def test_two_runs_stage_into_separate_directories(tmp_path):
    a = staging_dir("run-a", root=str(tmp_path))
    b = staging_dir("run-b", root=str(tmp_path))
    assert a != b and os.path.isdir(a) and os.path.isdir(b)
    assert os.path.basename(a) == "run-a"


# -- content addressing ---------------------------------------------------

def test_the_digest_ignores_who_packaged_a_candidate():
    """Two sessions that find the same code must land on one cache entry."""
    a = candidate()
    b = candidate(name="a different name")
    b["provenance"] = {"authors": ["@someone-else"], "construction": "elsewhere",
                       "date": "2026-01-01", "references": ["arXiv:1234.5678"],
                       "notes": "found independently"}
    assert content_digest(a) == content_digest(b)


@pytest.mark.parametrize("field,value", [
    ("n", 5),
    ("k", 1),
    ("family", "bivariate-bicycle"),
])
def test_the_digest_follows_what_the_gate_reads(field, value):
    assert content_digest(candidate()) != content_digest(candidate(**{field: value}))


def test_the_digest_follows_the_witness():
    """The witness is the expensive part; a different one is a different code."""
    other = candidate()
    other["distance"]["X"]["witness"] = [2, 3]
    assert content_digest(candidate()) != content_digest(other)


def test_a_model_claim_is_inside_the_key():
    """provenance.model is checked by value, so it cannot be keyed away."""
    named = candidate()
    named["provenance"]["model"] = "Claude Opus 5"
    assert content_digest(candidate()) != content_digest(named)


# -- staging without clobbering -------------------------------------------

def test_a_free_path_is_used_as_written(tmp_path):
    p = str(tmp_path / "4-2-2.json")
    assert unique_path(p, candidate()) == p


def test_re_saving_the_same_candidate_needs_no_new_name(tmp_path):
    p = str(tmp_path / "4-2-2.json")
    save_submission(candidate(), p)
    assert unique_path(p, candidate()) == p
    assert holds_same_candidate(p, candidate())


def test_a_second_candidate_gets_its_own_name(tmp_path):
    p = str(tmp_path / "4-2-2.json")
    save_submission(candidate(), p)
    other = variant([2, 3])
    second = unique_path(p, other)
    assert second != p and second.endswith(".json")
    save_submission(other, second)
    third = unique_path(p, variant([1, 2]))
    assert third not in (p, second)


def test_saving_over_another_session_s_candidate_is_refused(tmp_path):
    """The witness in the file on disk cost the compute; do not delete it."""
    p = str(tmp_path / "4-2-2.json")
    save_submission(candidate(), p)
    before = open(p).read()
    with pytest.raises(CandidateCollision, match="already holds a different"):
        save_submission(variant([2, 3]), p)
    assert open(p).read() == before


def test_saving_the_same_candidate_again_is_not_a_collision(tmp_path):
    p = str(tmp_path / "4-2-2.json")
    save_submission(candidate(), p)
    assert save_submission(candidate(name="renamed"), p) == []


def test_a_caller_that_means_to_replace_still_can(tmp_path):
    p = str(tmp_path / "4-2-2.json")
    save_submission(candidate(), p)
    save_submission(variant([2, 3]), p, on_collision="overwrite")
    assert json.load(open(p))["distance"]["X"]["witness"] == [2, 3]
    with pytest.raises(ValueError, match="unknown mode"):
        save_submission(candidate(), p, on_collision="clobber")


# -- the verdict cache ----------------------------------------------------

def test_a_stored_refutation_comes_back_unchanged(tmp_path):
    c = cache_at(tmp_path)
    assert c.get(candidate()) is None
    c.put(candidate(), stamped())
    assert c.get(candidate()) == REFUTE_OK


def test_a_refutation_is_reused_for_the_same_code_packaged_by_someone_else(tmp_path):
    c = cache_at(tmp_path)
    c.put(candidate(), stamped())
    mine = candidate(name="my own name")
    mine["provenance"] = {"authors": ["@me"], "construction": "my own search",
                          "date": "2026-09-30"}
    assert c.get(mine) == REFUTE_OK


def test_a_verdict_without_the_gate_s_stamp_is_refused(tmp_path):
    """Otherwise the cache is a place to plant a pass, not a cache."""
    c = cache_at(tmp_path)
    assert c.put(candidate(), stamped(validator={})) is None
    assert c.put(candidate(),
                 stamped(validator={"source_sha256": "0" * 64})) is None
    assert c.get(candidate()) is None


def test_a_verdict_that_skipped_the_refutation_is_not_kept(tmp_path):
    c = cache_at(tmp_path)
    assert c.put(candidate(), stamped(), refuted=False) is None
    assert c.get(candidate()) is None


def test_a_verdict_with_no_refutation_block_is_not_kept(tmp_path):
    """A structural failure returns before the search, so it costs nothing."""
    c = cache_at(tmp_path)
    v = stamped(passed=False)
    v["gates"] = {"verify": {"ok": False, "failed_checks": ["css_commuting"]}}
    assert c.put(candidate(), v) is None
    assert c.get(candidate()) is None


def test_a_refutation_is_cached_too(tmp_path):
    """A refusal cost the same compute as a pass and is worth more."""
    c = cache_at(tmp_path)
    c.put(candidate(), stamped(passed=False, refute=REFUTED))
    assert c.get(candidate())["refuted"] is True


def test_a_found_refutation_is_never_downgraded(tmp_path):
    """The search is one-sided: a lighter operator found once stays found.

    A later run that happens not to rediscover it has not shown it is absent,
    so overwriting the witness with that silence would lose the only hard
    fact the cache holds.
    """
    c = cache_at(tmp_path)
    c.put(candidate(), stamped(passed=False, refute=REFUTED))
    c.put(candidate(), stamped(refute=REFUTE_OK))
    assert c.get(candidate()) == REFUTED
    assert json.load(open(c.path_for(candidate())))["attempts"] == 2


def test_a_changed_board_keeps_the_entry(tmp_path):
    """The point of the split: dedup and novelty move, the search does not.

    Keying on the board is what made the first version of this cache miss
    almost always (7 hits against 366 validations, #2314). Nothing served
    from here is a claim about codes/.
    """
    c = cache_at(tmp_path)
    c.put(candidate(), stamped())
    board = tmp_path / "codes"
    board.mkdir()
    (board / "a.json").write_text('{"n": 1}')
    assert cache_at(tmp_path).get(candidate()) == REFUTE_OK


def test_a_changed_validator_retires_the_entry(tmp_path):
    c = cache_at(tmp_path)
    c.put(candidate(), stamped())
    path = c.path_for(candidate())
    entry = json.load(open(path))
    entry["validator_sha256"] = "0" * 64
    open(path, "w").write(json.dumps(entry))
    assert cache_at(tmp_path).get(candidate()) is None


def test_a_document_that_would_fail_the_schema_is_never_served(tmp_path):
    """The key drops the date, so the schema check has to catch a bad one."""
    c = cache_at(tmp_path)
    c.put(candidate(), stamped())
    bad = candidate()
    bad["provenance"]["date"] = "the third of never"
    assert content_digest(bad) == content_digest(candidate())
    assert c.get(bad) is None


def test_an_unreadable_entry_is_a_miss_and_not_a_crash(tmp_path):
    c = cache_at(tmp_path)
    c.put(candidate(), stamped())
    open(c.path_for(candidate()), "w").write('{"entry_version": 2, "refu')
    assert c.get(candidate()) is None


# -- the wrapper ----------------------------------------------------------

def test_a_hit_still_runs_the_gate_and_only_skips_the_search(tmp_path):
    """Reuse is of the refutation alone; the board half is always recomputed."""
    seen = []

    def fake_gate(doc, *, seed=None, refute=True):
        seen.append(refute)
        return stamped(**({"gates": dict(stamped()["gates"],
                                         novelty={"board_advancing": True})}
                          if len(seen) > 1 else {}))

    c = cache_at(tmp_path)
    first, reused = validate_cached(candidate(), cache=c, validator=fake_gate)
    assert reused is False and first["gates"]["novelty"]["board_advancing"] is False
    second, reused = validate_cached(candidate(), cache=c, validator=fake_gate)
    assert reused is True
    assert seen == [True, False], "the second call must skip only the search"
    assert second["gates"]["novelty"]["board_advancing"] is True, \
        "novelty came from the fresh call, not the cache"
    assert second["gates"]["refute"] == REFUTE_OK


def test_a_cached_refutation_can_only_take_a_pass_away(tmp_path):
    c = cache_at(tmp_path)
    c.put(candidate(), stamped(passed=False, refute=REFUTED))

    def passes(doc, *, seed=None, refute=True):
        return stamped(passed=True)

    verdict, reused = validate_cached(candidate(), cache=c, validator=passes)
    assert reused is True
    assert verdict["passed"] is False
    assert verdict["gates"]["refute"] == REFUTED
    assert any("refuted" in lab for lab in verdict["labels"])


def test_a_clean_cached_refutation_cannot_give_a_pass_back(tmp_path):
    """The board half decides a failure on its own and the cache cannot undo it."""
    c = cache_at(tmp_path)
    c.put(candidate(), stamped())

    def duplicate(doc, *, seed=None, refute=True):
        v = stamped(passed=False)
        v["gates"]["dedup"] = {"exact_duplicate_of": "4-2-2.json"}
        return v

    verdict, reused = validate_cached(candidate(), cache=c, validator=duplicate)
    assert reused is True and verdict["passed"] is False


def test_a_structural_failure_on_a_hit_is_left_alone(tmp_path):
    """The gate returns before gates.refute exists; there is nothing to splice."""
    c = cache_at(tmp_path)
    c.put(candidate(), stamped(refute=REFUTED))

    def rejects(doc, *, seed=None, refute=True):
        v = stamped(passed=False)
        v["gates"] = {"verify": {"ok": False, "failed_checks": ["css_commuting"]}}
        return v

    verdict, _ = validate_cached(candidate(), cache=c, validator=rejects)
    assert verdict["passed"] is False
    assert "refute" in verdict["gates"]


def test_a_shallow_run_neither_reads_nor_writes_the_cache(tmp_path):
    """refute=False skips the expensive half, so its answer is not the answer."""
    c = cache_at(tmp_path)
    c.put(candidate(), stamped(refute=REFUTED))
    seen = []

    def fake_gate(doc, *, seed=None, refute=True):
        seen.append(refute)
        return stamped(passed=False)

    verdict, reused = validate_cached(candidate(), cache=c, validator=fake_gate,
                                      refute=False)
    assert seen == [False] and reused is False and verdict["passed"] is False
    assert c.get(candidate()) == REFUTED             # the deep answer survives


# -- the verdict beside the candidate (issue #2781) -------------------------

def test_the_verdict_lives_beside_the_candidate_under_its_own_suffix():
    from coordination import verdict_path
    assert verdict_path("/s/run/72-12-6.json") == "/s/run/72-12-6.verdict.json"
    assert verdict_path("/s/run/72-12-6-b.json") == "/s/run/72-12-6-b.verdict.json"
    # A verdict is never itself a candidate: the suffix is two extensions deep
    # and the file has no `checks`, so a `*.json` glob that reads it fails the
    # schema instead of gating it.
    assert verdict_path("/s/run/72-12-6.verdict.json").endswith(".verdict.verdict.json")


def test_gate_and_record_writes_the_full_verdict_next_to_the_candidate(tmp_path):
    """The documented CLI prints and forgets; this keeps what the gate said."""
    from coordination import gate_and_record, verdict_path
    doc = candidate()
    path = str(tmp_path / "4-2-2.json")
    save_submission(doc, path)
    calls = []

    def fake_gate(d, *, seed=None, refute=True):
        calls.append((seed, refute))
        return stamped(passed=True)

    verdict, out = gate_and_record(path, cache=cache_at(tmp_path),
                                   validator=fake_gate, seed=7)
    assert out == verdict_path(path) and os.path.exists(out)
    with open(out, encoding="utf-8") as f:
        on_disk = json.load(f)
    # The whole verdict, not a slice, plus a record of when and by whom.
    assert on_disk["passed"] is True and on_disk["gates"] == verdict["gates"]
    assert on_disk["labels"] == verdict["labels"]
    assert on_disk["recorded"]["candidate"] == "4-2-2.json"
    assert on_disk["recorded"]["content_digest"] == content_digest(doc)
    assert on_disk["recorded"]["refutation_reused"] is False
    assert on_disk["recorded"]["run_id"] == run_id()
    assert calls == [(7, True)]
    # The returned verdict is the gate's own, without the bookkeeping block.
    assert "recorded" not in verdict


def test_gate_and_record_goes_through_the_refutation_cache(tmp_path):
    """A refutation found once is reused and the record says so."""
    from coordination import gate_and_record
    doc = candidate()
    path = str(tmp_path / "4-2-2.json")
    save_submission(doc, path)
    cache = cache_at(tmp_path)
    cache.put(doc, stamped(passed=False, refute=REFUTED))

    def gate_without_search(d, *, seed=None, refute=True):
        assert refute is False, "a cached refutation must skip the search"
        return stamped(passed=True)

    verdict, out = gate_and_record(path, cache=cache, validator=gate_without_search)
    assert verdict["passed"] is False
    assert verdict["gates"]["refute"] == REFUTED
    with open(out, encoding="utf-8") as f:
        assert json.load(f)["recorded"]["refutation_reused"] is True


def test_a_failed_gate_is_recorded_too(tmp_path):
    """Negative verdicts are evidence as well; the file is written either way."""
    from coordination import gate_and_record
    path = str(tmp_path / "4-2-2.json")
    save_submission(candidate(), path)
    verdict, out = gate_and_record(
        path, cache=cache_at(tmp_path),
        validator=lambda d, *, seed=None, refute=True: stamped(passed=False))
    assert verdict["passed"] is False and os.path.exists(out)


def test_the_gate_cli_mode_exits_with_the_verdict(tmp_path, monkeypatch, capsys):
    import coordination
    path = str(tmp_path / "4-2-2.json")
    save_submission(candidate(), path)
    monkeypatch.setattr(coordination, "validate_cached",
                        lambda doc, **kw: (stamped(passed=False), False))
    rc = coordination._main(["gate", path])
    assert rc == 1
    out = capsys.readouterr()
    assert json.loads(out.out)["passed"] is False
    assert "verdict written to" in out.err
    assert os.path.exists(coordination.verdict_path(path))
    assert coordination._main(["gate"]) == 2


# -- the preflight (issue #3616) ------------------------------------------
#
# The gate's verify step refuses a document on checks that read the document
# alone and then, when its witnesses verify, still spends the random search
# on it. The preflight makes that refusal first, with the verifier's own
# function. What is pinned here: nothing is lost (the document and the
# report are kept), nothing is gated (the gate is not called and no verdict
# is written), and a refutation recorded beside a candidate is not searched
# for twice.

def test_saving_what_the_gate_would_refuse_keeps_it_out_of_the_way(tmp_path):
    doc = direct_sum_candidate()
    path = str(tmp_path / "8-4-2.json")
    with pytest.raises(PreflightFailure) as info:
        save_submission(doc, path)
    assert not os.path.exists(path)                      # nothing to gate under the name
    kept = rejected_path(path)
    assert os.path.exists(kept) and holds_same_candidate(kept, doc)   # the witness survived
    report = preflight_path(kept)
    with open(report, encoding="utf-8") as f:
        rep = json.load(f)
    assert [x["check"] for x in rep["failed"]] == ["tanner_connected",
                                                   "stabilizer_group_connected"]
    assert rep["recorded"]["content_digest"] == content_digest(doc)
    err = info.value
    assert err.kept == (kept, report) and err.path == path
    assert err.result["code_at_fault"] and err.result["kinds"] == ["construction"]
    assert "Tanner graph has 2 connected component(s)" in str(err)
    assert "no edit to the document fixes it" in str(err)


def test_two_refused_documents_of_one_name_both_survive(tmp_path):
    path = str(tmp_path / "8-4-2.json")
    a = direct_sum_candidate()
    b = direct_sum_candidate()
    b["distance"]["X"]["witness"] = [2, 3]               # another witness, another candidate
    for doc in (a, b):
        with pytest.raises(PreflightFailure):
            save_submission(doc, path)
    kept = sorted(os.listdir(os.path.join(str(tmp_path), REJECTED_DIRNAME)))
    assert len([k for k in kept if k.endswith(PREFLIGHT_SUFFIX)]) == 2
    assert len([k for k in kept if not k.endswith(PREFLIGHT_SUFFIX)]) == 2
    assert "8-4-2.json" in kept                           # the first keeps the plain name


def test_a_caller_that_means_to_stage_it_anyway_still_can(tmp_path):
    path = str(tmp_path / "8-4-2.json")
    assert save_submission(direct_sum_candidate(), path, preflight=False) == []
    assert os.path.exists(path) and not os.path.exists(rejected_path(path))


def test_a_document_that_passes_the_preflight_is_staged_as_before(tmp_path):
    path = str(tmp_path / "4-2-2.json")
    assert save_submission(candidate(), path) == []
    assert os.path.exists(path) and not os.path.exists(preflight_path(path))
    assert not os.path.isdir(os.path.join(str(tmp_path), REJECTED_DIRNAME))


def test_gate_and_record_refuses_before_the_gate_and_keeps_the_report(tmp_path):
    doc = direct_sum_candidate()
    path = str(tmp_path / "8-4-2.json")
    save_submission(doc, path, preflight=False)
    calls = []

    def gate(d, *, seed=None, refute=True):
        calls.append(refute)
        return stamped(passed=False)

    with pytest.raises(PreflightFailure) as info:
        gate_and_record(path, cache=cache_at(tmp_path), validator=gate)
    assert calls == []                                   # the search was never spent
    assert not os.path.exists(verdict_path(path))        # no verdict: the gate did not run
    report = preflight_path(path)
    assert info.value.kept == (report,) and os.path.exists(report)
    with open(report, encoding="utf-8") as f:
        assert json.load(f)["recorded"]["content_digest"] == content_digest(doc)
    assert "not gated" in str(info.value)


def test_gate_and_record_can_be_told_to_gate_regardless(tmp_path):
    path = str(tmp_path / "8-4-2.json")
    save_submission(direct_sum_candidate(), path, preflight=False)
    verdict, out = gate_and_record(
        path, cache=cache_at(tmp_path), preflight=False,
        validator=lambda d, *, seed=None, refute=True: stamped(passed=False))
    assert verdict["passed"] is False and os.path.exists(out)


def test_the_gate_cli_prints_the_report_and_not_a_verdict(tmp_path, capsys):
    import coordination
    path = str(tmp_path / "8-4-2.json")
    save_submission(direct_sum_candidate(), path, preflight=False)
    assert coordination._main(["gate", path]) == 1
    out = capsys.readouterr()
    report = json.loads(out.out)
    assert report["ok"] is False and "passed" not in report and "gates" not in report
    assert "stabilizer_group_connected" in out.err and "not gated" in out.err
    assert not os.path.exists(coordination.verdict_path(path))
    assert os.path.exists(coordination.preflight_path(path))


def test_a_refutation_recorded_beside_the_candidate_is_not_searched_again(tmp_path):
    """The record outlives the cache; a lighter logical found once is a witness."""
    doc = candidate()
    path = str(tmp_path / "4-2-2.json")
    save_submission(doc, path)
    record = stamped(passed=False, refute=REFUTED)
    record["recorded"] = {"candidate": "4-2-2.json",
                          "content_digest": content_digest(doc)}
    with open(verdict_path(path), "w", encoding="utf-8") as f:
        json.dump(record, f)
    cache = cache_at(tmp_path)
    assert cache.get(doc) is None                         # the cache was emptied

    def gate_without_search(d, *, seed=None, refute=True):
        assert refute is False, "the recorded refutation must be reused"
        return stamped(passed=True)

    verdict, out = gate_and_record(path, cache=cache, validator=gate_without_search)
    assert verdict["passed"] is False and verdict["gates"]["refute"] == REFUTED
    assert cache.get(doc) == REFUTED                      # and the cache has it back
    with open(out, encoding="utf-8") as f:
        assert json.load(f)["recorded"]["refutation_reused"] is True


def test_only_this_documents_own_refutation_seeds_the_cache(tmp_path):
    doc = candidate()
    path = str(tmp_path / "4-2-2.json")
    save_submission(doc, path)
    mine = {"content_digest": content_digest(doc)}
    cases = {
        "another document": dict(stamped(passed=False, refute=REFUTED),
                                 recorded={"content_digest": "not-this-one"}),
        "a clean search": dict(stamped(passed=True), recorded=mine),
        "another validator": dict(stamped(passed=False, refute=REFUTED,
                                          validator={"source_sha256": "stale", "seed": 9}),
                                  recorded=mine),
    }
    for why, record in cases.items():
        cache = VerdictCache(root=str(tmp_path / why.replace(" ", "-")))
        with open(verdict_path(path), "w", encoding="utf-8") as f:
            json.dump(record, f)
        assert seed_cache_from_record(cache, doc, verdict_path(path)) is False, why
        assert cache.get(doc) is None, why
    assert seed_cache_from_record(cache_at(tmp_path), doc, str(tmp_path / "missing.json")) is False


# -- advisory cell claims (issue #2314, item 6) ---------------------------
#
# A claim is a note, not a lock, and every test below is a consequence of
# that. The two that matter most are that an expired claim reads as absent
# (so a session that was killed cannot squat) and that a second session
# holding the same cell is *reported* rather than refused. A mechanism that
# blocked would be enforcing something, and the gate is the only thing
# entitled to enforce.

T0 = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


def test_a_claim_records_who_and_when_it_expires(tmp_path):
    rec = claim("weight-6/unrestricted", campaign="bb-1155", rid="s1",
                root=str(tmp_path), now=T0, minutes=30)
    assert rec["cell"] == "weight-6/unrestricted"
    assert rec["cell_key"] == ["weight-6", "unrestricted"]
    assert rec["session_id"] == "s1" and rec["campaign"] == "bb-1155"
    assert _parse(rec["expires_at"]) == T0 + timedelta(minutes=30)
    assert read_claim("weight-6/unrestricted", root=str(tmp_path), now=T0) == rec


def test_an_expired_claim_reads_as_absent(tmp_path):
    """The squat case: a killed session must not hold a cell forever."""
    claim("weight-6/unrestricted", rid="dead", root=str(tmp_path), now=T0,
          minutes=30)
    just_before = T0 + timedelta(minutes=29, seconds=59)
    assert read_claim("weight-6/unrestricted", root=str(tmp_path),
                      now=just_before) is not None
    after = T0 + timedelta(minutes=31)
    assert read_claim("weight-6/unrestricted", root=str(tmp_path), now=after) is None
    assert live_claims(root=str(tmp_path), now=after) == []
    assert prune_claims(root=str(tmp_path), now=after) == 1
    assert os.listdir(tmp_path) == []


def test_a_second_session_is_told_whose_claim_it_displaced(tmp_path):
    """Advisory means reported, never refused."""
    claim("weight-6/unrestricted", campaign="first", rid="s1",
          root=str(tmp_path), now=T0, minutes=30)
    rec = claim("weight-6/unrestricted", campaign="second", rid="s2",
                root=str(tmp_path), now=T0, minutes=30)
    assert rec["session_id"] == "s2"
    assert rec["displaced"]["session_id"] == "s1"
    assert rec["displaced"]["campaign"] == "first"
    # No exception, and the incumbent is simply gone: one file per cell.
    assert len(os.listdir(tmp_path)) == 1


def test_reclaiming_your_own_cell_is_not_a_collision(tmp_path):
    claim("weight-6/unrestricted", rid="s1", root=str(tmp_path), now=T0)
    rec = claim("weight-6/unrestricted", rid="s1", root=str(tmp_path), now=T0)
    assert "displaced" not in rec


def test_release_only_works_for_the_holder(tmp_path):
    claim("weight-6/unrestricted", rid="s1", root=str(tmp_path), now=T0,
          minutes=30)
    assert release("weight-6/unrestricted", rid="s2", root=str(tmp_path),
                   now=T0) is False
    assert read_claim("weight-6/unrestricted", root=str(tmp_path), now=T0)
    assert release("weight-6/unrestricted", rid="s1", root=str(tmp_path),
                   now=T0) is True
    assert read_claim("weight-6/unrestricted", root=str(tmp_path), now=T0) is None


def test_release_defaults_to_this_session_not_to_anyone(tmp_path):
    """A caller that forgets rid= must not get the permissive behaviour."""
    claim("weight-6/unrestricted", rid="s1", root=str(tmp_path), now=T0,
          minutes=30)
    monkey = os.environ.get(RUN_ID_ENV)
    os.environ[RUN_ID_ENV] = "somebody-else"
    try:
        assert release("weight-6/unrestricted", root=str(tmp_path), now=T0) is False
        assert read_claim("weight-6/unrestricted", root=str(tmp_path), now=T0)
    finally:
        if monkey is None:
            os.environ.pop(RUN_ID_ENV, None)
        else:
            os.environ[RUN_ID_ENV] = monkey


def test_a_claim_is_held_by_the_session_not_by_the_process(tmp_path, monkeypatch):
    """Every ./qldpc invocation is a new run; one shell is still one session.

    With run identity as the holder, the release that follows a claim from the
    same terminal belongs to a different process and finds nothing -- the
    sequence the docs show then fails for everyone who has not exported the
    environment variable.
    """
    import coordination
    monkeypatch.delenv(SESSION_ENV, raising=False)
    monkeypatch.delenv(RUN_ID_ENV, raising=False)
    runs = iter(["20261008-112521-host-38319", "20261008-112544-host-38327"])
    monkeypatch.setattr(coordination, "run_id", lambda: next(runs))
    rec = claim("weight-6/unrestricted", campaign="bb-1155",
                root=str(tmp_path), now=T0, minutes=30)
    # The session is who may release it; the run is only who wrote the note.
    assert rec["session_id"] == session_id()
    assert rec["run_id"] == "20261008-112521-host-38319"
    assert release("weight-6/unrestricted", root=str(tmp_path), now=T0) is True
    assert read_claim("weight-6/unrestricted", root=str(tmp_path), now=T0) is None


def test_releasing_an_expired_claim_reports_nothing_to_release(tmp_path):
    claim("weight-6/unrestricted", rid="s1", root=str(tmp_path), now=T0,
          minutes=5)
    after = T0 + timedelta(minutes=10)
    assert release("weight-6/unrestricted", rid="s1", root=str(tmp_path),
                   now=after) is False


def test_a_zero_lifetime_claim_is_refused_rather_than_written(tmp_path):
    """0 would write a claim its own author cannot see."""
    with pytest.raises(ValueError):
        claim("weight-6/unrestricted", rid="s1", root=str(tmp_path), now=T0,
              minutes=0)
    assert os.listdir(tmp_path) == []


def test_a_half_written_claim_does_not_break_the_listing(tmp_path):
    """A session killed mid-write leaves a file no reader may choke on."""
    claim("weight-6/unrestricted", rid="s1", root=str(tmp_path), now=T0,
          minutes=30)
    (tmp_path / "weight-8__unrestricted.json").write_text("{ truncated",
                                                           encoding="utf-8")
    assert [c["session_id"] for c in live_claims(root=str(tmp_path), now=T0)] == ["s1"]
    assert read_claim("weight-8/unrestricted", root=str(tmp_path), now=T0) is None


def test_a_claim_from_an_older_version_is_ignored(tmp_path):
    claim("weight-6/unrestricted", rid="s1", root=str(tmp_path), now=T0,
          minutes=30)
    path = tmp_path / "weight-6__unrestricted.json"
    stale = json.loads(path.read_text(encoding="utf-8"))
    stale["claim_version"] = 0
    path.write_text(json.dumps(stale), encoding="utf-8")
    assert read_claim("weight-6/unrestricted", root=str(tmp_path), now=T0) is None
    assert live_claims(root=str(tmp_path), now=T0) == []


def test_the_cell_name_is_a_filename_and_not_a_path(tmp_path):
    """'/' in a cell would otherwise resolve to nothing under claims/."""
    assert cell_slug("weight-6/unrestricted") == "weight-6__unrestricted"
    claim("weight-6/unrestricted", rid="s1", root=str(tmp_path), now=T0)
    assert os.listdir(tmp_path) == ["weight-6__unrestricted.json"]
    with pytest.raises(ValueError):
        cell_slug("   ")


def test_live_claims_are_newest_first_and_skip_the_claims_dir(tmp_path):
    claim("weight-6/unrestricted", rid="s1", root=str(tmp_path), now=T0,
          minutes=30)
    claim("weight-8/unrestricted", rid="s2",
          root=str(tmp_path), now=T0 + timedelta(minutes=1), minutes=30)
    (tmp_path / "notes.txt").write_text("not a claim", encoding="utf-8")
    assert [c["session_id"] for c in live_claims(root=str(tmp_path), now=T0)] == ["s2", "s1"]


def test_reading_claims_in_a_missing_directory_is_empty_not_an_error(tmp_path):
    assert live_claims(root=str(tmp_path / "nope"), now=T0) == []
    assert read_claim("weight-6/unrestricted", root=str(tmp_path / "nope"),
                      now=T0) is None
    assert prune_claims(root=str(tmp_path / "nope"), now=T0) == 0
