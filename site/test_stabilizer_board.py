"""The general stabilizer leaderboard (issue #2131).

Stabilizer entries render on docs/stabilizer.html and never on the CSS board;
their code page shows one Pauli-weight distance, the witness as a Pauli
string, and the generators as Pauli strings. Fixtures: the [[5,1,3]] code the
verifier ships and the CSS [[72,6,6]] fixture, so nothing here depends on a
board file a refutation could later remove.
"""

import importlib.util
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_site_build():
    spec = importlib.util.spec_from_file_location(
        "site_build_stabilizer", os.path.join(ROOT, "site", "build.py"))
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
    return build


def _read(build, *parts):
    with open(os.path.join(build.DOCS, *parts), encoding="utf-8") as f:
        return f.read()


def test_stabilizer_entries_render_on_their_own_board(tmp_path):
    build = _build_board(tmp_path, {"72-6-6": _fixture("72-6-6.json"),
                                    "5-1-3": _fixture("5-1-3.json")})
    index = _read(build, "index.html")
    stab = _read(build, "stabilizer.html")

    # the CSS board lists only the CSS code, and points at the other board
    assert 'data-code="72-6-6"' in index
    assert 'data-code="5-1-3"' not in index
    assert 'href="stabilizer.html"' in index
    assert "1 verified code," in index

    # the stabilizer board lists only the stabilizer code, in its own cells,
    # without the X/Z asymmetry column the CSS board has
    assert 'data-code="5-1-3"' in stab
    assert 'data-code="72-6-6"' not in stab
    assert "<th data-c=asym" in index
    assert "<th data-c=asym" not in stab
    assert 'data-asym="-1"' in stab
    assert 'href="codes/5-1-3.html"' in stab   # the tracks grid lists it
    assert 'href="index.html"' in stab
    assert "1 total, 1 records" in stab

    # both boards' codes are served by id, tagged with their type
    manifest = json.loads(_read(build, "codes", build.INDEX_MANIFEST))
    by_id = {c["id"]: c for c in manifest["codes"]}
    assert by_id["5-1-3"]["code_type"] == "stabilizer"
    assert by_id["72-6-6"]["code_type"] == "CSS"

    stats = json.loads(_read(build, "stats.json"))
    assert stats["verified_codes"] == 2
    assert stats["css_codes"] == 1 and stats["stabilizer_codes"] == 1


def test_stabilizer_code_page_shows_pauli_weight_and_generators(tmp_path):
    doc = _fixture("5-1-3.json")
    build = _build_board(tmp_path, {"5-1-3": doc})
    page = _read(build, "codes", "5-1-3.html")

    assert 'href="../stabilizer.html"' in page
    assert ">stabilizer</span>" in page
    # one distance, Pauli weight, no sides
    assert "<b>d</b> 3 &middot; witness Pauli weight 3" in page
    assert "X/Z asymmetry" not in page
    assert "d_X" not in page and "d_Z" not in page
    assert "Pauli-weight certifier is not built yet" in page
    # the witness and every generator as Pauli strings
    wit = doc["distance"]["P"]["witness"]
    assert build.pauli_string(wit, 5) in page
    assert "<h3>Stabilizer generators</h3>" in page
    for g in doc["checks"]["S"]:
        assert build.pauli_string(g, 5) in page
    assert "H_X" not in page and "H_Z" not in page
    # diagnostics come from the one generator Tanner graph (side S)
    assert "<b>girth</b> S " in page

    # the download artifact is the submission itself
    assert json.loads(_read(build, "codes", "5-1-3.json")) == doc


def test_stabilizer_board_has_its_own_headline_cards_and_leaderboard(tmp_path):
    """The stabilizer page carries the stats bar and the contributor
    leaderboard the CSS board has, over its own entries: a handle that only
    submitted a stabilizer code ranks there and nowhere on the CSS board."""
    stab_doc = _fixture("5-1-3.json")
    stab_doc["provenance"] = dict(stab_doc["provenance"], authors=["@stabber"],
                                  origin="submission", date="2026-10-01")
    css_doc = _fixture("72-6-6.json")
    css_doc["provenance"] = dict(css_doc["provenance"], authors=["@csser"],
                                 origin="submission", date="2026-10-01")
    build = _build_board(tmp_path, {"72-6-6": css_doc, "5-1-3": stab_doc})
    index = _read(build, "index.html")
    stab = _read(build, "stabilizer.html")

    assert "<section class=statsbar>" in stab
    assert "best kd&sup2;/n at w &le;" in stab
    assert "1 codes on the board" in stab or "<b>1</b><span>codes on the board" in stab
    assert "id=leaderboard" in stab
    assert 'data-h="@stabber"' in stab and 'data-h="@csser"' not in stab
    assert 'data-h="@csser"' in index and 'data-h="@stabber"' not in index
    # the Participate modal asks for the symplectic matrix, not H_X / H_Z
    assert "key s, or a and b" in stab and "keys hx, hz" not in stab
    assert "keys hx, hz" in index
    # no layout, so no g: the headline card shows the dot, the row the dot
    assert "has no code with a verifier-accepted layout" in stab


def test_pauli_string_marks_y_once():
    build = load_site_build()
    assert build.pauli_string({"X": [0, 2], "Z": [2, 3]}, 5) == "XIYZI"


def test_empty_stabilizer_board_still_renders(tmp_path):
    build = _build_board(tmp_path, {"72-6-6": _fixture("72-6-6.json")})
    stab = _read(build, "stabilizer.html")
    assert "No stabilizer entries yet" in stab
    assert "0 verified codes," in _read(build, "index.html")


def test_stats_carry_the_novelty_split_and_the_census_shows_it(tmp_path):
    """The board publishes how much of its novelty field has been audited.

    provenance.novelty is the only field that says whether a code is new
    (issue #4024): the split and the audited count go to stats.json, and the
    count sits on the stats bar's census beside the certified-exact count.
    """
    css_doc = _fixture("72-6-6.json")
    css_doc["provenance"] = dict(css_doc["provenance"], novelty="known_parameters")
    stab_doc = _fixture("5-1-3.json")          # no novelty field: unaudited
    build = _build_board(tmp_path, {"72-6-6": css_doc, "5-1-3": stab_doc})

    stats = json.loads(_read(build, "stats.json"))
    assert stats["novelty"] == {"unknown": 1, "known_parameters": 1,
                                "new_parameters": 0}
    assert stats["novelty_audited"] == 1

    index = _read(build, "index.html")
    stab = _read(build, "stabilizer.html")
    assert "<b>1</b><span>novelty audited</span>" in index
    assert "<b>0</b><span>novelty audited</span>" in stab
    assert "<span>certified exact</span>" in index and "<span>certified exact</span>" in stab
