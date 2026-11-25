"""Classical code-combining product constructions for quantum LDPC codes.

  * **Hypergraph product** (Tillich-Zémor, arXiv:0903.0566)
      HP(H1, H2):  n = n1*n2 + m1*m2,  CSS guaranteed.
      When H1 = H2 = H:  n = n^2 + m^2, d <= min(drow, dcol).

  * **Lifted product** (Panteleev-Kalachev, arXiv:2111.03654)
      LP(G, A, B):  n = 2N,  CSS guaranteed.
      Equivalent to two-block group algebra (2BGA, Lin-Pryadko arXiv:2306.16400)
      with potentially different left/right supports.

  * **HP of two 2BGA codes** — a useful composition that inherits
      algebraic structure from both parents.  The general balanced product
      (Hastings-Haah-O'Donnell, arXiv:2009.03921) is broader.

CSS commutation is AUTOMATIC for all three: the tensor-product structure
guarantees it for HP and BP (which is HP of two 2BGA codes), and left/right
regular reps commute for LP.

The sampler functions yield (spec, HX, HZ) triples consumable by kit/search.screen.
"""

import numpy as np
from group_algebra import L_rep, R_rep, build_2bga


# ======================================================================
#  Hypergraph product  (Tillich-Zémor)
# ======================================================================
def hypergraph_product(H1, H2):
    """Hypergraph product of two classical parity-check matrices.

    Parameters
    ----------
    H1 : (m1, n1) int array  — parity check of classical code C1
    H2 : (m2, n2) int array  — parity check of classical code C2

    Returns
    -------
    HX, HZ : (num_checks, n) int8 arrays, where n = n1*n2 + m1*m2.
    CSS commutation guaranteed.
    """
    H1 = np.asarray(H1, dtype=np.int8) % 2
    H2 = np.asarray(H2, dtype=np.int8) % 2
    m1, n1 = H1.shape
    m2, n2 = H2.shape

    I_n1 = np.eye(n1, dtype=np.int8)
    I_n2 = np.eye(n2, dtype=np.int8)
    I_m1 = np.eye(m1, dtype=np.int8)
    I_m2 = np.eye(m2, dtype=np.int8)

    HX = np.hstack(
        [
            np.kron(H1, I_n2),  # (m1*n2, n1*n2)
            np.kron(I_m1, H2.T),  # (m1*n2, m1*m2)
        ]
    ).astype(np.int8)

    HZ = np.hstack(
        [
            np.kron(I_n1, H2),  # (n1*m2, n1*n2)
            np.kron(H1.T, I_m2),  # (n1*m2, m1*m2)
        ]
    ).astype(np.int8)

    return HX, HZ


# ======================================================================
#  Lifted product  (two-block group algebra)
# ======================================================================
def lifted_product(mul, a, b):
    """Lifted product (two-block group algebra) over a finite group.

    Equivalent to group_algebra.build_2bga when a == b, but allows
    different left/right supports for more construction freedom.

    Parameters
    ----------
    mul : (N, N) int array  — Cayley table of the group (identity at index 0).
    a   : list of int       — left-support element indices (subset of G).
    b   : list of int       — right-support element indices (subset of G).

    Returns
    -------
    HX, HZ : int8 arrays of shape (N, 2N).  CSS guaranteed.

    References
    ----------
    Panteleev & Kalachev, arXiv:2111.03654; Lin & Pryadko, arXiv:2306.16400.
    """
    N = mul.shape[0]
    a, b = list(a), list(b)

    # Sum of left regular reps: La = Σ_{g∈a} L(g)   (N×N, mod 2)
    La = np.zeros((N, N), dtype=np.int8)
    for g in a:
        La = (La + L_rep(mul, g)) % 2

    # Sum of right regular reps: Rb = Σ_{g∈b} R(g)  (N×N, mod 2)
    Rb = np.zeros((N, N), dtype=np.int8)
    for g in b:
        Rb = (Rb + R_rep(mul, g)) % 2

    # HX = [La | Rb],  HZ = [Rb^T | La^T]   (both N × 2N)
    # CSS: La·Rb^T + Rb·La^T = 0 (left/right reps commute)
    HX = np.hstack([La, Rb]).astype(np.int8)
    HZ = np.hstack([Rb.T, La.T]).astype(np.int8)
    return HX, HZ


