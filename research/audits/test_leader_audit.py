"""Regression tests for the audit harness (``leader_audit.py``).

Three properties matter because the harness is allowed to gate a script and its
output can become a distance revision:

* a proposal that fails the independent GF(2) re-check can neither move the
  reading nor reach the witness file -- otherwise an accelerator bug could
  manufacture a refutation, which is the exact failure the re-check exists to
  prevent;
* the lightest witness seen so far is on disk before the ladder finishes, so a
  rung killed by a time limit does not cost a re-run;
* a verdict is about the code and the instrument that was asked for -- right
  ``pair_depth``, both backends, no silently-skipped rung, no scoring of an
  entry that is not the claimed CSS code;
* a candidate that would beat a board entry only on d is measured against that
  entry at one identical budget, and the decision names which of the two claims
  came down.

The searches are stubbed throughout and the fixture is synthetic: these test the
plumbing, not the codes, and they never read ``codes/``. Pinning a live board
entry would make a future revision or rename of that entry fail the suite with
the harness unchanged.
"""

import argparse
import json
import os
import sys
import types

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import leader_audit as la  # noqa: E402
import surrogate  # noqa: E402

# [[4,2,2]]: the all-ones check on both sides. H_X H_Z^T = 0 over GF(2),
# k = 4 - rank(H_X) - rank(H_Z) = 2, and 1100 lies in ker(H_Z) but outside
# rowspace(H_X), so it is a hand-checkable weight-2 logical witness.
FIXTURE = {
    "n": 4,
    "k": 2,
    "checks": {"X": [[0, 1, 2, 3]], "Z": [[0, 1, 2, 3]]},
    "distance": {"d": 2, "X": {"value": 2}, "Z": {"value": 2}},
}
WITNESS = (2, "X", [0, 1])


@pytest.fixture
def entry(tmp_path):
    """Return a synthetic board entry on disk, in the shape ``load_entry`` reads."""
    path = tmp_path / "synth-4-2-2.json"
    path.write_text(json.dumps(FIXTURE))
    return str(path)


def _ladder_args(entry, witness_out, ladder=((2000, [1]), (4000, [2])), pair_depth=10):
    return types.SimpleNamespace(
        entry=str(entry),
        ladder=list(ladder),
        threads=2,
        pair_depth=pair_depth,
        witness_out=str(witness_out),
    )


def _screen_args(entries, witness_dir=None, seeds=(1, 2)):
    return types.SimpleNamespace(
        entries=[str(e) for e in entries],
        trials=2000,
        seeds=list(seeds),
        threads=2,
        pair_depth=10,
        witness_dir=None if witness_dir is None else str(witness_dir),
    )


def test_pair_depth_reaches_both_backends(monkeypatch, entry):
    """`--pair-depth` must reach the NumPy search *and* the accelerator.

    A shallower depth than the claim's own ladder under-reads, so a silent
    default would make the verdict an artifact of the instrument. Stubbing
    ``ris`` cannot see this, which is how the NumPy path went unnoticed.
    """
    _n, _k, HX, HZ, _doc = la.load_entry(entry)
    seen = []

    def recording(hself, hopp, trials, seed, pair_depth=10, bases=None):
        seen.append(pair_depth)
        return 2, [0, 1]

    monkeypatch.setattr(surrogate, "_search_lightest", recording)
    monkeypatch.setattr(surrogate, "_fast", None)
    la.ris(HX, HZ, trials=1000, seed=7, threads=1, pair_depth=64)
    assert seen == [64, 64], "the NumPy search did not receive the requested depth"

    got = {}

    class FakeFast:
        @staticmethod
        def distance_rand_witness(HXa, HZa, trials, seed, pair_depth, threads):
            got.update(trials=trials, seed=seed, pair_depth=pair_depth, threads=threads)
            return 2, "X", [0, 1]

    monkeypatch.setattr(surrogate, "_fast", FakeFast())
    la.ris(HX, HZ, trials=1000, seed=7, threads=3, pair_depth=64)
    assert got == {"trials": 1000, "seed": 7, "pair_depth": 64, "threads": 3}


