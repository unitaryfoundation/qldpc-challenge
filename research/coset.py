"""Coset-based two-block codes (Aydin-Tamo-Barg, arXiv:2606.17268).

A strict generalization of the regular 2BGA (``group_algebra.py``): qubits are
indexed by the COSET space G/H for a subgroup H <= G (record codes use a
NON-normal H), rather than by G itself. This escapes the abelian-BB design space
and reaches the highest verified efficiencies, at check weight 8 (filtered by
the w slider on the board, not a track).

Construction:
  m := [G:H] = number of cosets;  n = 2m;  each block is m x m.
  Left action  (any g in G):           L(g): xH |-> (g x)H
  Right action (only g in N_G(H)):      R(g): xH |-> (x g)H   (normalizer!)
  L(a) = sum_{g in supp a} L(g),  R(b) = sum_{g in supp b} R(g)  (b subset N_G(H))
  H_X = [ L(a) | R(b) ],  H_Z = [ R(b)^T | L(a)^T ]
CSS is AUTOMATIC: L(g1) and R(g2) commute for g1 in G, g2 in N_G(H).

H = {e}  =>  cosets = G, N_G(H) = G  =>  reduces to the regular 2BGA.

Reuses the group builders from ``group_algebra`` (perm_group, cyclic_product,
sym, alt, dihedral, metacyclic).
"""
import numpy as np

from group_algebra import perm_group, cyclic_product, sym, alt, dihedral  # noqa: F401


def inverse(mul, g):
    """Index of g^{-1} (the h with g*h = e)."""
    row = mul[g]
    return int(np.where(row == 0)[0][0])


def subgroup_closure(mul, gens):
    """Smallest subgroup (set of element indices) containing ``gens`` and the
    identity."""
    H = {0}
    frontier = list(set(gens) | {0})
    H.update(frontier)
    while frontier:
        nxt = []
        for a in list(H):
            for b in frontier:
                for prod in (mul[a, b], mul[b, a]):
                    if prod not in H:
                        H.add(int(prod)); nxt.append(int(prod))
        frontier = nxt
    return sorted(H)


def left_cosets(mul, H):
    """Partition G into left cosets xH. Returns ``(reps, coset_of)`` where
    ``coset_of[x]`` is the coset index (0..m-1) of element x and ``reps[c]`` is
    a representative of coset c."""
    N = mul.shape[0]
    coset_of = [-1] * N
    reps = []
    for x in range(N):
        if coset_of[x] != -1:
            continue
        c = len(reps); reps.append(x)
        for h in H:
            coset_of[int(mul[x, h])] = c
    return reps, coset_of


def normalizer(mul, H):
    """N_G(H) = { g : g H g^{-1} = H } as a sorted list of element indices."""
    N = mul.shape[0]
    Hset = set(H)
    out = []
    for g in range(N):
        gi = inverse(mul, g)
        if all(int(mul[mul[g, h], gi]) in Hset for h in H):
            out.append(g)
    return out


def index_in(mul, H):
    """[G:H]."""
    return mul.shape[0] // len(H)


def _perm_L(mul, reps, coset_of, g):
    """Coset permutation for the left action of g: c -> coset of (g * rep_c)."""
    return [coset_of[int(mul[g, reps[c]])] for c in range(len(reps))]


def _perm_R(mul, reps, coset_of, g):
    """Coset permutation for the right action of g (g must be in N_G(H))."""
    return [coset_of[int(mul[reps[c], g])] for c in range(len(reps))]


def _block(m, perms):
    """Sum (mod 2) of permutation matrices given by coset-permutations."""
    M = np.zeros((m, m), dtype=np.int8)
    for p in perms:
        for c in range(m):
            M[p[c], c] ^= 1
    return M


def build_coset(mul, H, a, b, check_normalizer=True):
    """Coset two-block code. ``H`` a subgroup (element-index list), ``a`` a
    subset of G, ``b`` a subset of N_G(H). Returns ``(HX, HZ)`` int8 of shape
    (m, 2m), CSS guaranteed."""
    reps, coset_of = left_cosets(mul, H)
    m = len(reps)
    if check_normalizer:
        Nset = set(normalizer(mul, H))
        bad = [g for g in b if g not in Nset]
        if bad:
            raise ValueError(f"b has elements outside N_G(H): {bad}")
    La = _block(m, [_perm_L(mul, reps, coset_of, g) for g in a])
    Rb = _block(m, [_perm_R(mul, reps, coset_of, g) for g in b])
    HX = np.concatenate([La, Rb], axis=1).astype(np.int8)
    HZ = np.concatenate([Rb.T, La.T], axis=1).astype(np.int8)
    return HX, HZ


if __name__ == "__main__":
    from css import verify_css, compute_k
    from surrogate import distance_rand
    from group_algebra import build_2bga

    # (1) H = {e}: coset construction must reduce to the regular 2BGA.
    mul, tup = cyclic_product(6, 6)
    idx = {t: i for i, t in enumerate(tup)}
    a = [idx[(3, 0)], idx[(0, 1)], idx[(0, 2)]]
    b = [idx[(0, 3)], idx[(1, 0)], idx[(2, 0)]]
    HXc, HZc = build_coset(mul, [0], a, b)
    HXr, HZr = build_2bga(mul, a, b)
    print("(1) H={e} reduces to 2BGA:",
          np.array_equal(HXc, HXr) and np.array_equal(HZc, HZr),
          f" n={HXc.shape[1]} k={compute_k(HXc, HZc)} d<={distance_rand(HXc, HZc, trials=400)}")

    # (2) A genuine NON-NORMAL H in a non-abelian group: S4, H = <(0 1)>.
    #     m = [G:H] = 12, n = 24. CSS is automatic (right action by N_G(H)).
    mul4, el4 = sym(4)
    t = el4.index((1, 0, 2, 3))
    H = subgroup_closure(mul4, [t])
    Nrm = normalizer(mul4, H)
    print(f"(2) S4: |G|={len(el4)} |H|={len(H)} [G:H]={index_in(mul4, H)} "
          f"|N_G(H)|={len(Nrm)} (H normal? {len(Nrm) == len(el4)})")
    a = [0, el4.index((1, 2, 0, 3)), el4.index((0, 1, 3, 2))]   # weight-3 in G
    b = list(Nrm[:3])                                            # weight-3 in N_G(H)
    HX, HZ = build_coset(mul4, H, a, b)
    print(f"    construction runs; css={verify_css(HX, HZ)} (automatic), "
          f"n={HX.shape[1]} k={compute_k(HX, HZ)}")
    print("    (arbitrary low-weight a,b usually give k=0; finding (a,b) for "
          "good (k,d) is the\n     search problem -- a planned Phase 2 follow-on.)")
