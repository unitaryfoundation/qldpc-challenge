"""Heuristic distance verification (random-information-set search).

Server-side, reproducible UPPER-BOUND search for a low-weight logical operator. It
sits between the witness upper bound (`d<=`, cheap CI) and exact certification
(`d=`, verify/certify.py), filling the gap for dense / high-rate codes that exact
IP cannot reach. Two outcomes:

  refuted      a logical lighter than the claimed distance was found -> the claim
               is over-stated; the true distance is <= the found weight.
  corroborated a large fixed-budget search found nothing lighter -> confidence
               beyond a single witness (NOT a proof; exact remains the only d=).

This is purely an upper-bound search: every method here only exhibits a logical of
some weight, i.e. tightens d <= w. It never proves a lower bound. The run is
reproducible (fixed seed + trial budget) and computed server-side, never trusted
from the submission.

Engine: random information set (QDistRnd-style). Canonical path is pure Python on
verify/gf2.py (no build). If the gf2_fast C++ extension is importable it is used
for a faster, larger overall weight search; witnesses are always extracted by the
Python path (the C++ returns weights only).

General stabilizer codes (code_type "stabilizer"): there are no
sides. The same RREF engine runs once on K = ker(B | A), the normalizer of
S = (A | B) written as Pauli vectors (x | z), scoring every candidate by its
Pauli weight |supp x union supp z| (a Y counts once) and testing nontriviality
by anticommutation with a logical basis of N(S) modulo S. The accelerator has no
Pauli-weight kernel, so the fast pass runs on the symplectic doubling
H'_X = (A | B), H'_Z = (B | A) (arXiv:2609.30069, eq. 12), a CSS code on 2n
qubits whose X-logicals are exactly the Pauli logicals of the original (a
Z-logical maps to one by swapping halves). Its Hamming weight over 2n bits is an
upper bound on the Pauli weight, so every proposal is re-scored by Pauli weight
in Python before it counts; d'_X = d'_Z by the half-swap symmetry, so one side is
enough. The verdict for a stabilizer code is reported under the single side "P".

Usage: python verify/heuristic_distance.py codes/foo.json [--trials N] [--seed S]
       exit code 2 on a refuted claim (so it can gate if desired).
"""
import argparse
import json
import sys
import time

import numpy as np

import gf2

try:
    import gf2_fast as _fast            # optional C++ accelerator (weights only)
except ImportError:
    _fast = None


def _matrix(support_list, n):
    H = np.zeros((len(support_list), n), dtype=np.int8)
    for r, sup in enumerate(support_list):
        for q in sup:
            H[r, q] ^= 1
    return H


def _is_stabilizer(doc):
    return doc.get("code_type") == "stabilizer"


def stabilizer_matrices(doc):
    """Return (A, B), int8, of a stabilizer submission, S = (A | B)."""
    n = doc["n"]
    gens = doc["checks"]["S"]
    return (_matrix([g["X"] for g in gens], n),
            _matrix([g["Z"] for g in gens], n))


def doubled_matrices(A, B):
    """Return the symplectic doubling of S = (A | B).

    H'_X = (A | B), H'_Z = (B | A), a CSS code on 2n qubits. Isotropy of S is
    exactly its CSS commutation.
    """
    return (np.concatenate([A, B], axis=1).astype(np.int8),
            np.concatenate([B, A], axis=1).astype(np.int8))


def pauli_weight_rows(rows, n):
    """Pauli weight of each (x | z) row of a 2n-column array."""
    return (rows[:, :n] | rows[:, n:]).sum(1)


def _pauli_from_doubled(v, side, n):
    """Map a logical of the doubled CSS code back to a Pauli (x | z).

    An X-logical lies in ker(B | A) = N(S) and is already a Pauli vector; a
    Z-logical lies in ker(A | B) and outside row(B | A), so swapping its
    halves puts it in N(S) outside row(S) with the same Pauli weight.
    """
    v = np.asarray(v, dtype=np.int8)
    return v if side == "X" else np.concatenate([v[n:], v[:n]])


def _rref_perm(K, perm):
    """RREF of K under a random column permutation, mapped back to original
    columns. Reduced rows are low-weight combinations of K's rows (candidate
    low-weight logicals); the weight is permutation-invariant."""
    R, _ = gf2.rref(K[:, perm])
    out = np.zeros_like(R)
    out[:, perm] = R
    return out


