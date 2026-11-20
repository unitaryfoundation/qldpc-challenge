"""GF(2) polynomial arithmetic and the designed-divisor route to cyclic GB codes.

Every one of the board's 25 most efficient entries is a cyclic
generalized-bicycle code, H_X = [circ(a) | circ(b)] over Z_m with m near 340,
check weight 12 to 32, and none of them came from random supports (issue
#2778). For that family k = 2 deg gcd(a, b, x^m - 1), so a random pair of
supports has gcd 1 with x^m - 1 almost always and k = 2: measured at weight 12
on Z_315, Z_330, and Z_341, 150 of 180 random draws had k = 2 and none had
k above 12. The entries at the frontier instead pick a divisor g of x^m - 1
first, so that k is designed, and then look for sparse multiples of g to use
as a and b. ``research/cyclic_gb.py`` is the full search stack for that
route and needs sympy to factor x^m - 1; this module is the part a sampler
needs, with the factorization done here over GF(2) so the kit stays
numpy-only.

Polynomials are Python ints with bit i the coefficient of x^i, which makes
multiplication a shift-and-xor loop and keeps m = 341 well under a
millisecond per product.
"""

import numpy as np
from css import kernel_basis, rref


def deg(a):
    """Degree of ``a``; -1 for the zero polynomial."""
    return a.bit_length() - 1


def mul(a, b):
    """Return the product of ``a`` and ``b`` over GF(2)."""
    r = 0
    while b:
        if b & 1:
            r ^= a
        a <<= 1
        b >>= 1
    return r


def mod(a, m):
    """Return the remainder of ``a`` modulo ``m`` over GF(2)."""
    dm = deg(m)
    while a and deg(a) >= dm:
        a ^= m << (deg(a) - dm)
    return a


def div(a, m):
    """Return the quotient of ``a`` by ``m`` over GF(2)."""
    q, dm = 0, deg(m)
    while a and deg(a) >= dm:
        s = deg(a) - dm
        q |= 1 << s
        a ^= m << s
    return q


def gcd(a, b):
    """Return the greatest common divisor of ``a`` and ``b`` over GF(2)."""
    while b:
        a, b = b, mod(a, b)
    return a


def x_pow_m_minus_1(m):
    """Return x^m - 1, which over GF(2) is x^m + 1."""
    return (1 << m) | 1


def factor_squarefree(f, rng):
    """Return the irreducible factors of a squarefree ``f`` over GF(2).

    Distinct-degree factorization peels off the product of all irreducible
    factors of each degree d as gcd(f, x^(2^d) - x), and equal-degree
    splitting breaks that product with random trace maps. x^m - 1 is
    squarefree exactly when m is odd, which is the only case a cyclic GB code
    wants. ``rng`` is a ``random.Random``.
    """
    out, d, g = [], 1, f
    x = 2
    xp = x
    while deg(g) >= 2 * d:
        xp = mod(mul(xp, xp), g)  # x^(2^d) mod g
        h = gcd(g, xp ^ x)
        if deg(h) > 0:
            out += _equal_degree_split(h, d, rng)
            g = div(g, h)
            xp = mod(xp, g)
        d += 1
    if deg(g) > 0:
        out.append(g)
    return out


def _equal_degree_split(h, d, rng):
    """Split ``h``, a product of distinct irreducibles of degree ``d``."""
    if deg(h) == d:
        return [h]
    while True:
        r = rng.getrandbits(deg(h)) | 1
        t, s = 0, mod(r, h)
        for _ in range(d):  # Tr(r) = r + r^2 + ... + r^(2^(d-1))
            t ^= s
            s = mod(mul(s, s), h)
        g = gcd(h, t)
        if 0 < deg(g) < deg(h):
            return _equal_degree_split(g, d, rng) + _equal_degree_split(div(h, g), d, rng)


def designed_divisor(factors, deg_band, rng, tries=500):
    """Return a product of some of ``factors`` with degree in ``deg_band``.

    None when ``tries`` random subsets all miss the band, which happens when
    the band is narrower than the factor degrees allow (on Z_341 the factors
    have degrees 1, 5, and 10, so a band that admits no sum of those is
    empty).
    """
    lo, hi = deg_band
    facs = list(factors)
    for _ in range(tries):
        rng.shuffle(facs)
        g, dg = 1, 0
        for p in facs:
            if dg + deg(p) <= hi and rng.random() < 0.5:
                g = mul(g, p)
                dg += deg(p)
        if lo <= dg <= hi:
            return g
    return None


def to_vector(p, m):
    """Return the length-``m`` coefficient vector of ``p``."""
    return np.array([(p >> i) & 1 for i in range(m)], dtype=np.int8)


def from_support(support, m):
    """Return the polynomial with the given exponent support."""
    p = 0
    for e in support:
        p |= 1 << (int(e) % m)
    return p


def circulant(v):
    """Return the m x m circulant whose rows are the cyclic shifts of ``v``."""
    return np.array([np.roll(v, i) for i in range(len(v))], dtype=np.int8)


def reciprocal(p):
    """Return x^deg(p) p(1/x), the polynomial with the coefficients reversed."""
    d = deg(p)
    return int(format(p, f"0{d + 1}b")[::-1], 2) if d >= 0 else 0


def sparse_multiples(m, g, weight_band, rng, trials=200, max_words=64):
    """Return sparse multiples of ``g`` modulo x^m - 1 as exponent supports.

    With h = (x^m - 1)/g, the multiples of g are the kernel of the circulant
    whose rows are the shifts of the reciprocal of h (the shifts of h itself
    give the multiples of the reciprocal of g, which has the same degree and
    so the same k, but is a different ideal). Each trial permutes the
    columns, row-reduces a kernel basis, and keeps the rows whose weight
    falls in ``weight_band``; this is the Prange search of
    ``research/cyclic_gb.py``, without its pairwise-sum pass. ``rng`` is a
    numpy generator.
    """
    h = reciprocal(div(x_pow_m_minus_1(m), g))
    K = kernel_basis(circulant(to_vector(h, m)))
    if K.size == 0:
        return []
    lo, hi = weight_band
    words = {}
    for _ in range(trials):
        perm = rng.permutation(m)
        red = rref(K[:, perm])[0]
        w = red.sum(axis=1)
        for i in np.where((w >= lo) & (w <= hi))[0]:
            v = np.zeros(m, dtype=np.int8)
            v[perm] = red[i]
            words.setdefault(tuple(int(q) for q in np.flatnonzero(v)), True)
            if len(words) >= max_words:
                return list(words)
    return list(words)


def cyclic_gb(m, a, b):
    """Return (H_X, H_Z) of the cyclic GB code with supports ``a``, ``b``.

    H_X = [circ(a) | circ(b)] and H_Z = [circ(b)^T | circ(a)^T], the board's
    convention for this family; the blocks commute because circulants do.
    """
    A = circulant(to_vector(from_support(a, m), m))
    B = circulant(to_vector(from_support(b, m), m))
    return (np.concatenate([A, B], axis=1), np.concatenate([B.T, A.T], axis=1))


def designed_k(m, a, b):
    """Return k = 2 deg gcd(a, b, x^m - 1), the dimension the pair encodes."""
    g = gcd(gcd(from_support(a, m), from_support(b, m)), x_pow_m_minus_1(m))
    return 2 * deg(g)
