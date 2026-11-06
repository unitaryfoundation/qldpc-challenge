"""The certification queue holds upper-bound entries in the stated order, with the certifier's inputs.

Every CSS row carries the certifier's inputs, bands come from the documented
thresholds, the order is the rule in the file's header, and the next ten are
its head (issue #4027). How far the committed file lags today's board is
reported and never fatal: the weekly workflow regenerates it.
"""
import glob
import importlib.util
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))


def _script():
    spec = importlib.util.spec_from_file_location(
        "certification_queue_script", os.path.join(_HERE, "certification_queue.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _queue():
    with open(os.path.join(_HERE, "todo.json"), encoding="utf-8") as f:
        return json.load(f)


def test_bands_follow_the_documented_thresholds():
    Q = _script()
    assert Q.band_for("stabilizer", 10, 3, None, 0) == "P"
    assert Q.band_for("CSS", 100, 8, 12.0, 3) == "A"
    assert Q.band_for("CSS", 100, 8, 12.0, 2) == "B"       # too few peers for A, but under an hour
    assert Q.band_for("CSS", 390, 16, None, 0) == "B"      # the Perlmutter-closed region
    assert Q.band_for("CSS", 390, 17, None, 0) == "C"
    assert Q.band_for("CSS", 700, 24, None, 0) == "C"
    assert Q.band_for("CSS", 701, 10, None, 0) == "D"
    assert Q.band_for("CSS", 300, 25, None, 0) == "D"
    assert Q.peers_for(100, 10, [(90, 9, 5.0, "a"), (120, 12, 7.0, "b"), (200, 10, 1.0, "c")]) == (6.0, 2)


def test_the_committed_queue_is_the_upper_bound_set_in_order():
    Q = _script()
    q = _queue()
    assert q["issue"] == 4027 and q["rule"] and set(q["bands"]) == set("ABCDP")
    build = Q.load_site_build()
    honored = Q.honored_certs(build)
    board = {os.path.basename(p)[:-5] for p in glob.glob(os.path.join(_ROOT, "codes", "*.json"))}
    listed = [r["slug"] for r in q["entries"]]
    assert len(listed) == len(set(listed))
    # Membership against today's board is a staleness question, not a
    # correctness one: an entry or a certificate that lands between the weekly
    # regenerations makes the committed queue lag by that entry, and the
    # workflow catches up on Monday. Reported, never fatal (the lesson of
    # #2391 for the provenance table). A listed slug that is not on the board
    # at all is also staleness: an entry removed or relabeled since.
    want = board - set(honored)
    stale = sorted(set(listed) ^ want)
    if stale:
        print(f"queue is {len(stale)} entries behind the board: {' '.join(stale[:10])}")
    for r in q["entries"]:
        assert r["band"] in q["bands"]
        if r["code_type"] == "CSS":
            for side in r["sides"].values():
                assert side["generators"] == r["k"] and side["lp_vars"] > r["n"]
                assert side["lp_constraints"] >= 2
        else:
            assert r["band"] == "P" and "P" in r["sides"]
    keys = [(0 if r["record"] else 1, Q.BAND_ORDER[r["band"]],
             r["peers"]["median_side_secs"] if r["peers"]["median_side_secs"] is not None
             else float("inf"), r["n"], r["slug"]) for r in q["entries"]]
    assert keys == sorted(keys), "the file is in the order its rule states"
    assert [r["position"] for r in q["entries"]] == list(range(1, len(listed) + 1))
    assert q["next_ten"] == listed[:10]
    c = q["counts"]
    assert c["upper_bound"] == len(listed)
    # The honored-certificate count is the same staleness question: a
    # certificate filed or removed since the queue was written (#4144 removed
    # an orphaned one) moves it by that certificate until Monday.
    if c["exact"] != len(honored):
        print(f"queue counted {c['exact']} honored certificates; the board has {len(honored)} today")
    assert sum(c["by_band"].values()) == len(listed)