def ris_min_logical(HX, HZ, trials, seed, pair_depth=8, max_seconds=None):
    """RIS upper-bound search for the lightest nontrivial X-type logical: a vector
    in ker(H_Z) that anticommutes with some Z-logical. Returns (weight, witness),
    or (None, None) if the code has no logicals of this type. Stops after `trials`
    permutations or `max_seconds` wall-clock, whichever comes first (the time cap
    keeps the CI gate bounded regardless of n)."""
    n = HX.shape[1]
    K = gf2.kernel_basis(HZ)
    LZ = gf2.logical_basis(HX, HZ)
    if K.shape[0] == 0 or LZ.shape[0] == 0:
        return None, None
    rng = np.random.default_rng(seed)
    best, wit = n + 1, None
    deadline = (time.monotonic() + max_seconds) if max_seconds else None

    def consider(rows):
        nonlocal best, wit
        w = rows.sum(1)
        nontrivial = ((rows @ LZ.T) % 2).any(1)
        for i in np.where(nontrivial & (w > 0) & (w < best))[0]:
            best, wit = int(w[i]), rows[i].copy()

    for t in range(trials):
        red = _rref_perm(K, rng.permutation(n))
        consider(red)
        if pair_depth > 1 and red.shape[0] >= 2:        # short combinations
            w = red.sum(1)
            light = np.argsort(w)[:min(pair_depth, red.shape[0])]
            sub = red[light]
            for a in range(len(light) - 1):
                consider(sub[a] ^ sub[a + 1:])
        if deadline and (t & 63) == 0 and time.monotonic() > deadline:
            break
    return best, wit


def ris_min_pauli_logical(A, B, trials, seed, pair_depth=8, max_seconds=None):
    """Search for the lightest nontrivial logical Pauli operator, by Pauli weight.

    RIS upper-bound search on the stabilizer code S = (A | B). Returns
    (weight, witness) with the witness a 2n-vector (x | z), or (None, None)
    when the code has no logicals. Same engine and budget shape as
    ris_min_logical: K = ker(B | A) is the normalizer written as Pauli
    vectors, L a logical basis of N(S) modulo S, and a candidate is nontrivial
    iff it anticommutes with some row of L, i.e. (x | z) . (L_z | L_x) = 1.
    """
    n = A.shape[1]
    S, SL = doubled_matrices(A, B)              # S = (A | B), S Lambda = (B | A)
    K = gf2.kernel_basis(SL)
    L = gf2.logical_basis(SL, S)                # ker(S Lambda) reduced mod row(S)
    if K.shape[0] == 0 or L.shape[0] == 0:
        return None, None
    LS = np.concatenate([L[:, n:], L[:, :n]], axis=1)   # L Lambda, so rows @ LS.T is the symplectic product
    rng = np.random.default_rng(seed)
    best, wit = n + 1, None
    deadline = (time.monotonic() + max_seconds) if max_seconds else None

    def consider(rows):
        nonlocal best, wit
        w = pauli_weight_rows(rows, n)
        nontrivial = ((rows @ LS.T) % 2).any(1)
        for i in np.where(nontrivial & (w > 0) & (w < best))[0]:
            best, wit = int(w[i]), rows[i].copy()

    for t in range(trials):
        red = _rref_perm(K, rng.permutation(2 * n))
        consider(red)
        if pair_depth > 1 and red.shape[0] >= 2:        # short combinations
            w = pauli_weight_rows(red, n)
            light = np.argsort(w)[:min(pair_depth, red.shape[0])]
            sub = red[light]
            for a in range(len(light) - 1):
                consider(sub[a] ^ sub[a + 1:])
        if deadline and (t & 63) == 0 and time.monotonic() > deadline:
            break
    return best, wit


def _valid_logical(v, H_ker, H_row):
    """Report whether v is a nontrivial logical operator.

    True when v lies in ker(H_ker) and outside rowspace(H_row). Used to check
    anything the C++ accelerator hands back before it is recorded, so an
    accelerator bug cannot put an unbacked witness into a verdict.
    """
    if v.sum() == 0 or ((H_ker @ v) % 2).any():
        return False
    return gf2.rank(np.vstack([H_row, v[None, :]])) > gf2.rank(H_row)


def valid_pauli_logical(v, A, B):
    """Report whether the Pauli vector v = (x | z) is a nontrivial logical of S.

    In ker(B | A) and outside row(A | B). The Pauli-weight form of
    _valid_logical, applied to every accelerator proposal for a stabilizer
    code before it is trusted.
    """
    S, SL = doubled_matrices(A, B)
    return _valid_logical(np.asarray(v, dtype=np.int8), SL, S)


