"""X/Z asymmetry column and per-side split (issue #1845).

Presentation only: the board table gets a sortable X/Z column with the ratio
max(d_X, d_Z) / min(d_X, d_Z), the per-side distances and check weights on
hover, and the code page shows the same figures. The asymmetric entry is a
rectangular planar surface code built here as the hypergraph product of two
repetition codes of different lengths, so d_X != d_Z by construction and the
test does not depend on any board file that a refutation could later remove.
"""

import importlib.util
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_site_build():
    spec = importlib.util.spec_from_file_location("site_build_asymmetry", os.path.join(ROOT, "site", "build.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def planar_surface_code(l1, l2):
    """Planar surface code as the hypergraph product of rep(l1) and rep(l2).

    Parameters [[l1*l2 + (l1-1)*(l2-1), 1, min(l1, l2)]]. Qubits 0..l1*l2-1
    form the l1 x l2 grid (index i*l2 + j); the rest form the (l1-1) x (l2-1)
    grid. The Z logical runs down one column of the first grid (weight l1)
    and the X logical along one row (weight l2), so d_Z = l1 and d_X = l2.
    """
    m1, m2 = l1 - 1, l2 - 1
    n1, n2 = l1, l2
    off = n1 * n2
    x_checks, z_checks = [], []
    for a in range(m1):  # H1 rows (bits a, a+1) x every column b
        for b in range(n2):
            sup = [a * n2 + b, (a + 1) * n2 + b]
            sup += [off + a * m2 + c for c in range(m2) if b in (c, c + 1)]
            x_checks.append(sorted(sup))
    for i in range(n1):  # every row i x H2 rows (bits c, c+1)
        for c in range(m2):
            sup = [i * n2 + c, i * n2 + c + 1]
            sup += [off + a * m2 + c for a in range(m1) if i in (a, a + 1)]
            z_checks.append(sorted(sup))
    x_logical = [0 * n2 + j for j in range(n2)]
    z_logical = [i * n2 + 0 for i in range(n1)]
    n = off + m1 * m2
    return {
        "schema_version": "0.3",
        "name": f"[[{n},1,{min(l1, l2)}]] {l1}x{l2} planar surface code",
        "code_type": "CSS",
        "n": n,
        "k": 1,
        "checks": {"X": x_checks, "Z": z_checks},
        "distance": {
            "d": min(l1, l2),
            "X": {"value": l2, "confidence": "upper_bound", "witness": x_logical},
            "Z": {"value": l1, "confidence": "upper_bound", "witness": z_logical},
        },
        "family": "topological",
        "provenance": {
            "authors": ["@example"],
            "origin": "submission",
            "construction": f"hypergraph product of rep({l1}) and rep({l2})",
            "date": "2026-01-01",
        },
    }


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


def test_asymmetric_entry_renders_ratio_and_sides(tmp_path):
    with open(os.path.join(ROOT, "verify", "fixtures", "72-6-6.json")) as f:
        symmetric = json.load(f)
    asym = planar_surface_code(3, 5)  # d_Z = 3, d_X = 5, ratio 5/3
    build = _build_board(tmp_path, {"72-6-6": symmetric, "23-1-3": asym})

    with open(os.path.join(build.DOCS, "index.html")) as f:
        index = f.read()
    assert "<th data-c=asym class=num" in index
    assert 'data-code="23-1-3"' in index
    assert 'data-asym="1.6667"' in index
    assert 'data-asym="1"' in index  # the symmetric fixture sorts as 1
    # the cell shows the ratio, and the per-side facts ride on hover
    assert 'title="d_X &le; 5, d_Z &le; 3 &middot; w_X = 4, w_Z = 4">1.67</td>' in index

    with open(os.path.join(build.DOCS, "codes", "23-1-3.html")) as f:
        page = f.read()
    assert "<div class=l>X/Z</div><div class=v>1.67</div>" in page
    assert "<b>X/Z asymmetry</b> 1.67 &middot; d_X &le; 5, d_Z &le; 3 &middot; w_X = 4, w_Z = 4" in page
    assert "<b>X-checks</b> 10 (max weight 4)" in page
    assert "Z-checks</b> 12 (max weight 4)" in page


def test_side_tiers_follow_the_certificate():
    build = load_site_build()
    doc = {"distance": {"d": 3, "X": {"value": 5}, "Z": {"value": 3}}}
    assert build.side_tiers(None, doc) == {"X": "ub", "Z": "ub"}
    cert = {"d": 3, "d_exact": True, "sides": {"X": {"value": 5, "exact": False}, "Z": {"value": 3, "exact": True}}}
    assert build.side_tiers(cert, doc) == {"X": "ub", "Z": "exact"}
    # a stale certificate (distance edited since) upgrades nothing
    stale = dict(cert, d=4)
    assert build.side_tiers(stale, doc) == {"X": "ub", "Z": "ub"}
    assert build.asym_ratio(5, 3) == build.asym_ratio(3, 5) == 1.6667
    assert build.asym_ratio(7, 7) == 1