def test_the_two_sides_use_independent_seed_streams(monkeypatch, entry):
    """The Z side must not replay the next ladder seed's X side.

    With plain ``seed`` / ``seed + 1`` the Z side of seed 101 and the X side of
    seed 102 are the same stream, which is not the fresh independent seeds a
    ladder rung advertises.
    """
    _n, _k, HX, HZ, _doc = la.load_entry(entry)
    seeds = []

    def recording(hself, hopp, trials, seed, pair_depth=10, bases=None):
        seeds.append(seed)
        return 2, [0, 1]

    monkeypatch.setattr(surrogate, "_search_lightest", recording)
    monkeypatch.setattr(surrogate, "_fast", None)
    la.ris(HX, HZ, trials=10, seed=101, threads=1)
    assert len(seeds) == 2

    x_stream = np.random.default_rng(seeds[0]).random(8)
    z_stream = np.random.default_rng(seeds[1]).random(8)
    assert not np.array_equal(x_stream, z_stream)
    assert not np.array_equal(z_stream, np.random.default_rng(102).random(8))


def test_no_logical_from_the_accelerator_does_not_fall_through(monkeypatch, entry):
    """The n+1 sentinel is a result, not a reason to re-run in NumPy.

    Falling through would repeat the whole budget on the NumPy path, which is
    milliseconds per trial: hours at the 8M rungs, not a cheap second opinion.
    """
    _n, _k, HX, HZ, _doc = la.load_entry(entry)
    fell_through = []

    class FakeFast:
        @staticmethod
        def distance_rand_witness(HXa, HZa, trials, seed, pair_depth, threads):
            return HXa.shape[1] + 1, "", []

    monkeypatch.setattr(surrogate, "_fast", FakeFast())
    monkeypatch.setattr(surrogate, "_search_lightest", lambda *a, **k: fell_through.append(1) or (2, [0, 1]))
    weight, side, support, _dt = la.ris(HX, HZ, trials=8_000_000, seed=1, threads=1, pair_depth=64)
    assert (weight, side, support) == (float("inf"), "", [])
    assert fell_through == [], "the NumPy fallback was re-entered at the full budget"


def test_seedless_ladder_rung_is_rejected():
    """A rung with no seeds runs nothing; it must not be accepted silently."""
    with pytest.raises(argparse.ArgumentTypeError):
        la._parse_ladder(["2000"])
    with pytest.raises(argparse.ArgumentTypeError):
        la._parse_ladder(["2000:1", "2000"])
    with pytest.raises(argparse.ArgumentTypeError):
        la._parse_ladder(["0:1"])

    assert la._parse_ladder(["2000:1,2", "4000:3"]) == [(2000, [1, 2]), (4000, [3])]


def test_usage_errors_do_not_exit_two(entry):
    """2 means "a claim was refuted"; a mistyped invocation must not look like one."""
    with pytest.raises(SystemExit) as excinfo:
        la.main(["ladder", entry, "--ladder", "2000"])
    assert excinfo.value.code == la.EXIT_INVALID
    assert excinfo.value.code != la.EXIT_REFUTED

    with pytest.raises(SystemExit) as excinfo:
        la.main(["screen", entry, "--no-such-flag"])
    assert excinfo.value.code == la.EXIT_INVALID


def test_prepared_bases_are_built_once_per_entry(monkeypatch, entry, tmp_path):
    """The GF(2) bases are built once, not once per seed."""
    builds = []
    real_prepare = surrogate.prepare_distance_search

    def counting(HX, HZ):
        builds.append(1)
        return real_prepare(HX, HZ)

    monkeypatch.setattr(surrogate, "prepare_distance_search", counting)
    monkeypatch.setattr(surrogate, "_fast", None)
    monkeypatch.setattr(surrogate, "_search_lightest", lambda *a, **k: (2, [0, 1]))

    la.cmd_ladder(_ladder_args(entry, tmp_path / "w.json", ladder=((2000, [1, 2, 3]),)))
    assert len(builds) == 1, "the GF(2) bases were rebuilt per seed"

    builds.clear()
    la.cmd_screen(_screen_args([entry], seeds=(1, 2, 3)))
    assert len(builds) == 1, "the GF(2) bases were rebuilt per seed"


def test_invalid_proposal_is_discarded(monkeypatch, entry, tmp_path):
    """An unvalidated witness must not refute the claim or be written out."""
    monkeypatch.setattr(la, "ris", lambda *a, **k: (3, "X", [0, 1, 2], 0.0))
    out = tmp_path / "witness.json"
    rc = la.cmd_ladder(_ladder_args(entry, out))
    assert rc == la.EXIT_OK, "a bogus proposal was scored as a refutation"
    assert not out.exists(), "a bogus proposal reached the witness file"