def pauli_witness(v, n):
    """Return the {"X": [...], "Z": [...]} form of a 2n Pauli vector (x | z)."""
    v = np.asarray(v)
    return {"X": sorted(int(j) for j in np.nonzero(v[:n])[0]),
            "Z": sorted(int(j) for j in np.nonzero(v[n:])[0])}


def _estimate_stabilizer(doc, trials, seed, fast_trials, max_seconds):
    """Run estimate() for a stabilizer code: one Pauli-weight side, P."""
    n = doc["n"]
    A, B = stabilizer_matrices(doc)
    claimed = int(doc["distance"]["d"])
    wP, witP = ris_min_pauli_logical(A, B, trials, seed, max_seconds=max_seconds)
    sides = {}
    if wP is not None:
        sides["P"] = {"value": doc["distance"].get("P", {}).get("value"),
                      "lightest_found": wP, "witness": pauli_witness(witP, n)}
    d_heur = wP

    method = "ris-pauli"
    if _fast is not None and 0 < fast_trials <= trials:
        print(f"warning: gf2_fast is available but skipped "
              f"(fast_trials={fast_trials} <= trials={trials}); raise "
              f"--fast-trials or lower --trials to use the accelerator "
              f"(fast_trials=0 disables it deliberately)", file=sys.stderr)
    if _fast is not None and fast_trials > trials:
        # The accelerator searches the doubled CSS code by Hamming weight over
        # 2n bits, an upper bound on the Pauli weight (a Y is two bits, one
        # qubit). Its proposal is mapped back to a Pauli, validated by the
        # pinned python stack, and re-scored by Pauli weight; only then may
        # it tighten the verdict.
        HX2, HZ2 = doubled_matrices(A, B)
        d_fast, side, sup = _fast.distance_rand_witness(HX2, HZ2, fast_trials,
                                                        seed, 8, 8)
        if d_fast is not None and side in ("X", "Z"):
            v = np.zeros(2 * n, dtype=np.int8)
            v[list(sup)] = 1
            v = _pauli_from_doubled(v, side, n)
            if valid_pauli_logical(v, A, B):
                wp = int(pauli_weight_rows(v[None, :], n)[0])
                if d_heur is None or wp < d_heur:
                    d_heur = wp
                    sides.setdefault("P", {})
                    sides["P"].update(lightest_found=wp,
                                      witness=pauli_witness(v, n))
        method = "ris-pauli+gf2_fast(doubled)"
        trials = max(trials, fast_trials)

    if d_heur is None:
        verdict = "inconclusive"
    elif d_heur < claimed:
        verdict = "refuted"
    elif d_heur == claimed:
        verdict = "corroborated"
    else:
        verdict = "inconclusive"
    return {"name": doc.get("name", ""), "claimed_d": claimed,
            "d_heuristic": d_heur, "verdict": verdict,
            "sides": sides, "trials": trials, "seed": seed, "method": method}


