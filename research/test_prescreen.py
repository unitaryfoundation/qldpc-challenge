"""Tests for the pre-gate checks (issue #3620).

The checks exist to skip gate runs whose outcome is already decided, so the
property that matters is that they decide exactly what the gate decides and
nothing more: a direct sum is refused the way the gate refuses it, an exact
board duplicate is recognized by the gate's own fingerprint, a WL match is
flagged and never dropped by default, and a connected code the board does
not hold passes through untouched. The board itself is injected, except in
the one test that pins the real index to the quickstart's documented
duplicate.
"""
import json
import os
import subprocess
import sys

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "kit"))

import prescreen as P
import qldpc_verify  # prescreen put verify/ on the path
import search as S
from bb import build_bb
from submit import make_submission

STEANE = np.array([[1, 0, 1, 0, 1, 0, 1],
                   [0, 1, 1, 0, 0, 1, 1],
                   [0, 0, 0, 1, 1, 1, 1]], dtype=np.int8)
REVERSED = STEANE[:, ::-1].copy()          # a qubit permutation of Steane
BB72 = build_bb(6, 6, [(3, 0), (0, 1), (0, 2)], [(0, 3), (1, 0), (2, 0)])
TWO_STEANES = P.direct_sum(STEANE, STEANE)


def _index_of(*named):
    """Build an injected board index: (name, HX, HZ) triples in board_index()'s shape."""
    out = []
    for name, HX, HZ in named:
        ident = P.identity(HX, HZ)
        out.append({"name": name, "n": int(np.asarray(HX).shape[1]), "k": 0,
                    "d": 0, "fingerprints": {ident["fingerprint"]},
                    "signatures": {ident["signature"]}})
    return out


STEANE_INDEX = _index_of(("7-1-3.json", STEANE, STEANE))


def test_one_code_is_one_block():
    st = P.block_structure(STEANE, STEANE)
    assert st == {"tanner_components": 1, "blocks": 1, "block_sizes": [7],
                  "connected": True}
    assert P.describe_structure(st) == "one connected code"


def test_a_direct_sum_is_counted_block_by_block():
    st = P.block_structure(TWO_STEANES, TWO_STEANES)
    assert (st["tanner_components"], st["blocks"], st["block_sizes"]) == (2, 2, [7, 7])
    assert not st["connected"]
    assert "2 independent block(s)" in P.describe_structure(st)


def test_a_redundant_cross_block_row_joins_the_graph_but_not_the_code():
    """Pin why the row-space count exists.

    One check spanning both blocks makes the Tanner graph connected without
    making the code one code.
    """
    bridge = (TWO_STEANES[0] ^ TWO_STEANES[3])[None, :]
    HX = np.concatenate([TWO_STEANES, bridge], axis=0)
    st = P.block_structure(HX, TWO_STEANES)
    assert st["tanner_components"] == 1
    assert st["blocks"] == 2
    assert not st["connected"]


def test_identity_is_the_verifiers_own():
    doc = make_submission(STEANE, STEANE, name="[[7,1,3]] Steane",
                          construction="Hamming", authors=["@test"], trials=200)
    rep = qldpc_verify.verify(doc, refute=False)
    ident = P.identity(STEANE, STEANE)
    assert ident["fingerprint"] == rep["fingerprint"]
    assert ident["fingerprint"] == S.fingerprint(STEANE, STEANE)
    assert ident["signature"] == rep["signature"]["hash"]


def test_lookup_distinguishes_an_exact_duplicate_from_a_permutation():
    assert P.lookup(P.identity(STEANE, STEANE), STEANE_INDEX) == {
        "exact": "7-1-3.json", "wl": None}
    ident = P.identity(REVERSED, REVERSED)
    assert ident["fingerprint"] != P.identity(STEANE, STEANE)["fingerprint"]
    assert ident["signature"] == P.identity(STEANE, STEANE)["signature"]
    assert P.lookup(ident, STEANE_INDEX) == {"exact": None, "wl": "7-1-3.json"}
    assert P.lookup(P.identity(*BB72), STEANE_INDEX) == {"exact": None, "wl": None}


