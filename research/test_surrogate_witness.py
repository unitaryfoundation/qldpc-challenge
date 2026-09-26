"""Tests for the public witness-returning search on ``surrogate``.

What is pinned here is the contract callers rely on instead of reaching into
private names: ``pair_depth`` reaches both backends, a backend proposal is
validated in Python before it is returned, and "found nothing" and "proposed
something that is not a logical" are distinguishable without being confusable
with a real result.

The accelerator is exercised through a fake, so the suite is identical with and
without ``make fast``. The one test that needs the real backend skips when it is
absent.
"""
import os
import sys

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "kit"))
sys.path.insert(0, os.path.join(_HERE, "..", "verify"))

import surrogate  # noqa: E402
from bb import build_bb  # noqa: E402


@pytest.fixture(scope="module")
def code():
    """Build the [[72,12,6]] bivariate bicycle code: small, and d is known."""
    return build_bb(6, 6, [(3, 0), (0, 1), (0, 2)], [(0, 3), (1, 0), (2, 0)])


class FakeFast:
    """An accelerator stub that returns whatever the test wants."""

    def __init__(self, reply):
        self.reply = reply
        self.seen = {}

    def distance_rand_witness(self, HX, HZ, trials, seed, pair_depth, threads):
        self.seen = {"trials": trials, "seed": seed,
                     "pair_depth": pair_depth, "threads": threads}
        return self.reply


def test_pair_depth_reaches_the_numpy_search(monkeypatch, code):
    HX, HZ = code
    seen = []

    def recording(hself, hopp, trials, seed, pair_depth=10, bases=None):
        seen.append(pair_depth)
        return float("inf"), []

    monkeypatch.setattr(surrogate, "_fast", None)
    monkeypatch.setattr(surrogate, "_search_lightest", recording)
    surrogate.distance_rand_witness(HX, HZ, trials=5, seed=1, pair_depth=64)
    assert seen == [64, 64], "one side searched at a different depth"


def test_pair_depth_reaches_the_accelerator(monkeypatch, code):
    HX, HZ = code
    fake = FakeFast((HX.shape[1] + 1, "", []))
    monkeypatch.setattr(surrogate, "_fast", fake)
    surrogate.distance_rand_witness(HX, HZ, trials=17, seed=3, threads=2,
                                    pair_depth=64, backend="auto")
    assert fake.seen == {"trials": 17, "seed": 3, "pair_depth": 64,
                         "threads": 2}


def test_the_default_depth_is_unchanged_on_both_backends(monkeypatch, code):
    HX, HZ = code
    seen = []

    def recording(hself, hopp, trials, seed, pair_depth=10, bases=None):
        seen.append(pair_depth)
        return float("inf"), []

    monkeypatch.setattr(surrogate, "_fast", None)
    monkeypatch.setattr(surrogate, "_search_lightest", recording)
    surrogate.distance_rand_witness(HX, HZ, trials=5, seed=1)
    assert seen == [10, 10]

    fake = FakeFast((HX.shape[1] + 1, "", []))
    monkeypatch.setattr(surrogate, "_fast", fake)
    surrogate.distance_rand_witness(HX, HZ, trials=5, seed=1, backend="auto")
    assert fake.seen["pair_depth"] == 10


def test_the_two_sides_draw_independent_streams(monkeypatch, code):
    """The Z side must not replay the X side, nor the next seed's X side."""
    HX, HZ = code
    seeds = []

    def recording(hself, hopp, trials, seed, pair_depth=10, bases=None):
        seeds.append(seed)
        return float("inf"), []

    monkeypatch.setattr(surrogate, "_fast", None)
    monkeypatch.setattr(surrogate, "_search_lightest", recording)
    surrogate.distance_rand_witness(HX, HZ, trials=5, seed=101)
    assert len(seeds) == 2
    x = np.random.default_rng(seeds[0]).random(8)
    z = np.random.default_rng(seeds[1]).random(8)
    assert not np.array_equal(x, z)
    assert not np.array_equal(z, np.random.default_rng(102).random(8))


