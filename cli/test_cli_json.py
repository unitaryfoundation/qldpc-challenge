"""The machine-readable contract of `qldpc submit --json` (issue #2328).

With --json, stdout carries exactly one JSON record and nothing else; every
human-readable line goes to stderr. The record names the stage reached, the
files written, the drafted title and body, the branch, and the commands that
remain (or the PR URL), or an error with a class and a stage. A caller never
parses prose. The board's [[12,4,2]] checks go in as an .npz, the code tier
is searched and verified for real, and the board lookups are stubbed because
they re-verify the whole board.
"""

import json
import os

import numpy as np
import pytest
import qldpc
from qldpc_verify import _matrix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAST = ["--trials", "300", "--fast-trials", "0", "--no-circuit"]


@pytest.fixture(scope="module")
def npz(tmp_path_factory):
    doc = json.load(open(os.path.join(ROOT, "codes", "12-4-2.json")))
    n = doc["n"]
    path = tmp_path_factory.mktemp("in") / "bb12.npz"
    np.savez(path, hx=_matrix(doc["checks"]["X"], n),
             hz=_matrix(doc["checks"]["Z"], n))
    return str(path)


@pytest.fixture(autouse=True)
def _no_board(monkeypatch):
    monkeypatch.setattr(qldpc, "_load_board_entries", lambda: [])
    monkeypatch.setattr(qldpc, "_board_identities",
                        lambda: ([], lambda rep: (set(), set())))


def _record(capsys):
    captured = capsys.readouterr()
    record = json.loads(captured.out)          # one object, nothing else
    assert captured.out.strip().startswith("{") and captured.out.count("\n{") == 0
    return record, captured.err


def test_dry_run_record_carries_the_document(npz, capsys, tmp_path):
    out = str(tmp_path / "codes")
    rc = qldpc.main(["submit", npz, "--authors", "@me", "--dry-run", "--json",
                     "--out", out, *FAST])
    record, err = _record(capsys)
    assert rc == 0 and record["ok"] and record["exit_code"] == 0
    assert record["stage"] == "dry-run" and record["dry_run"]
    assert record["slug"] == "12-4-2" and (record["n"], record["k"], record["d"]) == (12, 4, 2)
    assert record["would_write"] == os.path.join(out, "12-4-2.json")
    assert record["doc"]["n"] == 12 and record["doc"]["checks"]["X"]
    assert "verifying" in err                    # the prose went to stderr
    assert not os.path.exists(out)


def test_written_submission_record_names_files_and_next_steps(npz, capsys, tmp_path):
    out = str(tmp_path / "codes")
    note = tmp_path / "note.md"
    note.write_text("# [[12,4,2]] test note\n\nA note.\n", encoding="utf-8")
    rc = qldpc.main(["submit", npz, "--authors", "@me", "Jane Doe", "--json",
                     "--out", out, "--note-file", str(note), *FAST])
    record, _ = _record(capsys)
    assert rc == 0 and record["ok"]
    assert record["stage"] == "draft"
    assert record["code_path"] == os.path.join(out, "12-4-2.json")
    assert os.path.exists(record["code_path"])
    assert record["note_path"].endswith(os.path.join("notes", "12-4-2.md"))
    assert record["circuits_dir"] is None
    assert record["title"].startswith("Add [[12,4,2]]")
    assert record["branch"] == "submit-12-4-2"
    assert record["pr_author"] == "me"
    assert os.path.exists(record["body_file"])
    steps = record["next_steps"]
    assert steps[0] == "git checkout -b submit-12-4-2"
    assert steps[1].startswith("git add ") and record["code_path"] in steps[1]
    assert steps[3] == "git push -u origin submit-12-4-2"
    assert steps[4].startswith("gh pr create --title ") and record["body_file"] in steps[4]
    # the dedup ran against the (empty) board, so the equivalence box is ticked
    assert record["dedup"] == {"checked": True, "match": None, "kind": None}
    body = open(record["body_file"], encoding="utf-8").read()
    assert "- [x] Checked against the current board" in body
    assert "- [ ]" not in body
    os.remove(record["note_path"])              # notes/ is the real tree


