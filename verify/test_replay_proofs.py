"""The proof_log tier is a claim that a refutation can be re-derived.

What is tested is that the replay rejects a certificate whose recorded
formula hash is not what the emitter now produces, since a refutation of
some other formula says nothing about this entry, and that a genuine entry
replays end to end when the solver and checker are present.
"""
import copy
import json
import os
import shutil
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)

pytest.importorskip("pysat")
import replay_proofs as R  # noqa: E402

TOOLS = all(shutil.which(t) for t in ("kissat", "drat-trim"))


def _one_small():
    """Return the smallest replayable certificate on the board."""
    certs = R.replayable()
    assert certs, "no proof_log certificate carries a replay recipe"
    slug = min(certs, key=lambda s: json.load(
        open(os.path.join(_ROOT, "codes", s + ".json")))["n"])
    return slug, certs[slug]


@pytest.mark.board
def test_every_proof_log_certificate_is_replayable():
    """A proof_log entry without recipe and hash cannot be audited."""
    for p in os.listdir(os.path.join(_ROOT, "certs")):
        if not p.endswith(".json") or p == "proof_log_batch.jsonl":
            continue
        with open(os.path.join(_ROOT, "certs", p), encoding="utf-8") as f:
            v = json.load(f).get("verification") or {}
        if v.get("level") == "proof_log":
            assert v.get("replay") and v.get("cnf_sha256"), p


def test_the_sample_is_deterministic_in_the_seed():
    secs = R.recorded_secs()
    pool = sorted(s for s in R.replayable() if secs.get(s, 0) <= 20)
    import random
    a = random.Random(7).sample(pool, 5)
    b = random.Random(7).sample(pool, 5)
    assert a == b and len(set(a)) == 5


@pytest.mark.skipif(not TOOLS, reason="kissat and drat-trim not on PATH")
def test_a_tampered_hash_fails_before_any_solving(tmp_path):
    slug, cert = _one_small()
    bad = copy.deepcopy(cert)
    bad["verification"]["cnf_sha256"] = ";".join(
        f"{p.split('=')[0]}={'0' * 64}"
        for p in cert["verification"]["cnf_sha256"].split(";"))
    rep = R.replay(slug, bad, str(tmp_path), tlim=60)
    assert not rep["ok"]
    for blk in rep["sides"].values():
        assert blk["cnf_sha256_matches"] is False
        assert "kissat" not in blk, "a mismatched formula must not be solved"


@pytest.mark.skipif(not TOOLS, reason="kissat and drat-trim not on PATH")
def test_the_smallest_entry_replays_end_to_end(tmp_path):
    slug, cert = _one_small()
    rep = R.replay(slug, cert, str(tmp_path), tlim=120)
    assert rep["ok"], rep
    for blk in rep["sides"].values():
        assert blk["cnf_sha256_matches"] and blk["kissat"] == "UNSAT"
        assert blk["drat_trim"] == "VERIFIED"
