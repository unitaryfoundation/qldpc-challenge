"""Check that the verifier's diagnostics (issue #1844) reach the rendered site.

Sortable girth and witness-diameter columns on the board table and a
diagnostics section on the code page, with the ranking untouched.
"""

import importlib.util
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_site_build():
    spec = importlib.util.spec_from_file_location("site_build_diagnostics", os.path.join(ROOT, "site", "build.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_diagnostics_render_and_sort(tmp_path):
    build = load_site_build()
    with open(os.path.join(ROOT, "verify", "fixtures", "72-6-6.json")) as f:
        doc = json.load(f)
    codes = tmp_path / "codes"
    codes.mkdir()
    with open(codes / "72-6-6.json", "w") as f:
        json.dump(doc, f)
    build.ROOT = str(tmp_path)
    build.DOCS = str(tmp_path / "docs")
    build.CERTS = str(tmp_path / "certs")
    build.build()

    entries = build.load_entries()
    assert len(entries) == 1
    e = entries[0]
    diag = e["diag"]
    assert e["girth"] == min(diag["tanner_girth"].values())
    assert e["ldiam"] == max(diag["logical_diameter"].values())

    index = (tmp_path / "docs" / "index.html").read_text()
    assert "data-c=girth" in index and "data-c=ldiam" in index
    row = re.search(r'<tr class="[^"]*" data-href="codes/72-6-6.html"[^>]*>', index).group(0)
    assert f'data-girth="{e["girth"]}"' in row
    assert f'data-ldiam="{e["ldiam"]}"' in row
    # the ranking inputs are what they were: the row's eff attribute is
    # untouched and the record star still comes from the Pareto frontier
    assert f'data-eff="{e["eff"]}"' in row and 'data-record="1"' in row

    page = (tmp_path / "docs" / "codes" / "72-6-6.html").read_text()
    assert "<h3>Diagnostics</h3>" in page
    assert f"H_X {diag['tanner_girth']['X']}" in page
    assert "trapping sets H_X" in page and "trapping sets H_Z" in page
    assert "witness diameter" in page
    assert str(diag["logical_diameter"]["X"]) in page


def test_summaries_handle_missing_data():
    build = load_site_build()
    assert build.ts_summary(None) == ""
    assert build.ts_summary({"counts": [[1, 3, 5], [2, 4, 9], [2, 2, 1]]}) == "(1,3)×5 (2,2)×1"
    assert build.side_girth({"tanner_girth": {"X": "acyclic"}}, "X") == "acyclic"
    assert build.side_girth({}, "Z") == "&middot;"
    e = {"diag": {"tanner_girth": {"X": 6, "Z": "acyclic"}}, "ldiam": None}
    assert "H_Z girth acyclic" in build.girth_cell_title(e)
    assert "no verified layout" in build.ldiam_cell_title(e)


def test_the_recipe_at_other_sizes_block_is_display_only(tmp_path):
    """Render one lifted recipe's per-size verdicts with the caveat, and nothing otherwise.

    Issue #4031: the block is display-only and absent for a recipe that was
    not lifted.
    """
    import importlib.util
    import os
    spec = importlib.util.spec_from_file_location(
        "site_build_multisize", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                             "site", "build.py"))
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    rec = {"status": "lifted", "constructor": "bb.build_bb", "rule": "l +- 1", "passed": 1, "tried": 2,
           "reproduces_entry": True, "own": {"n": 144, "k": 12, "w": 6},
           "sizes": [{"label": "l=6, m=6", "n": 72, "k": 12, "w": 6, "components": 1, "pass": True,
                      "checks": {"commutes": True, "encodes": True, "connected": True, "within_caps": True}},
                     {"label": "l=13, m=6", "n": 156, "k": 0, "w": 6, "components": 1, "pass": False,
                      "checks": {"commutes": True, "encodes": False, "connected": True, "within_caps": True}}]}
    html_out = build.multisize_block(rec)
    assert "Recipe at other sizes" in html_out and "passes at</b> 1 of 2 sizes" in html_out
    assert "[[72,12]] w=6, passes" in html_out and "[[156,0]] w=6, fails: k = 0" in html_out
    assert "no distance at any size" in html_out and "rebuilds this entry" in html_out
    assert build.multisize_block({"status": "no_lift_rule"}) == "" and build.multisize_block(None) == ""
