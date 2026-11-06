"""A certificate may not claim a verification level it cannot evidence.

The exact tier is the strongest thing the board asserts and was, until
#2511, the least checkable: the upper bound ships a logical operator anyone
can re-verify in seconds, and the lower bound shipped a solver's verdict.
`verification.level` records what that verdict is worth, and the only way it
stays meaningful is if claiming a level requires the artifact.
"""
import copy
import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)

import check_certs as C  # noqa: E402

BASE = {"d": 12, "d_exact": True, "solver": "CryptoMiniSat 5.14.7 SAT",
        "sides": {"X": {"value": 12, "exact": True}},
        "verification": {"level": "solver"}}


def test_every_committed_certificate_declares_a_level():
    assert C.main([]) == 0, "certs/ does not validate"


def test_the_board_claims_no_level_it_cannot_evidence():
    """Every level the board claims has the evidence that level requires.

    Certificates are solver verdicts and, since #2728, proof_log entries
    carrying a checked refutation. The tripwire that used to pin the set to
    solver alone fired when that landed, which is what it was for; what is
    pinned now is the thing worth pinning, that no entry claims a level
    whose artifact is missing, and that formal has not appeared without the
    replay recipe #2511 specifies for it.
    """
    import glob
    levels = {}
    for p in glob.glob(os.path.join(_ROOT, "certs", "*.json")):
        with open(p, encoding="utf-8") as f:
            cert = json.load(f)
        v = cert.get("verification") or {}
        levels.setdefault(v.get("level"), []).append((p, v))
    assert set(levels) <= {"solver", "proof_log", "formal"}, \
        f"unknown level: {sorted(set(levels))}"
    for level, rows in levels.items():
        if level == "solver":
            continue
        for path, v in rows:
            slug = os.path.basename(path)
            # Evidence is a file in the tree or the recipe that re-derives
            # the check. proof_log ships the recipe (PR #2754): the
            # refutations are too large to commit and a committed blob is
            # not something CI can audit, so the certificate carries the
            # formula's hash and replay_proofs.py regenerates and re-checks
            # it on a schedule.
            if v.get("artifact"):
                art = os.path.join(_ROOT, v["artifact"])
                assert os.path.isfile(art), \
                    f"{slug}: level {level} names an artifact not in the tree"
                assert os.path.getsize(art) > 0, f"{slug}: empty artifact"
            else:
                assert v.get("replay"), \
                    f"{slug}: level {level} with neither artifact nor replay"
                if level == "proof_log":
                    assert v.get("cnf_sha256"), \
                        f"{slug}: replayed proof_log without cnf_sha256"
            assert v.get("checker"), f"{slug}: level {level} with no checker"
    for path, v in levels.get("formal", []):
        assert v.get("replay") and v.get("checks_sha256"), (
            f"{os.path.basename(path)}: a formal certificate needs the "
            "replay recipe and the hash binding it to this code, since the "
            "proof is a theorem rather than a file")


@pytest.mark.parametrize("level", ["proof_log", "formal"])
def test_a_stronger_level_needs_an_artifact_that_exists(level):
    c = copy.deepcopy(BASE)
    c["verification"] = {"level": level, "checker": "drat-trim 2024-05"}
    assert C.evidence_problems("x", c), "no artifact must be refused"

    c["verification"]["artifact"] = "certs/proofs/does-not-exist.drat"
    probs = C.evidence_problems("x", c)
    assert probs and "not a file committed in this tree" in probs[0], \
        "an artifact that is not committed must be refused"


@pytest.mark.parametrize("level", ["proof_log", "formal"])
def test_a_stronger_level_needs_a_named_checker(level):
    c = copy.deepcopy(BASE)
    c["verification"] = {"level": level, "artifact": "schema/cert.schema.json"}
    probs = C.evidence_problems("x", c)
    assert any("checker" in p for p in probs), \
        "an unchecked artifact is not a check"


def test_solver_level_does_not_smuggle_an_artifact():
    """If something checkable exists, the certificate should claim its level."""
    c = copy.deepcopy(BASE)
    c["verification"] = {"level": "solver",
                         "artifact": "schema/cert.schema.json"}
    assert C.evidence_problems("x", c)


def test_an_unknown_level_is_refused():
    c = copy.deepcopy(BASE)
    c["verification"] = {"level": "probably_fine"}
    assert C.evidence_problems("x", c)


def test_a_well_formed_stronger_certificate_passes():
    """The path has to work, or nobody will use it.

    An artifact in the tree carries proof_log; formal is bound to a board
    entry by its hash and is exercised below with a real one.
    """
    c = copy.deepcopy(BASE)
    c["verification"] = {"level": "proof_log",
                         "artifact": "schema/cert.schema.json",
                         "checker": "drat-trim 2024-05",
                         "reference": "arXiv:2605.16523"}
    assert C.evidence_problems("x", c) == []


