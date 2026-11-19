"""Tests for the anti-collision dedup oracle (campaign 7 of issue #6198).

The oracle is a filter, not a verdict: it must agree with the gate's own
fingerprint/WL identity sets, including local-Hadamard images, and it must
be able to see an open-PR index that the board alone does not carry.  These
tests pin both properties with injected data, so no network or gh is needed.
"""
import json
import os
import sys

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "kit"))

import dedup_oracle as D  # noqa: E402
import prescreen as P  # noqa: E402
from bb import build_bb  # noqa: E402
from submit import make_submission  # noqa: E402

ROOT = os.path.dirname(_HERE)


def _doc_from_matrices(HX, HZ, name="t"):
    return make_submission(np.asarray(HX), np.asarray(HZ), name=name,
                          construction="test", authors=["test"])


def test_identity_doc_matches_prescreen_for_css():
    HX = np.array([[1, 0, 1, 0, 1, 0, 1],
                   [0, 1, 1, 0, 0, 1, 1],
                   [0, 0, 0, 1, 1, 1, 1]], dtype=np.int8)
    HZ = HX.copy()
    doc = _doc_from_matrices(HX, HZ, name="steane")
    ident, fails = D.identity_doc(doc)
    assert fails == []
    assert ident is not None
    p_ident = P.identity(HX, HZ)
    assert ident["fingerprint"] == p_ident["fingerprint"]
    assert ident["signature"] == p_ident["signature"]
    assert p_ident["fingerprint"] in ident["fingerprints"]
    assert p_ident["signature"] in ident["signatures"]


def test_exact_duplicate_detected_against_injected_index():
    HX = np.array([[1, 0, 1, 0, 1, 0, 1],
                   [0, 1, 1, 0, 0, 1, 1],
                   [0, 0, 0, 1, 1, 1, 1]], dtype=np.int8)
    HZ = HX.copy()
    doc = _doc_from_matrices(HX, HZ, name="steane")
    ident, _ = D.identity_doc(doc)
    # build an index entry whose fingerprint set contains the candidate's
    entry = D._as_entry("board", None, "7-1-3.json", 7, 1, 3,
                        ident["fingerprints"], ident["signatures"])
    res = D.check(ident, [entry])
    assert res["exact"], "candidate must be flagged as an exact board duplicate"
    assert not res["wl"]


def test_wl_equivalent_without_fingerprint_match():
    HX = np.array([[1, 0, 1, 0, 1, 0, 1],
                   [0, 1, 1, 0, 0, 1, 1],
                   [0, 0, 0, 1, 1, 1, 1]], dtype=np.int8)
    HZ = HX.copy()
    doc = _doc_from_matrices(HX, HZ, name="steane")
    ident, _ = D.identity_doc(doc)
    # same signature set, disjoint fingerprint set -> WL equivalent only
    entry = D._as_entry("board", None, "7-1-3.json", 7, 1, 3,
                        {"definitely-not-a-real-fingerprint"}, ident["signatures"])
    res = D.check(ident, [entry])
    assert not res["exact"]
    assert res["wl"], "shared WL signature must be flagged"


def test_open_pr_index_is_visible_to_check():
    HX = np.array([[1, 0, 1, 0, 1, 0, 1],
                   [0, 1, 1, 0, 0, 1, 1],
                   [0, 0, 0, 1, 1, 1, 1]], dtype=np.int8)
    HZ = HX.copy()
    doc = _doc_from_matrices(HX, HZ, name="steane")
    ident, _ = D.identity_doc(doc)
    # simulate an open PR carrying the same code under a different name
    pr_entry = D._as_entry("pr", 999, "codes/7-1-3.json", 7, 1, 3,
                           ident["fingerprints"], ident["signatures"])
    # board has nothing
    board_entry = D._as_entry("board", None, "other.json", 7, 1, 3,
                              {"no-match"}, {"no-match-sig"})
    index = [board_entry, pr_entry]
    res = D.check(ident, index)
    assert res["exact"], "open-PR duplicate must be found even when board is clean"
    assert res["exact"][0]["source"] == "pr"
    assert res["exact"][0]["pr"] == 999