def test_entry_that_is_not_the_claimed_code_is_rejected(monkeypatch, tmp_path):
    """A wrong k, or non-commuting checks, must not yield a verdict or a witness.

    Otherwise a gating script acts on a refutation of something that is not the
    claimed CSS code.
    """
    import copy

    mismatched_k = copy.deepcopy(FIXTURE)
    mismatched_k["k"] = 5  # recomputed k is 2
    not_css = copy.deepcopy(FIXTURE)
    not_css["checks"] = {"X": [[0, 1]], "Z": [[0]]}  # H_X H_Z^T = 1

    for name, payload in (("bad-k.json", mismatched_k), ("not-css.json", not_css)):
        path = tmp_path / name
        path.write_text(json.dumps(payload))
        out = tmp_path / f"{name}.witness"
        monkeypatch.setattr(la, "ris", lambda *a, **k: (2, "X", [0, 1], 0.0))
        assert la.cmd_ladder(_ladder_args(str(path), out)) == la.EXIT_INVALID
        assert not out.exists()


def test_witness_written_on_every_new_best(monkeypatch, entry, tmp_path):
    """The best-so-far survives a later rung that yields nothing usable."""
    n, _k, HX, HZ, _doc = la.load_entry(entry)
    seen = []

    def staged(*args, **kwargs):
        seen.append(1)
        if len(seen) == 1:
            return WITNESS[0], WITNESS[1], WITNESS[2], 0.0
        return 1, "X", [0], 0.0  # lighter, but not a logical

    monkeypatch.setattr(la, "ris", staged)
    out = tmp_path / "witness.json"
    assert la.cmd_ladder(_ladder_args(entry, out)) == la.EXIT_OK

    payload = json.loads(out.read_text())
    assert (payload["weight"], payload["side"], payload["support"]) == WITNESS
    assert payload["seed"] == 1
    assert payload["claim"] == 2 and payload["verdict"] == la.VERDICT_HOLDS

    # the written support is a witness, re-checked against the raw matrices
    ok, why = la.validate_witness(n, HX, HZ, payload["side"], payload["weight"], payload["support"])
    assert ok, why


def test_a_stale_witness_is_cleared(monkeypatch, entry, tmp_path):
    """A file left by an earlier run must not read as this run's artifact."""
    out = tmp_path / "witness.json"
    out.write_text(json.dumps({"verdict": "refuted", "support": [0, 1]}))
    monkeypatch.setattr(la, "ris", lambda *a, **k: (float("inf"), "", [], 0.0))
    assert la.cmd_ladder(_ladder_args(entry, out, ladder=((2000, [1]),))) == la.EXIT_OK
    assert not out.exists(), "a stale witness survived a run that found nothing"


def test_no_eff_line_when_nothing_was_found(monkeypatch, entry, tmp_path, capsys):
    """`eff(kd^2/n)` of the n+1 sentinel is not a number worth printing."""
    monkeypatch.setattr(la, "ris", lambda *a, **k: (float("inf"), "", [], 0.0))
    assert la.cmd_ladder(_ladder_args(entry, tmp_path / "w.json", ladder=((2000, [1]),))) == la.EXIT_OK
    out = capsys.readouterr().out
    assert "eff(kd^2/n)" not in out
    assert la.VERDICT_INCONCLUSIVE in out


def test_refutation_writes_witness_and_exits_two(monkeypatch, entry, tmp_path):
    """Exit code 2 and a saved witness are the two artifacts a revision needs."""
    real_load = la.load_entry

    def soft_claim(path):
        n, k, HX, HZ, doc = real_load(path)
        doc["distance"]["d"] = 6  # pretend the board over-claims
        return n, k, HX, HZ, doc

    monkeypatch.setattr(la, "load_entry", soft_claim)
    monkeypatch.setattr(la, "ris", lambda *a, **k: (WITNESS[0], WITNESS[1], WITNESS[2], 0.0))
    out = tmp_path / "witness.json"
    rc = la.cmd_ladder(_ladder_args(entry, out, ladder=((2000, [1]),)))
    assert rc == la.EXIT_REFUTED
    assert json.loads(out.read_text())["verdict"] == la.VERDICT_REFUTED


def test_screen_keeps_one_witness_per_entry(monkeypatch, entry, tmp_path):
    """A triage screen can also refute, so it saves its witnesses too."""
    monkeypatch.setattr(la, "ris", lambda *a, **k: (WITNESS[0], WITNESS[1], WITNESS[2], 0.0))
    witness_dir = tmp_path / "witnesses"
    assert la.cmd_screen(_screen_args([entry], witness_dir)) == la.EXIT_OK
    payload = json.loads((witness_dir / f"{la._witness_stem(entry)}.json").read_text())
    assert payload["weight"] == WITNESS[0] and payload["entry"] == entry
    assert not any(p.name.endswith(".tmp") for p in witness_dir.iterdir())


