"""The reachability campaign asks the dedup oracle before it stages a child (issue #6814).

Two properties are pinned with an injected index, so no board scan, network,
or gh is needed. An exact match (a fingerprint the board or an open PR already
carries) stops the child before the witness search is paid for and stages
nothing. A WL-only match is a probable permutation: the child is staged, the
result and the staged note name the match, and the gate keeps the last word.
With the oracle off or its index empty the save path is unchanged.
"""
import glob
import json
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "kit"))

import dedup_oracle as D  # noqa: E402
import reachability_campaign as RC  # noqa: E402
import submit  # noqa: E402

STEANE = [[0, 1, 3, 4], [1, 2, 4, 5], [3, 4, 5, 6]]


def _child():
    return {"n": 7, "k": 1, "d_ub": 3, "w": 4, "lc": "unrestricted", "wc": "weight-4",
            "checks": {"X": STEANE, "Z": STEANE},
            "parent_n": 9, "parent_file": "codes/9-1-3.json", "parent_d": 3}


def _ident():
    HX, HZ = RC.checks_to_matrices(_child()["checks"], 7)
    return D.identity_matrices(HX, HZ)


def _save(tmp_path, monkeypatch, index):
    monkeypatch.setitem(RC._DEDUP, "index", index)
    return RC._save_one(((7, 1, 3), _child(), str(tmp_path), 200))


def test_an_exact_match_is_skipped_before_the_witness_search(tmp_path, monkeypatch):
    ident = _ident()
    index = [D._as_entry("pr", 4242, "7-1-3.json", 7, 1, 3, ident["fingerprints"], ident["signatures"])]

    def no_search(*a, **k):
        raise AssertionError("the witness search must not run for a known duplicate")
    monkeypatch.setattr(submit, "make_submission", no_search)
    res = _save(tmp_path, monkeypatch, index)
    assert res["ok"] is False
    assert res["dedup"]["kind"] == "exact"
    assert res["dedup"]["names"] == ["pr#4242:7-1-3.json"]
    assert res["dedup"]["matches"][0] == {"source": "pr", "pr": 4242, "name": "7-1-3.json",
                                          "n": 7, "k": 1, "d": 3}
    assert "exact duplicate of pr#4242:7-1-3.json" in res["error"]
    assert glob.glob(str(tmp_path / "*")) == [], "nothing is staged for a duplicate"


def test_a_board_match_is_named_by_source(tmp_path, monkeypatch):
    ident = _ident()
    index = [D._as_entry("board", None, "7-1-3.json", 7, 1, 3, ident["fingerprints"], ident["signatures"])]
    res = _save(tmp_path, monkeypatch, index)
    assert res["ok"] is False
    assert res["dedup"]["names"] == ["board:7-1-3.json"]


def test_a_wl_only_match_is_staged_with_a_note(tmp_path, monkeypatch):
    ident = _ident()
    index = [D._as_entry("board", None, "7-1-3-b.json", 7, 1, 3, {"not-this-fingerprint"}, ident["signatures"])]
    res = _save(tmp_path, monkeypatch, index)
    assert res["ok"] is True
    assert res["dedup"]["kind"] == "wl"
    assert res["dedup"]["names"] == ["board:7-1-3-b.json"]
    assert os.path.exists(res["path"])
    with open(res["path"]) as f:
        doc = json.load(f)
    assert "board:7-1-3-b.json" in doc["provenance"]["notes"]
    assert "dedup_oracle" in doc["provenance"]["notes"]


def test_a_clean_child_stages_as_before(tmp_path, monkeypatch):
    for index in (None, []):
        res = _save(tmp_path, monkeypatch, index)
        assert res["ok"] is True, res
        assert "dedup" not in res
        with open(res["path"]) as f:
            doc = json.load(f)
        assert doc["provenance"]["notes"] == ""
        os.remove(res["path"])
        for stray in glob.glob(str(tmp_path / "*")):
            os.remove(stray)


def test_a_stale_index_entry_without_identity_does_not_match(tmp_path, monkeypatch):
    index = [D._as_entry("board", None, "x.json", 7, 1, 3, set(), set())]
    res = _save(tmp_path, monkeypatch, index)
    assert res["ok"] is True
    assert "dedup" not in res


