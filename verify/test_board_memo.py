"""The board memo survives the process, and only when it still means the same thing.

`board_reports` was memoized in-process only, so every new process paid a
full structural pass over the board before its first candidate: 102 s over
1,778 entries, growing with the board (issue #2582). The memo now lives on
disk as well.

What has to hold for that to be safe, and is pinned here one condition at a
time: a hit is byte-identical to a fresh pass, a key covers the validator and
not just the board, one changed entry re-verifies one entry rather than the
board, and CI reads no memo except one the job itself named.
"""
import json
import os
import shutil

import pytest
import qldpc_verify as Q

_HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(_HERE, "fixtures", "72-6-6.json")


@pytest.fixture
def board(tmp_path):
    """Two entries whose bytes differ, since the key is the bytes.

    A second verbatim copy of the fixture would share the first's memo entry
    and verify nothing, which is correct but makes every call count below
    read as one entry.
    """
    d = tmp_path / "codes"
    d.mkdir()
    shutil.copy(FIXTURE, d / "72-6-6.json")
    doc = json.loads(open(FIXTURE, encoding="utf-8").read())
    doc["name"] = "a second entry with different bytes"
    (d / "99-9-9.json").write_text(json.dumps(doc))
    return d


@pytest.fixture
def memo(tmp_path, monkeypatch):
    """Point the disk memo at a scratch directory and turn it on."""
    cache = tmp_path / "boardcache"
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("QLDPC_BOARD_CACHE", str(cache))
    return cache


def count_passes(monkeypatch):
    """Count structural verifications, so a hit is observable and not inferred."""
    calls = []
    real = Q.verify
    monkeypatch.setattr(
        Q, "verify",
        lambda doc, *a, **k: (calls.append(1), real(doc, *a, **k))[1])
    return calls


def fresh(code_dir):
    """Run a pass with the in-process snapshot cleared."""
    Q._BOARD_CACHE.clear()
    return Q.board_reports(str(code_dir))


def shape(reports):
    return [(e["slug"], e["report"], e["load_error"]) for e in reports]


def test_a_hit_is_what_a_fresh_pass_would_have_computed(board, tmp_path,
                                                        monkeypatch):
    """The whole argument for caching this is that it is deterministic."""
    monkeypatch.setenv("QLDPC_BOARD_CACHE", "")      # no memo at all
    want = shape(fresh(board))

    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("QLDPC_BOARD_CACHE", str(tmp_path / "boardcache"))
    calls = count_passes(monkeypatch)
    assert shape(fresh(board)) == want, "a cold memo must not change the answer"
    assert len(calls) == 2, "the pass with a cold memo verifies both entries"
    assert shape(fresh(board)) == want, "and a warm one must not either"
    assert len(calls) == 2, "the second pass answers from disk"


def test_the_memo_outlives_the_process_memo(board, memo, monkeypatch):
    fresh(board)
    calls = count_passes(monkeypatch)
    Q._CLOSURE_DIGEST.clear()                  # as a new process would start
    fresh(board)
    assert calls == [], "a warm memo should verify nothing"


def test_one_changed_entry_reverifies_one_entry(board, memo, monkeypatch):
    """Why the key is per entry and not the whole-board digest.

    The in-process memo keys on every board byte, so one merged submission
    re-arms all 1,778 entries. That is the specific reason it cannot amortise
    across a campaign.
    """
    fresh(board)
    p = board / "99-9-9.json"
    doc = json.loads(p.read_text())
    doc["k"] = 5
    p.write_text(json.dumps(doc))
    calls = count_passes(monkeypatch)
    out = fresh(board)
    assert len(calls) == 1, "the untouched entry must still come from the memo"
    changed = next(e for e in out if e["slug"] == "99-9-9")
    assert changed["doc"]["k"] == 5 and not changed["report"]["ok"]


def test_a_changed_validator_closure_retires_every_entry(board, memo, monkeypatch,
                                                         tmp_path):
    """codes/ can be byte-identical while the verifier is not.

    A branch switch, a re-pin or an unmerged local edit all leave the board
    alone, and a board-only key would then answer with reports from a
    verifier that is no longer the one being asked, letting unmerged logic
    inside the hash-pinned gate decide dedup and novelty.
    """
    fresh(board)
    calls = count_passes(monkeypatch)
    Q._CLOSURE_DIGEST.clear()
    monkeypatch.setattr(Q, "validator_closure_digest",
                        lambda *a, **k: "a-different-closure")
    fresh(board)
    assert len(calls) == 2, "a different closure must not reuse its reports"


