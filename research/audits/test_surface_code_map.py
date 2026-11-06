"""The finite-size map picks the smallest-n entry at each (k, d) and compares it with k d^2 surface patches."""
import glob
import importlib.util
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))


def _script():
    spec = importlib.util.spec_from_file_location("surface_code_map_script", os.path.join(_HERE, "surface_code_map.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _e(slug, n, k, d, w, loc, tier="ub", family="other", code_type="CSS"):
    return {"slug": slug, "n": n, "k": k, "d": d, "d_X": d, "d_Z": d, "w": w, "locality_class": loc,
            "tier": tier, "family": family, "code_type": code_type}


def test_best_entry_prefers_smaller_n_then_exact_then_more_logicals():
    mod = _script()
    pool = [_e("a-2-5", 30, 2, 5, 6, "unrestricted"), _e("b-1-5", 30, 1, 5, 6, "unrestricted", tier="exact"),
            _e("c-1-6", 40, 1, 6, 4, "local-2d-single")]
    assert mod.best_entry(pool, 1, 5)["slug"] == "b-1-5"        # same n: the exact distance wins
    assert mod.best_entry(pool, 1, 6)["slug"] == "c-1-6"
    assert mod.best_entry(pool, 2, 6) is None
    pool[1]["tier"] = "ub"
    assert mod.best_entry(pool, 1, 5)["slug"] == "a-2-5"        # same n and tier: more logical qubits


def test_locality_pools_nest_and_weight_caps_apply():
    mod = _script()
    single, bil, un = (_e("s", 25, 1, 5, 4, "local-2d-single"), _e("b", 20, 1, 5, 8, "local-2d-bilayer"),
                       _e("u", 10, 1, 5, 12, "unrestricted"))
    assert mod.eligible(single, "unrestricted", None) and mod.eligible(single, "local-2d-single", 4)
    assert not mod.eligible(bil, "local-2d-single", None) and not mod.eligible(bil, "local-2d-bilayer", 6)
    assert mod.eligible(bil, "local-2d-bilayer", 8) and not mod.eligible(un, "local-2d-bilayer", None)
    assert not mod.eligible(_e("st", 5, 1, 3, 3, "unrestricted", code_type="stabilizer"), "unrestricted", None)


def test_rows_compare_with_k_d_squared_and_name_every_entry_once():
    mod = _script()
    entries = [_e("25-1-5", 25, 1, 5, 4, "local-2d-single", tier="exact", family="topological"),
               _e("17-1-5", 17, 1, 5, 6, "unrestricted", tier="exact"),
               _e("44-2-10", 44, 2, 10, 8, "local-2d-bilayer")]
    rec = mod.finite_size_map(entries, k_targets=(1,), d_min=3, per_k_max=2)
    cell = {(c["track"], c["weight_cap"]): c for c in rec["cells"] if c["k"] == 1}
    row5 = [r for r in cell[("unrestricted", None)]["rows"] if r["d"] == 5][0]
    assert row5["best"] == "17-1-5" and row5["n_patches"] == 25 and row5["beats"]
    assert row5["ratio"] == round(25 / 17, 3)
    assert {"k": 1, "d": 5, "slug": "25-1-5"} in rec["board_surface"]
    row10 = [r for r in cell[("local-2d-bilayer", None)]["rows"] if r["d"] == 10][0]
    assert row10["best"] == "44-2-10" and row10["beats"]            # k' = 2 stands in for k = 1
    single = cell[("local-2d-single", 4)]
    assert single["rows"][-1]["d"] == 5 and not single["rows"][-1]["beats"]   # 25 is not < 25
    assert single["best"] is None and single["d_beating_count"] == 0
    price = [p for p in rec["locality_price"] if p["d"] == 10][0]
    assert price["unrestricted"] == "44-2-10" and price["bilayer"] == "44-2-10" and price["single"] is None
    assert rec["per_k"][1]["k"] == 2 and rec["per_k"][1]["unrestricted"]["slug"] == "44-2-10"
    assert rec["per_k"][1]["local-2d-single"] is None
    assert set(rec["entries"]) == {"25-1-5", "17-1-5", "44-2-10"} and rec["entries"]["17-1-5"]["n"] == 17
    assert "17-1-5" in mod.markdown({"generated": "today", "head": None, "entries_considered": 3, **rec})


def test_the_committed_record_matches_the_schema_and_is_self_consistent():
    paths = sorted(glob.glob(os.path.join(_HERE, "surface_code_map-*.json")))
    assert paths, "a dated record is committed beside the script"
    with open(paths[-1], encoding="utf-8") as f:
        rec = json.load(f)
    assert rec["schema"] == "qldpc-surface-code-map/1" and rec["k_targets"] == [1, 10, 25, 50, 100]
    E = rec["entries"]
    for c in rec["cells"]:
        for r in c["rows"]:
            b = E[r["best"]]
            assert r["n_patches"] == c["k"] * r["d"] ** 2
            assert b["k"] >= c["k"] and b["d"] >= r["d"]
            assert r["beats"] == (b["n"] < r["n_patches"])
        assert c["d_beating_count"] == sum(r["beats"] for r in c["rows"])
    for p in rec["locality_price"]:
        if p["bilayer"]:
            assert E[p["bilayer"]]["n"] >= E[p["unrestricted"]]["n"]
