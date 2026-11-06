"""The recorded family-concentration measurement has to be consistent and labeled as declared.

Shares are over a frontier's records, so the top share bounds the top-two
share and the HHI sits between an even split and a single family; the moved
count is the sum of the per-cell flags; and the caveat that `family` is the
self-declared label travels inside the record (issue #4025).
"""
import glob
import importlib.util
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))


def _latest():
    paths = sorted(glob.glob(os.path.join(_HERE, "family_concentration-*.json")))
    assert paths, "a dated measurement is committed beside this test"
    with open(paths[-1], encoding="utf-8") as f:
        return json.load(f)


def _script():
    spec = importlib.util.spec_from_file_location(
        "family_concentration_script", os.path.join(_HERE, "family_concentration.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_record_is_internally_consistent():
    r = _latest()
    assert r["issue"] == 4025 and r["date"] and r["head"]
    for scope in [r["global"], *r["cells"].values()]:
        assert 0 <= scope["top1_share"] <= scope["top2_share"] <= 1
        # untagged records are in the denominator and not in the sum, so the
        # top share squared is the bound that holds, not 1/families
        assert scope["top1_share"] ** 2 - 0.002 <= scope["hhi"] <= 1
        assert scope["untagged_share"] + scope["top1_share"] <= 1.001
        assert sum(t["records"] for t in scope["top"]) <= scope["records"]
        assert len(scope["top"]) <= 2
    for c in r["cells"].values():
        assert c["records"] <= c["members"]
        assert c["untagged"] + sum(t["records"] for t in c["top"]) <= c["records"]
        assert c["moved"] == (c["incumbent"] is not None
                              and c["leader"]["family"] != c["incumbent"]["family"])
    assert r["cells_moved"] == sum(c["moved"] for c in r["cells"].values())
    assert r["cells_total"] == len(r["cells"]) >= r["cells_moved"]
    assert "self-declared" in r["caveat"]


def test_the_tables_name_every_cell():
    r = _latest()
    md = _script().markdown(r)
    assert "HHI" in md and f"Cells moved: {r['cells_moved']} of {r['cells_total']}." in md
    for key in r["cells"]:
        assert f"| {key} |" in md
