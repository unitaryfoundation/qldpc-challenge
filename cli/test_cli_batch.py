"""`qldpc submit-batch` (issue #7449): dedup, gate, and file a batch, one PR per code.

The batch runs each survivor through `submit` with the shared flags, so these
tests exercise the real code tier search at a small budget on the board's own
small entries, and stub the board lookups and the PR opener, which are the
two things a test must not do for real: load the whole board, or push.
"""

import json
import os

import numpy as np
import pytest
import qldpc
from qldpc_verify import _matrix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAST = ["--trials", "300", "--fast-trials", "0"]


def _npz(tmp, slug, name=None, perm=None):
    doc = json.load(open(os.path.join(ROOT, "codes", f"{slug}.json")))
    n = doc["n"]
    hx, hz = _matrix(doc["checks"]["X"], n), _matrix(doc["checks"]["Z"], n)
    if perm is not None:
        hx, hz = hx[:, perm], hz[:, perm]
    path = tmp / f"{name or slug}.npz"
    np.savez(path, hx=hx, hz=hz)
    return str(path)


@pytest.fixture(autouse=True)
def _no_board(monkeypatch):
    monkeypatch.setattr(qldpc, "_load_board_entries", lambda: [])
    monkeypatch.setattr(qldpc, "_board_identities", lambda: ([], lambda rep: (set(), set())))
    monkeypatch.setattr(qldpc, "_batch_index", lambda args: [])


def _record(capsys):
    captured = capsys.readouterr()
    assert captured.out.strip().startswith("{") and captured.out.count("\n{") == 0
    return json.loads(captured.out), captured.err


def _by_path(record):
    return {os.path.basename(row["path"]): row for row in record["candidates"]}


def test_batch_dedups_inside_the_batch_and_writes_the_rest(tmp_path, capsys):
    a = _npz(tmp_path, "12-4-2")
    same = _npz(tmp_path, "12-4-2", name="copy")
    rng = np.random.default_rng(7)
    permuted = _npz(tmp_path, "12-4-2", name="permuted", perm=rng.permutation(12))
    other = _npz(tmp_path, "7-1-3")
    out = str(tmp_path / "codes")
    rc = qldpc.main(["submit-batch", a, same, permuted, other, "--authors", "@me", "--out", out, "--json", *FAST])
    record, err = _record(capsys)
    rows = _by_path(record)
    assert rows["copy.npz"]["status"] == "duplicate" and rows["copy.npz"]["duplicate_of"]["kind"] == "exact"
    assert rows["permuted.npz"]["status"] == "duplicate" and rows["permuted.npz"]["duplicate_of"]["kind"] == "wl"
    assert rows["copy.npz"]["duplicate_of"]["path"] == a
    assert rows["12-4-2.npz"]["status"] == "written" and rows["12-4-2.npz"]["slug"] == "12-4-2"
    assert rows["7-1-3.npz"]["status"] == "written" and (rows["7-1-3.npz"]["n"], rows["7-1-3.npz"]["k"]) == (7, 1)
    assert rows["12-4-2.npz"]["w"] == 6 and rows["12-4-2.npz"]["next_steps"]
    assert record["counts"] == {"duplicate": 2, "written": 2}
    assert rc == 0 and record["ok"] and record["stage"] == "done" and not record["stopped_early"]
    assert sorted(os.listdir(out)) == ["12-4-2.json", "7-1-3.json"]
    assert "verifying" in err  # every step's prose went to stderr


def test_keep_wl_matches_files_the_probable_permutation(tmp_path, capsys):
    a = _npz(tmp_path, "12-4-2")
    permuted = _npz(tmp_path, "12-4-2", name="permuted", perm=np.random.default_rng(3).permutation(12))
    out = str(tmp_path / "codes")
    # a dry run: with files written, the second would meet submit's own
    # revision check on codes/12-4-2.json first (the same slug, another code)
    argv = ["submit-batch", a, permuted, "--authors", "@me", "--out", out, "--json", "--keep-wl-matches", "--dry-run"]
    rc = qldpc.main(argv + FAST)
    record, _ = _record(capsys)
    rows = _by_path(record)
    # gated like any other candidate, then dropped: the same (n, k, d, w) as the first
    assert rows["12-4-2.npz"]["status"] == "dry-run"
    assert rows["permuted.npz"]["status"] == "parameter-tie"
    assert rows["permuted.npz"]["duplicate_of"] == {"path": a, "kind": "parameters", "axes": [12, 4, 2, 6]}
    assert rc == 0 and record["counts"] == {"dry-run": 1, "parameter-tie": 1}


def test_dry_run_gates_everything_and_writes_nothing(tmp_path, capsys):
    a = _npz(tmp_path, "12-4-2")
    b = _npz(tmp_path, "7-1-3")
    out = str(tmp_path / "codes")
    rc = qldpc.main(["submit-batch", a, b, "--authors", "@me", "--out", out, "--json", "--dry-run", *FAST])
    record, _ = _record(capsys)
    assert rc == 0 and record["counts"] == {"dry-run": 2}
    assert all(row["submit"]["would_write"] for row in record["candidates"])
    assert not os.path.exists(out)