def test_base_ref_is_carried_into_the_first_step(npz, capsys, tmp_path):
    out = str(tmp_path / "codes")
    rc = qldpc.main(["submit", npz, "--authors", "@me", "--json", "--out", out,
                     "--base-ref", "origin/main", *FAST])
    record, _ = _record(capsys)
    assert rc == 0
    assert record["base_ref"] == "origin/main"
    assert record["next_steps"][0] == "git checkout -b submit-12-4-2 origin/main"


def test_a_board_match_leaves_the_box_for_a_human(npz, capsys, tmp_path, monkeypatch):
    out = str(tmp_path / "codes")
    board = [{"name": "12-4-2.json", "fingerprint": "f0", "sig": "s0",
              "css_fingerprints": [], "css_sigs": []}]
    monkeypatch.setattr(qldpc, "_board_identities",
                        lambda: (board, lambda rep: ({"f0"}, {"s0"})))
    rc = qldpc.main(["submit", npz, "--authors", "@me", "--json", "--out", out, *FAST])
    record, _ = _record(capsys)
    assert rc == 0
    assert record["dedup"] == {"checked": True, "match": "12-4-2.json",
                               "kind": "exact fingerprint"}
    body = open(record["body_file"], encoding="utf-8").read()
    assert "- [ ] Possibly equivalent to `12-4-2.json` (exact fingerprint)" in body


def test_usage_errors_are_a_json_record_with_exit_code_two(npz, capsys, tmp_path):
    out = str(tmp_path / "codes")
    rc = qldpc.main(["submit", npz, "--authors", "@me", "--json", "--out", out,
                     "--no-circuit", "--circuits", str(tmp_path)])
    record, _ = _record(capsys)
    assert rc == 2 and not record["ok"] and record["exit_code"] == 2
    assert record["error"]["class"] == "usage"
    assert "--no-circuit and --circuits" in record["error"]["message"]


def test_an_existing_file_is_a_write_stage_error(npz, capsys, tmp_path):
    out = str(tmp_path / "codes")
    os.makedirs(out)
    open(os.path.join(out, "12-4-2.json"), "w").close()
    rc = qldpc.main(["submit", npz, "--authors", "@me", "--json", "--out", out, *FAST])
    record, _ = _record(capsys)
    assert rc == 1 and not record["ok"]
    assert record["error"]["stage"] == "write" and record["error"]["class"] == "write"
    assert "already exists" in record["error"]["message"]


def test_without_json_the_human_output_is_unchanged(npz, capsys, tmp_path):
    out = str(tmp_path / "codes")
    rc = qldpc.main(["submit", npz, "--authors", "@me", "--out", out, *FAST])
    text = capsys.readouterr().out
    assert rc == 0
    assert "next: open a PR with this file" in text
    assert "git checkout -b submit-12-4-2" in text
    assert not text.lstrip().startswith("{")


def test_harness_flag_lands_in_provenance(npz, capsys, tmp_path):
    out = str(tmp_path / "codes")
    rc = qldpc.main(["submit", npz, "--authors", "@me", "--dry-run", "--json",
                     "--out", out, "--harness", "OpenCode agent harness", *FAST])
    record, err = _record(capsys)
    assert rc == 0 and record["ok"]
    assert record["doc"]["provenance"].get("harness") == "OpenCode agent harness"


def test_harness_absent_without_flag(npz, capsys, tmp_path):
    out = str(tmp_path / "codes")
    rc = qldpc.main(["submit", npz, "--authors", "@me", "--dry-run", "--json",
                     "--out", out, *FAST])
    record, err = _record(capsys)
    assert rc == 0 and record["ok"]
    assert "harness" not in record["doc"]["provenance"]
