"""Single-block annihilator attack on two-block CSS entries (issue #2706).

Write a CSS entry's checks as ``H = [A | B]`` over two equal blocks. A vector
supported in one block alone lies in the kernel of those checks exactly when
that block annihilates it, so the candidates are the kernel of one block: a
subspace of a few dozen dimensions rather than the whole code. Information-set
decoding inside that subspace reaches operators that uniform sampling of the
whole code effectively never does, which is how two entries that had absorbed
eight million uniform trials without moving were refuted in twenty seconds on
one core.

This is a correction mechanism, not a search. It re-prices claims the board
already holds, and it only ever reports a weight it can hand you the operator
for: every finding carries a support that is checked in-tree to be in the
kernel of the opposite checks and outside the row space of its own side. A
clean result is a statement about the budget that was spent, never a proof
that nothing lighter exists.

    from annihilator import attack
    report = attack(doc, trials=40_000, seed=11)
"""

import os
import sys
import time

import numpy as np

for _p in (os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "verify"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import gf2  # noqa: E402

SIDES = ("X", "Z")
BLOCKS = ("left", "right")


def matrix(support_list, n):
    """Dense GF(2) matrix from a list of row supports."""
    H = np.zeros((len(support_list), n), dtype=np.uint8)
    for i, row in enumerate(support_list):
        H[i, list(row)] = 1
    return H


def block_columns(n, block):
    """Column indices of one of the two equal blocks."""
    half = n // 2
    return np.arange(half) if block == "left" else np.arange(half, n)


def subspace(H_opp, cols):
    """Basis of the vectors supported on `cols` that H_opp annihilates."""
    return gf2.kernel_basis(np.asarray(H_opp, dtype=np.uint8)[:, cols])


def _light_vectors(K, trials, rng):
    """Yield low-weight members of the subspace by information-set decoding.

    Yields (information set index, vector). One pass is a random column
    order, a reduction to systematic form, and then every row and every
    pair of rows as a candidate. Pairs cost one
    vectorized xor over the basis and reach weights no single row does, which
    is where most of the hits below actually come from.
    """
    dim, m = K.shape
    if dim == 0:
        return
    for passes in range(1, max(1, trials // max(1, dim)) + 1):
        perm = rng.permutation(m)
        R, _ = gf2.rref(K[:, perm])
        inv = np.empty(m, dtype=int)
        inv[perm] = np.arange(m)
        R = R[:, inv]
        R = R[R.any(axis=1)]
        if not len(R):
            return
        weights = R.sum(axis=1)
        order = np.argsort(weights)
        for i in order[: min(len(order), 8)]:
            yield passes, R[i]
        # Pairs from the lightest few rows: the cheapest depth that reaches
        # a cancellation a single row cannot.
        head = order[: min(len(order), 12)]
        for a_i in range(len(head)):
            for b_i in range(a_i + 1, len(head)):
                yield passes, R[head[a_i]] ^ R[head[b_i]]


def attack_side(HX, HZ, side, block, *, trials=40_000, seed=0):
    """Search one block's annihilator for a light logical of one type.

    ``side`` names the logical type: an X-type operator lies in the kernel of
    the Z checks and outside the row space of the X checks, and a Z-type
    operator the other way round.
    """
    n = HX.shape[1]
    H_opp, H_same = (HZ, HX) if side == "X" else (HX, HZ)
    cols = block_columns(n, block)
    K = subspace(H_opp, cols)
    out = {"side": side, "block": block, "subspace_dim": int(len(K))}
    if not len(K):
        return out
    rank_same = gf2.rank(H_same)
    rng = np.random.default_rng(seed)
    best, best_v, best_at = None, None, None
    for at, short in _light_vectors(np.asarray(K, dtype=np.uint8), trials, rng):
        w = int(short.sum())
        if w == 0 or (best is not None and w >= best):
            continue
        v = np.zeros(n, dtype=np.uint8)
        v[cols] = short
        # A vector in the row space of its own side is a stabilizer, not a
        # logical, and says nothing about the distance.
        if gf2.rank(np.vstack([H_same, v])) == rank_same:
            continue
        best, best_v, best_at = w, v, at
    if best is not None:
        out["weight"] = best
        out["support"] = [int(j) for j in np.nonzero(best_v)[0]]
        # Which information set first produced it, which is what the
        # board's witness_provenance records beside the survival budget.
        out["found_at_samples"] = int(best_at)
    return out


def verify_finding(HX, HZ, side, support):
    """Confirm a reported operator really is a logical of the claimed type."""
    n = HX.shape[1]
    v = np.zeros(n, dtype=np.uint8)
    v[list(support)] = 1
    H_opp, H_same = (HZ, HX) if side == "X" else (HX, HZ)
    in_kernel = int((H_opp @ v % 2).sum()) == 0
    nontrivial = gf2.rank(np.vstack([H_same, v])) > gf2.rank(H_same)
    return bool(in_kernel and nontrivial), int(v.sum())


def attack(doc, *, trials=40_000, seed=0):
    """Run the attack on one entry and report every side and block.

    The verdict is ``refuted`` when an operator lighter than the claimed
    distance turns up, ``tightened`` when a side's own claimed weight falls
    but the distance does not, and ``clean`` when neither happens at this
    budget.
    """
    n = doc["n"]
    checks = doc.get("checks") or {}
    if "X" not in checks or "Z" not in checks:
        # A stabilizer entry carries one symplectic matrix rather than two
        # CSS blocks, so there is no A | B to split. Out of scope rather
        # than a failure, and recorded as such so the next sweep does not
        # retry it.
        return {
            "n": n,
            "verdict": "skipped",
            "detail": f"not CSS: checks are {sorted(checks) or 'absent'}, so there is no two-block split to attack",
        }
    if n % 2:
        return {"n": n, "verdict": "skipped", "detail": "odd blocklength has no two equal blocks"}
    HX = matrix(doc["checks"]["X"], n)
    HZ = matrix(doc["checks"]["Z"], n)
    d = int(doc["distance"]["d"])
    claimed = {s: int((doc["distance"].get(s) or {}).get("value") or d) for s in SIDES}
    t0 = time.time()
    findings, dims = [], {}
    for side in SIDES:
        for block in BLOCKS:
            got = attack_side(HX, HZ, side, block, trials=trials, seed=seed)
            dims[f"{side}-{block}"] = got["subspace_dim"]
            if "weight" not in got:
                continue
            ok, w = verify_finding(HX, HZ, side, got["support"])
            if not ok:
                raise ValueError(
                    f"{side}/{block}: the search returned a vector that is "
                    f"not a logical of that type; this is a bug in the "
                    f"attack, not a result"
                )
            got["claimed_side"] = claimed[side]
            if w < claimed[side]:
                findings.append(got)
    best = min((f["weight"] for f in findings), default=None)
    verdict = "clean"
    if best is not None:
        verdict = "refuted" if best < d else "tightened"
    return {
        "n": n,
        "claimed_d": d,
        "claimed_sides": claimed,
        "subspace_dims": dims,
        "trials": trials,
        "seed": seed,
        "secs": round(time.time() - t0, 1),
        "verdict": verdict,
        "lightest": best,
        "findings": findings,
    }
