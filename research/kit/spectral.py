"""Spectral (Frobenius-orbit) screening tools for semisimple BB codes.

Methods from arXiv:2608.27565 (Sabo, Can, Marquis, "Spectral Theory of
Semisimple Bivariate Bicycle Codes"), restricted to the binary semisimple
case: both torus dimensions odd (gcd(2, l*m) = 1).

What this adds over ``surrogate.mixed_volume`` (which only *bounds* k):

* ``spectral_k``        -- the EXACT logical dimension k = 2|Z_a ∩ Z_b|
  (paper Thm 81), matrix-free, from GF(2^e) evaluations of the check
  polynomials on the root grid Z_l x Z_m.
* ``colon_lower_bound`` -- a PROVEN lower bound d >= min{E_a, E_b, N_a,b}
  (Thm 88/91, conservative strip form of Remark 92). Each term is a minimum
  distance of a classical 2D cyclic code defined by a zero-region, itself
  lower-bounded by 2D BCH strips (Thm 58): delta-1 consecutive full zero
  columns/rows prove d >= delta (one-sided), delta_x*delta_y (two-sided).
* ``cover_k``           -- the cover dimension law k_h = k + 2|delta-Z|
  (Thm 126): the exact k of any odd cover (l,m) -> (s*l, s*m), s odd,
  computed before the cover is ever built.

HONEST SEMANTICS. Everything here is a *pruning* instrument, never a claim:
the board certifies d <= via witnesses and recomputes k from H. The lower
bound proves a candidate is DEAD (its true distance cannot reach a target);
it never proves one is good. Even-dimension grids (the repeated-root case,
which includes the 6x6 gross code) are out of scope -- use matrix rank
(``css.compute_k``) there. The X-side bound equals the Z-side bound because
the inversion map sends cyclic strips to cyclic strips (paper Example 95),
so the bound applies to d = min(dX, dZ).
"""

import math

import numpy as np

# ---------------------------------------------------------------------------
# GF(2^e) machinery. Primitive polynomials (exponent lists) for e <= 16, each
# verified at first use by checking that x has order 2^e - 1 (needs the prime
# factorization of every Mersenne number below).
# ---------------------------------------------------------------------------
_PRIM_EXPONENTS = {
    1: (1, 0),
    2: (2, 1, 0),
    3: (3, 1, 0),
    4: (4, 1, 0),
    5: (5, 2, 0),
    6: (6, 1, 0),
    7: (7, 1, 0),
    8: (8, 4, 3, 2, 0),
    9: (9, 4, 0),
    10: (10, 3, 0),
    11: (11, 2, 0),
    12: (12, 6, 4, 1, 0),
    13: (13, 4, 3, 1, 0),
    14: (14, 5, 3, 1, 0),
    15: (15, 1, 0),
    16: (16, 5, 3, 2, 0),
    17: (17, 3, 0),
    18: (18, 7, 0),
    19: (19, 5, 2, 1, 0),
    20: (20, 3, 0),
}

_MERSENNE_FACTORS = {
    1: (),
    2: (3,),
    3: (7,),
    4: (3, 5),
    5: (31,),
    6: (3, 7),
    7: (127,),
    8: (3, 5, 17),
    9: (7, 73),
    10: (3, 11, 31),
    11: (23, 89),
    12: (3, 5, 7, 13),
    13: (8191,),
    14: (3, 43, 127),
    15: (7, 31, 151),
    16: (3, 5, 17, 257),
    17: (131071,),  # Mersenne prime M17
    18: (3, 7, 19, 73),
    19: (524287,),  # Mersenne prime M19
    20: (3, 5, 11, 31, 41),
}

_MAX_DEGREE = 20


def _poly_mulmod(a, b, mod):
    """Carryless product of two GF(2) polynomials (int bitmasks), reduced mod
    ``mod``."""
    res = 0
    while b:
        if b & 1:
            res ^= a
        b >>= 1
        a <<= 1
    # reduce
    mb = mod.bit_length()
    while res.bit_length() >= mb:
        res ^= mod << (res.bit_length() - mb)
    return res


def _poly_powmod(base, expn, mod):
    result = 1
    while expn:
        if expn & 1:
            result = _poly_mulmod(result, base, mod)
        base = _poly_mulmod(base, base, mod)
        expn >>= 1
    return result