def test_the_no_logical_sentinel_is_falsy_and_carries_no_rejection(monkeypatch, code):
    """A search that found nothing is a result, not an error."""
    HX, HZ = code
    monkeypatch.setattr(surrogate, "_fast", FakeFast((HX.shape[1] + 1, "", [])))
    found = surrogate.distance_rand_witness(HX, HZ, trials=5, seed=1,
                                            backend="auto")
    assert not found
    assert found.weight == float("inf") and found.side == "" and found.support == []
    assert found.rejected == "", "no proposal was made, so none was rejected"
    assert surrogate.distance_rand(HX, HZ, trials=5, seed=1,
                                   backend="auto") == float("inf")


def test_an_invalid_accelerator_proposal_is_never_returned_as_a_logical(monkeypatch, code):
    """Qubits 0 and 1 are not a weight-2 logical of this code."""
    HX, HZ = code
    monkeypatch.setattr(surrogate, "_fast", FakeFast((2, "X", [0, 1])))
    found = surrogate.distance_rand_witness(HX, HZ, trials=5, seed=1,
                                            backend="auto")
    assert not found, "an unvalidated proposal was returned as a logical"
    assert found.weight == float("inf") and found.support == []
    assert found.rejected, "the reason for the rejection was dropped"
    with pytest.raises(RuntimeError):
        surrogate.distance_rand(HX, HZ, trials=5, seed=1, backend="auto")


def test_an_invalid_numpy_result_is_rejected_the_same_way(monkeypatch, code):
    """Both backends go through one validator, so both are caught."""
    HX, HZ = code
    monkeypatch.setattr(surrogate, "_fast", None)
    monkeypatch.setattr(surrogate, "_search_lightest",
                        lambda *a, **k: (2, [0, 1]))
    found = surrogate.distance_rand_witness(HX, HZ, trials=5, seed=1)
    assert not found and found.rejected


def test_a_real_search_returns_a_witness_that_validates(code):
    """The support a caller writes into a submission is checked here first."""
    HX, HZ = code
    found = surrogate.distance_rand_witness(HX, HZ, trials=200, seed=0,
                                            backend="numpy")
    assert found, "the numpy search found no logical in a k=12 code"
    assert found.weight == len(found.support) == 6
    ok, why = surrogate.validate_logical(HX, HZ, found.side, found.weight,
                                         found.support)
    assert ok, why


@pytest.mark.skipif(surrogate._fast is None,
                    reason="gf2_fast is not built (make fast)")
def test_the_real_accelerator_also_returns_a_validated_witness(code):
    HX, HZ = code
    found = surrogate.distance_rand_witness(HX, HZ, trials=2000, seed=0,
                                            backend="fast")
    assert found and not found.rejected
    ok, why = surrogate.validate_logical(HX, HZ, found.side, found.weight,
                                         found.support)
    assert ok, why


def test_the_scalar_and_witness_forms_agree(code):
    HX, HZ = code
    found = surrogate.distance_rand_witness(HX, HZ, trials=200, seed=0,
                                            backend="numpy")
    assert surrogate.distance_rand(HX, HZ, trials=200, seed=0,
                                   backend="numpy") == found.weight


def test_validate_logical_rejects_what_the_verifier_would(code):
    HX, HZ = code
    n = HX.shape[1]
    good = surrogate.distance_rand_witness(HX, HZ, trials=200, seed=0,
                                           backend="numpy")
    side, support = good.side, good.support
    cases = {
        "no witness": ("", 2, [0, 1]),
        "weight != support size": (side, len(support) + 1, support),
        "bad support": (side, 2, [0, n + 5]),
    }
    for expected, (s, w, sup) in cases.items():
        ok, why = surrogate.validate_logical(HX, HZ, s, w, sup)
        assert not ok and why == expected, (expected, why)
    dup = [support[0], support[0]]
    ok, why = surrogate.validate_logical(HX, HZ, side, 2, dup)
    assert not ok and why == "bad support"
    # a stabilizer row commutes with everything but is trivial
    row = sorted(int(q) for q in np.nonzero(HX[0])[0])
    ok, why = surrogate.validate_logical(HX, HZ, "X", len(row), row)
    assert not ok and why == "lies in the stabilizer row space (trivial)"


def test_pair_depth_must_be_at_least_one(code):
    HX, HZ = code
    with pytest.raises(ValueError):
        surrogate.distance_rand_witness(HX, HZ, trials=5, seed=1, pair_depth=0)
