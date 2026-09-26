"""Free Z2 double-cover ("doubling") machinery for bivariate bicycle codes.

The s=2 complement to ``spectral.cover_k`` (which handles odd covers only):
the cover of a base BB code on Z_l x Z_m is the BB code on Z_{2l} x Z_m with
the *same* polynomial supports.  n doubles (n_cover = 2 * n_base); the
qec-lab program (github.com/Stavan-Jain/qec-lab, experiments/bb_lab) proves:

  A12 theorem: for a free Z2 BB cover, the following are equivalent --
      (R)  sigma_* = id on H1(cover)
      k(cover) == k(base)
      1 + x^l  in (A, B)   in F2[x,y]/(x^{2l}-1, y^m-1)
  and under (R), when the base floors hold, d(cover) = 2 * d(base).

So k-preservation is a *decidable, cheap* necessary screen for doubling, and
a preserved-k cover with a witnessed d near 2*d_base is a candidate whose
distance plausibly doubled at fixed k -- the regime the odd-cover ladder
cannot reach (odd covers grow n at fixed k).

HONEST SEMANTICS. Everything here is a *screening* instrument. k-preservation
is exact (it is a rank computation, the same one the verifier recomputes).
The doubling *value* d_cover = 2*d_base is NOT claimed by this module -- the
template's floor conditions are per-instance and not checked here. Every
distance number this module produces is a surrogate upper bound; the gate
decides. Validation anchors (both known qec-lab instances,
github.com/Stavan-Jain/qec-lab @ c3f23c6ff27081d43944fb0b145819807e89c783,
`experiments/bb_lab/`):
  gross base Z6xZ6  -> cover Z12xZ6  [[144,12,12]], k preserved 12
  pair72 base Z3xZ6 -> cover Z6xZ6   [[72,4,8]],   k preserved
"""
import numpy as np

from bb import build_bb
from css import compute_k, verify_css


def build_bb_cover(l, m, A_terms, B_terms):
    """Free Z2 double cover in x: base Z_l x Z_m -> cover Z_{2l} x Z_m.

    Same supports, so check weight is unchanged. Returns (HX, HZ) with
    n_cover = 4*l*m = 2 * n_base.
    """
    return build_bb(2 * l, m, A_terms, B_terms)


def cover_params(l, m, A_terms, B_terms):
    """(n_base, n_cover) for a base grid."""
    return 2 * l * m, 4 * l * m


def k_preserved(l, m, A_terms, B_terms):
    """Exact A12 screen: is k(cover) == k(base)?

    Equivalent (qec-lab A12) to the Bezout membership 1+x^l in (A,B), i.e.
    to the homotopy condition (R). Exact, cheap, and the same rank arithmetic
    the verifier recomputes -- a passed screen cannot be gamed.
    """
    HXb, HZb = build_bb(l, m, A_terms, B_terms)
    HXc, HZc = build_bb_cover(l, m, A_terms, B_terms)
    if not verify_css(HXc, HZc):
        return None  # cannot happen for BB, but never assume
    kb = compute_k(HXb, HZb)
    kc = compute_k(HXc, HZc)
    return kc == kb


def doubling_screen(l, m, A_terms, B_terms, base_trials=200, cover_trials=300,
                    min_k=4, seed=0):
    """Full cheap screen of one base -> cover pair. Returns None if the base
    or cover fails a stage, else a dict of facts (all distances upper bounds).

    Stages: base k >= min_k -> CSS on cover -> k preserved (A12) ->
    surrogate witnesses on both.
    """
    from surrogate import distance_rand

    HXb, HZb = build_bb(l, m, A_terms, B_terms)
    kb = compute_k(HXb, HZb)
    if kb < min_k:
        return None
    HXc, HZc = build_bb_cover(l, m, A_terms, B_terms)
    if not verify_css(HXc, HZc):
        return None
    kc = compute_k(HXc, HZc)
    if kc != kb:
        return None
    db = distance_rand(HXb, HZb, trials=base_trials, seed=seed)
    dc = distance_rand(HXc, HZc, trials=cover_trials, seed=seed + 1)
    n_base, n_cover = HXb.shape[1], HXc.shape[1]
    return {
        "l": l, "m": m,
        "A_terms": [list(t) for t in A_terms],
        "B_terms": [list(t) for t in B_terms],
        "n_base": n_base, "k_base": int(kb), "d_base_ub": int(db),
        "n_cover": n_cover, "k_cover": int(kc), "d_cover_ub": int(dc),
        "eff_base": round(kb * db**2 / n_base, 2),
        "eff_cover": round(kc * dc**2 / n_cover, 2),
        "d_ratio": round(dc / db, 2) if db else None,
        "k_preserved": True,
    }


