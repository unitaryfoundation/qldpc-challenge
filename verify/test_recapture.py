"""Tests for the recapture record (verify/recapture.py, issue #2897).

SAME     A search with a capture returns exactly what it returns without one,
         seed for seed: the capture reads what consider() computed and never
         writes best.
ALL      Every nontrivial logical consider() sees at weight <= the threshold is
         kept, once per distinct vector; the Steane code's seven weight-3 X
         logicals come out as seven operators in one class.
CLASS    The class id is the same for two presentations of one logical and
         different for two classes; the operator id tells vectors apart.
CAP      Past the per-side cap new vectors are counted, not kept.
RECORD   entry_record is JSON, columnar, sorted, and carries the battery.
APPEND   append_record writes one line per entry and a run killed after k
         entries leaves k readable lines.
SWEEP    refute_board --recapture writes one record per checked entry, clean
         or refuted, none for a skipped or errored one, and the stand-in
         refuter is handed the capture.
"""
import json
import os
import subprocess
import sys
import tempfile

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gf2  # noqa: E402
import heuristic_distance as H  # noqa: E402
import recapture as RC  # noqa: E402
import refute_board as RB  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STEANE = np.array([[1, 0, 1, 0, 1, 0, 1],
                   [0, 1, 1, 0, 0, 1, 1],
                   [0, 0, 0, 1, 1, 1, 1]], dtype=np.int8)


def _toric(L=5):
    """Build the L x L toric code, qubits on edges: 2L^2 qubits, k = 2, d = L."""
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


def _doc(slug):
    with open(os.path.join(ROOT, "codes", slug + ".json"), encoding="utf-8") as f:
        return json.load(f)


# -- SAME ------------------------------------------------------------------

@pytest.mark.parametrize("slug", ["7-1-3", "72-12-6"])
def test_a_capture_does_not_change_the_search(slug):
    doc = _doc(slug)
    cap = RC.Capture(threshold=doc["distance"]["d"])
    plain = H.refute_check(doc, seed=11, max_seconds=20)
    with_cap = H.refute_check(doc, seed=11, max_seconds=20, capture=cap)
    assert plain == with_cap
    assert cap.result["verdict"] in ("corroborated", "refuted", "inconclusive")
    assert cap.captured() > 0 and set(cap.sides) == {"X", "Z"}


def test_ris_min_logical_is_the_same_with_and_without_a_sink():
    HX, HZ = _toric()
    sink = RC.SideSink(threshold=5)
    a = H.ris_min_logical(HX, HZ, trials=30, seed=3)
    b = H.ris_min_logical(HX, HZ, trials=30, seed=3, capture=sink)
    assert a[0] == b[0] and np.array_equal(a[1], b[1])
    assert sink.hits >= len(sink.found) > 0


# -- ALL and CLASS ----------------------------------------------------------

def test_every_weight_three_steane_logical_is_kept_once():
    cap = RC.Capture(threshold=3)
    H.ris_min_logical(STEANE, STEANE, trials=50, seed=1, capture=cap.side("X"))
    vectors = cap.side("X").vectors()
    canon = RC.Canonicalizer(STEANE)
    assert len(vectors) == 7 and {w for _, w in vectors} == {3}
    assert len({RC.operator_id(v) for v, _ in vectors}) == 7       # seven operators
    assert len({canon.class_id(v) for v, _ in vectors}) == 1         # one class (k = 1)
    for v, _ in vectors:                                              # each a real logical
        assert gf2.commutes(v, STEANE) and not gf2.in_rowspace(v, STEANE)
    assert cap.side("X").hits > 7                                      # recaptures were counted


def test_class_id_is_invariant_under_stabilizers_and_separates_classes():
    HX, HZ = _toric()
    canon = RC.Canonicalizer(HX)
    LX = gf2.logical_basis(HZ, HX)                   # two X-type logical classes
    assert LX.shape[0] == 2
    a, b = LX[0], LX[1]
    a_shifted = (a ^ HX[0] ^ HX[7]) % 2              # another presentation of a's class
    assert canon.class_id(a) == canon.class_id(a_shifted)
    assert canon.class_id(a) != canon.class_id(b)
    assert canon.class_id(a) != canon.class_id((a ^ b) % 2)
    assert RC.operator_id(a) != RC.operator_id(a_shifted)
    assert len(RC.operator_id(a)) == RC.ID_HEX


