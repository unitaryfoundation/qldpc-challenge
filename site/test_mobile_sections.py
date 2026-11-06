"""Phone layout of the main page's sections (issue #3931).

A phone showed four things a desktop did not: the whole (n, k, LER) frontier,
two dozen rows of three lines each; the stabilizer-board card below it; every
code card within the default weight, because the Show-all cap from issue #336
tested for "every row shown" while the weight slider loads at BOARD_DEFAULT_W
(#2132); and the how-to-contribute cards only after all of that. The cap runs
in the browser, so this file pins the markup and the condition it is built
from; the layout itself was measured at 390 px in headless Chrome.
"""

import copy
import importlib.util
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_site_build():
    spec = importlib.util.spec_from_file_location(
        "site_build_mobile_sections", os.path.join(ROOT, "site", "build.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture(name):
    with open(os.path.join(ROOT, "verify", "fixtures", name)) as f:
        return json.load(f)


def _build_board(tmp_path, docs):
    build = load_site_build()
    codes = tmp_path / "codes"
    codes.mkdir()
    for slug, doc in docs.items():
        with open(codes / f"{slug}.json", "w") as f:
            json.dump(doc, f)
    build.ROOT = str(tmp_path)
    build.DOCS = str(tmp_path / "docs")
    build.CERTS = str(tmp_path / "certs")
    build.build()
    with open(os.path.join(build.DOCS, "index.html"), encoding="utf-8") as f:
        return build, f.read()


def _ler_entry(i, rate):
    """The fields ler_frontier_panel reads, for one frontier row."""
    return {"slug": f"c{i}", "n": 10 + i, "k": 1, "d": 3, "w": 4,
            "ler": rate, "ler_key": (0.005, "bposd-cs-10"),
            "ler_points": {"X": [{"ler_per_round": rate}],
                           "Z": [{"ler_per_round": rate}]},
            "ler_by_p": {0.005: rate}, "d_circ": None,
            "authors_list": ["@someone"]}


def _with_ler(doc):
    """A CSS fixture with a measured tier: one gate point per side."""
    doc = copy.deepcopy(doc)
    doc["schema_version"] = "0.5"   # the measured tier's curves need 0.5
    point = {"p": 0.005, "shots": 10000, "failures": 100, "seed": 1,
             "decoder": "bposd-cs-10", "ler_per_round": 0.01,
             "ci95": [0.009, 0.011]}
    side = {"value": 6, "confidence": "upper_bound",
            "witness": [0, 1, 2, 3, 4, 5]}
    doc["circuit"] = {"d_circ": {"X": side, "Z": dict(side)},
                      "rounds": 6, "stim_version": "1.16.0",
                      "ler": {"X": [point], "Z": [dict(point)]}}
    return doc


def test_ler_frontier_gets_a_phone_cap_only_past_the_cap_rows():
    build = load_site_build()
    cap = build.LER_PHONE_ROWS
    long = [_ler_entry(i, 0.1 - 0.01 * i) for i in range(cap + 2)]
    html = build.ler_frontier_panel(long, set(range(len(long))))
    assert html.count("<li>") == cap + 2
    assert 'class="showall lershow"' in html
    assert f"Show all {cap + 2} codes" in html
    # the button only opens the section; the rows past the cap are hidden by
    # the stylesheet, on phones alone, until it does
    assert 'classList.add("open")' in html
    assert (f".lerfront:not(.open) .latestlist li:nth-child(n+{cap + 1})"
            "{display:none}") in build.CSS
    assert ".lerfront.open .showall{display:none}" in build.CSS

    short = long[:cap]
    html = build.ler_frontier_panel(short, set(range(len(short))))
    assert html.count("<li>") == cap
    assert "lershow" not in html


def test_stabilizer_card_precedes_the_ler_frontier(tmp_path):
    _, index = _build_board(tmp_path, {
        "72-6-6": _with_ler(_fixture("72-6-6.json")),
        "5-1-3": _fixture("5-1-3.json")})
    card = index.index("<div class=xboard>")
    frontier = index.index("<section class=\"latest lerfront\" id=lerfront>")
    board = index.index("<section id=board>")
    assert card < frontier < board
    # the three steps still follow the board, and the newest codes close it
    assert board < index.index("<div class=how>") < index.index(
        "<section class=latest><h2 class=track>Recently added")


def test_card_cap_keys_off_the_loaded_filters():
    """The weight slider loads at BOARD_DEFAULT_W, so "every row shown" is
    false at load and the #336 cap never applied; the loaded filter state is
    the baseline now, read from the inputs' defaultValue so a browser that
    restores form state on reload does not move it."""
    build = load_site_build()
    assert "function atdefault()" in build.JS
    assert "el.value===el.defaultValue" in build.JS
    assert "(shown===rows.length||atdefault())" in build.JS
    # the button names what it will reveal, not the whole board
    assert "showall.textContent='Show all '+shown+' codes'" in build.JS