def estimate(doc, trials=20000, seed=0, fast_trials=400000, max_seconds=None):
    """Heuristic distance verdict for a submission `doc`.

    ``trials`` is the pure-Python RIS budget per side; ``fast_trials`` is the
    gf2_fast accelerator's overall budget, used only when it exceeds ``trials``
    (the fast path reports weights, not witnesses, so it must out-search the
    Python pass to add anything). Pass ``fast_trials=0`` to disable the
    accelerator explicitly (refute_check does: the CI gate is pure Python with
    a fixed seed, so it stays deterministic). Any other skipped-accelerator
    combination warns on stderr -- see issue #290.

    A stabilizer code (code_type "stabilizer") takes _estimate_stabilizer:
    one Pauli-weight side P, the whole budget on it."""
    if _is_stabilizer(doc):
        return _estimate_stabilizer(doc, trials, seed, fast_trials, max_seconds)
    n = doc["n"]
    HX = _matrix(doc["checks"]["X"], n)
    HZ = _matrix(doc["checks"]["Z"], n)
    claimed = int(doc["distance"]["d"])

    half = (max_seconds / 2) if max_seconds else None       # split budget per side
    wX, witX = ris_min_logical(HX, HZ, trials, seed, max_seconds=half)        # X (ker HZ)
    wZ, witZ = ris_min_logical(HZ, HX, trials, seed + 1, max_seconds=half)    # Z (ker HX)
    sides = {}
    if wX is not None:
        sides["X"] = {"value": doc["distance"].get("X", {}).get("value"),
                      "lightest_found": wX,
                      "witness": sorted(int(j) for j in np.nonzero(witX)[0])}
    if wZ is not None:
        sides["Z"] = {"value": doc["distance"].get("Z", {}).get("value"),
                      "lightest_found": wZ,
                      "witness": sorted(int(j) for j in np.nonzero(witZ)[0])}
    d_heur = min([w for w in (wX, wZ) if w is not None], default=None)

    method = "ris"
    if _fast is not None and 0 < fast_trials <= trials:
        print(f"warning: gf2_fast is available but skipped "
              f"(fast_trials={fast_trials} <= trials={trials}); raise "
              f"--fast-trials or lower --trials to use the accelerator "
              f"(fast_trials=0 disables it deliberately)", file=sys.stderr)
    # Optional C++ accelerator: a larger overall search (min over both sides).
    if _fast is not None and fast_trials > trials:
        # Take the witness straight from the accelerator rather than asking the
        # Python pass to re-find it. The re-find never worked at large n: the
        # accelerator is orders of magnitude faster per trial, so a budget that
        # lets it reach weight w leaves the Python pass far short of w, and the
        # tighter weight was recorded with no witness to back it.
        d_fast, side, sup = _fast.distance_rand_witness(HX, HZ, fast_trials,
                                                        seed, 8, 8)
        d_fast = int(d_fast) if d_fast is not None else None
        if d_fast is not None and (d_heur is None or d_fast < d_heur):
            d_heur = d_fast
            if side in ("X", "Z"):
                wit = np.zeros(n, dtype=np.int8)
                wit[list(sup)] = 1
                # Validate before recording: the accelerator is not the trusted
                # stack, so a witness only counts once gf2 agrees it is in the
                # right kernel and outside the opposite rowspace.
                H_ker, H_row = (HZ, HX) if side == "X" else (HX, HZ)
                if _valid_logical(wit, H_ker, H_row):
                    sides.setdefault(side, {})
                    sides[side].update(
                        lightest_found=int(wit.sum()),
                        witness=sorted(int(j) for j in np.nonzero(wit)[0]))
        method = "ris+gf2_fast"
        trials = max(trials, fast_trials)

    if d_heur is None:
        verdict = "inconclusive"
    elif d_heur < claimed:
        verdict = "refuted"          # found a lighter logical -> claim over-stated
    elif d_heur == claimed:
        verdict = "corroborated"     # found exactly the claimed weight, none lighter
    else:
        verdict = "inconclusive"     # budget too small to even reach the claimed weight

    return {"name": doc.get("name", ""), "claimed_d": claimed,
            "d_heuristic": d_heur, "verdict": verdict,
            "sides": sides, "trials": trials, "seed": seed, "method": method}


def refute_check(doc, seed=0, max_seconds=10.0, trials=None):
    """CI gate. Run a bounded, time-capped RIS search and report whether it found a
    logical LIGHTER than the claimed distance. Returns (refuted, d_found, witness,
    trials). Sound (the witness is a checkable lighter logical) but not complete (a
    null result is not a proof); pure Python with a fixed seed, so deterministic and
    non-flaky. Budget is n-scaled trials under a wall-clock cap; pass ``trials`` to
    override the default target (the CI gate scales both with code size)."""
    n = doc["n"]
    if trials is None:
        trials = min(8000, 2500 + 40 * n)
    res = estimate(doc, trials=trials, seed=seed, fast_trials=0,
                   max_seconds=max_seconds)
    claimed = int(doc["distance"]["d"])
    dh = res["d_heuristic"]
    refuted = dh is not None and dh < claimed
    witness = None
    if refuted:
        for s in res["sides"].values():
            if s.get("lightest_found") == dh:
                witness = s["witness"]
                break
    return refuted, dh, witness, res["trials"]


def main(path, trials, seed, fast_trials=None):
    doc = json.load(open(path))
    # A bigger --trials budget must never silently turn the accelerator off
    # (issue #290): unless --fast-trials is given explicitly, scale the fast
    # budget with the requested depth. --fast-trials 0 forces pure Python.
    if fast_trials is None:
        fast_trials = max(400000, 4 * trials)
    res = estimate(doc, trials=trials, seed=seed, fast_trials=fast_trials)
    print(json.dumps(res, indent=2))
    return 2 if res["verdict"] == "refuted" else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--trials", type=int, default=20000,
                    help="pure-Python RIS trials per side (default 20000)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--fast-trials", type=int, default=None,
                    help="gf2_fast overall trial budget (default: "
                         "max(400000, 4*trials)); 0 disables the accelerator")
    args = ap.parse_args()
    sys.exit(main(args.path, args.trials, args.seed, args.fast_trials))