def test_prescreen_verdict_names_what_the_gate_would_say():
    v = P.prescreen(TWO_STEANES, TWO_STEANES, index=STEANE_INDEX)
    assert v["gate_would_refuse"]
    assert v["reasons"][0].startswith("not one code: ")
    v = P.prescreen(STEANE, STEANE, index=STEANE_INDEX)
    assert v["reasons"] == ["duplicate: identical to board entry 7-1-3.json"]
    v = P.prescreen(REVERSED, REVERSED, index=STEANE_INDEX)
    assert not v["gate_would_refuse"]
    assert v["labels"] == ["possibly equivalent (same WL signature) to 7-1-3.json"]
    v = P.prescreen(*BB72, index=STEANE_INDEX, board=False)
    assert v["board"] == {"exact": None, "wl": None} and not v["reasons"]


CANDIDATES = [("steane", STEANE, STEANE), ("permuted", REVERSED, REVERSED),
              ("sum", TWO_STEANES, TWO_STEANES), ("bb", *BB72),
              ("steane again", STEANE, STEANE)]


def test_screen_drops_what_the_gate_would_refuse_and_flags_the_rest():
    audit = {}
    recs = S.screen(CANDIDATES, trials=100, seed=0, index=STEANE_INDEX,
                    audit=audit)
    assert {r["spec"] for r in recs} == {"permuted", "bb"}
    assert audit["candidates"] == 5
    assert audit["rejected_repeat"] == 1
    assert audit["rejected_disconnected"] == 1
    assert audit["rejected_board_exact"] == 1
    assert audit["flagged_board_wl"] == 1 and audit["rejected_board_wl"] == 0
    flagged = next(r for r in recs if r["spec"] == "permuted")
    assert flagged["board_wl"] == "7-1-3.json"
    assert "board_wl" not in next(r for r in recs if r["spec"] == "bb")


def test_screen_can_drop_wl_matches_or_skip_the_board():
    audit = {}
    recs = S.screen(CANDIDATES, trials=100, seed=0, index=STEANE_INDEX,
                    audit=audit, board="drop")
    assert {r["spec"] for r in recs} == {"bb"}
    assert audit["rejected_board_wl"] == 1 and audit["flagged_board_wl"] == 0

    audit = {}
    recs = S.screen(CANDIDATES, trials=100, seed=0, board=None, audit=audit)
    assert {r["spec"] for r in recs} == {"steane", "permuted", "bb"}
    assert audit["rejected_disconnected"] == 1
    assert audit["rejected_board_exact"] == 0
    assert all("board_wl" not in r for r in recs)

    with pytest.raises(ValueError, match="board must be"):
        S.screen(CANDIDATES, trials=10, board="maybe")


def test_screen_adaptive_runs_the_same_prepass():
    audit = {}
    recs = S.screen_adaptive(CANDIDATES, stages=(50, 100), index=STEANE_INDEX,
                             audit=audit)
    assert {r["spec"] for r in recs} == {"permuted", "bb"}
    assert audit["rejected_disconnected"] == 1
    assert audit["rejected_board_exact"] == 1
    assert audit["rejected_repeat"] == 1
    assert next(r for r in recs if r["spec"] == "permuted")["board_wl"] == "7-1-3.json"
    assert audit["trials_flat"] == 2 * 100          # the two survivors, deepest stage


def test_make_submission_refuses_a_direct_sum():
    with pytest.raises(ValueError, match="2 independent block"):
        make_submission(TWO_STEANES, TWO_STEANES, name="[[14,2,3]] two Steanes",
                        construction="direct sum", authors=["@test"], trials=50)


def test_the_real_board_holds_the_quickstart_code():
    """Agree with QUICKSTART.md, which marks its [[72,12,6]] example `# gate: duplicate`.

    The pre-check must say the same from the gate's own index.
    """
    assert P.board_match(*BB72)["exact"] == "72-12-6.json"


