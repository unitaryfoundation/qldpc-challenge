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
    monkeypatch.setattr(Q, "verify", lambda doc, *a, **k: (calls.append(1), real(doc, *a, **k))[1])
    return calls


def fresh(code_dir):
    """Run a pass with the in-process snapshot cleared."""
    Q._BOARD_CACHE.clear()
    return Q.board_reports(str(code_dir))


def shape(reports):
    return [(e["slug"], e["report"], e["load_error"]) for e in reports]


def test_a_hit_is_what_a_fresh_pass_would_have_computed(board, tmp_path, monkeypatch):
    """The whole argument for caching this is that it is deterministic."""
    monkeypatch.setenv("QLDPC_BOARD_CACHE", "")  # no memo at all
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
    Q._CLOSURE_DIGEST.clear()  # as a new process would start
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


def test_a_changed_validator_closure_retires_every_entry(board, memo, monkeypatch, tmp_path):
    """codes/ can be byte-identical while the verifier is not.

    A branch switch, a re-pin or an unmerged local edit all leave the board
    alone, and a board-only key would then answer with reports from a
    verifier that is no longer the one being asked, letting unmerged logic
    inside the hash-pinned gate decide dedup and novelty.
    """
    fresh(board)
    calls = count_passes(monkeypatch)
    Q._CLOSURE_DIGEST.clear()
    monkeypatch.setattr(Q, "validator_closure_digest", lambda *a, **k: "a-different-closure")
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
    Q._CLOSURE_DIGEST.clear()  # as the job's next process would start
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


def test_two_entries_with_the_same_bytes_share_one_memo_entry(tmp_path, memo, monkeypatch):
    """The key is the content, so a byte-identical copy is already answered.

    Worth pinning rather than discovering: the report does not depend on the
    path or the slug, which are attached outside the memo. It does depend on
    more than the entry's own bytes when the entry names another one (a
    benchmark baseline, an architecture partner, a relabeling's parent),
    which verify() reads from its own checkout's codes/; board_cache_dir
    says what that asks of the processes that share a memo.
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


def test_a_pooled_pass_gives_the_serial_reports_and_fills_the_memo(tmp_path, monkeypatch):
    """board_reports(jobs=N) verifies the misses in worker processes (issue #5578).

    A worker verifies one file's bytes; the parent assembles the entries in
    path order and writes the memo, so what a reader gets, and what the memo
    holds, is what the serial pass produces.
    """
    import shutil

    board = tmp_path / "codes"
    board.mkdir()
    for i in range(3):
        doc = json.loads(open(FIXTURE, encoding="utf-8").read())
        doc["name"] = f"copy {i}"
        (board / f"72-6-6-{i}.json").write_text(json.dumps(doc))
    memo_a, memo_b = tmp_path / "memo-a", tmp_path / "memo-b"
    monkeypatch.setenv(Q.BOARD_CACHE_ENV, str(memo_a))
    Q._BOARD_CACHE.clear()
    serial = Q.board_reports(str(board))
    monkeypatch.setenv(Q.BOARD_CACHE_ENV, str(memo_b))
    Q._BOARD_CACHE.clear()
    pooled = Q.board_reports(str(board), jobs=2)
    assert [e["slug"] for e in pooled] == [e["slug"] for e in serial]
    assert [e["report"] for e in pooled] == [e["report"] for e in serial]
    written = sorted(p.name for p in memo_b.rglob("*.json"))
    assert written == sorted(p.name for p in memo_a.rglob("*.json")) and len(written) == 3
    shutil.rmtree(memo_b)


# The key covers the entries verify() reads for an entry (issue #7253), so a
# memo can be carried from one state of the board to another: runs on main do.


def _relabel_board(tmp_path):
    """Return a board with a parent entry and a child that declares it as its Clifford relabeling."""
    d = tmp_path / "codes"
    d.mkdir()
    shutil.copy(FIXTURE, d / "72-6-6.json")
    child = json.loads(open(FIXTURE, encoding="utf-8").read())
    child["name"] = "relabeling of the fixture"
    child.setdefault("provenance", {})["clifford_relabel_of"] = "72-6-6"
    (d / "72-6-6-b.json").write_text(json.dumps(child))
    return d


def test_partner_slugs_name_what_verify_reads():
    assert Q._partner_slugs({"n": 1}) == []
    assert Q._partner_slugs("not a dict") == []
    doc = {
        "benchmark": {"surface_baseline": {"slug": "9-1-3"}},
        "architecture": {"gadgets": [{"partner": "25-1-5"}, {"operation": "x"}, "junk"]},
        "provenance": {"clifford_relabel_of": "7-1-3"},
    }
    assert Q._partner_slugs(doc) == ["25-1-5", "7-1-3", "9-1-3"]
    assert Q._partner_slugs({"benchmark": {"surface_baseline": {"slug": 7}}}) == []
    assert Q._partner_slugs({"provenance": {"clifford_relabel_of": None}}) == []


def test_a_changed_partner_retires_the_entry_that_reads_it(tmp_path, memo, monkeypatch):
    """The verdict on a relabeling reads its parent, so the parent's bytes are in its key."""
    board = _relabel_board(tmp_path)
    # verify() reads the parent from this checkout's codes/; the scratch
    # board stands in for it, for the verdict and for the key alike
    monkeypatch.setattr(Q, "_checkout_codes_dir", lambda: str(board))
    fresh(board)
    with open(board / "72-6-6-b.json", "rb") as f:
        child = f.read()
    key_before = Q._memo_path(str(memo), child)
    parent = board / "72-6-6.json"
    doc = json.loads(parent.read_text())
    doc["name"] = "the parent, edited"
    parent.write_text(json.dumps(doc))
    assert Q._memo_path(str(memo), child) != key_before, "the child's key must move with its parent's bytes"
    calls = count_passes(monkeypatch)
    fresh(board)
    assert len(calls) == 2, "the edited parent and the child that reads it are both re-verified"
    calls.clear()
    fresh(board)
    assert calls == []


def test_an_entry_without_partners_is_keyed_on_its_own_bytes(board, memo):
    with open(board / "72-6-6.json", "rb") as f:
        data = f.read()
    assert Q._partner_bytes(data) == []
    import hashlib

    h = hashlib.sha256()
    h.update(Q.validator_closure_digest().encode("utf-8") + b"\0" + data)
    key = h.hexdigest()
    assert Q._memo_path(str(memo), data) == os.path.join(str(memo), key[:2], key[2:] + ".json")


def test_an_absent_partner_is_part_of_the_key(tmp_path, memo):
    child = json.dumps({"name": "orphan", "provenance": {"clifford_relabel_of": "no-such-entry-0-0-0"}}).encode()
    assert Q._partner_bytes(child) == [("no-such-entry-0-0-0", None)]
    assert Q._memo_path(str(memo), child) != Q._memo_path(str(memo), child.replace(b"orphan", b"orphan2"))


def test_a_version_one_memo_is_a_miss(board, memo, monkeypatch):
    """The key changed meaning, so a file the old key would have answered from is not read."""
    fresh(board)
    with open(board / "72-6-6.json", "rb") as f:
        data = f.read()
    path = Q._memo_path(str(memo), data)
    memo_doc = json.load(open(path))
    memo_doc["memo_version"] = 1
    json.dump(memo_doc, open(path, "w"))
    calls = count_passes(monkeypatch)
    fresh(board)
    assert len(calls) == 1