def test_build_dedup_index_reports_an_empty_open_pr_part(monkeypatch, capsys):
    ident = _ident()
    board_only = [D._as_entry("board", None, "7-1-3.json", 7, 1, 3, ident["fingerprints"], ident["signatures"])]
    seen = {}

    def fake_combined_index(**kw):
        seen.update(kw)
        return board_only
    monkeypatch.setattr(D, "combined_index", fake_combined_index)
    monkeypatch.setattr(RC, "DEDUP_ORACLE", True)
    monkeypatch.setattr(RC, "DEDUP_OPEN_PRS", True)
    monkeypatch.setattr(RC, "DEDUP_REFRESH", True)
    monkeypatch.setattr(RC, "DEDUP_PR_LIMIT", 50)
    index = RC.build_dedup_index()
    assert index is board_only
    assert RC._DEDUP["index"] is board_only
    assert seen == {"include_board": True, "include_open_prs": True, "open_pr_limit": 50, "refresh": True}
    out = capsys.readouterr().out
    assert "1 board entries, 0 open-PR codes" in out
    assert "WARNING" in out and "open-PR index is empty" in out


def test_build_dedup_index_is_quiet_when_open_prs_are_indexed(monkeypatch, capsys):
    ident = _ident()
    index = [D._as_entry("board", None, "a.json", 7, 1, 3, ident["fingerprints"], ident["signatures"]),
             D._as_entry("pr", 7, "b.json", 7, 1, 3, {"fp"}, {"sig"})]
    monkeypatch.setattr(D, "combined_index", lambda **kw: index)
    monkeypatch.setattr(RC, "DEDUP_ORACLE", True)
    monkeypatch.setattr(RC, "DEDUP_OPEN_PRS", True)
    assert RC.build_dedup_index() is index
    out = capsys.readouterr().out
    assert "1 board entries, 1 open-PR codes" in out
    assert "WARNING" not in out


def test_build_dedup_index_honours_the_off_switch(monkeypatch, capsys):
    monkeypatch.setattr(D, "combined_index", lambda **kw: (_ for _ in ()).throw(AssertionError("not called")))
    monkeypatch.setattr(RC, "DEDUP_ORACLE", False)
    assert RC.build_dedup_index() is None
    assert RC._DEDUP["index"] is None
    assert "off (DEDUP_ORACLE=0)" in capsys.readouterr().out


def test_save_init_hands_the_index_to_a_worker(monkeypatch):
    monkeypatch.setitem(RC._DEDUP, "index", None)
    marker = [D._as_entry("board", None, "m.json", 7, 1, 3, {"fp"}, {"sig"})]
    RC._save_init(marker)
    assert RC._DEDUP["index"] is marker


def test_a_save_pool_worker_sees_the_index(tmp_path):
    # the production wiring: the index travels to the save workers through the
    # pool initializer, so a duplicate is refused inside the subprocess too
    import multiprocessing as mp
    ident = _ident()
    index = [D._as_entry("pr", 11, "7-1-3.json", 7, 1, 3, ident["fingerprints"], ident["signatures"])]
    with mp.Pool(processes=1, initializer=RC._save_init, initargs=(index,)) as pool:
        res = pool.map(RC._save_one, [((7, 1, 3), _child(), str(tmp_path), 200)])[0]
    assert res["ok"] is False
    assert res["dedup"]["names"] == ["pr#11:7-1-3.json"]
    assert glob.glob(str(tmp_path / "*")) == []


def test_log_dedup_appends_json_lines(tmp_path, monkeypatch):
    path = tmp_path / "dedup.jsonl"
    monkeypatch.setattr(RC, "OUT_DEDUP", str(path))
    RC.log_dedup({"event": "skipped", "n": 7})
    RC.log_dedup({"event": "flagged", "n": 8})
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert lines == [{"event": "skipped", "n": 7}, {"event": "flagged", "n": 8}]


def test_log_dedup_never_raises(monkeypatch):
    monkeypatch.setattr(RC, "OUT_DEDUP", "/nonexistent-dir/dedup.jsonl")
    RC.log_dedup({"event": "skipped"})


def test_identity_used_by_the_check_is_the_gates_own():
    # the oracle index carries the gate's fingerprint sets; the campaign checks the
    # child's own fingerprint against them, which is prescreen.identity's value
    import prescreen as P
    HX, HZ = RC.checks_to_matrices(_child()["checks"], 7)
    ident = D.identity_matrices(HX, HZ)
    own = P.identity(HX, HZ)
    assert ident["fingerprints"] == {own["fingerprint"]}
    assert ident["signatures"] == {own["signature"]}
    assert np.asarray(HX).shape == (3, 7)
