"""The front page's frontier map (issue #3346) draws exactly the star's own
per-cell Pareto frontier, as links that work without JavaScript.

The map must never become a fourth frontier implementation (see
verify/board_frontier_audit.py for why): its points come from
``cell_frontiers()``, the same per-cell computation ``compute_records()``
reads, and these tests pin that the drawn set, the star, and the per-entry
cell membership shipped to the client all agree.
"""

import importlib.util
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_site_build():
    spec = importlib.util.spec_from_file_location(
        "site_build_frontier", os.path.join(ROOT, "site", "build.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _entry(slug, n, k, d, w, loc="unrestricted", wc="weight-any", ct="CSS",
           tier="upper_bound", date="2026-01-01"):
    return {"slug": slug, "n": n, "k": k, "d": d, "w": w,
            "eff": round(k * d * d / n, 3), "geo": None, "model": None,
            "origin": "submission", "family": "", "date": date, "tier": tier,
            "locality_class": loc, "weight_class": wc, "code_type": ct}


# A small board with every way a code can be a record: outright (A), by a
# cheaper check (C), only through its locality cell (D), on the other board
# (E) -- and one code (B) that no cell lets through.
BOARD = [
    _entry("72-6-6", 72, 6, 6, 6, wc="weight-6"),
    _entry("72-6-5", 72, 6, 5, 6, wc="weight-6"),            # dominated by A
    _entry("72-4-8", 72, 4, 8, 4, wc="weight-4"),
    _entry("72-6-4", 72, 6, 4, 4, loc="local-2d-bilayer", wc="weight-4"),
    _entry("5-1-3", 5, 1, 3, 4, wc="weight-4", ct="stabilizer"),
]


def test_cell_frontiers_are_what_the_star_reads():
    b = load_site_build()
    fronts = b.cell_frontiers(BOARD)
    union = set().union(*fronts.values())
    assert union == b.compute_records(BOARD)
    assert 1 not in union, "a dominated code is on no cell's frontier"
    assert fronts[("unrestricted", "weight-any")] == {0, 2, 3}
    assert fronts[("local-2d-bilayer", "weight-4")] == {3}
    assert fronts[("unrestricted", "weight-4", "stabilizer")] == {4}


def test_frontier_cells_membership_matches_cell_frontiers():
    b = load_site_build()
    cells, default, member = b.frontier_cells(BOARD)
    assert cells[default][:3] == ("unrestricted", "weight-any", "CSS")
    fronts = b.cell_frontiers(BOARD)
    for ci, (L, W, T, _label) in enumerate(cells):
        key = (L, W) if T == "CSS" else (L, W, T)
        assert {i for i, m in enumerate(member) if ci in m} == fronts[key]
    # the stabilizer board's cells carry their type in the label; CSS do not
    assert all(("stabilizer" in c[3]) == (c[2] == "stabilizer") for c in cells)


def _anchors(svg):
    return re.findall(r'<a href="codes/([^"]+)\.html">', svg)


def test_frontier_map_draws_exactly_the_cell_frontier_as_links():
    b = load_site_build()
    cells, default, member = b.frontier_cells(BOARD)
    rows = [{"n": e["n"], "k": e["k"], "d": e["d"], "w": e["w"],
             "eff": e["eff"], "t": e["date"], "x": e["tier"] == "exact",
             "slug": e["slug"]}
            for i, e in enumerate(BOARD) if default in member[i]]
    svg = b.frontier_map(rows)
    assert set(_anchors(svg)) == {"72-6-6", "72-4-8", "72-6-4"}
    assert len(_anchors(svg)) == 3, "one link per record"
    # each link wraps a coloured point and a hit target carrying the tooltip
    assert svg.count("class=pt data-code=") == 3
    assert svg.count('class=hit data-code="72-4-8" data-tip="[[72,4,8]] · w=4') == 1
    # colour is the distance band, size the check weight
    assert f'fill="{b.FR_RAMP[b.d_band(8)]}"' in svg
    assert f'r="{b.fr_radius(4)}"' in svg and f'r="{b.fr_radius(6)}"' in svg
    legend = b.frontier_legend(3)
    assert legend.count("data-band=") == len(b.D_BANDS) == 7
    assert all(col in legend for col in b.FR_RAMP)


def test_d_bands_cover_every_distance():
    b = load_site_build()
    assert [b.d_band(d) for d in (1, 3, 4, 5, 6, 8, 9, 12, 13, 20, 21, 40, 41, 999)] == \
        [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6]
    assert [b.fr_radius(w) for w in (3, 4, 5, 6, 7, 8, 9, 40)] == \
        [6.0, 6.0, 5.0, 5.0, 4.0, 4.0, 3.2, 3.2]


def test_frontier_cells_default_follows_the_board():
    """A page charts one board; a stabilizer-only board defaults to ITS
    global cell rather than to a CSS cell that is not there."""
    b = load_site_build()
    cells, default, _ = b.frontier_cells([e for e in BOARD if e["code_type"] != "CSS"])
    assert cells[default][:3] == ("unrestricted", "weight-any", "stabilizer")
    assert all(c[2] == "stabilizer" for c in cells)


def test_front_page_frontier_section(tmp_path):
    """Built from the verifier fixtures (a CSS code and two stabilizer codes):
    the main page charts the CSS board only, so the section ships the map for
    the CSS global cell, the mode button, no board picker, and per-entry
    membership equal to the star."""
    build = load_site_build()
    codes = tmp_path / "codes"
    codes.mkdir()
    for name in ("72-6-6", "5-1-3", "17-1-7"):
        with open(os.path.join(ROOT, "verify", "fixtures", f"{name}.json")) as f:
            doc = json.load(f)
        doc.setdefault("provenance", {})["date"] = "2026-01-01"
        with open(codes / f"{name}.json", "w") as f:
            json.dump(doc, f)
    build.ROOT = str(tmp_path)
    build.DOCS = str(tmp_path / "docs")
    build.CERTS = str(tmp_path / "certs")
    build.build()
    entries = [e for e in build.load_entries() if e["code_type"] == "CSS"]
    index = (tmp_path / "docs" / "index.html").read_text()

    assert "data-m=frontier" in index
    assert "data-t=" not in index, "one board per page -> no board picker"
    assert "data-l=local-2d-bilayer" in index and "data-c=weight-4" in index
    plot = re.search(r'<div class="plot frplot" id=frplot>(.*?)</div>', index,
                     re.S).group(1)
    want = build.cell_frontiers(entries)[("unrestricted", "weight-any")]
    assert set(_anchors(plot)) == {entries[i]["slug"] for i in want}
    legend = re.search(r'<div class=chartlegend id=frlegend>(.*?)</div>', index,
                       re.S).group(1)
    assert legend.count("data-band=") == 7

    cells = json.loads(re.search(
        r'<script id="rccells" type="application/json">(.*?)</script>', index).group(1))
    data = json.loads(re.search(
        r'<script id="rcdata" type="application/json">(.*?)</script>', index).group(1))
    assert cells["def"] == ["unrestricted", "weight-any", "CSS"]
    assert cells["ramp"] == build.FR_RAMP
    by_slug = {r["slug"]: r for r in data}
    starred = {entries[i]["slug"] for i in build.compute_records(entries)}
    assert {s for s, r in by_slug.items() if r["fr"]} == starred
    # membership decodes through rccells to the same per-cell frontiers
    fronts = build.cell_frontiers(entries)
    for ci, (L, W, T, _lab) in enumerate(cells["cells"]):
        key = (L, W) if T == "CSS" else (L, W, T)
        assert {s for s, r in by_slug.items() if ci in r["fr"]} == \
            {entries[i]["slug"] for i in fronts[key]}
