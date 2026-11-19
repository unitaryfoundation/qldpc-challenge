"""The distance-revision harvest emits exactly the edit the board accepts as a correction (issue #6813).

The Shor code is the fixture: its X logicals weigh 3 or 9 and its Z logicals
3, 5, 7, or 9, so an entry can claim [[9,1,5]] with valid witnesses (X on all
nine qubits, Z on five) and still be refuted to [[9,1,3]] on both sides. The
emitted document has to pass the structural half of the verifier and the
refutation binding of verify/check_authorship.py under the harvester's
handle, and the folded note has to keep the old note's body for
verify/check_prose.py. Searches here are tiny; the ladder budget itself is
pinned against reachability_campaign.screening_trials.
"""
import base64
import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_HERE, os.path.join(_HERE, "kit"), os.path.join(_ROOT, "verify")):
    sys.path.insert(0, _p)

import check_authorship as CA  # noqa: E402
import check_prose as CP  # noqa: E402
import qldpc_verify  # noqa: E402
import reachability_campaign as RC  # noqa: E402
import revision_harvest as RH  # noqa: E402

SHOR_X = [[0, 1, 2, 3, 4, 5], [3, 4, 5, 6, 7, 8]]
SHOR_Z = [[0, 1], [1, 2], [3, 4], [4, 5], [6, 7], [7, 8]]


def shor_doc(d_x, wit_x, d_z, wit_z, *, name=None, notes="", schema="0.1"):
    d = min(d_x, d_z)
    return {
        "schema_version": schema,
        "name": name or f"[[9,1,{d}]] Shor",
        "code_type": "CSS", "n": 9, "k": 1,
        "checks": {"X": SHOR_X, "Z": SHOR_Z},
        "distance": {"d": d,
                     "X": {"value": d_x, "confidence": "upper_bound", "witness": wit_x},
                     "Z": {"value": d_z, "confidence": "upper_bound", "witness": wit_z}},
        "provenance": {"authors": ["@someone"], "construction": "Shor's nine-qubit code.",
                       "references": [], "date": "2026-01-01", "notes": notes},
        "family": "other",
    }


OVERCLAIM = shor_doc(9, list(range(9)), 5, [0, 1, 2, 3, 6], notes="Seeded.")
CORRECT = shor_doc(3, [0, 1, 2], 3, [0, 3, 6])


def _write(path, doc):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(RH.canonical(doc))
    return str(path)


def _run(tmp_path, doc, **kw):
    codes = tmp_path / "codes"
    codes.mkdir(exist_ok=True)
    path = _write(codes / ("9-1-%d.json" % doc["distance"]["d"]), doc)
    out = tmp_path / "out"
    args = dict(out_dir=str(out), handle="harvester", date="2026-11-19", seeds=[1, 2], scale=1.0,
                min_trials=200, max_trials=400, threads=1, pair_depth=10, codes_dir=str(codes), log=lambda *a: None)
    args.update(kw)
    return path, RH.harvest_one(path, **args)


def test_the_fixtures_are_valid_entries():
    for doc in (OVERCLAIM, CORRECT):
        rep = qldpc_verify.verify(doc, refute=False)
        assert rep["ok"], [c for c in rep["checks"] if not c["ok"]]


def test_an_over_claim_is_refuted_and_emitted(tmp_path):
    path, row = _run(tmp_path, OVERCLAIM)
    assert row["verdict"] == "refuted"
    assert row["d_new"] == 3 and row["new_slug"] == "9-1-3"
    assert row["sides"], "at least the side the joint search reported came down"
    with open(row["revision"], encoding="utf-8") as fh:
        new = json.load(fh)
    assert new["distance"]["d"] == 3
    for side in row["sides"]:
        assert new["distance"][side]["value"] == 3
        assert new["distance"][side]["witness_provenance"]["tool"].endswith("gf2_fast pair depth 10") or \
            new["distance"][side]["witness_provenance"]["tool"].endswith("numpy pair depth 10")
    for side in ("X", "Z"):
        if side not in row["sides"]:
            assert new["distance"][side] == OVERCLAIM["distance"][side], "an unreported side is untouched"
    assert CA.refutation_binding("harvester", OVERCLAIM, new)[0]