def sample_doubling_bases(n_samples, l_choices=None, m_choices=None,
                          weight=3, seed=0, max_cover_n=700):
    """Yield (spec, HX, HZ) cover triples for random weight-`weight` base
    polynomial pairs, same shape as the kit's other samplers for search.screen.

    Only bases whose cover fits the board's n <= 700 cap are emitted.
    spec carries everything needed to rebuild base and cover.
    """
    import random

    rng = random.Random(seed)
    if l_choices is None:
        l_choices = [3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
    if m_choices is None:
        m_choices = [3, 4, 5, 6, 7, 8, 9, 10, 12]
    out = 0
    while out < n_samples:
        l = rng.choice(l_choices)
        m = rng.choice(m_choices)
        if 4 * l * m > max_cover_n:
            continue
        cells = [(a, b) for a in range(l) for b in range(m)]
        # WLOG both supports contain (0,0): translating a support by a group
        # element permutes check rows, an equivalence.
        rest = [c for c in cells if c != (0, 0)]
        A_terms = [(0, 0)] + sorted(rng.sample(rest, weight - 1))
        B_terms = [(0, 0)] + sorted(rng.sample(rest, weight - 1))
        HX, HZ = build_bb_cover(l, m, A_terms, B_terms)
        spec = {
            "family": "bb-double-cover",
            "l": l, "m": m,
            "A_terms": [list(t) for t in A_terms],
            "B_terms": [list(t) for t in B_terms],
        }
        yield spec, HX, HZ
        out += 1


if __name__ == "__main__":
    print("== validation anchors (known qec-lab instances) ==")
    anchors = [
        ("gross  Z6xZ6 -> Z12xZ6 [[144,12,12]]", 6, 6,
         [(3, 0), (0, 1), (0, 2)], [(0, 3), (1, 0), (2, 0)], 12),
        ("pair72 Z3xZ6 -> Z6xZ6  [[72,4,8]]",    3, 6,
         [(2, 0), (0, 1), (0, 3)], [(0, 0), (1, 0), (0, 2)], 4),
    ]
    ok_all = True
    for name, l, m, A, B, k_expect in anchors:
        HXb, HZb = build_bb(l, m, A, B)
        HXc, HZc = build_bb_cover(l, m, A, B)
        kb, kc = compute_k(HXb, HZb), compute_k(HXc, HZc)
        css = verify_css(HXc, HZc)
        nb, nc = HXb.shape[1], HXc.shape[1]
        ok = css and kb == kc == k_expect and nc == 2 * nb
        ok_all &= ok
        print(f"{name}: base n={nb} k={kb}, cover n={nc} k={kc} "
              f"css={css} k_preserved={kb == kc}  {'OK' if ok else 'FAIL'}")
    print("== sampler smoke (3 covers) ==")
    for spec, HX, HZ in sample_doubling_bases(3, seed=7):
        n, k = HX.shape[1], compute_k(HX, HZ)
        print(f"Z_{spec['l']}xZ_{spec['m']} -> cover n={n} k={k} "
              f"A={spec['A_terms']} B={spec['B_terms']}")
    print("ALL OK" if ok_all else "ANCHOR FAILURE")