def test_screen_witnesses_do_not_collide_across_directories(monkeypatch, tmp_path):
    """The same basename in two directories must not share one witness file."""
    paths = []
    for sub in ("a", "b"):
        d = tmp_path / sub
        d.mkdir()
        p = d / "same-4-2-2.json"
        p.write_text(json.dumps(FIXTURE))
        paths.append(str(p))

    monkeypatch.setattr(la, "ris", lambda *a, **k: (WITNESS[0], WITNESS[1], WITNESS[2], 0.0))
    witness_dir = tmp_path / "witnesses"
    assert la.cmd_screen(_screen_args(paths, witness_dir)) == la.EXIT_OK

    written = sorted(p.name for p in witness_dir.iterdir())
    assert len(written) == 2, f"two entries shared one witness file: {written}"
    seen = {json.loads((witness_dir / name).read_text())["entry"] for name in written}
    assert seen == set(paths)


def _pair_args(candidate, peers, seeds=(1,), witness_dir=None):
    return types.SimpleNamespace(
        candidate=str(candidate),
        peer=[str(p) for p in peers],
        trials=2000,
        seeds=list(seeds),
        threads=2,
        pair_depth=10,
        witness_dir=None if witness_dir is None else str(witness_dir),
    )


def _write(tmp_path, name, d):
    """Write a fixture-shaped entry whose claimed distance is d."""
    doc = json.loads(json.dumps(FIXTURE))
    doc["distance"] = {"d": d, "X": {"value": d}, "Z": {"value": d}}
    path = tmp_path / name
    path.write_text(json.dumps(doc))
    return str(path)


def test_pair_gives_the_candidate_and_its_peer_the_same_budget(monkeypatch, entry, tmp_path):
    """Candidate and peer are measured identically: one budget, one depth, twice.

    A gain measured on the candidate at a deeper budget than the board entry is
    an instrument artifact, not a distance difference.
    """
    peer = _write(tmp_path, "peer.json", 1)
    seen = []

    def fake(_hx, _hz, trials, _seed, threads=8, pair_depth=10, prepared=None):
        seen.append((trials, pair_depth))
        return WITNESS[0], WITNESS[1], WITNESS[2], 0.0

    monkeypatch.setattr(la, "ris", fake)
    la.cmd_pair(_pair_args(entry, [peer]))
    assert seen == [(2000, 10), (2000, 10)], "the two entries were measured differently"


def test_pair_redirects_when_the_board_peer_is_the_soft_one(monkeypatch, entry, tmp_path, capsys):
    """Candidate holds its claim, the peer is refuted at the same budget.

    That is the finding worth acting on: the board number moved, so the
    submission to make is the peer's distance revision, not the candidate.
    """
    peer = _write(tmp_path, "peer.json", 6)  # claim 6, search finds 2 -> refuted
    monkeypatch.setattr(la, "ris", lambda *a, **k: (WITNESS[0], WITNESS[1], WITNESS[2], 0.0))
    rc = la.cmd_pair(_pair_args(entry, [peer]))
    out = capsys.readouterr().out
    assert rc == la.EXIT_REFUTED
    assert la.DECISION_REDIRECT in out


def test_pair_drops_a_candidate_whose_own_claim_collides(monkeypatch, tmp_path, capsys):
    """The candidate comes down first: dropping it outranks any peer finding."""
    candidate = _write(tmp_path, "cand.json", 6)  # claim 6, search finds 2 -> refuted
    peer = _write(tmp_path, "peer.json", 6)  # also soft, but not the point
    monkeypatch.setattr(la, "ris", lambda *a, **k: (WITNESS[0], WITNESS[1], WITNESS[2], 0.0))
    rc = la.cmd_pair(_pair_args(candidate, [peer]))
    out = capsys.readouterr().out
    assert rc == la.EXIT_REFUTED
    assert la.DECISION_DROP in out and la.DECISION_REDIRECT not in out


def test_pair_neither_reached_is_inconclusive_and_exits_zero(monkeypatch, entry, tmp_path, capsys):
    """An under-read budget says nothing about either code, and must not gate."""
    peer = _write(tmp_path, "peer.json", 1)
    monkeypatch.setattr(la, "ris", lambda *a, **k: (float("inf"), "", [], 0.0))
    rc = la.cmd_pair(_pair_args(entry, [peer]))
    out = capsys.readouterr().out
    assert rc == la.EXIT_OK
    assert la.DECISION_INCONCLUSIVE in out


