"""The layout sweep places what the tools can place, as the change the layout binding admits.

The torus screen places the 72-6-6 fixture at the bilayer cap; the attached
entry differs from the original by exactly a first locality block, an
appended note, and the schema bump, in the board's canonical format, and the
verifier classes it. Selection is smallest n first and leaves alone what an
earlier run settled at this budget (issue #4148).
"""
import copy
import json
import os

import check_authorship
import check_codes_format
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FIXTURE = os.path.join(ROOT, "verify", "fixtures", "72-6-6.json")

import layout_sweep as LS  # noqa: E402


@pytest.fixture(scope="module")
def bare():
    """Return the fixture with its layout removed: a layoutless two-block entry."""
    with open(FIXTURE, encoding="utf-8") as f:
        doc = json.load(f)
    doc.pop("locality", None)
    return doc


def test_the_screen_places_the_fixture_and_the_binding_admits_the_result(bare, tmp_path):
    checks = LS.checks_of(bare)
    found, r = LS.screen(bare, checks)
    assert found is not None and found["stage"] == "screen" and found["layers"] == 2
    assert r == 4.1231, "the (6, 6) grid of test_torus_grid"
    assert found["radius"] == 4.1232, "the claim is rounded up, so the verifier's measured <= claim holds"
    new = LS.attach(bare, found, credit="@vprusso", date="2026-10-27")
    assert new["schema_version"] == "0.2" and bare.get("schema_version") == "0.1"
    assert new["locality"]["layers"] == 2 and new["locality"]["interaction_radius"] == 4.1232
    assert new["locality"]["contributed_by"]["by"] == ["@vprusso"]
    assert len(new["locality"]["contributed_by"]["method"]) <= 400
    assert new["provenance"]["notes"].endswith("(research/local2d/layout_sweep.py, screen stage).")
    ok, cls, failed = LS.verify_layout(new)
    assert ok and cls == "local-2d-bilayer" and failed == []
    assert check_authorship.addition_binding("vprusso", bare, new, "locality", "a layout") == (True, "")
    assert check_authorship.addition_binding("someoneelse", bare, new, "locality", "a layout")[0] is False
    assert check_codes_format.check_text(LS.canonical(new)) is None
    assert bare.get("locality") is None, "attach copies"


def test_a_dishonest_or_long_range_layout_is_not_a_candidate(bare):
    checks = LS.checks_of(bare)
    stacked = [[0.0, 0.0]] * bare["n"]
    assert LS.candidate(checks, stacked, "x", "fold") is None, "72 qubits on one site"
    far = [[float(10 * i), 0.0] for i in range(bare["n"])]
    assert LS.candidate(checks, far, "x", "fold") is None, "honest but over every cap"
    honest = LS.candidate(checks, LS.tg.grid(6, 6), "x", "screen")
    assert honest is not None and honest["layers"] == 2


def test_selection_is_smallest_first_and_skips_what_an_earlier_run_settled(tmp_path):
    codes = tmp_path / "codes"
    codes.mkdir()
    for slug, n, extra in (("big", 100, {}), ("small", 20, {}), ("laid", 10, {"locality": {"coordinates": [[0, 0]],
                                                                                      "layers": 1}}),
                           ("stab", 8, {"code_type": "stabilizer"}), ("done", 30, {}), ("missed", 40, {}),
                           ("cheap", 50, {}), ("stale", 35, {}), ("screened", 45, {})):
        doc = {"code_type": "CSS", "n": n, "k": 1, "checks": {"X": [[0]], "Z": [[1]]}, "distance": {"d": 1}}
        doc.update(extra)
        with open(codes / f"{slug}.json", "w", encoding="utf-8") as f:
            json.dump(doc, f)
    entries = LS.layoutless(str(codes))
    assert [s for s, _ in entries] == ["small", "done", "stale", "missed", "screened", "cheap", "big"]
    last = {"done": {"outcome": "accepted", "entry_seconds": 600, "date": "2026-10-20"},
            "stale": {"outcome": "accepted", "entry_seconds": 600, "date": "2026-09-01"},
            "missed": {"outcome": "miss", "entry_seconds": 600, "date": "2026-10-20"},
            "screened": {"outcome": "miss", "entry_seconds": 600, "date": "2026-10-20", "stages": ["screen"]},
            "cheap": {"outcome": "miss", "entry_seconds": 60, "date": "2026-10-20"}}
    today = "2026-10-26"
    chosen, skipped = LS.select(entries, last=last, entry_seconds=600, today=today)
    assert [s for s, _ in chosen] == ["small", "stale", "screened", "cheap", "big"], \
        "a shorter budget, fewer stages, or an accepted row older than AWAITING_DAYS: reopened"
    assert skipped == {"awaiting_pr": 1, "missed_at_budget": 1}
    chosen, skipped = LS.select(entries, last=last, entry_seconds=600, stages=("screen",), today=today)
    assert [s for s, _ in chosen] == ["small", "stale", "cheap", "big"] and skipped["missed_at_budget"] == 2
    chosen, _ = LS.select(entries, last=last, entry_seconds=600, retry=True, today=today)
    assert [s for s, _ in chosen] == ["small", "stale", "missed", "screened", "cheap", "big"], \
        "retry reopens misses, not accepted ones"
    chosen, _ = LS.select(entries, last=last, entry_seconds=600, slugs=["missed", "done", "big"], today=today)
    assert [s for s, _ in chosen] == ["done", "missed", "big"], "named slugs lift both skips"


