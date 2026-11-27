"""`research/does_it_advance.py` (issue #7442): the gate's novelty block from parameters, as one record.

The rule is `frontier.novelty`, tested in test_frontier.py; these tests pin
the record around it: the board readings, the collision block, and the
`--json` contract.
"""

import json
import os
import subprocess
import sys

import does_it_advance as D
import frontier as F

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)


def _row(n, k, d, w, slug, lc="unrestricted", code_type="CSS"):
    return {
        "n": n,
        "k": k,
        "d": d,
        "w": w,
        "slug": slug,
        "name": f"{slug}.json",
        "code_type": code_type,
        "weight_class": D.weight_class(w),
        "locality_class": lc,
    }


def _codes_dir(tmp_path, *rows):
    d = tmp_path / "codes"
    d.mkdir()
    for r in rows:
        doc = {
            "n": r["n"],
            "k": r["k"],
            "name": r["name"],
            "code_type": r["code_type"],
            "distance": {"d": r["d"]},
            "checks": {"X": [list(range(r["w"]))], "Z": [list(range(r["w"]))]},
        }
        if r["locality_class"] != "unrestricted":
            doc["locality"] = {"coordinates": [[0, 0]] * r["n"], "layers": 1}
        (d / f"{r['slug']}.json").write_text(json.dumps(doc))
    return str(d)


def test_the_quick_board_reads_the_files_and_labels_a_layout_bilayer(tmp_path):
    codes = _codes_dir(tmp_path, _row(72, 12, 6, 6, "72-12-6"), _row(30, 4, 3, 4, "30-4-3", lc="local-2d-single"))
    board = D.load_board(codes)
    assert [b["slug"] for b in board] == ["30-4-3", "72-12-6"]
    assert board[0]["locality_class"] == "local-2d-bilayer"  # best-effort without the radius
    assert board[1]["weight_class"] == "weight-6" and board[1]["w"] == 6


def test_the_record_carries_the_gate_block_and_the_collisions(tmp_path):
    codes = _codes_dir(
        tmp_path, _row(72, 12, 6, 6, "72-12-6"), _row(72, 12, 6, 8, "72-12-6-b"), _row(72, 12, 5, 6, "72-12-5")
    )
    board = D.load_board(codes)
    cand = D.candidate_row(72, 12, 6, 6)
    rec = D.record(board, cand, source="quick", codes_dir=codes)
    assert rec["schema_version"] == D.SCHEMA_VERSION
    assert rec["candidate"]["cell"] == ["weight-6", "unrestricted"] and rec["candidate"]["kd2_over_n"] == 6.0
    assert rec["board"] == {"entries": 3, "source": "quick", "codes": os.path.relpath(codes, ROOT)}
    nov = rec["novelty"]
    assert nov["board_advancing"] and nov["dominators"] == nov["dominated_by"] == []
    # the w = 8 twin is in a looser cell, so it is neither a rival nor beaten: the gain is on d alone
    assert nov["advances_by"] == ["d"] and nov["d_only_peers"] == ["[[72,12,5]] w=6 72-12-5.json"]
    assert nov["d_only_gain"] and nov["beaten"] == [["[[72,12,5]] w=6 72-12-5.json", ["d"]]]
    col = rec["collisions"]
    assert col["slug"] == "72-12-6" and col["slug_taken_by"] == os.path.relpath(
        os.path.join(codes, "72-12-6.json"), ROOT
    )
    assert col["suggested_slug"] == "72-12-6-c"  # -b is taken too
    assert set(col["same_parameters"]) == {"[[72,12,6]] w=6 72-12-6.json", "[[72,12,6]] w=8 72-12-6-b.json"}
    assert col["ties"] == ["[[72,12,6]] w=6 72-12-6.json"]  # the w = 8 twin is in another cell


def test_a_free_slug_has_no_suggestion_and_a_dominated_candidate_is_not_advancing(tmp_path):
    codes = _codes_dir(tmp_path, _row(72, 12, 7, 6, "72-12-7"))
    rec = D.record(D.load_board(codes), D.candidate_row(72, 12, 6, 6), source="quick", codes_dir=codes)
    assert not rec["novelty"]["board_advancing"] and rec["novelty"]["dominators"] == ["[[72,12,7]] w=6 72-12-7.json"]
    assert rec["collisions"]["slug_taken_by"] is None and rec["collisions"]["suggested_slug"] is None


def test_novelty_is_frontiers(tmp_path):
    codes = _codes_dir(tmp_path, _row(72, 12, 5, 6, "72-12-5"), _row(60, 20, 8, 10, "60-20-8"))
    board = D.load_board(codes)
    assert D.novelty(board, 72, 12, 6, 6) == F.novelty(D.candidate_row(72, 12, 6, 6), board)


def test_the_cli_json_record_is_the_documented_one(tmp_path):
    codes = _codes_dir(tmp_path, _row(72, 12, 5, 6, "72-12-5"))
    proc = subprocess.run(
        [
            sys.executable,
            os.path.join(_HERE, "does_it_advance.py"),
            "--n",
            "72",
            "--k",
            "12",
            "--d",
            "6",
            "--w",
            "6",
            "--codes",
            codes,
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    rec = json.loads(proc.stdout)
    assert set(rec) == {"schema_version", "candidate", "board", "novelty", "collisions"}
    assert set(rec["novelty"]) >= {
        "board_advancing",
        "advances_by",
        "dominators",
        "dominated_by",
        "d_only_gain",
        "d_only_peers",
        "beaten",
        "cell",
        "board",
    }
    assert set(rec["collisions"]) == {"slug", "slug_taken_by", "suggested_slug", "same_parameters", "ties"}
    assert rec["novelty"]["d_only_gain"] and rec["board"]["source"] == "quick"
    human = subprocess.run(
        [
            sys.executable,
            os.path.join(_HERE, "does_it_advance.py"),
            "--n",
            "72",
            "--k",
            "12",
            "--d",
            "6",
            "--w",
            "6",
            "--codes",
            codes,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert (
        "board_advancing : True" in human.stdout and "tied on n,k,w with [[72,12,5]] w=6 72-12-5.json" in human.stdout
    )
