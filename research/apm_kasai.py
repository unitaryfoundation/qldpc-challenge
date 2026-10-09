"""Kasai affine-permutation CSS codes at board-admissible blocklengths.

Builds and searches the family behind the submitted [[696,352,<=10]]: Kasai's
affine-permutation-matrix (APM) CSS construction (arXiv:2504.17790, Def. 1) with
J = 3 active block rows and L/2 = 6, so n = 2*(L/2)*P = 12P and the check
weight is 12.

    H_X^{(L)}[j,l] = f_{-j+l}      H_Z^{(L)}[j,l] = g^{-1}_{j-l}
    H_X^{(R)}[j,l] = g_{-j+l}      H_Z^{(R)}[j,l] = f^{-1}_{j-l}

with f_i, g_i the affine maps x -> a x + b mod P. Indices are mod L/2.

TWO THINGS THIS FILE TEACHES, both of which cost search time to learn.

1. Orthogonality comes from the block SUM cancelling, not from pairwise
   commutation. Kasai's Requirement 1 (f_{l-j} commutes with g_{k-l} for all
   l, j, k) is SUFFICIENT but not NECESSARY: in the paper's own P = 96
   instance only 1 of the 36 (f_i, g_j) pairs actually commutes, while
   sum_i F_{i-j}G_{k-i} + sum_i G_{i-j}F_{k-i} = 0 holds for all j, k.
   Enforcing Requirement 1 rejects the useful region; sampling (f, g) freely
   satisfies the true identity with probability ~0 (measured 0/300 at P=57).

2. Sampling from an ABELIAN centralizer C(A) makes the identity hold
   identically -- both product sums are symmetric and coincide, so they cancel
   over GF(2) -- and then the search budget goes entirely into distance.
   This is what the submitted instance does, with reference APM A = 1x+2 mod 58
   (orbits (29,29)) and all 12 blocks distinct elements of C(A).

The one constraint that does bind is CONNECTIVITY. The verifier rejects a
disconnected entry outright ("tanner_connected", "stabilizer_group_connected"),
and a disconnected H reads as a much stronger [[n,k]] than it is: its k is the
SUM over components. An earlier P = 57 draw screened as [[684,350]] was really
a disjoint 456-qubit and 228-qubit code. Every candidate here is checked with
``connected()`` before its parameters are believed; the submitted P = 58
instance verifies as a single component.

Usage
-----
    python research/apm_kasai.py --build 58 --A 1 2          # the submitted code
    python research/apm_kasai.py --reproduce 2604.16209     # the paper's P=96 row
    python research/apm_kasai.py --search 58 --A 1 2 --draws 3000

``--reproduce 2604.16209`` rebuilds the [[1152,580]] instance from Table A1 of
arXiv:2604.16209 (Zhao et al.), which is the check that this transcription of
the construction is faithful: n=1152, k=580, H_X H_Z^T = 0.
"""
import argparse
import json
import random
import sys

import numpy as np

sys.path.insert(0, "research/kit")
sys.path.insert(0, "verify")

HALF = 6   # L/2: number of f-blocks and of g-blocks
J = 3      # active block rows


# --------------------------------------------------------------------------
# affine arithmetic on Z_P, as pairs (a, b) meaning x -> a x + b mod P
# --------------------------------------------------------------------------

def compose(f, g, P):
    """f . g (apply g first)."""
    a1, b1 = f
    a2, b2 = g
    return ((a1 * a2) % P, (a1 * b2 + b1) % P)


def identity(P):
    return (1, 0)


def orbits(A, P):
    """Cycle-length decomposition of x -> A x mod P, longest first."""
    seen, out = [False] * P, []
    for x in range(P):
        if seen[x]:
            continue
        y, L = x, 0
        while not seen[y]:
            seen[y] = True
            y = (A[0] * y + A[1]) % P
            L += 1
        out.append(L)
    return sorted(out, reverse=True)


def centralizer(A, P):
    """Every affine T with T A = A T."""
    a, b = A
    out = []
    for al in range(1, P):
        if np.gcd(al, P) != 1:
            continue
        for be in range(P):
            if ((al * b + be) - (a * be + b)) % P == 0:
                out.append((al, be))
    return out


# --------------------------------------------------------------------------
# matrices
# --------------------------------------------------------------------------

def apm(P, f):
    """The P x P permutation matrix of the affine map f.

    Note f(j) = i <=> F[i,j] = 1, so the matrix of f^{-1} is exactly F^T. A
    Z-side block is therefore just ``.T``; writing apm(inv(f)).T inverts twice
    and silently breaks CSS commutation.
    """
    M = np.zeros((P, P), dtype=np.int64)
    for x in range(P):
        M[(f[0] * x + f[1]) % P, x] = 1
    return M


def build(P, F, G):
    """H_X, H_Z of shape (J*P, 2*HALF*P). n = 2*HALF*P = 12P."""
    n = 2 * HALF * P
    HX = np.zeros((J * P, n), dtype=np.int64)
    HZ = np.zeros((J * P, n), dtype=np.int64)
    for j in range(J):
        for l in range(HALF):
            HX[j * P:(j + 1) * P, l * P:(l + 1) * P] = apm(P, F[(l - j) % HALF])
            HX[j * P:(j + 1) * P, (HALF + l) * P:(HALF + l + 1) * P] = apm(P, G[(l - j) % HALF])
            HZ[j * P:(j + 1) * P, l * P:(l + 1) * P] = apm(P, G[(j - l) % HALF]).T
            HZ[j * P:(j + 1) * P, (HALF + l) * P:(HALF + l + 1) * P] = apm(P, F[(j - l) % HALF]).T
    return HX % 2, HZ % 2


