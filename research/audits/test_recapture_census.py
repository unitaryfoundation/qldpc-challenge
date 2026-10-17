"""Calibration of the recapture estimator (research/audits/recapture.py, issue #2897).

Named ``test_recapture_census`` because ``verify/test_recapture.py`` tests the
record and pytest needs distinct test module names.

The issue's condition for showing anything is that the estimator's intervals
cover a known |L| on codes small enough to enumerate. The 5 x 5 toric code has
exactly ten weight-5 X-type logical operators (the five horizontal and five
vertical loops; enumerated by brute force here) in two classes, and the RIS
search at one to three trials per run finds a random handful of them, so runs
of the real search are the sampling units and the truth is known on both
units. The arithmetic is pinned separately on hand-computed cases, and the
record-reading path on records written by verify/recapture.py itself.
"""
import importlib.util
import itertools
import json
import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "verify"))

import gf2  # noqa: E402
import heuristic_distance as H  # noqa: E402


def _load(name, path):
    """Bind a module by path.

    verify/recapture.py (the record) and this directory's recapture.py (the
    estimator) share a file name.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RC = _load("verify_recapture", os.path.join(ROOT, "verify", "recapture.py"))
est = _load("audit_recapture", os.path.join(HERE, "recapture.py"))


def _toric(L=5):
    def ih(r, c):
        return (r % L) * L + (c % L)

    def iv(r, c):
        return L * L + (r % L) * L + (c % L)
    n = 2 * L * L
    HX = np.zeros((L * L, n), np.int8)
    HZ = np.zeros((L * L, n), np.int8)
    for r in range(L):
        for c in range(L):
            v = r * L + c
            for q in (ih(r, c), ih(r, c - 1), iv(r, c), iv(r - 1, c)):
                HX[v, q] ^= 1
            for q in (ih(r, c), ih(r + 1, c), iv(r, c), iv(r, c + 1)):
                HZ[v, q] ^= 1
    return HX, HZ


HX, HZ = _toric()
N = HX.shape[1]


def _truth():
    """Every weight-5 X-type logical of the 5 x 5 toric code, by brute force."""
    LZ = gf2.logical_basis(HX, HZ)
    canon = RC.Canonicalizer(HX)
    ops, classes = set(), set()
    for comb in itertools.combinations(range(N), 5):
        v = np.zeros(N, np.int8)
        v[list(comb)] = 1
        if ((HZ @ v) % 2).any() or not ((LZ @ v) % 2).any():
            continue
        ops.add(RC.operator_id(v))
        classes.add(canon.class_id(v))
    return ops, classes


TRUE_OPS, TRUE_CLASSES = _truth()


def test_the_ground_truth_is_what_the_lattice_says():
    assert len(TRUE_OPS) == 10 and len(TRUE_CLASSES) == 2


def _doc():
    return {"n": N, "k": 2, "code_type": "CSS",
            "checks": {"X": [[int(q) for q in np.nonzero(r)[0]] for r in HX],
                       "Z": [[int(q) for q in np.nonzero(r)[0]] for r in HZ]},
            "distance": {"d": 5}}


def _runs(trials, seeds):
    """One record per run of the real RIS search on the X side at ``trials`` trials."""
    recs = []
    for s in seeds:
        cap = RC.Capture(threshold=5)
        H.ris_min_logical(HX, HZ, trials=trials, seed=s, capture=cap.side("X"))
        cap.result = {"method": "ris", "trials": trials}
        recs.append(RC.entry_record(_doc(), "50-2-5", run_seed=s, file_seed=s, capture=cap, seconds=0.1,
                                    refuted=False, d_found=5, trials=trials, battery=RC.battery_of(cap)))
    return recs


# -- the arithmetic ------------------------------------------------------------

def test_chao_on_hand_computed_cases():
    # bias-corrected incidence form: S + ((m-1)/m) f1 (f1-1) / (2 (f2+1))
    e, lo, hi, var = est.chao(10, 4, 2, runs=1000)
    assert abs(e - (10 + 0.999 * 4 * 3 / 6)) < 1e-9 and 10 <= lo <= e <= hi
    e0, lo0, hi0, _ = est.chao(10, 0, 3, runs=20)        # everything seen twice or more
    assert e0 == 10 and (lo0, hi0) == (10, 10)
    e2, lo2, hi2, var2 = est.chao(6, 5, 0, runs=10)       # f2 = 0 branch
    assert e2 == pytest.approx(6 + 0.9 * 5 * 4 / 2) and var2 > 0 and lo2 >= 6 and hi2 > e2
    assert est.chao(0, 0, 0, runs=5) == (0.0, 0.0, 0.0, 0.0)
    assert est.chao(4, 4, 0, runs=1)[0] == 4.0           # one run: no estimate


def test_the_interval_cannot_fall_below_what_was_seen():
    for f1, f2, m in ((7, 1, 3), (20, 0, 5), (1, 1, 2), (3, 3, 50)):
        e, lo, hi, _ = est.chao(25, f1, f2, m)
        assert 25 <= lo <= e <= hi


# -- calibration on the toric code ------------------------------------------------

def _censuses(trials, runs, batches=20):
    """Independent censuses of the real search: (op class at w = 5, cls class at w = 5)."""
    out = []
    for batch in range(batches):
        recs = _runs(trials, range(1000 * batch, 1000 * batch + runs))
        st = est.census(recs, unit="op")["50-2-5"]["X"]["ris/py/10s"]
        assert st["runs"] == runs and st["trials"] == trials * runs
        out.append((st["classes"][5], est.census(recs, unit="cls")["50-2-5"]["X"]["ris/py/10s"]["classes"][5]))
    return out


@pytest.mark.parametrize("trials,runs", [(1, 50), (2, 30), (3, 20)])
def test_the_interval_covers_the_enumerated_truth_when_runs_recapture(trials, runs):
    """Cover the ten operators in at least sixteen of twenty censuses.

    Twenty independent censuses of the real search, in regimes where each
    operator is recaptured a few times; the class count saturates at two
    with a degenerate interval. The seeds are fixed, so this is a pin of a
    deterministic computation, not a statistical test re-rolled until it
    passes. Measured 2026-10-17: 20 of 20 in each of these three regimes.
    """
    covered = 0
    for c, cls in _censuses(trials, runs):
        assert c["S_obs"] <= 10 and not c["censored"] and c["calibrated"]
        assert c["S_obs"] <= c["estimate"] and 0 < c["coverage"] <= 1
        covered += c["ci95"][0] <= 10 <= c["ci95"][1]
        assert cls["S_obs"] <= 2 and cls["ci95"][0] <= 2 <= cls["ci95"][1]
    print(f"\n  trials={trials} runs={runs}: interval covered |L_5| = 10 in {covered}/20 censuses")
    assert covered >= 16, covered


@pytest.mark.parametrize("trials,runs", [(1, 25), (3, 10)])
def test_the_sparse_regime_is_marked_and_fails_in_both_directions(trials, runs):
    """Mark every sparse census, where the interval is not to be read.

    With one or two captures per run and few runs, the 95% interval misses
    the truth in a sizeable share of censuses (measured 2026-10-17: 10 of 20
    at one trial and 25 runs), and in both directions: a complete census
    with singletons is read as incomplete (interval above 10), and a census
    missing one operator whose bias correction vanishes (no singletons, or
    one) gets a width-zero interval at 9. The report therefore marks a class
    whose mean incidence is under MIN_MEAN_INCIDENCE as sparse, and every
    census here must carry that mark.
    """
    above = below = 0
    for c, _ in _censuses(trials, runs):
        assert not c["calibrated"], c
        if c["ci95"][0] > 10:
            above += 1
            assert c["S_obs"] == 10 and c["f1"] > 0, c
        elif c["ci95"][1] < 10:
            below += 1
            assert c["S_obs"] < 10 and c["estimate"] == c["S_obs"], c
    print(f"\n  trials={trials} runs={runs}: {above} censuses missed from above, {below} from below, "
          f"all marked sparse")
    text = est.render(est.census(_runs(trials, range(runs))))
    assert "(sparse)" in text


def test_enough_runs_saturate_and_say_so():
    recs = _runs(3, range(60))
    c = est.census(recs, unit="op")["50-2-5"]["X"]["ris/py/10s"]["classes"][5]
    assert c["S_obs"] == 10 and c["f1"] == 0 and c["estimate"] == 10 and c["ci95"] == [10, 10]


# -- reading records and reporting ---------------------------------------------

def test_strata_without_captures_report_budget_only():
    recs = _runs(1, range(3))
    for r in recs:                                     # nothing found at weight <= 5
        r["sides"]["X"].update(captured=0, w=[], op=[], cls=[])
    st = est.census(recs)["50-2-5"]["X"]["ris/py/10s"]
    assert st["classes"] == {} and "3 run(s), 3 trials" in st["note"]
    one = est.census(_runs(2, [4]))["50-2-5"]["X"]["ris/py/10s"]
    assert one["classes"] == {} and "no recapture" in one["note"]
    text = est.render(est.census(recs))
    assert "No weight class has captures" in text and "Budget only" in text


def test_runs_are_deduplicated_and_batteries_stratified():
    recs = _runs(2, range(6))
    doubled = recs + [json.loads(json.dumps(recs[0]))]              # the same run twice
    assert est.census(doubled)["50-2-5"]["X"]["ris/py/10s"]["runs"] == 6
    deep = json.loads(json.dumps(recs[1]))
    deep["battery"]["key"] = "ris/py/60s"
    deep["run_seed"] = 999
    strata = est.census(recs + [deep])["50-2-5"]["X"]
    assert set(strata) == {"ris/py/10s", "ris/py/60s"} and strata["ris/py/60s"]["runs"] == 1


def test_a_censored_class_is_marked_and_not_estimated():
    recs = _runs(2, range(6))
    recs[2]["sides"]["X"]["overflow"] = 4
    c = est.census(recs)["50-2-5"]["X"]["ris/py/10s"]["classes"][5]
    assert c["censored"] is True and c["estimate"] is None and c["ci95"] is None
    assert "(censored)" in est.render(est.census(recs))


def test_files_round_trip_including_gzip_and_a_torn_line(tmp_path):
    recs = _runs(1, range(4))
    plain = tmp_path / "a.jsonl"
    for r in recs[:2]:
        RC.append_record(str(plain), r)
    with open(plain, "a", encoding="utf-8") as f:
        f.write('{"slug": "50-2-5", "sides": {"X": {"w": [5')          # killed mid-write
    import gzip
    with gzip.open(tmp_path / "b.jsonl.gz", "wt", encoding="utf-8") as f:
        for r in recs[2:]:
            f.write(json.dumps(r) + "\n")
    loaded, skipped = est.load_records([str(plain), str(tmp_path / "b.jsonl.gz")])
    assert len(loaded) == 4 and skipped == 1
    rc = est.main(["report", str(plain), str(tmp_path / "b.jsonl.gz"), "--json", str(tmp_path / "out.json")])
    assert rc == 0
    with open(tmp_path / "out.json", encoding="utf-8") as f:
        out = json.load(f)
    assert "4 record(s)" in out["source"] and "1 unreadable" in out["source"] and "50-2-5" in out["census"]


def test_no_table_and_no_records_is_a_usage_error_not_a_report(tmp_path):
    assert est.main(["report", "--table", str(tmp_path / "none.json")]) == 2


# -- the incidence table ---------------------------------------------------------

def test_folding_accumulates_across_sweeps_and_counts_a_run_once(tmp_path):
    table_path = str(tmp_path / "incidence.json")
    week1, week2 = _runs(2, range(10)), _runs(2, range(10, 20))
    table = est.load_table(table_path)                 # none yet: a fresh table
    assert est.fold(table, week1) == 10
    assert est.fold(table, week1) == 0                 # the same runs again: nothing new
    assert est.fold(table, week2) == 10
    est.save_table(table, table_path)
    again = est.load_table(table_path)
    assert again["folded_records"] == 20 and again["updated"]
    st = again["entries"]["50-2-5"]["X"]["ris/py/10s"]
    assert len(st["runs"]) == 20 and st["trials"] == 40 and st["claimed_d"] == 5
    counts = st["classes"]["5"]["op"]
    assert sum(counts.values()) == sum(len(set(r["sides"]["X"]["op"])) for r in week1 + week2)
    # the census over the table is the census over the records
    direct = est.census(week1 + week2)["50-2-5"]["X"]["ris/py/10s"]["classes"][5]
    assert est.census_from_table(again)["50-2-5"]["X"]["ris/py/10s"]["classes"][5] == direct
    # and the CLI reports from it
    rc = est.main(["report", "--table", table_path, "--slug", "50-2-5", "--json", str(tmp_path / "o.json")])
    assert rc == 0
    with open(tmp_path / "o.json", encoding="utf-8") as f:
        assert "50-2-5" in json.load(f)["census"]


def test_the_fold_command_writes_the_table(tmp_path):
    recs = _runs(1, range(5))
    path = tmp_path / "r.jsonl"
    for r in recs:
        RC.append_record(str(path), r)
    table_path = str(tmp_path / "t" / "incidence.json")
    assert est.main(["fold", "--table", table_path, str(path)]) == 0
    assert est.main(["fold", "--table", table_path, str(path)]) == 0     # idempotent
    assert est.load_table(table_path)["folded_records"] == 5


def test_too_many_ids_censor_a_class_and_withhold_the_estimate(monkeypatch):
    monkeypatch.setattr(est, "MAX_IDS", 4)
    recs = _runs(3, range(12))
    c = est.census(recs)["50-2-5"]["X"]["ris/py/10s"]["classes"][5]
    assert c["censored"] and c["estimate"] is None and c["S_obs"] == 4
    assert ">= 4 (censored)" in est.render(est.census(recs)) and "withheld" in est.render(est.census(recs))


def test_a_table_from_another_version_is_refused(tmp_path):
    with open(tmp_path / "t.json", "w", encoding="utf-8") as f:
        json.dump({"table_version": 99}, f)
    with pytest.raises(ValueError, match="table_version"):
        est.load_table(str(tmp_path / "t.json"))