def test_the_per_side_pass_tightens_both_sides(tmp_path):
    path, row = _run(tmp_path, OVERCLAIM, side_trials=300)
    assert row["verdict"] == "refuted"
    assert row["d_new"] == 3 and row["new_slug"] == "9-1-3"
    assert set(row["sides"]) == {"X", "Z"}
    assert row["sides"]["X"]["found"] == 3 and row["sides"]["Z"]["found"] == 3
    assert os.path.exists(row["revision"])
    stem = row["revision"][:-5]
    assert os.path.exists(stem + ".body.md") and os.path.exists(stem + ".revision.json")
    with open(row["revision"], encoding="utf-8") as fh:
        text = fh.read()
    new = json.loads(text)
    assert text == RH.canonical(new), "the candidate is written in the board's canonical form"
    assert new["distance"]["d"] == 3
    assert new["name"] == "[[9,1,3]] Shor"
    assert new["schema_version"] == "0.2"
    for side in ("X", "Z"):
        wp = new["distance"][side]["witness_provenance"]
        assert wp["found_by"] == ["@harvester"] and wp["date"] == "2026-11-19"
        assert wp["found_at_samples"] >= 200 and wp["seeds"] and len(wp["tool"]) <= 80
        assert new["distance"][side]["confidence"] == "upper_bound"
        assert len(new["distance"][side]["witness"]) == 3
    assert new["provenance"]["notes"].startswith("Seeded. Distance revision 2026-11-19 (witnesses by @harvester)")
    assert "X side 9 -> 3" in new["provenance"]["notes"] and "Z side 5 -> 3" in new["provenance"]["notes"]


def test_the_emitted_document_passes_the_verifier_and_the_refutation_binding(tmp_path):
    path, row = _run(tmp_path, OVERCLAIM, side_trials=300)
    with open(row["revision"], encoding="utf-8") as fh:
        new = json.load(fh)
    rep = qldpc_verify.verify(new, refute=False)
    assert rep["ok"], [c for c in rep["checks"] if not c["ok"]]
    ok, why = CA.refutation_binding("harvester", OVERCLAIM, new)
    assert ok, why
    ok, why = CA.refutation_binding("someoneelse", OVERCLAIM, new)
    assert not ok and "found_by" in why


def test_a_correct_claim_holds_and_emits_nothing(tmp_path):
    path, row = _run(tmp_path, CORRECT)
    assert row["verdict"] == "holds"
    assert "revision" not in row and row["sides"] == {}
    assert row["joint"] == 3
    assert not os.path.exists(tmp_path / "out" / "revisions")


def test_one_sided_tightening_keeps_the_other_witness(tmp_path):
    doc = shor_doc(3, [0, 1, 2], 5, [0, 1, 2, 3, 6])
    path, row = _run(tmp_path, doc, side_trials=300)
    assert row["verdict"] == "tightened" and set(row["sides"]) == {"Z"}
    assert row["d_new"] == 3 and row["new_slug"] == "9-1-3-b", "d is unchanged, so the slug needs a suffix"
    assert row["title"] == "Distance revision: [[9,1,3]], Z side 5 -> 3"
    with open(row["revision"][:-5] + ".body.md", encoding="utf-8") as fh:
        body = fh.read()
    assert "d stays 3 (Z side 5 -> 3)" in body and "kd^2/n unchanged at 1.00" in body
    with open(row["revision"][:-5] + ".revision.json", encoding="utf-8") as fh:
        header = json.load(fh)["note_header"]
    assert header.startswith("# [[9,1,3]]: distance revision, Z side 5 -> 3\n"
                             "## Revision 2026-11-19: [[9,1,3]], Z side 5 -> 3")
    with open(row["revision"], encoding="utf-8") as fh:
        new = json.load(fh)
    assert new["distance"]["X"] == doc["distance"]["X"], "the side that held is untouched"
    assert new["distance"]["Z"]["value"] == 3 and new["distance"]["d"] == 3
    assert CA.refutation_binding("harvester", doc, new)[0]


def test_pr_text_names_the_route_and_the_sides(tmp_path):
    path, row = _run(tmp_path, OVERCLAIM, side_trials=300)
    stem = row["revision"][:-5]
    with open(stem + ".revision.json", encoding="utf-8") as fh:
        rec = json.load(fh)
    assert rec["title"] == "Distance revision: [[9,1,5]] -> [[9,1,3]]"
    with open(stem + ".body.md", encoding="utf-8") as fh:
        body = fh.read()
    assert "Correcting a distance already on the board" in body
    assert "- X side 9 -> 3:" in body and "- Z side 5 -> 3:" in body
    assert "kd^2/n 2.78 -> 1.00" in body
    assert "—" not in body and "—" not in rec["note_header"]
    assert rec["note_header"].startswith("# [[9,1,3]]:")
    assert rec["old_slug"] == "9-1-5" and rec["new_slug"] == "9-1-3"


def test_slug_choice_skips_an_occupied_slug_and_keeps_a_suffix(tmp_path):
    codes = tmp_path / "codes"
    codes.mkdir()
    assert RH.revision_slug(str(codes), "9-1-5", 9, 1, 3) == "9-1-3"
    _write(codes / "9-1-3.json", CORRECT)
    assert RH.revision_slug(str(codes), "9-1-5", 9, 1, 3) == "9-1-3-b"
    assert RH.revision_slug(str(codes), "9-1-5-c", 9, 1, 3) == "9-1-3-c"
    _write(codes / "9-1-3-c.json", CORRECT)
    assert RH.revision_slug(str(codes), "9-1-5-c", 9, 1, 3) == "9-1-3-b"


