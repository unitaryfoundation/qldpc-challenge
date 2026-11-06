"""The cost table has to be re-measurable from a clean checkout and say what it measured.

Every grid entry is a board entry (so the measurement can be repeated), the
committed table carries one record per grid entry with the parameters and the
environment that produced it, every certification side carries one of the
statuses the script knows (a time-limited run is a status, not a missing
number), and the rendered table names every entry (issue #4026).
"""
import importlib.util
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))


def _script():
    spec = importlib.util.spec_from_file_location("cost_measure", os.path.join(_HERE, "measure.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _table():
    with open(os.path.join(_HERE, "cost_table.json"), encoding="utf-8") as f:
        return json.load(f)


def test_every_grid_entry_is_on_the_board():
    M = _script()
    slugs = [s for s, _ in M.GRID]
    assert len(slugs) == len(set(slugs))
    for slug in slugs:
        assert os.path.exists(os.path.join(_ROOT, "codes", slug + ".json")), slug
    # the cap corners the issue names are in the grid
    docs = {s: json.load(open(os.path.join(_ROOT, "codes", s + ".json"), encoding="utf-8"))
            for s in slugs}
    assert any(d["n"] == 700 for d in docs.values())
    assert any(d["n"] == 1000 for d in docs.values())
    # Distance coverage is descriptive: board bounds can be revised (#2941).
    assert any(d.get("code_type") == "stabilizer" for d in docs.values())


def test_the_committed_table_covers_the_grid_and_labels_its_limits():
    M = _script()
    t = _table()
    assert t["issue"] == 4026 and t["environment"]["cpu"] and t["environment"]["head"]
    p = t["parameters"]
    assert p["ris_trials"] > 0 and p["fast_trials"] and p["certify_tlim_s"] > 0
    by_slug = {e["slug"]: e for e in t["entries"]}
    assert set(by_slug) == {s for s, _ in M.GRID}
    for e in t["entries"]:
        g = e["gate"]
        # the refutation's 10 s cap is a wall cap checked between trials, so a
        # large entry overruns it by its last trial (42 s observed at n = 696,
        # k = 352); it is bounded, not tight
        assert g["gate_total_s"] >= 0 and g["refute_s"] <= g["refute_cap_s"] + 60
        assert e["rungs"]["submit_search_s"] >= 0
        c = e["certify"]
        if e["code_type"] == "stabilizer":
            assert c["status"] == "not_available"
        else:
            for side in ("X", "Z"):
                assert c[side]["status"] in M.CERTIFY_STATUSES, (e["slug"], side)
                if c[side]["status"] == "wall_cap":
                    assert c[side]["secs"] >= p["certify_wall_s"] - 1
    md = open(os.path.join(_HERE, "cost_table.md"), encoding="utf-8").read()
    for slug in by_slug:
        assert f"| {slug} |" in md


def test_render_names_a_time_limited_side_as_such():
    M = _script()
    tbl = {"parameters": {"ris_trials": 20000, "fast_trials": [200000, 2000000],
                          "certify_tlim_s": 60, "certify_wall_s": 120},
           "environment": {"date": "2026-10-23", "cpu": "x", "cores": 1, "python": "3",
                           "numpy": "2", "scipy": "1", "accelerator": True, "head": "abc"},
           "board_pass_cold_s": 1.0,
           "entries": [{"slug": "s-1-1", "measured_slug": "s-1-2", "code_type": "CSS", "n": 1, "k": 1, "d": 1, "w": 1,
                        "gate": {"gate_total_s": 1.0, "refute_s": 0.5},
                        "rungs": {"ris_20000_X_s": 1.0, "ris_20000_Z_s": 2.0, "fast_200000_s": 0.1,
                                  "fast_2000000_s": 1.0, "submit_search_s": 4.0},
                        "certify": {"X": {"status": "wall_cap", "secs": 120.0},
                                    "Z": {"status": "milp_tlim", "secs": 61.0, "generators": 7}}}]}
    md = M.render(tbl)
    assert "| s-1-1 |" in md and "wall cap, 120 s" in md and "MILP limit, 61.0 s (7 generators)" in md
    assert "s-1-2 -> s-1-1" in md and "original measured input" in md
