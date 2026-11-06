"""The open-PR duplicate check (issue #4107).

Two PRs that each add one presentation of the same code pass verify_all
alone, so the check compares a PR's entries with every other open PR's and
refuses the later filing. GitHub is faked here: the tests cover the
identities, the pairing, the verdict, and the plumbing around a temp repo.
"""
import json
import os
import subprocess

import check_pr_duplicates as D
import pytest
import validation_gate as G


def _four_one_two(swapped=False):
    HX, HZ = [[1, 1, 1, 1]], [[1, 1, 0, 0], [0, 0, 1, 1]]
    if swapped:
        HX, HZ = HZ, HX
    return G.css_doc(f"[[4,1,2]] {'swapped' if swapped else 'as filed'}", HX, HZ, 2,
                     construction="test fixture", confidence="upper_bound")


def test_an_xz_swap_shares_a_fingerprint_through_its_hadamard_image():
    a, b = D.identities(_four_one_two()), D.identities(_four_one_two(swapped=True))
    assert a[0] & b[0] and a[1] & b[1]
    s = D.identities(G.shor())
    assert not (a[0] & s[0]) and not (a[1] & s[1])


def test_only_board_entries_count():
    assert D.is_entry("codes/4-1-2.json")
    for p in ("codes/README.md", "codes/sub/4-1-2.json", "notes/4-1-2.md", "verify/fixtures/5-1-3.json"):
        assert not D.is_entry(p)


def test_collisions_pair_entries_and_skip_the_same_path():
    a, b = D.identities(_four_one_two()), D.identities(_four_one_two(swapped=True))
    s = D.identities(G.shor())
    found = D.collisions({"codes/4-1-2.json": a},
                         [(10, "codes/4-1-2-b.json", b), (11, "codes/4-1-2.json", b),
                          (12, "codes/9-1-3.json", s)])
    assert found == [{"kind": "identical", "path": "codes/4-1-2.json", "number": 10,
                      "other_path": "codes/4-1-2-b.json"}]


def test_a_shared_signature_alone_is_possible():
    found = D.collisions({"codes/x.json": ({"fa"}, {"s"})}, [(5, "codes/y.json", ({"fb"}, {"s"}))])
    assert [c["kind"] for c in found] == ["possible"]


def test_the_later_filing_is_refused_and_the_earlier_warned():
    found = [{"kind": "identical", "path": "codes/4-1-2.json", "number": 10,
              "other_path": "codes/4-1-2-b.json"}]
    code, lines = D.verdict(found, 20, {10: {"author": "a"}})
    assert code == 1 and lines[0].startswith("::error::") and "#10" in lines[0]
    found[0]["number"] = 30
    code, lines = D.verdict(found, 20, {30: {"author": "a"}})
    assert code == 0 and lines[0].startswith("::warning::") and "#30" in lines[0]
    found[0].update(kind="possible", number=10)
    code, lines = D.verdict(found, 20, {10: {"author": "a"}})
    assert code == 0 and "Weisfeiler-Leman" in lines[0]
    assert D.verdict([], 20, {}) == (0, [])


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    """Build a repo whose main holds the Shor code and whose pr branch adds the [[4,1,2]] entry."""
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "codes"))
    with open(os.path.join(root, "codes", "9-1-3.json"), "w") as f:
        json.dump(G.shor(), f)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "checkout", "-q", "-b", "pr")
    with open(os.path.join(root, "codes", "4-1-2.json"), "w") as f:
        json.dump(_four_one_two(), f)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "pr")
    return root


def _fake_github(monkeypatch, prs, entries):
    """Stand in for gh and the pull-ref fetch.

    `prs` maps PR number to {author, title}; `entries` maps PR number to
    {codes path: document}. Returns the numbers fetched and dropped.
    """
    calls = {"fetched": [], "dropped": []}
    monkeypatch.setattr(D, "open_prs", lambda repo, exclude: {n: p for n, p in prs.items() if n != exclude})
    monkeypatch.setattr(D, "pr_entries", lambda repo, n: sorted(entries.get(n, {})))
    monkeypatch.setattr(D, "fetch_heads", lambda root, ns: calls["fetched"].extend(ns))
    monkeypatch.setattr(D, "drop_heads", lambda root, ns: calls["dropped"].extend(ns))
    monkeypatch.setattr(D, "pr_doc", lambda root, n, path: entries[n][path])
    return calls


_ARGS = ["--base", "main", "--repo", "o/r", "--pr-number", "20"]


def test_main_refuses_the_later_pr(repo, monkeypatch, capsys):
    calls = _fake_github(monkeypatch,
                         {10: {"author": "a", "title": "t"}, 30: {"author": "b", "title": "t"}},
                         {10: {"codes/4-1-2-b.json": _four_one_two(swapped=True)},
                          30: {"codes/9-1-3.json": G.shor()}})
    rc = D.main(["--root", repo, *_ARGS])
    out = capsys.readouterr().out
    assert rc == 1 and "::error::codes/4-1-2.json" in out and "#10" in out, out
    assert calls["fetched"] == [10, 30] and calls["dropped"] == [10, 30]


def test_main_warns_when_this_pr_is_the_earlier_filing(repo, monkeypatch, capsys):
    _fake_github(monkeypatch, {30: {"author": "b", "title": "t"}},
                 {30: {"codes/4-1-2-b.json": _four_one_two(swapped=True)}})
    rc = D.main(["--root", repo, *_ARGS])
    out = capsys.readouterr().out
    assert rc == 0 and "::warning::codes/4-1-2.json" in out and "#30" in out, out


def test_main_passes_when_no_open_pr_carries_the_code(repo, monkeypatch, capsys):
    _fake_github(monkeypatch, {30: {"author": "b", "title": "t"}, 31: {"author": "c", "title": "t"}},
                 {30: {"codes/9-1-3.json": G.shor()}})
    rc = D.main(["--root", repo, *_ARGS])
    out = capsys.readouterr().out
    assert rc == 0 and "no entry of this PR matches" in out, out


def test_main_passes_with_a_warning_when_github_is_unreachable(repo, monkeypatch, capsys):
    def boom(repo, exclude):
        raise subprocess.CalledProcessError(1, ["gh"], stderr="HTTP 503")
    monkeypatch.setattr(D, "open_prs", boom)
    rc = D.main(["--root", repo, *_ARGS])
    out = capsys.readouterr().out
    assert rc == 0 and "::warning::could not list" in out and "HTTP 503" in out, out


def test_main_has_nothing_to_compare_without_a_changed_entry(repo, monkeypatch, capsys):
    monkeypatch.setattr(D, "open_prs", lambda repo, exclude: pytest.fail("gh must not be called"))
    rc = D.main(["--root", repo, "--base", "HEAD", "--repo", "o/r", "--pr-number", "20"])
    assert rc == 0 and "nothing to compare" in capsys.readouterr().out