def orthogonal(P, F, G):
    """Kasai's block-sum identity, checked directly rather than enforced."""
    Fm = [apm(P, f) for f in F]
    Gm = [apm(P, g) for g in G]
    for j in range(J):
        for k in range(J):
            S = np.zeros((P, P), dtype=np.int64)
            for i in range(HALF):
                S = (S + Fm[(i - j) % HALF] @ Gm[(k - i) % HALF]
                     + Gm[(i - j) % HALF] @ Fm[(k - i) % HALF]) % 2
            if S.any():
                return False
    return True


def connected(HX, HZ):
    """True iff the combined qubit/check Tanner graph is one component.

    Vertices 0..nx-1 are X-checks, nx..nx+nz-1 are Z-checks, nx+nz.. are
    qubits. Verified against verify/qldpc_verify._tanner_component_count.
    """
    n = HX.shape[1]
    nx, nz = HX.shape[0], HZ.shape[0]
    off_q = nx + nz
    parent = list(range(off_q + n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for H, off in ((HX, 0), (HZ, nx)):
        for r in range(H.shape[0]):
            for q in np.nonzero(H[r])[0]:
                union(off + r, off_q + int(q))
    return len({find(off_q + q) for q in range(n)}) == 1


# --------------------------------------------------------------------------
# the submitted instance
# --------------------------------------------------------------------------

# Table A1 of arXiv:2604.16209, the P = 96 row. Its instances (n = 1152, 2304,
# 4608) all exceed the verifier's blocklength cap (BASE_MAX_N = 700 at check
# weight 12), so it is used here only to validate the transcription.
PAPER_P96_F = [(5, 41), (85, 77), (73, 66), (1, 0), (1, 72), (37, 9)]
PAPER_P96_G = [(61, 15), (1, 24), (89, 62), (25, 22), (85, 93), (25, 78)]

# The submitted [[696,352,<=10]]: P = 58, reference A = 1x+2 (orbits (29,29)).
# All 12 blocks are distinct elements of C(A) = {x -> x + 3b mod 58}.
SUBMITTED_P = 58
SUBMITTED_A = (1, 2)
SUBMITTED_BLOCKS = [
    (1, 37), (1, 56), (1, 33), (1, 20), (1, 42), (1, 23),
    (1, 25), (1, 43), (1, 17), (1, 10), (1, 36), (1, 45),
]


def submitted_matrices():
    b = SUBMITTED_BLOCKS
    return build(SUBMITTED_P, b[:HALF], b[HALF:])


def reproduce_paper():
    HX, HZ = build(96, PAPER_P96_F, PAPER_P96_G)
    from css import compute_k, verify_css
    print(f"paper P=96: n={HX.shape[1]} k={compute_k(HX, HZ)} "
          f"commutes={verify_css(HX, HZ)}   (expected n=1152 k=580 True)")


def report(tag, P, HX, HZ):
    from css import compute_k, verify_css
    k = compute_k(HX, HZ)
    print(f"{tag}: n={HX.shape[1]} k={k} commutes={verify_css(HX, HZ)} "
          f"connected={connected(HX, HZ)} "
          f"max_check_weight={int(HX.sum(axis=1).max())}")
    return k


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reproduce", action="store_true",
                    help="rebuild the paper's P=96 instance as a transcription check")
    ap.add_argument("--build", type=int, metavar="P",
                    help="build and report the submitted instance at this P")
    ap.add_argument("--search", type=int, metavar="P",
                    help="search for connected instances at this P")
    ap.add_argument("--A", type=int, nargs=2, help="reference APM a b for --search")
    ap.add_argument("--draws", type=int, default=3000)
    ap.add_argument("--trials", type=int, default=400)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    if args.reproduce:
        reproduce_paper()
        return
    if args.build:
        HX, HZ = submitted_matrices()
        report("submitted", SUBMITTED_P, HX, HZ)
        return
    if args.search:
        if not args.A:
            ap.error("--search needs --A a b")
        P, A = args.search, tuple(args.A)
        C = [t for t in centralizer(A, P) if t != identity(P)]
        print(f"P={P} n={2*HALF*P} A={A} orbits={orbits(A, P)} |C(A)|={len(C)}")
        rng = random.Random(args.seed)
        from css import verify_css
        from surrogate import distance_rand
        kept, tried = [], 0
        while len(kept) < 20 and tried < args.draws:
            tried += 1
            b = tuple(rng.sample(C, 2 * HALF))
            HX, HZ = build(P, list(b[:HALF]), list(b[HALF:]))
            if not verify_css(HX, HZ) or not connected(HX, HZ):
                continue
            kept.append((compute_k_safe(HX, HZ),
                         distance_rand(HX, HZ, trials=args.trials,
                                       seed=args.seed), [list(t) for t in b]))
        kept.sort(key=lambda r: (-r[0], -r[1]))
        for k, d, b in kept:
            print(f"  k={k} d<={d:.0f}")
        print(f"# connected {len(kept)}/{tried} draws", file=sys.stderr)
        if kept:
            print(json.dumps(kept[0][2]))
        return
    ap.error("pass one of --reproduce / --build / --search")


def compute_k_safe(HX, HZ):
    from css import compute_k
    return compute_k(HX, HZ)


if __name__ == "__main__":
    main()