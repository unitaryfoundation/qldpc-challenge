"""Heuristic routing cost on the site (issue #1847): shown on code pages and
as an optional sortable column on the board, labeled heuristic, never a rank;
codes without a layout get no value."""

import copy
import importlib.util
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_site_build():
    spec = importlib.util.spec_from_file_location(
        "site_build_routing", os.path.join(ROOT, "site", "build.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build(tmp_path):
    """A three-code board from one fixture: the bilayer layout as shipped, a
    cap-exceeding line layout (unrestricted with coordinates), and no layout."""
    build = load_site_build()
    with open(os.path.join(ROOT, "verify", "fixtures", "72-6-6.json")) as f:
        doc = json.load(f)
    codes = tmp_path / "codes"
    codes.mkdir()
    with open(codes / "72-6-6.json", "w") as f:
        json.dump(doc, f)
    line = copy.deepcopy(doc)
    line["name"] = "line layout"
    line["locality"] = {"coordinates": [[float(i), 0.0] for i in range(doc["n"])],
                        "layers": 1}
    with open(codes / "72-6-6-line.json", "w") as f:
        json.dump(line, f)
    bare = copy.deepcopy(doc)
    bare["name"] = "no layout"
    bare.pop("locality")
    with open(codes / "72-6-6-bare.json", "w") as f:
        json.dump(bare, f)

    build.ROOT = str(tmp_path)
    build.DOCS = str(tmp_path / "docs")
    build.CERTS = str(tmp_path / "certs")
    os.makedirs(os.path.join(build.DOCS, "codes"), exist_ok=True)
    build.build()
    return build


def _read(build, *parts):
    with open(os.path.join(build.DOCS, *parts)) as f:
        return f.read()


def test_entries_carry_the_verifier_routing_cost(tmp_path):
    build = _build(tmp_path)
    by = {e["slug"]: e for e in build.load_entries()}
    assert by["72-6-6"]["route_total"] > 0
    assert by["72-6-6"]["route_max"] <= by["72-6-6"]["route_total"]
    assert by["72-6-6-line"]["locality_class"] == "unrestricted"
    assert by["72-6-6-line"]["route_total"] > by["72-6-6"]["route_total"]
    assert by["72-6-6-bare"]["route_total"] is None
    assert by["72-6-6-bare"]["route_max"] is None


def test_code_page_shows_the_cost_labeled_heuristic(tmp_path):
    build = _build(tmp_path)
    by = {e["slug"]: e for e in build.load_entries()}
    page = _read(build, "codes", "72-6-6-line.html")
    e = by["72-6-6-line"]
    assert f'<div class=l>swaps</div><div class=v>{e["route_total"]}</div>' in page
    assert (f'{e["route_total"]} nearest-neighbor SWAPs per round in total, '
            f'at most {e["route_max"]} for one check') in page
    assert "heuristic: MST lower bound" in page
    assert "minimum qubit spacing" in page
    assert "not a rank" in page
    bare = _read(build, "codes", "72-6-6-bare.html")
    assert "<div class=l>swaps</div>" not in bare
    assert "routing cost" not in bare


def test_board_has_an_optional_sortable_swaps_column(tmp_path):
    build = _build(tmp_path)
    by = {e["slug"]: e for e in build.load_entries()}
    index = _read(build, "index.html")
    # a sortable header, hidden until the swaps toggle or an unrestricted cell
    assert 'data-c=route class="num col-route"' in index
    assert "id=routetoggle" in index
    css = _read(build, "style.css")
    assert ".board .col-route,.board col.colroute{display:none" in css
    assert ".board.showroute .col-route{display:table-cell}" in css
    assert "cell:unrestricted~" in index
    # hover text says what a nearest neighbor is and that it is not a rank
    assert "minimum qubit spacing" in index
    assert "not a rank" in index
    # each row sorts on its total; a layout-less code sorts last with a dot
    for slug in ("72-6-6", "72-6-6-line"):
        assert f'data-route="{by[slug]["route_total"]}"' in index
        assert (f'title="heuristic routing cost: {by[slug]["route_total"]} '
                'nearest-neighbor SWAPs') in index
    assert 'data-route="-1"' in index
    assert ('data-label="swaps" title="no verified layout; routing cost '
            'undefined">&middot;</td>') in index
    # the swaps>=N search term is documented and parsed
    assert "swaps&lt;=50" in index
    assert "|swaps|route|ler|asym)" in index