def test_pair_without_a_d_only_peer_is_a_usage_error(monkeypatch, entry, capsys):
    """`pair` answers one question; a candidate with no peer does not have it."""
    monkeypatch.setattr(la, "_CODES", os.path.join(os.path.dirname(entry), "no-such-dir"))
    assert la.cmd_pair(_pair_args(entry, [])) == la.EXIT_INVALID
    assert "not the suspect pattern" in capsys.readouterr().err


def test_select_peers_takes_only_equal_n_k_w_with_a_lower_d(monkeypatch, entry, tmp_path):
    """The peer set is exactly the entries a d-only gain would be measured against."""
    board = tmp_path / "codes"
    board.mkdir()
    doc = json.loads(json.dumps(FIXTURE))
    variants = {
        "peer.json": {"n": 4, "k": 2, "d": 1},  # the d-only peer
        "heavier.json": {"n": 4, "k": 2, "d": 3},  # not lower d: no gain over it
        "other-n.json": {"n": 5, "k": 2, "d": 1},  # different n: not a d-only tie
        "other-k.json": {"n": 4, "k": 1, "d": 1},  # different k: a structural win too
        "weight-1.json": {"n": 4, "k": 2, "d": 1},  # different check weight
    }
    for name, over in variants.items():
        variant = json.loads(json.dumps(doc))
        variant.update({k: v for k, v in over.items() if k in ("n", "k")})
        variant["distance"] = {"d": over["d"], "X": {"value": over["d"]}, "Z": {"value": over["d"]}}
        if name == "weight-1.json":
            variant["checks"] = {"X": [[0], [1], [2], [3]], "Z": [[0], [1], [2], [3]]}
        (board / name).write_text(json.dumps(variant))

    monkeypatch.setattr(la, "_CODES", str(board))
    peers = la.select_peers(entry)
    assert peers == [str(board / "peer.json")], peers


def test_peer_weight_comes_from_the_same_definition_as_the_candidate(monkeypatch, entry, tmp_path):
    """A repeated check index cancels over GF(2), so both sides count it that way.

    Weighing the candidate from its matrices and a peer from its raw JSON rows
    gave two answers to one quantity, inside a function whose only job is an
    equal-w comparison. The peer below ties the candidate on the raw distinct
    index count (4) but its dense weight is 3, so it is not a weight peer.
    """
    board = tmp_path / "codes"
    board.mkdir()
    variant = json.loads(json.dumps(FIXTURE))
    variant["distance"] = {"d": 1, "X": {"value": 1}, "Z": {"value": 1}}
    variant["checks"] = {"X": [[0, 0, 1, 2, 3]], "Z": [[0, 0, 1, 2, 3]]}
    (board / "repeat.json").write_text(json.dumps(variant))

    _, _, HX, HZ, _ = la.load_entry(entry)
    assert la._dense_weight(HX, HZ) == 4
    assert la._doc_weight(variant) == 3  # the doc route, dense
    assert len(set(variant["checks"]["X"][0])) == 4  # what the raw route counted
    monkeypatch.setattr(la, "_CODES", str(board))
    assert la.select_peers(entry) == []


def test_decide_is_order_sensitive():
    """A collapsing candidate is dropped even when the peer is also soft."""
    cand = {"verdict": la.VERDICT_REFUTED}
    peer = [{"verdict": la.VERDICT_REFUTED}]
    assert la.decide(cand, peer) == (la.DECISION_DROP, la.EXIT_REFUTED)
    assert la.decide({"verdict": la.VERDICT_HOLDS}, peer) == (la.DECISION_REDIRECT, la.EXIT_REFUTED)
    assert la.decide({"verdict": la.VERDICT_HOLDS}, [{"verdict": la.VERDICT_HOLDS}]) == (
        la.DECISION_CREDIBLE,
        la.EXIT_OK,
    )
    assert la.decide({"verdict": la.VERDICT_HOLDS}, [{"verdict": la.VERDICT_INCONCLUSIVE}]) == (
        la.DECISION_INCONCLUSIVE,
        la.EXIT_OK,
    )
    assert la.decide({"verdict": la.VERDICT_INCONCLUSIVE}, [{"verdict": la.VERDICT_HOLDS}]) == (
        la.DECISION_INCONCLUSIVE,
        la.EXIT_OK,
    )
