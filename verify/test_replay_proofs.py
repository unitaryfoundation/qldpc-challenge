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


def test_shards_partition_and_balance_by_recorded_runtime():
    items = ["a", "b", "c", "d", "e", "f"]
    secs = {"a": 12, "b": 11, "c": 10, "d": 9, "e": 2, "f": 1}
    shards = [R.select_shard(items, f"{i}/3", secs) for i in range(3)]
    assert sorted(sum(shards, [])) == items
    assert shards == [["a", "f"], ["b", "e"], ["c", "d"]]
    loads = [sum(secs[s] for s in shard) for shard in shards]
    assert loads == [13, 13, 19]
    for bad in ("3/3", "-1/3", "0/0", "x"):
        with pytest.raises(ValueError):
            R.select_shard(items, bad, secs)


def test_a_budget_stops_opening_entries_and_is_reported_not_failed(monkeypatch, capsys):
    """--max-minutes ends the run cleanly; what was not opened is counted, not failed."""
    certs = {f"e{i}": {"verification": {"level": "proof_log"}} for i in range(5)}
    monkeypatch.setattr(R, "replayable", lambda: certs)
    monkeypatch.setattr(R.shutil, "which", lambda tool: "/usr/bin/" + tool)
    opened = []
    monkeypatch.setattr(R, "replay", lambda slug, cert, work, tlim: (opened.append(slug),
                                                                      {"ok": True, "sides": {}})[1])
    rc = R.main(["--all", "--max-minutes", "0"])
    out = capsys.readouterr().out
    assert rc == 0 and opened == []
    assert "0 replayed, 0 failed, 5 left unopened at the 0 min budget" in out
    rc = R.main(["--all", "--shard", "1/2"])
    assert rc == 0 and opened == ["e1", "e3"]
    assert "2 replayed, 0 failed" in capsys.readouterr().out


def test_budget_skips_an_entry_that_wont_fit_and_runs_smaller_entries(monkeypatch, capsys):
    certs = {slug: {"verification": {"level": "proof_log"}} for slug in ("a-long", "b-short")}
    secs = {"a-long": 8, "b-short": 2}
    monkeypatch.setattr(R, "replayable", lambda: certs)
    monkeypatch.setattr(R, "recorded_secs", lambda: secs)
    monkeypatch.setattr(R.shutil, "which", lambda tool: "/usr/bin/" + tool)
    opened = []
    monkeypatch.setattr(
        R, "replay", lambda slug, cert, work, tlim: (opened.append(slug), {"ok": True, "sides": {}})[1]
    )

    rc = R.main(["--all", "--max-minutes", "0.1"])

    assert rc == 0 and opened == ["b-short"]
    assert "1 replayed, 0 failed, 1 left unopened at the 0.1 min budget" in capsys.readouterr().out