def test_the_canonicalizers_follow_the_code_type():
    assert set(RC.canonicalizers(_doc("7-1-3"))) == {"X", "Z"}
    stab = _doc("10-2-4")
    assert stab["code_type"] == "stabilizer" and set(RC.canonicalizers(stab)) == {"P"}
    cap = RC.Capture(threshold=stab["distance"]["d"])
    plain = H.refute_check(stab, seed=2, max_seconds=20)
    assert H.refute_check(stab, seed=2, max_seconds=20, capture=cap) == plain
    assert "P" in cap.sides and cap.side("P").found
    rec = RC.entry_record(stab, "10-2-4", run_seed=1, file_seed=2, capture=cap, seconds=1.0,
                          refuted=plain[0], d_found=plain[1], trials=plain[3], battery=RC.battery_of(cap))
    assert rec["sides"]["P"]["captured"] == len(cap.side("P").found)
    assert all(c is not None for c in rec["sides"]["P"]["cls"])


# -- CAP -----------------------------------------------------------------------

def test_past_the_cap_new_vectors_are_counted_not_kept():
    sink = RC.SideSink(threshold=5, cap=3)
    rows = np.eye(6, dtype=np.int8)
    sink.add(rows, [1] * 6)
    sink.add(rows[:2], [1, 1])                       # recaptures of kept vectors
    assert len(sink.found) == 3 and sink.overflow == 3 and sink.hits == 8


def test_a_fold_find_is_added_through_the_capture_only_under_the_threshold():
    cap = RC.Capture(threshold=3)
    cap.add_vector("X", np.array([1, 1, 1, 0, 0, 0, 0], np.int8), 3)
    cap.add_vector("X", np.array([1, 1, 1, 1, 0, 0, 0], np.int8), 4)
    cap.add_vector("Z", np.zeros(7, np.int8), 0)
    assert cap.captured() == 1 and "Z" not in cap.sides


# -- RECORD and APPEND --------------------------------------------------------

def test_entry_record_is_columnar_sorted_json_with_the_battery(tmp_path):
    doc = _doc("7-1-3")
    cap = RC.Capture(threshold=3)
    refuted, d_found, _, trials = H.refute_check(doc, seed=5, max_seconds=20, capture=cap)
    rec = RC.entry_record(doc, "7-1-3", run_seed=99, file_seed=5, capture=cap, seconds=0.42,
                          refuted=refuted, d_found=d_found, trials=trials, battery=RC.battery_of(cap))
    json.dumps(rec)                                                     # JSON-serializable
    assert rec["record_version"] == RC.RECORD_VERSION
    assert (rec["slug"], rec["run_seed"], rec["file_seed"], rec["claimed_d"]) == ("7-1-3", 99, 5, 3)
    assert rec["threshold"] == 3 and rec["cap"] == RC.DEFAULT_CAP and rec["trials"] == trials
    assert rec["battery"]["key"].startswith("ris") and rec["battery"]["key"].endswith("/py/10s")
    assert "(" not in rec["battery"]["key"] and rec["battery"]["accelerated"] is False
    x = rec["sides"]["X"]
    assert x["captured"] == 7 == len(x["w"]) == len(x["op"]) == len(x["cls"])
    assert x["w"] == sorted(x["w"]) and x["op"] == sorted(x["op"]) and len(set(x["cls"])) == 1
    path = RC.append_record(str(tmp_path / "r.jsonl"), rec)
    RC.append_record(path, rec)
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["slug"] == "7-1-3"


def test_the_battery_key_drops_the_per_entry_counts():
    cap = RC.Capture(threshold=6)
    cap.result = {"method": "ris+orbit-fold(3)", "trials": 5000, "fold_partitions": 3}
    b = RC.battery_of(cap, max_seconds=10.0)
    assert b["key"] == "ris+orbit-fold/py/10s" and b["method"] == "ris+orbit-fold(3)"
    cap.result = {"method": "ris+orbit-fold(5)+gf2_fast", "trials": 400000}
    assert RC.battery_of(cap, 10.0)["key"] == "ris+orbit-fold+gf2_fast/fast/10s"
    assert RC.battery_of(RC.Capture(threshold=1))["key"] == "ris/py/10s"   # no result yet