# ======================================================================
#  HP of two 2BGA parent codes
# ======================================================================
def balanced_product(mul1, a1, b1, mul2, a2, b2):
    """Hypergraph product of two 2BGA parent codes.

    Builds HP(build_2bga(mul1,a1,b1), build_2bga(mul2,a2,b2)).  The
    child inherits circulant structure from both parents.

    References
    ----------
    The general balanced product is Hastings-Haah-O'Donnell (arXiv:2009.03921).
    This function implements the simpler HP-of-2BGA composition.
    """
    HX1, HZ1 = build_2bga(mul1, a1, b1)
    HX2, HZ2 = build_2bga(mul2, a2, b2)
    return hypergraph_product(HX1, HX2)


# ======================================================================
#  Samplers (yield (spec, HX, HZ) for kit/search.screen)
# ======================================================================
def _rand_classical(rows, cols, weight, rng):
    """Random sparse binary matrix with ``weight`` ones per row."""
    H = np.zeros((rows, cols), dtype=np.int8)
    for i in range(rows):
        H[i, rng.choice(cols, size=min(weight, cols), replace=False)] = 1
    return H


def _build_group(order, rng):
    """Try to build a group of the given order. Returns (mul, N) or None."""
    from group_algebra import cyclic_product, dihedral, metacyclic

    if order <= 12 and order % 2 == 0 and rng.random() < 0.6:
        mul, _ = dihedral(order // 2)
        if mul.shape[0] == order:
            return mul
    for n in range(3, order + 1):
        if order % n != 0:
            continue
        k = order // n
        if k < 2:
            continue
        for r in range(2, n):
            if pow(r, k, n) == 1:
                mul, _ = metacyclic(n, k, r)
                if mul.shape[0] == order:
                    return mul
    mul, _ = cyclic_product(order)
    return mul if mul.shape[0] == order else None


def sample_hypergraph_product(num, *, n_range=(4, 12), m_range=(3, 8), row_w=3, seed=0):
    """Yield ``num`` random HP codes ``(spec, HX, HZ)``."""
    rng = np.random.default_rng(seed)
    yielded = 0
    for _ in range(num * 5):
        if yielded >= num:
            return
        m1 = int(rng.integers(max(2, m_range[0]), m_range[1] + 1))
        n1 = int(rng.integers(max(3, n_range[0]), n_range[1] + 1))
        H1 = _rand_classical(m1, n1, min(row_w, n1), rng)
        if rng.random() < 0.5:
            HX, HZ = hypergraph_product(H1, H1)
            spec = {"family": "hypergraph-product", "H1_shape": [m1, n1], "H2_shape": [m1, n1]}
        else:
            m2 = int(rng.integers(max(2, m_range[0]), m_range[1] + 1))
            n2 = int(rng.integers(max(3, n_range[0]), n_range[1] + 1))
            H2 = _rand_classical(m2, n2, min(row_w, n2), rng)
            HX, HZ = hypergraph_product(H1, H2)
            spec = {"family": "hypergraph-product", "H1_shape": [m1, n1], "H2_shape": [m2, n2]}
        if HX.shape[1] > 800:
            continue
        yield (spec, HX, HZ)
        yielded += 1


def sample_lifted_product(num, *, order_range=(6, 20), weight_a=3, weight_b=3, seed=0):
    """Yield ``num`` random LP codes ``(spec, HX, HZ)``."""
    rng = np.random.default_rng(seed)
    yielded = 0
    for _ in range(num * 5):
        if yielded >= num:
            return
        order = int(rng.integers(order_range[0], order_range[1] + 1))
        g = _build_group(order, rng)
        if g is None:
            continue
        N = g.shape[0]
        a = [int(x) for x in rng.choice(N, size=min(weight_a, N), replace=False)]
        b = [int(x) for x in rng.choice(N, size=min(weight_b, N), replace=False)]
        HX, HZ = lifted_product(g, a, b)
        if HX.shape[1] > 800:
            continue
        spec = {"family": "lifted-product", "group_order": N, "support_a": sorted(a), "support_b": sorted(b)}
        yield (spec, HX, HZ)
        yielded += 1


def sample_balanced_product(num, *, order_range=(4, 12), seed=0):
    """Yield ``num`` balanced-product codes ``(spec, HX, HZ)``."""
    rng = np.random.default_rng(seed)
    yielded = 0
    for _ in range(num * 5):
        if yielded >= num:
            return
        g1 = _build_group(int(rng.integers(*order_range)), rng)
        g2 = _build_group(int(rng.integers(*order_range)), rng)
        if g1 is None or g2 is None:
            continue
        N1, N2 = g1.shape[0], g2.shape[0]
        w1, w2 = min(3, N1 - 1), min(3, N2 - 1)
        a1 = [int(x) for x in rng.choice(N1, size=w1, replace=False)]
        b1 = [int(x) for x in rng.choice(N1, size=w1, replace=False)]
        a2 = [int(x) for x in rng.choice(N2, size=w2, replace=False)]
        b2 = [int(x) for x in rng.choice(N2, size=w2, replace=False)]
        HX, HZ = balanced_product(g1, a1, b1, g2, a2, b2)
        if HX.shape[1] > 800:
            continue
        spec = {
            "family": "balanced-product",
            "parent1": {"order": N1, "a": sorted(a1), "b": sorted(b1)},
            "parent2": {"order": N2, "a": sorted(a2), "b": sorted(b2)},
        }
        yield (spec, HX, HZ)
        yielded += 1


# ======================================================================
#  Self-test
# ======================================================================
if __name__ == "__main__":
    from css import compute_k, verify_css
    from surrogate import distance_rand

    print("=== product constructions self-test ===\n")

    # 1. Hypergraph product
    H1 = np.array([[1, 1, 0, 0], [0, 1, 1, 0], [0, 0, 1, 1]], dtype=np.int8)
    HX_hp, HZ_hp = hypergraph_product(H1, H1)
    n_hp = HX_hp.shape[1]
    k_hp = compute_k(HX_hp, HZ_hp)
    css_hp = verify_css(HX_hp, HZ_hp)
    d_hp = distance_rand(HX_hp, HZ_hp, trials=200)
    print(f"HP [4,1,2] self-prod: n={n_hp} k={k_hp} css={css_hp} d<={d_hp}")

    # 2. Lifted product on Z_6
    from group_algebra import cyclic_product

    mul6, _ = cyclic_product(6)
    HX_lp, HZ_lp = lifted_product(mul6, [0, 1, 2], [0, 1, 2])
    n_lp = HX_lp.shape[1]
    k_lp = compute_k(HX_lp, HZ_lp)
    css_lp = verify_css(HX_lp, HZ_lp)
    d_lp = distance_rand(HX_lp, HZ_lp, trials=200)
    print(f"LP Z_6 a=b=[0,1,2]: n={n_lp} k={k_lp} css={css_lp} d<={d_lp}")

    # 3. Balanced product
    from group_algebra import build_2bga

    mul4, _ = cyclic_product(4)
    mul6, _ = cyclic_product(6)
    HX_bp, HZ_bp = balanced_product(mul4, [0, 1, 2], [0, 1, 2], mul6, [0, 1, 2], [0, 1, 2])
    n_bp = HX_bp.shape[1]
    k_bp = compute_k(HX_bp, HZ_bp)
    css_bp = verify_css(HX_bp, HZ_bp)
    d_bp = distance_rand(HX_bp, HZ_bp, trials=200)
    print(f"BP Z_4 x Z_6 2BGA: n={n_bp} k={k_bp} css={css_bp} d<={d_bp}")

    # 4. Sampler smoke
    print("\n=== sampler smoke ===")
    for name, fn, n in [
        ("HP", sample_hypergraph_product, 10),
        ("LP", sample_lifted_product, 10),
        ("BP", sample_balanced_product, 5),
    ]:
        count = sum(1 for _ in fn(n, seed=42))
        print(f"  {name}: {count} codes")
