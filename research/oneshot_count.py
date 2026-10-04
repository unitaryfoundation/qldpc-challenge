"""Size and rank of the one-shot level map (arXiv:2610.02137) on real bases.

The paper's construction is a chain-complex operation on the seed code: its
local cones ``K^x, K^q, K^z`` (Def 104) hollowed-tensored with the m-vertex
repetition code (Def 111), glued into the level map ``Gamma`` of Eq. (249).
Its output cell spaces are

    X' = Y_0^x,   Q' = Y_1^x (+) Y_0^q,   Z' = Y_2^x (+) Y_1^q (+) Y_0^z
    Y_0^x = V(K^x) x V      Y_1^x = E(K^x) x V  (+)  V(G^x) x E
    Y_0^q = V(K^q) x V      Y_1^q = E(K^q) x V  (+)  {q,z'} x E

so the qubit count needs only five incidence sums of the seed -- P, T, A, S and
n -- and no matrices.  Those sums are what this counts, on every board entry.

Two things come out, and both are the reason the paper cannot advance this
board by itself:

  * Lemma 118 gives ``H_Q(Gamma) ~ H_Q(C)``, so ``k' = k`` exactly.  A map with
    k' = k and n' > n is Pareto-dominated by its own input on the (n, k, d, w)
    rule, whatever happens to d.
  * n' is not ``m n``.  The abstract's ``[[n m, k]]`` is per *tower level*, and
    one level inflates by far more than the sheet count: for the board's codes
    the factor runs from ~15 (n = 6) to ~920 (n = 90).

    uv run --frozen python research/oneshot_count.py
"""
import glob
import json
import os

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def incidences(HX, HZ):
    """(n, P, T, A, S) for the seed code's local cones.

    P = #{{(x,q)}} = sum_x |dx|      S = #{{(q,z)}} = sum_z |dz|
    T = #{{(x,q,z)}} = sum_q deg_X(q) deg_Z(q)
    A = #{{(x,z)}} = sum_x |{z : x ^ z}| over pairs at incidence distance 2
    """
    n = HX.shape[1]
    Xsup = [set(np.nonzero(r)[0].tolist()) for r in HX]
    Zsup = [set(np.nonzero(r)[0].tolist()) for r in HZ]
    P = sum(len(s) for s in Xsup)
    S = sum(len(s) for s in Zsup)
    deg_X = np.zeros(n, dtype=np.int64)
    for x in Xsup:
        for q in x:
            deg_X[q] += 1
    deg_Z = np.zeros(n, dtype=np.int64)
    for z in Zsup:
        for q in z:
            deg_Z[q] += 1
    T = int((deg_X * deg_Z).sum())
    A = sum(len(x & z) for x in Xsup for z in Zsup if x & z)
    return n, P, T, A, S


def qubit_count(n, P, T, A, S, m=3):
    """Qubit count for the m-sheet level map (App. A cell inventory, Eq. 249)."""
    E = m - 1
    Y1x = m * (P + T + A) + E * (P + A)     # E(K^x) x V  +  V(G^x) x E
    Y0q = m * (n + S)                      # V(K^q) x V
    return int(Y1x + Y0q)


def to_matrix(supports, n):
    M = np.zeros((len(supports), n), dtype=np.int8)
    for i, s in enumerate(supports):
        M[i, list(s)] = 1
    return M


def main(limit=200):
    rows = []
    for path in sorted(glob.glob(os.path.join(REPO, "codes", "*.json"))):
        doc = json.load(open(path))
        if doc.get("code_type", "CSS") != "CSS" or doc["n"] > limit:
            continue
        n = doc["n"]
        HX = to_matrix(doc["checks"]["X"], n)
        HZ = to_matrix(doc["checks"]["Z"], n)
        nn, P, T, A, S = incidences(HX, HZ)
        rows.append((os.path.basename(path), n, doc["k"],
                     qubit_count(nn, P, T, A, S, 3) / n,
                     qubit_count(nn, P, T, A, S, 2) / n))
    rows.sort(key=lambda r: -r[3])
    print(f"{'entry':>22s} {'n':>5s} {'k':>4s} {'n3/n':>9s} {'n2/n':>9s}")
    for r in rows:
        print(f"{r[0]:>22s} {r[1]:5d} {r[2]:4d} {r[3]:9.1f} {r[4]:9.1f}")
    print(f"\n{len(rows)} CSS entries with n <= {limit}")
    print("n3/n, n2/n: qubit-count inflation of one level at m = 3 and m = 2 sheets.")
    print("k' = k throughout (Lemma 118), so every one of these is dominated by "
          "its own input.")


if __name__ == "__main__":
    main()
