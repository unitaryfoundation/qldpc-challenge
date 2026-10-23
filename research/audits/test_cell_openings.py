"""The openings record names the earliest member of each cell and family, as history and not a flag."""
import glob
import importlib.util
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))


def _script():
    spec = importlib.util.spec_from_file_location("cell_openings_script", os.path.join(_HERE, "cell_openings.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _entry(slug, date, family, origin="submission", modular=False, geo_dim=None):
    return {"slug": slug, "date": date, "family": family, "origin": origin, "n": 10, "k": 1, "d": 2,
            "modular": modular, "geo_dim": geo_dim}


def test_the_first_member_is_by_date_then_slug_and_per_family():
    mod = _script()
    entries = [_entry("b-1-1", "2026-02-01", "tile"), _entry("a-1-1", "2026-02-01", "tile"),
               _entry("c-1-1", "2026-01-01", "topological", origin="baseline", geo_dim=3),
               _entry("d-1-1", "2026-03-01", "lifted-product", modular=True)]
    cells = {("unrestricted", "weight-any"): [0, 1, 2, 3], ("unrestricted", "weight-4"): [0, 1]}
    out = mod.openings(entries, cells)
    big = out["unrestricted~weight-any"]
    assert big["first"]["slug"] == "c-1-1" and big["members"] == 4
    assert big["first_by_declared_family"]["tile"]["slug"] == "a-1-1"      # same date: slug breaks the tie
    assert big["first_modular"]["slug"] == "d-1-1" and big["first_3d_layout"]["slug"] == "c-1-1"
    small = out["unrestricted~weight-4"]
    assert small["first"]["slug"] == "a-1-1" and small["first_modular"] is None


def test_the_committed_record_is_consistent_and_labeled_as_history():
    paths = sorted(glob.glob(os.path.join(_HERE, "cell_openings-*.json")))
    assert paths, "a dated record is committed beside the script"
    with open(paths[-1], encoding="utf-8") as f:
        r = json.load(f)
    assert r["issue"] == 4029 and "not a property of a code" in r["caveat"]
    c = r["counts"]
    assert c["cells"] == len(r["cells"]) and c["distinct_cell_openers"] <= c["cells"]
    for key, v in r["cells"].items():
        assert v["first"]["slug"] in {x["slug"] for x in v["first_by_declared_family"].values()}
        assert v["first"]["family"] in v["first_by_declared_family"]
    md = _script().markdown(r)
    assert all(f"| {key} |" in md for key in r["cells"])