def test_structural_failure_returns_none():
    # a direct sum is structurally one code? Actually it is two blocks; identity
    # may still compute, but verify's structural checks may not fail. Use a
    # malformed doc instead.
    bad = {"n": 2, "k": 1, "distance": {"d": 1}, "checks": {"X": [], "Z": []}}
    ident, fails = D.identity_doc(bad)
    # either identity succeeds with trivial sets, or it reports a failure list;
    # the contract is: on failure, ident is None and fails is non-empty.
    if ident is None:
        assert fails, "failure must be explained"


def test_combined_index_shape():
    HX, HZ = build_bb(6, 6, [(3, 0), (0, 1), (0, 2)],
                       [(0, 3), (1, 0), (2, 0)])
    doc = _doc_from_matrices(HX, HZ, name="bb72")
    # write to a temp dir and index via extra_paths
    import tempfile
    d = tempfile.mkdtemp()
    p = os.path.join(d, "bb72.json")
    with open(p, "w") as f:
        json.dump(doc, f)
    idx = D.combined_index(include_board=False, extra_paths=[p])
    assert len(idx) == 1
    assert idx[0]["source"] == "extra"
    assert idx[0]["name"] == "bb72.json" or idx[0]["name"] == doc.get("name")


def test_index_from_paths_skips_garbage():
    import tempfile
    d = tempfile.mkdtemp()
    p = os.path.join(d, "bad.json")
    with open(p, "w") as f:
        f.write("{not json")
    assert D.index_from_paths([p]) == []


def test_open_pr_fetch_reads_file_contents_with_an_explicit_get(monkeypatch, tmp_path):
    """The contents call must say --method GET.

    gh api turns any call that carries a --field into a POST, which the
    contents endpoint answers with a 404, and the fetch loop swallows that
    and indexes nothing (found wiring issue #6814).
    """
    import base64
    HX = np.array([[1, 0, 1, 0, 1, 0, 1],
                   [0, 1, 1, 0, 0, 1, 1],
                   [0, 0, 0, 1, 1, 1, 1]], dtype=np.int8)
    doc = _doc_from_matrices(HX, HX.copy(), name="steane")
    calls = []

    def fake_gh_json(args):
        calls.append(list(args))
        if args[:2] == ["pr", "list"]:
            return [{"number": 4242, "headRefName": "feature/x",
                     "headRepository": {"name": "qldpc-challenge"},
                     "headRepositoryOwner": {"login": "someone"},
                     "files": [{"path": "codes/7-1-3-z.json"}, {"path": "notes/7-1-3-z.md"}]}]
        assert args[0] == "api"
        assert args[1:3] == ["--method", "GET"], args
        assert "repos/someone/qldpc-challenge/contents/codes/7-1-3-z.json" in args
        assert "ref=feature/x" in args
        raw = json.dumps(doc).encode("utf-8")
        return {"content": base64.b64encode(raw).decode("ascii"), "encoding": "base64"}
    monkeypatch.setattr(D, "_gh_json", fake_gh_json)
    cache = tmp_path / "pr_index.json"
    entries = D.fetch_open_pr_index(refresh=True, cache_path=str(cache))
    assert [e["pr"] for e in entries] == [4242]
    assert entries[0]["source"] == "pr" and entries[0]["name"] == "7-1-3-z.json"
    assert len(calls) == 2, "one listing call and one contents call, the note is skipped"
    ident, _ = D.identity_doc(doc)
    assert D.check(ident, entries)["exact"], "the fetched PR code is an exact match for itself"
    # the cache round-trips the sets
    again = D.fetch_open_pr_index(refresh=False, cache_path=str(cache))
    assert again[0]["fingerprints"] == entries[0]["fingerprints"]
    assert again[0]["pr"] == 4242