def _primitive_poly(e):
    """Verified primitive polynomial of degree ``e`` as an int bitmask."""
    if e not in _PRIM_EXPONENTS:
        raise ValueError(
            f"no primitive polynomial tabulated for degree {e} "
            f"(max {_MAX_DEGREE}); shrink the grid"
        )
    poly = sum(1 << i for i in _PRIM_EXPONENTS[e])
    m = (1 << e) - 1
    for p in _MERSENNE_FACTORS[e]:
        if _poly_powmod(2, m // p, poly) == 1:
            raise RuntimeError(
                f"tabulated degree-{e} polynomial is not " "primitive -- fix the table"
            )
    return poly


class _GF:
    """GF(2^e) with log/exp tables over the generator x."""

    def __init__(self, e):
        self.e = e
        self.order = (1 << e) - 1
        poly = _primitive_poly(e)
        exp = np.zeros(self.order, dtype=np.int64)
        val = 1
        for t in range(self.order):
            exp[t] = val
            val = _poly_mulmod(val, 2, poly)
        log = np.zeros(1 << e, dtype=np.int64)
        log[1:] = -1  # unused sentinel; log is only queried on nonzero codes
        for t in range(self.order):
            log[exp[t]] = t
        self.exp, self.log = exp, log

    def mul(self, a, b):
        """Elementwise product of nonzero field-code arrays."""
        return self.exp[(self.log[a] + self.log[b]) % self.order]


_GF_CACHE = {}


def _gf(e):
    if e not in _GF_CACHE:
        _GF_CACHE[e] = _GF(e)
    return _GF_CACHE[e]


def _ord2(L):
    """Multiplicative order of 2 modulo odd L >= 1."""
    if L % 2 == 0:
        raise ValueError(
            f"grid dimension lcm {L} is even: non-semisimple "
            "ring, spectral formulas do not apply"
        )
    e, v = 1, 2 % L
    while v != 1:
        v = v * 2 % L
        e += 1
    return e


# ---------------------------------------------------------------------------
# Root-grid evaluation and the region decomposition (paper Defs 78/79).
# ---------------------------------------------------------------------------
def _root_tabs(l, m):
    """Order-l and order-m roots of unity in GF(2^e), as power tables."""
    L = math.lcm(l, m)
    e = _ord2(L)
    if e > _MAX_DEGREE:
        raise ValueError(
            f"field degree {e} > {_MAX_DEGREE} for lcm({l},{m})"
            f"={L}; shrink the grid"
        )
    gf = _gf(e)
    M = gf.order
    ii = np.arange(l)
    jj = np.arange(m)
    alpha_tab = gf.exp[(ii * (M // l)) % M] if l > 1 else np.ones(1, np.int64)
    beta_tab = gf.exp[(jj * (M // m)) % M] if m > 1 else np.ones(1, np.int64)
    return gf, alpha_tab, beta_tab


def _eval_grid(l, m, terms, gf, alpha_tab, beta_tab):
    """Evaluate sum_{(u,v) in terms} x^u y^v at every grid point (alpha^i,
    beta^j). Returns an (l, m) int64 array of field codes; 0 = vanishes."""
    acc = np.zeros((l, m), dtype=np.int64)
    ii = np.arange(l)
    jj = np.arange(m)
    for u, v in terms:
        pa = alpha_tab[(ii * u) % l]
        pb = beta_tab[(jj * v) % m]
        acc ^= gf.mul(pa[:, None], pb[None, :])
    return acc


def spectral_regions(l, m, A_terms, B_terms):
    """Zero sets and the four-region decomposition of the root grid.

    Returns a dict with boolean arrays ``Za, Zb, T, Uab, Uba, F`` (True =
    point in the set) and a ``counts`` dict. T = Za & Zb (common zeros),
    Uab = Za \\ Zb, Uba = Zb \\ Za, F = complement of Za | Zb.
    """
    if l % 2 == 0 or m % 2 == 0:
        raise ValueError("spectral screening needs odd l and m (semisimple)")
    gf, alpha_tab, beta_tab = _root_tabs(l, m)
    Za = _eval_grid(l, m, A_terms, gf, alpha_tab, beta_tab) == 0
    Zb = _eval_grid(l, m, B_terms, gf, alpha_tab, beta_tab) == 0
    T = Za & Zb
    Uab = Za & ~Zb
    Uba = Zb & ~Za
    F = ~(Za | Zb)
    counts = {
        name: int(arr.sum())
        for name, arr in (("T", T), ("Uab", Uab), ("Uba", Uba), ("F", F))
    }
    return dict(Za=Za, Zb=Zb, T=T, Uab=Uab, Uba=Uba, F=F, counts=counts)


def spectral_k(l, m, A_terms, B_terms):
    """Exact k = 2|Z_a ∩ Z_b| (Thm 81) without building any matrix."""
    return 2 * spectral_regions(l, m, A_terms, B_terms)["counts"]["T"]


# ---------------------------------------------------------------------------
# 2D BCH strip bound (Thm 58) and the colon-ideal floor (Thm 91).
# ---------------------------------------------------------------------------
def _longest_cyclic_run(mask):
    n = len(mask)
    if mask.all():
        return n
    best = cur = 0
    for v in np.concatenate([mask, mask]):
        cur = cur + 1 if v else 0
        if cur > best:
            best = cur
    return min(best, n)


def bch_strip_bound(S):
    """Proven lower bound for the classical 2D cyclic code C(S) = {f : f
    vanishes on S}, from full zero strips (Thm 58). S is an (l, m) boolean
    array, True = defining zero. Empty S means the whole ring (d = 1); S
    everything means the zero code."""
    S = np.asarray(S, dtype=bool)
    if not S.any():
        return 1
    if S.all():
        return 1 << 30
    dx = 1 + _longest_cyclic_run(S.all(axis=1))
    dy = 1 + _longest_cyclic_run(S.all(axis=0))
    return max(dx, dy, dx * dy)


def colon_lower_bound(l, m, A_terms, B_terms):
    """Proven floor d >= min{E_a, E_b, N_a,b} (Thm 91, conservative form).

    E_a >= d(C(U_ba ∪ F)), E_b >= d(C(U_ab ∪ F)) via annihilator strips, and
    N_a,b = d(C(U_ba)) + d(C(U_ab)) via colon-ideal strips. Also returns the
    exact k. Valid for d = min(dX, dZ): inversion maps strips to strips.
    """
    r = spectral_regions(l, m, A_terms, B_terms)
    Ea = bch_strip_bound(r["Uba"] | r["F"])
    Eb = bch_strip_bound(r["Uab"] | r["F"])
    N = bch_strip_bound(r["Uba"]) + bch_strip_bound(r["Uab"])
    return dict(k=2 * r["counts"]["T"], Ea=Ea, Eb=Eb, N=N, d_lower=min(Ea, Eb, N))


def cover_k(l, m, A_terms, B_terms, s):
    """Exact k of the s-fold cover BB(s*l, s*m) with the same polynomial
    supports (Thm 126: k_h = k + 2|delta-Z|; we simply count common zeros on
    the cover grid). ``s`` must be odd so the cover ring stays semisimple."""
    if s % 2 == 0:
        raise ValueError("cover degree s must be odd (semisimple cover ring)")
    return spectral_k(s * l, s * m, A_terms, B_terms)


# ---------------------------------------------------------------------------
# Self-test / calibration demo.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    import os

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from bb import build_bb, KNOWN
    from css import compute_k
    from surrogate import distance_rand

    print("1) KNOWN odd-grid code: [[90,8,10]] on Z_15 x Z_3")
    p = KNOWN["[[90,8,10]]"]
    lb = colon_lower_bound(p["l"], p["m"], p["A"], p["B"])
    HX, HZ = build_bb(p["l"], p["m"], p["A"], p["B"])
    k_true = compute_k(HX, HZ)
    print(
        f"   spectral k = {lb['k']}  matrix k = {k_true}  "
        f"{'MATCH' if lb['k'] == k_true else 'MISMATCH'}"
    )
    print(f"   regions = {spectral_regions(p['l'], p['m'], p['A'], p['B'])['counts']}")
    print(
        f"   floor: E_a={lb['Ea']} E_b={lb['Eb']} N={lb['N']} "
        f"-> d >= {lb['d_lower']} (board d = 10)"
    )

    print("2) exact-k validation on random odd grids (vs matrix rank)")
    rng = np.random.default_rng(7)
    bad = 0
    for t in range(60):
        l, m = (int(a) for a in rng.choice([3, 5, 7, 9, 15], size=2))
        A = [tuple(int(v) for v in rng.integers(0, (l, m))) for _ in range(3)]
        A = list(dict.fromkeys(A)) or [(0, 0)]
        B = [tuple(int(v) for v in rng.integers(0, (l, m))) for _ in range(3)]
        B = list(dict.fromkeys(B)) or [(0, 1)]
        ks = spectral_k(l, m, A, B)
        km = compute_k(*build_bb(l, m, A, B))
        if ks != km:
            bad += 1
            print(f"   MISMATCH l={l} m={m} A={A} B={B}: spectral {ks} vs {km}")
    print(f"   60 random codes, {60 - bad} matches, {bad} mismatches")

    print("3) floor <= witnessed upper bound on the same random codes")
    viol = 0
    for t in range(20):
        l, m = (int(a) for a in rng.choice([3, 5, 7, 9], size=2))
        A = [tuple(int(v) for v in rng.integers(0, (l, m))) for _ in range(3)]
        B = [tuple(int(v) for v in rng.integers(0, (l, m))) for _ in range(3)]
        lb2 = colon_lower_bound(l, m, A, B)
        du = distance_rand(*build_bb(l, m, A, B), trials=300, seed=t)
        if lb2["d_lower"] > du:
            viol += 1
            print(f"   VIOLATION l={l} m={m}: floor {lb2['d_lower']} > upper {du}")
    print(f"   20 codes, {20 - viol} consistent, {viol} violations")

    print("4) cover law: predicted k_h vs built cover (Thm 126)")
    l, m, A, B = 3, 5, [(0, 0), (1, 0), (0, 1)], [(0, 2), (2, 0), (1, 1)]
    for s in (3, 5):
        pred = cover_k(l, m, A, B, s)
        got = compute_k(*build_bb(s * l, s * m, A, B))
        print(
            f"   s={s}: predicted {pred}, built {got}  "
            f"{'MATCH' if pred == got else 'MISMATCH'}"
        )
