"""Layout flags and diagnostics on the rendered site (issue #1846)."""

import copy
import importlib.util
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_site_build():
    spec = importlib.util.spec_from_file_location(
        "site_build_layout_flags", os.path.join(ROOT, "site", "build.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture():
    with open(os.path.join(ROOT, "verify", "fixtures", "72-6-6.json")) as f:
        return json.load(f)


def _build(tmp_path, docs):
    """Run the full build against a board holding the given documents."""
    build = load_site_build()
    codes = tmp_path / "codes"
    codes.mkdir()
    for slug, doc in docs.items():
        with open(codes / f"{slug}.json", "w") as f:
            json.dump(doc, f)
    build.ROOT = str(tmp_path)
    build.DOCS = str(tmp_path / "docs")
    build.CERTS = str(tmp_path / "certs")
    os.makedirs(os.path.join(build.DOCS, "codes"), exist_ok=True)
    build.build()
    return build


def _read(build, *parts):
    with open(os.path.join(build.DOCS, *parts)) as f:
        return f.read()


def test_modular_flag_and_diagnostics_render(tmp_path):
    plain = _fixture()
    modular = copy.deepcopy(plain)
    modular["schema_version"] = "0.3"
    modular["name"] = "modular copy"
    modular["locality"]["modules"] = [
        0 if c[1] < 3 else 1 for c in modular["locality"]["coordinates"]]
    build = _build(tmp_path, {"72-6-6": plain, "72-6-6-mod": modular})

    index = _read(build, "index.html")
    # exactly one row carries the chip and the search term; the tab appears
    assert index.count('class="tchip mod"') == 1
    assert 'data-q="modular"' in index
    assert "2 modules" in index

    page = _read(build, "codes", "72-6-6-mod.html")
    assert "<h3>Modular layout</h3>" in page
    assert "<b>modules</b> 2" in page
    assert "<b>max ports per module</b> 1" in page
    assert "cross-module checks" in page
    assert 'class=modtable' in page

    plain_page = _read(build, "codes", "72-6-6.html")
    assert "Modular layout" not in plain_page
    assert 'class="tchip mod"' not in plain_page


def test_modular_flag_leaves_scores_alone(tmp_path):
    plain = _fixture()
    modular = copy.deepcopy(plain)
    modular["schema_version"] = "0.3"
    modular["locality"]["modules"] = [3] * modular["n"]
    build = load_site_build()
    import sys
    sys.path.insert(0, os.path.join(ROOT, "verify"))
    import qldpc_verify
    a, b = qldpc_verify.verify(plain), qldpc_verify.verify(modular)
    assert a["computed"]["locality_class"] == b["computed"]["locality_class"]
    n, k, d = plain["n"], plain["k"], plain["distance"]["d"]
    assert (build.geo_score(plain, n, k, d, "x")
            == build.geo_score(modular, n, k, d, "x"))


PLAQUETTE = {
    "schema_version": "0.1",
    "name": "[[4,2,2]] plaquette",
    "code_type": "CSS",
    "n": 4,
    "k": 2,
    "checks": {"X": [[0, 1, 2, 3]], "Z": [[0, 1, 2, 3]]},
    "distance": {
        "d": 2,
        "X": {"value": 2, "confidence": "upper_bound", "witness": [0, 1]},
        "Z": {"value": 2, "confidence": "upper_bound", "witness": [0, 1]},
    },
    "provenance": {"authors": ["@test"], "construction": "one plaquette"},
    "locality": {"coordinates": [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]],
                 "layers": 1},
}


def _lift_to_3d(doc):
    d = copy.deepcopy(doc)
    seen, coords = {}, []
    for c in d["locality"]["coordinates"]:
        z = seen.get(tuple(c), 0)
        seen[tuple(c)] = z + 1
        coords.append([float(c[0]), float(c[1]), float(z)])
    d["locality"]["coordinates"] = coords
    d["locality"]["layers"] = 1
    d["locality"].pop("interaction_radius", None)
    return d


def test_geometric_efficiency_by_dimension():
    """D = 3 (issue #1849): g = 2 sqrt(2) kd/(n rho r^3); the [[4,2,2]]
    plaquette is the stated reference at 1, and D = 2 is unchanged."""
    import math
    build = load_site_build()
    g, r, rho = build.geo_score(PLAQUETTE, 4, 2, 2, "unrestricted")
    assert abs(g - 1.0) < 1e-12 and abs(r - math.sqrt(2)) < 1e-12 and rho == 1
    # the same code with planar coordinates keeps its D = 2 value
    flat = copy.deepcopy(PLAQUETTE)
    flat["locality"]["coordinates"] = [c[:2] for c in flat["locality"]["coordinates"]]
    g2, _, _ = build.geo_score(flat, 4, 2, 2, "unrestricted")
    assert abs(g2 - 2.0) < 1e-12
    assert build.layout_dimension(flat) == 2 and build.layout_dimension(PLAQUETTE) == 3

    plain = _fixture()
    n, k, d = plain["n"], plain["k"], plain["distance"]["d"]
    g2, r2, rho2 = build.geo_score(plain, n, k, d, "x")
    assert abs(g2 - 4.0 * k * d * d / (n * rho2 ** 2 * r2 ** 4)) < 1e-12
    lifted = _lift_to_3d(plain)
    g3, r3, rho3 = build.geo_score(lifted, n, k, d, "x")
    assert rho3 == 1 and r3 > r2
    assert abs(g3 - 2 * math.sqrt(2) * k * d / (n * r3 ** 3)) < 1e-12

    mixed = copy.deepcopy(lifted)
    mixed["locality"]["coordinates"][0] = mixed["locality"]["coordinates"][0][:2]
    assert build.geo_score(mixed, n, k, d, "x") == (None, None, None)
    assert build.layout_svg(lifted) is None and build.layout_svg(plain)


def test_3d_layout_renders(tmp_path):
    plain = _fixture()
    lifted = _lift_to_3d(plain)
    lifted["name"] = "3D copy"
    build = _build(tmp_path, {"72-6-6": plain, "72-6-6-3d": lifted})
    index = _read(build, "index.html")
    assert index.count("3D layout, g = ") == 1
    page = _read(build, "codes", "72-6-6-3d.html")
    assert "<h3>Verified 3D layout</h3>" in page
    assert "<b>bounding box</b> 5.0 &times; 5.0 &times; 1.0" in page
    assert "Verified 2D layout" not in page
    assert "Verified 2D layout" in _read(build, "codes", "72-6-6.html")
