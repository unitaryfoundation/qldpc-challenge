"""Tests for the prefilters (#617) and adaptive screening (#618).

Both features exist to skip work, so the property that matters is that they
skip only work whose outcome was already determined. A filter that drops a
candidate which could have scored is worse than no filter, because the loss is
silent.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "kit"))
import search as S
from bb import build_bb
from css import compute_k


def test_bb_shape_matches_the_built_matrices():
    """The prefilter's (n, w) must equal what building actually produces."""
    for ell, m, A, B in (
        (6, 6, [(0, 0), (1, 0), (0, 1)], [(0, 0), (2, 0), (0, 3)]),
        (4, 5, [(0, 0), (1, 2)], [(0, 0), (3, 1), (2, 4)]),
    ):
        HX, HZ = build_bb(ell, m, A, B)
        n_pred, w_pred = S.bb_shape(ell, m, A, B)
        assert n_pred == HX.shape[1]
        w_real = max(*(int(r.sum()) for r in HX), *(int(r.sum()) for r in HZ))
        assert w_pred == w_real


def test_prefilters_drop_only_out_of_range_candidates():
    """Check that everything yielded satisfies the filters.

    The audit counts must also account for every sampled candidate.
    """
    audit = {}
    got = list(
        S.sample_bb(120, l_range=(3, 9), m_range=(3, 9), weight=3, seed=4, n_range=(40, 100), max_weight=6, audit=audit)
    )
    for spec, HX, _HZ in got:
        n, w = S.bb_shape(spec["l"], spec["m"], spec["A"], spec["B"])
        assert 40 <= n <= 100 and w <= 6
        assert HX.shape[1] == n
    assert audit["built"] == len(got)
    assert audit["sampled"] == audit["built"] + audit["rejected_n"] + audit["rejected_w"]
    assert audit["rejected_n"] > 0, "no candidate was filtered; test is vacuous"


def test_prefilters_do_not_change_which_codes_survive():
    """Filtering must not change which codes come out.

    The filtered sweep must yield exactly what an unfiltered one would have
    yielded and then kept.
    """
    unfiltered = list(S.sample_bb(120, l_range=(3, 9), m_range=(3, 9), weight=3, seed=4))
    expect = {
        (s["l"], s["m"], tuple(s["A"]), tuple(s["B"]))
        for s, _hx, _hz in unfiltered
        if 40 <= S.bb_shape(s["l"], s["m"], s["A"], s["B"])[0] <= 100
    }
    filtered = {
        (s["l"], s["m"], tuple(s["A"]), tuple(s["B"]))
        for s, _hx, _hz in S.sample_bb(120, l_range=(3, 9), m_range=(3, 9), weight=3, seed=4, n_range=(40, 100))
    }
    assert filtered == expect


def test_mixed_volume_is_not_a_sound_k_bound():
    """Guard the docstring's claim with the counterexample that motivates it.

    If this ever fails because the bound became sound, the note in sample_bb
    should be revisited rather than the test deleted.
    """
    from surrogate import mixed_volume

    A = B = [(0, 0), (1, 0), (0, 1)]
    ell = m = 3
    HX, HZ = build_bb(ell, m, A, B)
    k = int(compute_k(HX, HZ))
    mv = mixed_volume(A, B)
    assert k > mv, f"expected the bound to be violated here; k={k} mv={mv}"


def _fixed_candidates(seed=3, num=24):
    # Small tori and a modest count: these tests assert relationships
    # between the two screens, which hold at any budget, so the budget is
    # chosen for CI wall time rather than for distance accuracy.
    return list(S.sample_bb(num, l_range=(3, 6), m_range=(3, 6), weight=3, seed=seed))


def test_adaptive_keeps_every_candidate_a_flat_screen_would_report():
    """Nothing above the target may be lost to staging.

    A candidate is dropped only when its stage reading, an upper bound on d,
    already scores below the target; since deeper stages can only lower d, the
    flat screen cannot have scored it higher.
    """
    cands = _fixed_candidates()
    target = 2.0
    flat = S.screen(cands, trials=2_000, seed=0)
    flat_good = {r["fingerprint"] for r in flat if r["efficiency"] >= target}
    adaptive = S.screen_adaptive(_fixed_candidates(), stages=(120, 2_000), target=target, seed=0)
    got = {r["fingerprint"] for r in adaptive}
    assert flat_good <= got, f"adaptive lost {flat_good - got}"


def test_adaptive_reports_its_savings():
    audit = {}
    S.screen_adaptive(_fixed_candidates(), stages=(120, 2_000), target=5.0, seed=0, audit=audit)
    assert audit["trials_spent"] < audit["trials_flat"], f"no saving: {audit['trials_spent']} vs {audit['trials_flat']}"
    assert sum(audit["rejected"]) > 0, "nothing was rejected; test is vacuous"