@pytest.mark.parametrize("art", [
    "/etc/hosts",                      # absolute: os.path.join drops ROOT
    "certs/../verify/check_certs.py",  # resolves in-tree, still not a path to
                                       # store, since a reader has to normalise
                                       # it before it names anything
    "certs",                           # a directory is not an artifact
    "certs/heuristic",
])
def test_an_artifact_outside_the_tree_is_refused(art):
    c = copy.deepcopy(BASE)
    c["verification"] = {"level": "proof_log", "artifact": art,
                         "checker": "drat-trim 2024-05"}
    assert C.evidence_problems("x", c), f"{art} must not be accepted"


@pytest.mark.parametrize("field", ["artifact", "checker", "reference"])
def test_solver_level_claims_no_check_it_did_not_run(field):
    """Refuse a checker named on a bare solver verdict.

    It asserts a check that is not there, exactly as an artifact would.
    """
    c = copy.deepcopy(BASE)
    c["verification"] = {"level": "solver", field: "drat-trim 2024-05"}
    assert C.evidence_problems("x", c)


def test_the_cert_writer_stamps_a_level_the_checker_accepts(tmp_path,
                                                           monkeypatch):
    """The gate is only worth having if the next regeneration satisfies it.

    certify_all.py writes certs/<slug>.json, so a cert written today has to
    carry the block check_certs.py requires, rather than needing a backfill
    after every run.
    """
    import certify_all

    monkeypatch.setattr(certify_all, "certify", lambda doc, tlim: {
        "d": 7, "d_exact": True, "sides": {"X": {"value": 7, "exact": True}}})
    monkeypatch.setattr(certify_all, "CERTS", str(tmp_path / "certs"))

    src = tmp_path / "98-6-7.json"
    src.write_text(json.dumps({"name": "98-6-7"}), encoding="utf-8")
    certify_all.run(str(src))

    with open(tmp_path / "certs" / "98-6-7.json", encoding="utf-8") as f:
        written = json.load(f)
    assert written["verification"] == {"level": "solver"}
    assert C.evidence_problems("98-6-7", written) == []


# -- the formal tier's binding (issue #2511) ---------------------------------

FORMAL_REPLAY = {"repo": "github.com/VerifiedQC/Lean-QEC", "commit": "e0b90148694c",
                 "theorem": "BB72_dist_6", "build": "lake exe cache get && lake build",
                 "toolchain": "leanprover/lean4:v4.30.0-rc2", "mathlib": "5450b53e5ddc"}


def _formal(slug="72-12-6", **over):
    c = copy.deepcopy(BASE)
    with open(os.path.join(_ROOT, "codes", f"{slug}.json"), encoding="utf-8") as f:
        doc = json.load(f)
    c["verification"] = {"level": "formal", "checker": "Lean 4 v4.30.0-rc2",
                         "replay": dict(FORMAL_REPLAY),
                         "checks_sha256": C.checks_sha256(doc)}
    c["verification"].update(over)
    return c


def test_the_binding_hash_names_the_presentation_not_the_file():
    """Row order and support order inside a row do not change it; a row does."""
    doc = {"checks": {"X": [[3, 1, 2], [0, 4]], "Z": [[5, 6]]}}
    same = {"checks": {"X": [[0, 4], [1, 2, 3]], "Z": [[6, 5]]}}
    other = {"checks": {"X": [[0, 4], [1, 2, 3]], "Z": [[6, 7]]}}
    assert C.checks_sha256(doc) == C.checks_sha256(same)
    assert C.checks_sha256(doc) != C.checks_sha256(other)
    assert len(C.checks_sha256(doc)) == 64


def test_a_formal_certificate_bound_to_its_code_passes():
    assert C.evidence_problems("72-12-6", _formal()) == []


def test_a_formal_certificate_bound_to_another_code_is_refused():
    with open(os.path.join(_ROOT, "codes", "16-6-4.json"), encoding="utf-8") as f:
        other = json.load(f)
    probs = C.evidence_problems("72-12-6", _formal(checks_sha256=C.checks_sha256(other)))
    assert probs and "some other matrix pair" in probs[0]


def test_a_formal_certificate_for_an_absent_entry_is_refused():
    probs = C.evidence_problems("999-1-1", _formal())
    assert probs and "not on the board" in probs[0]


# --- partial certificates: a proven lower bound below the claim (issue #4230) ----------------

def _entry(slug):
    with open(os.path.join(_ROOT, "codes", f"{slug}.json"), encoding="utf-8") as f:
        return json.load(f)