# -- SWEEP ---------------------------------------------------------------------

def _board(tmp, slugs):
    os.makedirs(os.path.join(tmp, "codes"), exist_ok=True)
    for slug in slugs:
        n, k, d = (int(x) for x in slug.split("-"))
        doc = {"n": n, "k": k, "code_type": "CSS",
               "checks": {"X": [[0, 1, 2, 3]], "Z": [[0, 1, 2, 3]]},
               "distance": {"d": d}}
        with open(os.path.join(tmp, "codes", slug + ".json"), "w", encoding="utf-8") as f:
            json.dump(doc, f)
    return RB.board_paths(tmp)


def test_the_sweep_writes_one_record_per_checked_entry():
    with tempfile.TemporaryDirectory() as tmp:
        paths = _board(tmp, ["4-2-2", "4-1-2", "4-0-2"])
        rec_path = os.path.join(tmp, "runs.jsonl")
        handed = []

        def refuter(doc, seed, capture=None):
            handed.append(capture)
            if doc["k"] == 0:
                raise RuntimeError("boom")
            capture.add_vector("X", np.array([1, 1, 0, 0], np.int8), 2)
            refuted = doc["k"] == 1
            return refuted, 1 if refuted else None, [0] if refuted else None, 10

        rep = RB.refute_paths(paths, 77, root=tmp, refute=refuter, out=lambda *_: None,
                              recapture=rec_path)
        assert rep["checked"] == 2 and len(rep["errored"]) == 1 and rep["recorded"] == 2
        assert all(isinstance(c, RC.Capture) for c in handed) and len(handed) == 3
        with open(rec_path, encoding="utf-8") as f:
            recs = [json.loads(line) for line in f]
        assert [r["slug"] for r in recs] == ["4-1-2", "4-2-2"]     # board order: ties by name
        assert [r["refuted"] for r in recs] == [True, False]
        assert all(r["run_seed"] == 77 and r["file_seed"] == RB.file_seed(77, f"codes/{r['slug']}.json")
                   for r in recs)
        assert recs[0]["sides"]["X"]["captured"] == 1 and recs[0]["threshold"] == 2
        # without --recapture the stand-in is called as before, with no capture
        plain = []
        RB.refute_paths(paths[:1], 1, root=tmp, refute=lambda doc, seed: plain.append(seed) or (False, None, None, 1),
                        out=lambda *_: None)
        assert plain and rep["recapture"] == rec_path


def test_a_run_killed_after_two_entries_keeps_two_lines():
    with tempfile.TemporaryDirectory() as tmp:
        paths = _board(tmp, ["4-2-2", "4-1-2", "4-3-2"])
        rec_path = os.path.join(tmp, "runs.jsonl")
        calls = []

        def refuter(doc, seed, capture=None):
            calls.append(1)
            if len(calls) == 3:
                raise RB._Stopped("SIGTERM")
            return False, None, None, 10

        rep = RB.refute_paths(paths, 5, root=tmp, refute=refuter, out=lambda *_: None, recapture=rec_path)
        assert rep["stopped_by"] == "SIGTERM" and rep["recorded"] == 2 and len(rep["unreached"]) == 1
        with open(rec_path, encoding="utf-8") as f:
            assert len(f.read().splitlines()) == 2


def test_the_cli_flag_reaches_the_file():
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(ROOT, "codes", "7-1-3.json"), encoding="utf-8") as f:
            doc = json.load(f)
        os.makedirs(os.path.join(tmp, "codes"))
        with open(os.path.join(tmp, "codes", "7-1-3.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f)
        rec_path = os.path.join(tmp, "runs.jsonl")
        proc = subprocess.run([sys.executable, os.path.join(ROOT, "verify", "refute_board.py"),
                               "--root", tmp, "--scope", "all", "--seed", "3", "--recapture", rec_path],
                              capture_output=True, text=True, check=False)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "1 entry record(s) appended" in proc.stdout
        with open(rec_path, encoding="utf-8") as f:
            rec = json.loads(f.readline())
        assert rec["slug"] == "7-1-3" and rec["sides"]["X"]["captured"] == 7