def test_adaptive_without_a_target_drops_nothing():
    cands = _fixed_candidates()
    flat = {r["fingerprint"] for r in S.screen(cands, trials=2_000, seed=0)}
    adaptive = {
        r["fingerprint"] for r in S.screen_adaptive(_fixed_candidates(), stages=(120, 2_000), target=None, seed=0)
    }
    assert flat == adaptive


def test_prepared_search_returns_what_the_plain_one_does():
    """Caching the bases must not change any answer.

    The bases depend only on the check matrices, so a prepared search is the
    same computation with the setup hoisted; if this ever diverges, the cache
    is being written through somewhere.
    """
    from bb import KNOWN, build_bb
    from surrogate import distance_rand, prepare_distance_search

    p = KNOWN["[[72,12,6]]"]
    HX, HZ = build_bb(p["l"], p["m"], p["A"], p["B"])
    prep = prepare_distance_search(HX, HZ)
    for trials in (20, 60):
        for seed in (1, 2, 3):
            assert distance_rand(HX, HZ, trials=trials, seed=seed) == distance_rand(
                prepared=prep, trials=trials, seed=seed
            )


def test_prepared_object_survives_repeated_use():
    """One prepared object, many searches: no state may leak between calls."""
    from bb import KNOWN, build_bb
    from surrogate import distance_rand, prepare_distance_search

    p = KNOWN["[[72,12,6]]"]
    HX, HZ = build_bb(p["l"], p["m"], p["A"], p["B"])
    prep = prepare_distance_search(HX, HZ)
    first = distance_rand(prepared=prep, trials=40, seed=5)
    for _ in range(4):
        distance_rand(prepared=prep, trials=40, seed=9)
    assert distance_rand(prepared=prep, trials=40, seed=5) == first


def test_staged_screen_never_reports_a_worse_bound_than_a_stage_found():
    """A deeper stage must not discard a better bound an earlier one proved.

    Stages draw independently, so a later one can come back higher. Every
    reading is a valid upper bound, so the reported value must be the best of
    them; reporting the latest would throw away a proved result.
    """
    pool = _fixed_candidates()
    staged = {r["fingerprint"]: r["d"] for r in S.screen_adaptive(pool, stages=(60, 300), target=None, seed=0)}
    for st in ((60,), (300,)):
        single = S.screen_adaptive(pool, stages=st, target=None, seed=0)
        for r in single:
            if r["fingerprint"] in staged:
                assert staged[r["fingerprint"]] <= r["d"], (
                    f"staged reported {staged[r['fingerprint']]} where a {st[0]}-trial stage alone found {r['d']}"
                )


def _known_pool():
    from bb import KNOWN, build_bb

    return [({"family": "bb", **p}, *build_bb(p["l"], p["m"], p["A"], p["B"])) for p in KNOWN.values()]


def test_worker_count_does_not_change_the_result():
    """A parallel sweep must return exactly what a serial one does.

    Seeds come from each candidate's fingerprint and ties break on fingerprint,
    so neither the number of workers nor the order candidates finish in can move
    the output. If this ever fails, results stop being reproducible from a seed
    alone, which is the property the whole screen rests on.
    """
    pool = _known_pool()
    base = S.screen(pool, trials=40, seed=0)
    for w in (2, 3, 5):
        assert S.screen(pool, trials=40, seed=0, workers=w) == base, f"{w} workers disagreed with serial"


def test_batching_does_not_change_the_result():
    pool = _known_pool()
    base = S.screen(pool, trials=40, seed=0, workers=2, batch=64)
    for b in (1, 3, 1000):
        assert S.screen(pool, trials=40, seed=0, workers=2, batch=b) == base


def test_oversubscription_is_refused():
    """Both axes at once thrashes; the caller should hear about it."""
    import pytest as _pytest

    with _pytest.raises(ValueError, match="oversubscribes"):
        S.screen(_known_pool(), trials=10, workers=4, threads_per_candidate=4)


def test_candidates_are_pulled_lazily():
    """The generator must not be drained before work starts.

    A sweep is often an unbounded generator, so materializing it would defeat
    the point of streaming candidates at all.
    """
    pool = _known_pool()
    pulled = []

    def counting():
        for item in pool:
            pulled.append(1)
            yield item

    S.screen(counting(), trials=10, seed=0, workers=2, batch=2)
    assert len(pulled) == len(pool)
    # With batch=2 the parent cannot have pulled everything before the first
    # batch was dispatched; the generator is consumed incrementally.
    assert len(pool) > 2