def test_rename_params_touches_only_the_leading_token():
    assert RH.rename_params("[[9,1,5]] Shor", 9, 1, 3) == "[[9,1,3]] Shor"
    assert RH.rename_params("[[ 9, 1, 5 ]] vs [[9,1,5]]", 9, 1, 3) == "[[9,1,3]] vs [[9,1,5]]"
    assert RH.rename_params("Shor code", 9, 1, 3) == "Shor code"
    assert RH.rename_params("[[7,1,3]] not this one", 9, 1, 3) == "[[7,1,3]] not this one"


def test_apply_moves_the_entry_and_folds_the_note(tmp_path):
    checkout = tmp_path / "repo"
    (checkout / "codes").mkdir(parents=True)
    (checkout / "notes").mkdir()
    _write(checkout / "codes" / "9-1-5.json", OVERCLAIM)
    old_note = ("---\nauthor: \"@someone\"\n---\n\n# [[9,1,5]]: Shor's code, seeded\n\n"
                "The search behind `codes/9-1-5.json` stopped at 400 trials.\n\nSecond paragraph about the "
                "construction.\nThird line that must survive the fold.\n")
    (checkout / "notes" / "9-1-5.md").write_text(old_note)
    path, row = _run(tmp_path, OVERCLAIM, apply_to=str(checkout), codes_dir=str(checkout / "codes"))
    assert row["verdict"] == "refuted"
    assert row["applied"] == ["codes/9-1-3.json", "notes/9-1-3.md"]
    assert not (checkout / "codes" / "9-1-5.json").exists()
    assert not (checkout / "notes" / "9-1-5.md").exists()
    new_text = (checkout / "codes" / "9-1-3.json").read_text()
    assert new_text == RH.canonical(json.loads(new_text))
    note = (checkout / "notes" / "9-1-3.md").read_text()
    assert note.startswith('---\nauthor: "@someone"\n---\n# [[9,1,3]]:'), note[:80]
    assert "## Original note, with the file paths updated" in note
    assert "`codes/9-1-3.json`" in note and "codes/9-1-5.json" not in note
    assert CP.retention(old_note, note) >= CP.RETENTION_MIN


def test_apply_refuses_a_missing_or_occupied_target(tmp_path):
    checkout = tmp_path / "repo"
    (checkout / "codes").mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        RH.apply_revision(str(checkout), "9-1-5", "9-1-3", OVERCLAIM, "# h\n")
    _write(checkout / "codes" / "9-1-5.json", OVERCLAIM)
    _write(checkout / "codes" / "9-1-3.json", CORRECT)
    with pytest.raises(FileExistsError):
        RH.apply_revision(str(checkout), "9-1-5", "9-1-3", OVERCLAIM, "# h\n")


def test_an_open_pr_entry_is_emitted_but_never_applied(tmp_path):
    checkout = tmp_path / "repo"
    (checkout / "codes").mkdir(parents=True)
    path, row = _run(tmp_path, OVERCLAIM, pr=4242, apply_to=str(checkout))
    assert row["verdict"] == "refuted" and row["pr"] == 4242
    assert os.path.basename(row["revision"]).startswith("pr-4242-")
    assert "open PR #4242" in row["apply_error"]
    with open(row["revision"][:-5] + ".body.md", encoding="utf-8") as fh:
        assert "carried by PR #4242" in fh.read()


def test_ladder_budget_is_the_campaigns_screening_trials():
    for d in (3, 8, 19, 20, 60, 200):
        assert RH.ladder_trials(d) == RC.screening_trials(d)
    assert RH.ladder_trials(3, scale=2.0) == 2 * RC.screening_trials(3)
    assert RH.ladder_trials(3, min_trials=10**7) == 10**7
    assert RH.ladder_trials(200, max_trials=5000) == 5000