def test_cli_refuses_a_staged_direct_sum(tmp_path):
    supports = [[int(q) for q in np.nonzero(r)[0]] for r in TWO_STEANES]
    path = tmp_path / "14-2-3.json"
    path.write_text(json.dumps({"n": 14, "k": 2,
                                "checks": {"X": supports, "Z": supports}}))
    proc = subprocess.run(
        [sys.executable, os.path.join(_HERE, "kit", "prescreen.py"), str(path),
         "--no-board"], capture_output=True, text=True, check=False)
    assert proc.returncode == 1, proc.stderr
    assert "2 independent block(s)" in proc.stdout
    assert "REFUSE" in proc.stdout


def test_cli_passes_a_connected_code_without_the_board(tmp_path):
    np.savez(tmp_path / "bb.npz", HX=BB72[0], HZ=BB72[1])
    proc = subprocess.run(
        [sys.executable, os.path.join(_HERE, "kit", "prescreen.py"),
         str(tmp_path / "bb.npz"), "--no-board", "--json"],
        capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    verdict = json.loads(proc.stdout)
    assert verdict["structure"]["connected"] and not verdict["reasons"]


# -- the verifier's structural half on a packaged document (issue #3616) ----
#
# The property is the same as above: the preflight refuses exactly what the
# gate's verify step refuses, in the verifier's own words, and sorts a fault
# in the code (nothing to fix) from a fault in the document (fix and save).

import validate_candidate  # noqa: E402  (prescreen put verify/ on the path)


def _packaged(HX, HZ):
    return make_submission(HX, HZ, name="preflight test", construction="t",
                           authors=["@tester"], trials=200, seed=1)


def _direct_sum_doc():
    """Two Steanes on disjoint qubits, with a valid witness on the first block.

    `make_submission` refuses to package this, so it is assembled by hand: the
    document the issue's n = 36 batch staged twelve of. Its witnesses verify,
    so the gate's verify step fails it and then still spends the random
    search on the distance they earn.
    """
    sup = [[int(q) for q in np.nonzero(r)[0]] for r in TWO_STEANES]
    doc = _packaged(STEANE, STEANE)
    doc.update(n=14, k=2, checks={"X": sup, "Z": sup})
    for side in ("X", "Z"):
        doc["distance"][side].update(value=3, witness=[0, 1, 2])
    doc["distance"]["d"] = 3
    return doc


def _typed_stabilizer():
    """Steane filed as a stabilizer code: the issue's typing failure."""
    rows = [[int(q) for q in np.nonzero(r)[0]] for r in STEANE]
    return {"schema_version": "0.4", "name": "Steane typed stabilizer",
            "code_type": "stabilizer", "n": 7, "k": 1,
            "checks": {"S": [{"X": r, "Z": []} for r in rows]
                       + [{"X": [], "Z": r} for r in rows]},
            "distance": {"d": 3, "P": {"value": 3, "confidence": "upper_bound",
                                       "witness": {"X": [0, 1, 2], "Z": []}}},
            "provenance": {"authors": ["@tester"], "construction": "t",
                           "date": "2026-10-17", "references": [], "notes": ""}}


def test_preflight_passes_a_packaged_code():
    r = P.preflight(_packaged(STEANE, STEANE))
    assert r["ok"] and not r["failed"] and not r["kinds"] and not r["code_at_fault"]
    assert r["computed"] == {"code_type": "CSS", "n": 7, "k": 1,
                             "max_check_weight": 4, "weight_class": "weight-4"}
    assert P.describe_preflight(r) == "the verifier's structural checks all pass"


def test_preflight_refuses_a_direct_sum_in_the_verifiers_words():
    r = P.preflight(_direct_sum_doc())
    assert [f["check"] for f in r["failed"]] == ["tanner_connected",
                                                 "stabilizer_group_connected"]
    assert r["failed"][0]["detail"] == "Tanner graph has 2 connected component(s)"
    assert "2 independent block(s)" in r["failed"][1]["detail"]
    assert r["kinds"] == ["construction"] and r["code_at_fault"]
    assert P.describe_preflight(r).endswith("no edit to the document fixes it")


def test_preflight_fails_exactly_the_checks_the_gate_fails():
    """`gates.verify.failed_checks` of the real gate, search off, is the preflight's list."""
    doc = _direct_sum_doc()
    verdict = validate_candidate.validate_candidate(doc, refute=False)
    assert not verdict["passed"]
    assert verdict["gates"]["verify"]["failed_checks"] == [
        f["check"] for f in P.preflight(doc)["failed"]]


def test_preflight_names_the_weight_cap():
    n = qldpc_verify.MAX_CHECK_WEIGHT + 1
    row = list(range(n))
    doc = _packaged(STEANE, STEANE)
    doc.update(n=n, k=n - 2, checks={"X": [row], "Z": [row]})
    doc["distance"] = {"d": 2,
                       "X": {"value": 2, "confidence": "upper_bound", "witness": [0, 1]},
                       "Z": {"value": 2, "confidence": "upper_bound", "witness": [0, 2]}}
    r = P.preflight(doc)
    # The schema caps a row at 32 qubits, so the refusal comes from
    # `schema_valid`, before the verifier's own weight check is reached;
    # the kind still says the code's weight is the fault.
    assert [(f["check"], f["kind"]) for f in r["failed"]] == [("schema_valid", "weight")]
    assert "checks/X/0" in r["failed"][0]["detail"] and "is too long" in r["failed"][0]["detail"]
    assert r["code_at_fault"]
    assert P.kind_of("check_weight_is_ldpc") == "weight"


def test_preflight_sorts_a_document_fault_from_a_code_fault():
    """The issue's commonest packaging failure, eight times in one batch."""
    doc = _packaged(STEANE, STEANE)
    del doc["distance"]["X"]["witness_provenance"]["date"]
    r = P.preflight(doc)
    assert [(f["check"], f["kind"]) for f in r["failed"]] == [("schema_valid", "packaging")]
    assert "'date' is a required property" in r["failed"][0]["detail"]
    assert not r["code_at_fault"]
    assert P.describe_preflight(r).endswith("fix the document and save it again")


def test_preflight_catches_a_css_code_typed_stabilizer():
    r = P.preflight(_typed_stabilizer())
    assert [(f["check"], f["kind"]) for f in r["failed"]] == [
        ("stabilizer_code_is_not_css", "typing")]
    assert 'set code_type to "CSS"' in r["failed"][0]["detail"]
    assert not r["code_at_fault"]


def test_every_kind_in_the_table_is_a_check_the_verifier_records():
    """The classification names real checks, so a renamed check cannot go unclassified."""
    with open(os.path.join(_HERE, "..", "verify", "qldpc_verify.py"), encoding="utf-8") as f:
        source = f.read()
    for kind, names in P.KINDS.items():
        for name in names:
            assert f'record("{name}"' in source, (kind, name)
    assert P.kind_of("distance_X_witness") == "witness"
    assert P.kind_of("d_matches_min_side") == "witness"
    assert P.kind_of("k_matches_claim") == "packaging"
    assert P.kind_of("schema_valid", "distance/X/witness_provenance: 'date' is a required property") == "packaging"
    assert P.kind_of("schema_valid", "checks/X/0: [] is too short") == "packaging"


def test_cli_preflights_a_staged_document(tmp_path):
    path = tmp_path / "14-2-3.json"
    path.write_text(json.dumps(_direct_sum_doc()))
    proc = subprocess.run(
        [sys.executable, os.path.join(_HERE, "kit", "prescreen.py"), str(path),
         "--no-board", "--json"], capture_output=True, text=True, check=False)
    assert proc.returncode == 1, proc.stderr
    out = json.loads(proc.stdout)
    assert [f["check"] for f in out["preflight"]["failed"]] == [
        "tanner_connected", "stabilizer_group_connected"]
    assert out["gate_would_refuse"]


def test_cli_preflights_a_stabilizer_document(tmp_path):
    path = tmp_path / "7-1-3.json"
    path.write_text(json.dumps(_typed_stabilizer()))
    proc = subprocess.run(
        [sys.executable, os.path.join(_HERE, "kit", "prescreen.py"), str(path),
         "--no-board"], capture_output=True, text=True, check=False)
    assert proc.returncode == 1, proc.stderr
    assert "REFUSE" in proc.stdout and "stabilizer_code_is_not_css" in proc.stdout