def test_a_bad_file_is_one_error_row_and_the_batch_goes_on(tmp_path, capsys):
    bad = tmp_path / "bad.npz"
    bad.write_bytes(b"not an npz")
    a = _npz(tmp_path, "12-4-2")
    out = str(tmp_path / "codes")
    rc = qldpc.main(["submit-batch", str(bad), a, "--authors", "@me", "--out", out, "--json", *FAST])
    record, _ = _record(capsys)
    rows = _by_path(record)
    assert rows["bad.npz"]["status"] == "error" and rows["bad.npz"]["error"]["stage"] == "load"
    assert rows["12-4-2.npz"]["status"] == "written"
    assert rc == 1 and not record["ok"] and record["error"]["stage"] == "submit"


def test_a_directory_and_a_glob_are_expanded_and_verdict_files_skipped(tmp_path, capsys):
    d = tmp_path / "run"
    d.mkdir()
    _npz(d, "12-4-2")
    (d / "12-4-2.verdict.json").write_text("{}")
    out = str(tmp_path / "codes")
    rc = qldpc.main(["submit-batch", str(d), "--authors", "@me", "--out", out, "--json", "--dry-run", *FAST])
    record, _ = _record(capsys)
    assert rc == 0 and [os.path.basename(r["path"]) for r in record["candidates"]] == ["12-4-2.npz"]


def test_no_candidates_is_a_usage_error_record(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    rc = qldpc.main(["submit-batch", str(empty), "--authors", "@me", "--json"])
    record, _ = _record(capsys)
    assert rc == 2 and record["error"]["class"] == "usage" and "no candidate files" in record["error"]["message"]


def test_open_pr_files_each_code_from_the_base_ref_and_stops_on_a_failure(tmp_path, capsys, monkeypatch):
    calls = []

    def fake_open_pr(slug, out, note_out=None, title=None, body_file=None, *, res=None, **kw):
        calls.append({"slug": slug, "out": out, "base_ref": kw.get("base_ref"), "pr_author": kw.get("pr_author")})
        if len(calls) == 2:
            res["error"] = {"stage": "open-pr", "command": "git push", "returncode": 1, "message": "no remote"}
            return 1
        res["pr_url"] = f"https://github.com/o/r/pull/{len(calls)}"
        res["pr_number"] = len(calls)
        return 0

    monkeypatch.setattr(qldpc, "open_pr", fake_open_pr)
    a = _npz(tmp_path, "12-4-2")
    b = _npz(tmp_path, "7-1-3")
    c = _npz(tmp_path, "15-7-3")
    out = str(tmp_path / "codes")
    rc = qldpc.main(["submit-batch", a, b, c, "--authors", "@me", "--out", out, "--json", "--open-pr", *FAST])
    record, _ = _record(capsys)
    rows = _by_path(record)
    assert rows["12-4-2.npz"]["status"] == "filed" and rows["12-4-2.npz"]["pr_url"].endswith("/pull/1")
    assert rows["7-1-3.npz"]["status"] == "error" and rows["7-1-3.npz"]["unfiled_files"] == [
        os.path.join(out, "7-1-3.json")
    ]
    assert rows["15-7-3.npz"]["status"] == "not-run"
    assert record["stopped_early"] and rc == 1 and record["error"]["stage"] == "open-pr"
    assert record["error"]["unfiled_files"] == [os.path.join(out, "7-1-3.json")]
    assert record["filed"] == ["https://github.com/o/r/pull/1"]
    assert [c["base_ref"] for c in calls] == ["origin/main", "origin/main"]  # the default, per code
    assert all(c["pr_author"] == "me" for c in calls)


def test_submit_argv_carries_the_shared_flags_and_a_note_from_the_note_dir(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "cand.md").write_text("# [[12,4,2]] note\n")
    args = qldpc.build_parser().parse_args(
        [
            "submit-batch",
            str(tmp_path / "cand.npz"),
            "--authors",
            "@me",
            "--model",
            "Claude Opus 4.8",
            "--family",
            "bivariate-bicycle",
            "--note-dir",
            str(notes),
            "--allow-non-frontier",
            "--circuit",
            "--base-ref",
            "",
        ]
    )
    argv = qldpc._batch_submit_argv(args, str(tmp_path / "cand.npz"))
    assert argv[:2] == ["submit", str(tmp_path / "cand.npz")]
    assert "--no-circuit" not in argv and "--base-ref" not in argv
    assert argv[argv.index("--model") + 1] == "Claude Opus 4.8"
    assert argv[argv.index("--family") + 1] == "bivariate-bicycle"
    assert argv[argv.index("--note-file") + 1] == str(notes / "cand.md")
    assert "--allow-non-frontier" in argv and "--json" in argv
    default = qldpc.build_parser().parse_args(["submit-batch", "x.npz", "--authors", "@me"])
    argv = qldpc._batch_submit_argv(default, "x.npz")
    assert "--no-circuit" in argv and argv[argv.index("--base-ref") + 1] == "origin/main"
    assert argv[argv.index("--fast-trials") + 1] == "2000000"  # submit's own depth, not a shallow default


def test_the_top_level_help_lists_submit_batch_as_a_json_subcommand(capsys):
    with pytest.raises(SystemExit):
        qldpc.main(["--help"])
    out = capsys.readouterr().out
    assert "submit-batch" in out