def test_state_skips_an_entry_already_probed_at_the_budget(tmp_path, monkeypatch, capsys):
    codes = tmp_path / "codes"
    codes.mkdir()
    path = _write(codes / "9-1-3.json", CORRECT)
    state = tmp_path / "state.json"
    out = tmp_path / "out"
    argv = [path, "--handle", "h", "--out", str(out), "--seeds", "1", "--max-trials", "300",
            "--state", str(state), "--threads", "1", "--codes-dir", str(codes)]
    assert RH.main(argv) == 0
    saved = json.load(open(state))
    assert len(saved) == 1 and next(iter(saved.values()))["verdict"] == "holds"
    assert RH.main(argv) == 0
    assert "already spent" in capsys.readouterr().out
    rows = [json.loads(line) for line in open(out / "harvest.jsonl")]
    assert len(rows) == 1, "the second run opened nothing"
    assert RH.main(argv + ["--rerun"]) == 0
    assert len(open(out / "harvest.jsonl").read().splitlines()) == 2
    # a bigger planned budget reopens the entry
    assert RH.main(argv[:-4] + ["--codes-dir", str(codes), "--max-trials", "350", "--min-trials", "350"]) == 0
    assert len(open(out / "harvest.jsonl").read().splitlines()) == 3


def test_main_requires_a_handle(tmp_path):
    with pytest.raises(SystemExit):
        RH.main(["--out", str(tmp_path)])


def test_skips_non_css_and_reports_unreadable(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    row = RH.harvest_one(str(bad), out_dir=str(tmp_path / "o"), handle="h", date="2026-11-19", seeds=[1],
                         scale=1.0, min_trials=1, max_trials=10, threads=1, pair_depth=10, codes_dir=str(tmp_path))
    assert row["verdict"] == "error" and "unreadable" in row["error"]
    stab = tmp_path / "s.json"
    stab.write_text(json.dumps({"code_type": "stabilizer", "n": 5, "k": 1, "stabilizers": [], "distance": {"d": 3}}))
    row = RH.harvest_one(str(stab), out_dir=str(tmp_path / "o"), handle="h", date="2026-11-19", seeds=[1],
                         scale=1.0, min_trials=1, max_trials=10, threads=1, pair_depth=10, codes_dir=str(tmp_path))
    assert row["verdict"] == "skipped"


def test_paths_from_text_resolves_mentions_and_parameters(tmp_path):
    codes = tmp_path / "codes"
    codes.mkdir()
    for slug in ("9-1-3", "9-1-3-b", "9-1-5", "7-1-3"):
        _write(codes / f"{slug}.json", CORRECT)
    text = "The sweep filed `codes/7-1-3.json` and [[9,1,3]] (twice: [[9, 1, 3]]) but not [[11,1,3]]."
    got = RH.paths_from_text(text, str(codes))
    assert [os.path.basename(p) for p in got] == ["7-1-3.json", "9-1-3.json", "9-1-3-b.json"]


def test_select_shard():
    items = list("abcdefg")
    assert RH.select_shard(items, None) == items
    assert RH.select_shard(items, "0/3") == ["a", "d", "g"]
    assert RH.select_shard(items, "2/3") == ["c", "f"]
    with pytest.raises(SystemExit):
        RH.select_shard(items, "3/3")


def test_fetch_open_pr_codes_uses_an_explicit_get_and_skips_notes(tmp_path):
    calls = []

    def fake_gh(args):
        calls.append(list(args))
        if args[:2] == ["pr", "list"]:
            return [{"number": 77, "headRefName": "feat/x", "headRepository": {"name": "r"},
                     "headRepositoryOwner": {"login": "o"},
                     "files": [{"path": "codes/9-1-5.json"}, {"path": "notes/9-1-5.md"}]}]
        assert args[1:3] == ["--method", "GET"], args
        assert "repos/o/r/contents/codes/9-1-5.json" in args and "ref=feat/x" in args
        return {"content": base64.b64encode(json.dumps(OVERCLAIM).encode()).decode()}
    found = RH.fetch_open_pr_codes(str(tmp_path), gh=fake_gh)
    assert len(calls) == 2
    assert [(os.path.relpath(p, tmp_path), n) for p, n in found] == [("pr-77/9-1-5.json", 77)]
    assert json.load(open(found[0][0]))["n"] == 9


def test_fetch_open_pr_codes_survives_a_failing_gh(tmp_path, capsys):
    def failing(args):
        raise OSError("gh: command not found")
    assert RH.fetch_open_pr_codes(str(tmp_path), gh=failing) == []
    assert "none harvested" in capsys.readouterr().out


def test_max_minutes_leaves_entries_unopened(tmp_path, monkeypatch, capsys):
    codes = tmp_path / "codes"
    codes.mkdir()
    paths = [_write(codes / f"9-1-3{s}.json", CORRECT) for s in ("", "-b", "-c")]
    clock = iter([0.0, 0.0, 10**6, 10**6, 10**6, 10**6, 10**6])
    monkeypatch.setattr(RH.time, "time", lambda: next(clock, 10**6))
    rc = RH.main(paths + ["--handle", "h", "--out", str(tmp_path / "o"), "--seeds", "1", "--max-trials", "50",
                          "--max-minutes", "1", "--threads", "1", "--codes-dir", str(codes)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "left unopened at 1 min" in out