def test_the_closure_digest_follows_the_manifest(tmp_path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps({"files": {"verify/x.py": "aa", "verify/y.py": "bb"}}))
    b.write_text(json.dumps({"files": {"verify/x.py": "aa", "verify/y.py": "cc"}}))
    Q._CLOSURE_DIGEST.clear()
    da = Q.validator_closure_digest(str(a))
    db = Q.validator_closure_digest(str(b))
    assert da != db and len(da) == 64
    assert Q.validator_closure_digest(str(tmp_path / "gone.json")) == "no-manifest"


def test_ci_has_no_memo_it_was_not_given(board, monkeypatch):
    """Keep a runner answering from the board in front of it.

    With the variable unset a checkout has its default memo and CI has none,
    so nothing a runner happens to find is ever read.
    """
    monkeypatch.delenv("QLDPC_BOARD_CACHE", raising=False)
    monkeypatch.delenv("CI", raising=False)
    assert Q.board_cache_dir().endswith(Q.BOARD_CACHE_DIRNAME)
    monkeypatch.setenv("CI", "true")
    assert Q.board_cache_dir() is None
    calls = count_passes(monkeypatch)
    fresh(board)
    fresh(board)
    assert len(calls) == 4, "with no memo, every pass verifies every entry"


def test_a_job_can_point_its_processes_at_one_memo(board, memo, monkeypatch):
    """One job, several processes, one pass (issue #5578).

    The sweep and the gate are two processes over the same board, and each
    used to verify all of it. A directory the job names is read in CI too:
    the first pass fills it and the next process answers from it.
    """
    monkeypatch.setenv("CI", "true")
    assert Q.board_cache_dir() == str(memo)
    calls = count_passes(monkeypatch)
    want = shape(fresh(board))
    assert len(calls) == 2, "the job's first pass verifies both entries"
    Q._CLOSURE_DIGEST.clear()                  # as the job's next process would start
    assert shape(fresh(board)) == want
    assert len(calls) == 2, "and its second pass verifies nothing"


@pytest.mark.parametrize("ci", [None, "true"])
def test_an_empty_value_turns_the_memo_off_everywhere(board, monkeypatch, ci):
    """What conftest.py relies on to keep the suite hermetic, in CI or out of it."""
    if ci is None:
        monkeypatch.delenv("CI", raising=False)
    else:
        monkeypatch.setenv("CI", ci)
    monkeypatch.setenv("QLDPC_BOARD_CACHE", "")
    assert Q.board_cache_dir() is None


def test_an_unreadable_entry_is_a_miss_and_not_a_crash(board, memo, monkeypatch):
    fresh(board)
    with open(board / "72-6-6.json", "rb") as f:
        data = f.read()
    with open(Q._memo_path(str(memo), data), "w") as f:
        f.write('{"memo_version": 1, "repo')
    calls = count_passes(monkeypatch)
    out = fresh(board)
    assert len(calls) == 1
    assert next(e for e in out if e["slug"] == "72-6-6")["report"]["ok"]


def test_a_broken_board_file_is_cached_as_the_error_it_is(board, memo, monkeypatch):
    (board / "broken.json").write_text("{")
    out = fresh(board)
    bad = next(e for e in out if e["slug"] == "broken")
    assert bad["report"] is None and "JSONDecodeError" in bad["load_error"]
    calls = count_passes(monkeypatch)
    again = fresh(board)
    assert calls == [], "a recorded parse failure is an answer, not a retry"
    assert shape(again) == shape(out)


def test_two_entries_with_the_same_bytes_share_one_memo_entry(tmp_path, memo,
                                                              monkeypatch):
    """The key is the content, so a byte-identical copy is already answered.

    Worth pinning rather than discovering: the report depends on the bytes
    alone, since path and slug are attached outside the memo and verify()
    reads only the parsed document.
    """
    d = tmp_path / "codes"
    d.mkdir()
    shutil.copy(FIXTURE, d / "72-6-6.json")
    shutil.copy(FIXTURE, d / "copy.json")
    calls = count_passes(monkeypatch)
    out = fresh(d)
    assert len(calls) == 1
    a, b = (e for e in out)
    assert a["slug"] != b["slug"] and a["report"] == b["report"]