def test_a_run_stages_the_screen_hit_logs_the_attempt_and_stage_attaches_it(bare, tmp_path):
    codes, out, attempts = tmp_path / "codes", tmp_path / "out", tmp_path / "attempts.jsonl"
    codes.mkdir()
    with open(codes / "72-6-6.json", "w", encoding="utf-8", newline="\n") as f:
        f.write(LS.canonical(bare))
    # an entry the screen cannot place (odd n) with no search stages: a miss that costs nothing
    odd = copy.deepcopy(bare)
    odd["n"] = 73
    with open(codes / "73-6-6.json", "w", encoding="utf-8", newline="\n") as f:
        f.write(LS.canonical(odd))
    m = LS.run_sweep(out_dir=str(out), attempts_path=str(attempts), credit="@vprusso", job_seconds=600,
                     entry_seconds=60, stages=("screen",), codes_dir=str(codes))
    assert m["outcomes"] == {"accepted": 1, "miss": 1} and m["staged"] == ["72-6-6"]
    rows = LS.load_jsonl(str(attempts))
    assert [r["slug"] for r in rows] == ["72-6-6", "73-6-6"]
    assert rows[0]["outcome"] == "accepted" and rows[0]["stage"] == "screen" and rows[0]["class"] == "local-2d-bilayer"
    assert rows[1]["outcome"] == "miss" and rows[1]["stage"] is None
    assert (out / "layouts" / "72-6-6.json").exists() and (out / "codes" / "72-6-6.json").exists()
    with open(out / "layouts" / "72-6-6.json", encoding="utf-8") as f:
        layout = json.load(f)
    assert layout["credit"] == "@vprusso" and layout["date"] == m["date"] and layout["layers"] == 2
    # a second run leaves both alone
    m2 = LS.run_sweep(out_dir=str(tmp_path / "out2"), attempts_path=str(attempts), credit="@vprusso",
                      job_seconds=600, entry_seconds=60, stages=("screen",), codes_dir=str(codes))
    assert m2["opened"] == 0 and m2["skipped"] == {"awaiting_pr": 1, "missed_at_budget": 1}
    # stage writes the current codes/ file with the layout, canonically, and refuses a second time
    staged, skipped = LS.stage(str(out), codes_dir=str(codes))
    assert staged == ["72-6-6"] and skipped == []
    assert LS.staged_slugs(str(out)) == ["72-6-6"] and rows[0]["stages"] == ["screen"]
    with open(codes / "72-6-6.json", encoding="utf-8") as f:
        text = f.read()
    assert check_codes_format.check_text(text) is None
    new = json.loads(text)
    assert check_authorship.addition_binding("vprusso", bare, new, "locality", "a layout") == (True, "")
    assert LS.stage(str(out), codes_dir=str(codes)) == ([], [("72-6-6", "already has a layout")])
    title, body = LS.pr_text(m, staged=["72-6-6"])
    assert title.startswith("Add first 2D-local layouts for 1 entry from the weekly layout sweep of ")
    assert "| 72-6-6 |" in body and "73-6-6" not in body and "@vprusso" in body
    assert "| 72-6-6 |" in LS.summary_markdown(m)


def test_the_layout_cap_stops_a_run_and_the_next_run_continues(bare, tmp_path):
    codes, attempts = tmp_path / "codes", tmp_path / "attempts.jsonl"
    codes.mkdir()
    for name in ("72-6-6", "72-6-6-b"):
        with open(codes / f"{name}.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(LS.canonical(bare))
    m = LS.run_sweep(out_dir=str(tmp_path / "out"), attempts_path=str(attempts), credit="@vprusso",
                     job_seconds=600, entry_seconds=60, stages=("screen",), codes_dir=str(codes), max_layouts=1)
    assert m["staged"] == ["72-6-6"] and m["opened"] == 1
    assert m["stopped_by_cap"] and not m["stopped_by_budget"] and m["left"] == 1
    assert "stopped at the layout cap with 1 left" in LS.summary_markdown(m)
    m2 = LS.run_sweep(out_dir=str(tmp_path / "out2"), attempts_path=str(attempts), credit="@vprusso",
                      job_seconds=600, entry_seconds=60, stages=("screen",), codes_dir=str(codes), max_layouts=1)
    assert m2["staged"] == ["72-6-6-b"] and m2["skipped"] == {"awaiting_pr": 1} and not m2["stopped_by_cap"]


def test_the_annealers_run_inside_the_budget_on_a_small_code(bare, tmp_path):
    """The search stages at tiny iteration counts: a miss or a hit, within the deadline, never a crash."""
    codes = tmp_path / "codes"
    codes.mkdir()
    path = codes / "72-6-6.json"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(LS.canonical(bare))
    got = LS.attempt("72-6-6", bare, str(path), stages=("fold", "hinge", "tri"), entry_seconds=30,
                     fold_iters=2000, hinge_iters=2000, hinge_seeds=1, tri_iters=20000, tri_rate=1e9)
    assert got["best_radius"] is not None and got["secs"] < 60
    if got["layout"] is not None:
        assert got["layout"]["stage"] in ("fold", "hinge") and got["layout"]["layers"] in (1, 2)
    # tri on its own, sized to run: the chain is deterministic per seed and returns a measured candidate or None
    found, r = LS.tri(str(path), LS.checks_of(bare), 20000)
    assert r > 0 and (found is None or found["stage"] == "tri")