def _partial(slug="72-12-6", d_lower=3, **over):
    doc = _entry(slug)
    d = doc["distance"]["d"]
    ladder = [{"W": w, "status": "UNSAT", "secs": 0.1} for w in range(1, d_lower)] \
        + [{"W": d_lower, "status": "TIMEOUT", "secs": 1.0}]
    c = {"name": doc["name"], "d": d, "d_exact": False, "d_lower": d_lower,
         "solver": "CryptoMiniSat 5.14 SAT", "tlim_per_solve": 1, "encoding": "selector",
         "sides": {s: {"value": d, "exact": False, "status": "TIMEOUT", "secs": 1.0, "proved_min": d_lower,
                       "ladder": copy.deepcopy(ladder), "note": f"no logical < {d_lower} exists; W = {d_lower} TIMEOUT"}
                   for s in "XZ"},
         "verification": {"level": "solver", "note": "no proof path was run",
                          "checks_sha256": C.checks_sha256(doc)}}
    c.update(over)
    return c


def _schema_errors(cert):
    jsonschema = pytest.importorskip("jsonschema")
    v = jsonschema.Draft202012Validator(C.load_schema())
    return [e.message for e in v.iter_errors(cert)]


def test_a_partial_certificate_passes_the_schema_and_both_rule_sets():
    c = _partial()
    assert _schema_errors(c) == []
    assert C.evidence_problems("72-12-6", c) == []
    assert C.bound_problems("72-12-6", c) == []


def test_a_partial_certificate_names_its_bound_and_its_binding():
    c = _partial()
    del c["d_lower"]
    assert any("d_lower" in e for e in _schema_errors(c))
    c = _partial()
    del c["verification"]["checks_sha256"]
    assert any("checks_sha256" in e for e in _schema_errors(c))


def test_a_bound_that_proves_nothing_or_reaches_the_claim_is_refused():
    c = _partial(d_lower=1)
    for blk in c["sides"].values():
        blk["proved_min"], blk["ladder"] = 1, [{"W": 1, "status": "TIMEOUT", "secs": 1.0}]
    assert any("proves nothing" in p for p in C.bound_problems("72-12-6", c))
    c = _partial(d_lower=6)
    assert any("reaches the claim" in p for p in C.bound_problems("72-12-6", c))


def test_a_bound_its_ladder_does_not_back_is_refused():
    c = _partial()
    c["sides"]["X"]["proved_min"] = 4
    probs = C.bound_problems("72-12-6", c)
    assert any("not backed by its ladder" in p for p in probs)
    c = _partial()
    c["sides"]["Z"]["proved_min"] = 2
    assert any("not the minimum" in p for p in C.bound_problems("72-12-6", c))


def test_a_sat_rung_is_a_refutation_not_a_certificate():
    c = _partial()
    c["sides"]["X"]["ladder"][-1] = {"W": 3, "status": "SAT", "secs": 1.0}
    assert any("refutation" in p for p in C.bound_problems("72-12-6", c))


def test_a_partial_certificate_bound_to_another_code_is_refused():
    c = _partial()
    c["verification"]["checks_sha256"] = C.checks_sha256(_entry("16-6-4"))
    probs = C.bound_problems("72-12-6", c)
    assert probs and "some other matrix pair" in probs[0]
    assert "not on the board" in C.bound_problems("999-1-1", _partial())[0]


def test_a_witness_below_the_proven_bound_fails_loudly(monkeypatch):
    """The free consistency check: a verified witness lighter than a proven bound is a bug, not a board update."""
    c = _partial(d_lower=5)
    doc = _entry("72-12-6")
    doc["distance"] = {"d": 4, "X": {"value": 4}, "Z": {"value": 6}}
    monkeypatch.setattr(C, "_code_doc", lambda slug: doc)
    probs = C.bound_problems("72-12-6", c)
    assert any("d <= 4" in p and "d >= 5" in p and "wrong" in p for p in probs)
    assert any("d_X <= 4" in p and "d_X >= 5" in p for p in probs)
    assert not any("d_Z" in p for p in probs)


def test_an_exact_certificate_may_carry_only_its_own_distance_as_d_lower():
    c = copy.deepcopy(BASE)
    c["d_lower"] = c["d"]
    assert C.bound_problems("72-12-6", c) == []
    c["d_lower"] = c["d"] - 1
    assert any("exact certificate's lower bound is its distance" in p for p in C.bound_problems("72-12-6", c))
    c = copy.deepcopy(BASE)
    c["sides"]["X"]["proved_min"] = c["d"] - 1
    assert any("is exact but proved_min" in p for p in C.bound_problems("72-12-6", c))
