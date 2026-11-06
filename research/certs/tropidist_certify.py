#!/usr/bin/env python3
r"""Exact distances from tropidist (arXiv:2611.08247) at the solver tier (issue #4716).

tropidist (github.com/Fanerst/tropidist, Cheng, Guo, and Pan) computes the
least weight of a vector e with H e = 0 and L e != 0 over GF(2) by exhaustive
evaluators: a cut-rank dynamic program, a weight-truncated version of it, and
a weight-bounded search with covering bounds and symmetry. Its record holds a
proved lower bound, the lightest vector it found, and the time at which each
bound was reached. This module turns a board entry into that problem, runs the
tool at a pinned checkout, re-checks the vector it returns with the board's own
validators, and writes a certificate in the #3666 shape.

Two encodings:

  CSS        one problem per side, as verify/sat_certify.py asks it. Side X
             is the least weight of an X-type logical: H = H_Z (the operator
             commutes with every Z check) and L = the Z-type logical
             representatives (it anticommutes with one of them, so it is not
             an X stabilizer). Side Z mirrors it.
  stabilizer one problem in Pauli weight. Each qubit becomes three mechanisms
             X_i, Z_i, Y_i; a row of H is a generator's symplectic product
             with each mechanism, and a row of L the same for each of the 2k
             logical representatives (ker (B|A) modulo row (A|B), the
             doubled-code picture verify/heuristic_distance.py uses). A
             minimum never selects two mechanisms on one qubit, since their
             product is the third mechanism with the same syndrome and label
             at weight one, so the least mechanism count is the Pauli
             distance (the merged-mechanism argument of the paper's
             Supplementary Section 2). This is the Pauli-weight certifier
             #4206 asks for, at the solver tier.

Trust: the lower bound is exhaustion inside the tool's kernel. Completeness is
proved in the paper, but nothing replayable accompanies a run, so the
certificate's verification.level is "solver", the level the HiGHS and
CryptoMiniSat records hold. The proof_log tier stays with sat_certify.py's
DRAT path. The vector the tool returns as its upper bound is re-verified here
before anything is written; a vector lighter than the entry's claim is a
refutation, not a certificate.

    uv run python research/certs/tropidist_certify.py codes/<slug>.json --tropidist /path/to/tropidist \\
        [--tlim 600] [--threads 4] [--json]

The checkout is given by --tropidist or the TROPIDIST_ROOT environment
variable; the tool needs numpy and a C compiler (its kernels build on first
use) and is run as ``python -m cdist`` from that directory.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "verify"))
import gf2  # noqa: E402
import heuristic_distance as HD  # noqa: E402

PAPER = "arXiv:2611.08247"
REPO = "github.com/Fanerst/tropidist"
ENV_ROOT = "TROPIDIST_ROOT"
LEVEL = "solver"
MECHANISMS = ("X", "Z", "Y")
VERIFICATION_NOTE = (
    "tropidist's lower bound is exhaustion inside its kernel (cut-rank dynamic program, "
    "weight-truncated DP, weight-bounded search; completeness proved in the paper, no "
    "replayable artifact), so this is a solver verdict; the vector it returned was "
    "re-verified by verify/heuristic_distance.py")


class TropidistError(RuntimeError):
    """The tool did not run, did not write a record, or returned a vector the board rejects."""


# ---------------------------------------------------------------------------- the checkout
def tropidist_root(path=None):
    """Return the checkout to run, from the argument or TROPIDIST_ROOT, or None."""
    root = path or os.environ.get(ENV_ROOT)
    if not root:
        return None
    root = os.path.abspath(root)
    if not os.path.isfile(os.path.join(root, "cdist", "__main__.py")):
        raise TropidistError(f"{root} is not a tropidist checkout (no cdist/__main__.py)")
    return root


def tropidist_commit(root):
    """Return the checkout's commit, or None when it is not a git tree."""
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def solver_string(root):
    """Return what the certificate records as its solver: the tool and the commit it ran at."""
    commit = tropidist_commit(root)
    return f"tropidist {commit[:12] if commit else 'unpinned'} ({PAPER}) exhaustive search"


# ---------------------------------------------------------------------------- the problems
def css_problems(doc):
    """Return {"X": (H, L), "Z": (H, L)} for a CSS entry, in the board's side convention.

    Side X asks for an X-type logical: in ker(H_Z) and anticommuting with a
    Z-type logical representative. Raises ValueError when a side's pairing
    set does not span the k logical classes, as sat_certify does: UNSAT (here,
    a lower bound) against a short pairing set would mean nothing.
    """
    n = doc["n"]
    HX = HD._matrix(doc["checks"]["X"], n)
    HZ = HD._matrix(doc["checks"]["Z"], n)
    k = n - gf2.rank(HX) - gf2.rank(HZ)
    out = {}
    for side, H_same, H_opp in (("X", HX, HZ), ("Z", HZ, HX)):
        L = gf2.logical_basis(H_same, H_opp)   # ker(H_same) modulo row(H_opp): the opposite-type logicals
        spanned = gf2.rank(np.vstack([H_opp, L])) - gf2.rank(H_opp) if len(L) else 0
        if spanned != k:
            raise ValueError(f"{side} side: pairing set spans {spanned} of {k} logical classes")
        out[side] = (H_opp, L)
    return out, int(k)


def _mechanism_rows(rows, n):
    """Symplectic products of (x | z) rows with the 3n mechanisms X_i, Z_i, Y_i, in that column order."""
    rows = np.asarray(rows, dtype=np.int8) % 2
    lx, lz = rows[:, :n], rows[:, n:]
    return np.concatenate([lz, lx, (lx + lz) % 2], axis=1).astype(np.int8)


def pauli_problem(doc):
    """Return (H, L) over the 3n Pauli mechanisms of a stabilizer entry, and k.

    H has one row per generator, L one per logical representative; the
    representatives span N(S)/S, so a vector in ker(H) is a nontrivial logical
    exactly when L maps it to a nonzero label.
    """
    n = doc["n"]
    A, B = HD.stabilizer_matrices(doc)
    S = np.concatenate([A, B], axis=1) % 2
    SL = np.concatenate([B, A], axis=1) % 2
    L = gf2.logical_basis(SL, S)
    k = doc["k"]
    if L.shape[0] != 2 * k:
        raise ValueError(f"stabilizer logical basis has {L.shape[0]} rows, expected 2k = {2 * k}")
    return (_mechanism_rows(S, n), _mechanism_rows(L, n)), int(k)


def problems(doc):
    """Return ({side: (H, L)}, k): sides X and Z for a CSS entry, side P for a stabilizer entry."""
    if doc.get("code_type") == "stabilizer":
        (H, L), k = pauli_problem(doc)
        return {"P": (H, L)}, k
    return css_problems(doc)


def write_mtx(path, M):
    """Write a binary matrix as a MatrixMarket coordinate pattern file, 1-based."""
    M = np.asarray(M) % 2
    r, c = np.nonzero(M)
    with open(path, "w", encoding="utf-8") as f:
        f.write("%%MatrixMarket matrix coordinate pattern general\n")
        f.write(f"{M.shape[0]} {M.shape[1]} {len(r)}\n")
        for i, j in zip(r.tolist(), c.tolist()):
            f.write(f"{i + 1} {j + 1}\n")


# ---------------------------------------------------------------------------- the vectors
def vector_from_columns(cols, n, stabilizer):
    """Return the GF(2) vector a list of problem columns stands for: length n, or (x | z) of length 2n."""
    if not stabilizer:
        v = np.zeros(n, dtype=np.int8)
        for c in cols:
            v[int(c)] ^= 1
        return v
    v = np.zeros(2 * n, dtype=np.int8)
    for c in cols:
        kind, q = divmod(int(c), n)
        if kind in (0, 2):
            v[q] ^= 1
        if kind in (1, 2):
            v[n + q] ^= 1
    return v


def check_vector(doc, side, cols):
    """Return (ok, weight) for the tool's vector: a nontrivial logical of the side, by the board's validators."""
    n = doc["n"]
    if side == "P":
        A, B = HD.stabilizer_matrices(doc)
        v = vector_from_columns(cols, n, True)
        return bool(HD.valid_pauli_logical(v, A, B)), int((v[:n] | v[n:]).sum())
    HX = HD._matrix(doc["checks"]["X"], n)
    HZ = HD._matrix(doc["checks"]["Z"], n)
    H_same, H_opp = (HX, HZ) if side == "X" else (HZ, HX)
    v = vector_from_columns(cols, n, False)
    return bool(HD._valid_logical(v, H_opp, H_same)), int(v.sum())


# ---------------------------------------------------------------------------- running the tool
def run_cdist(H, L, *, root, tlim, threads=1, kmin=None, python=None, tag="side"):
    """Run ``python -m cdist --matrices`` on one problem and return its record.

    ``kmin`` starts the search at that threshold (a lower bound proved
    earlier). Raises TropidistError when no record comes back.
    """
    with tempfile.TemporaryDirectory(prefix="tropidist-") as tmp:
        h_path, l_path = os.path.join(tmp, f"{tag}.H.mtx"), os.path.join(tmp, f"{tag}.L.mtx")
        rec_path = os.path.join(tmp, f"{tag}.json")
        write_mtx(h_path, H)
        write_mtx(l_path, L)
        cmd = [python or sys.executable, "-m", "cdist", "--matrices", h_path, l_path,
               "--threads", str(int(threads)), "--time-limit", str(float(tlim)), "--out", rec_path]
        if kmin and int(kmin) > 1:
            cmd += ["--config", f"kmin={int(kmin)}"]
        proc = subprocess.run(cmd, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                              check=False)
        if not os.path.exists(rec_path):
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()
            raise TropidistError("tropidist wrote no record" + (f": {tail[-1]}" if tail else ""))
        with open(rec_path, encoding="utf-8") as f:
            return json.load(f)


def side_block(doc, side, claim, rec, *, tlim):
    """Fold one record into a certificate side block, in sat_certify's vocabulary.

    UNSAT: the proved lower bound reaches the claim, so no lighter logical
    exists. SAT: the tool found a logical lighter than the claim, verified
    here; the entry is refuted. TIMEOUT: neither, and the proved lower bound
    is kept. A vector the board's validators reject, or a lower bound above
    the claim (which would contradict the entry's verified witness), is an
    error rather than a verdict.
    """
    lb, ub = rec.get("lower_bound"), rec.get("upper_bound")
    blk = {"value": int(claim), "secs": round(float(rec.get("seconds") or 0.0), 1)}
    if ub is not None and int(ub) < int(claim):
        ok, weight = check_vector(doc, side, rec.get("witness") or [])
        if not ok or weight != int(ub):
            raise TropidistError(f"{side} side: the tool's weight-{ub} vector is not a nontrivial "
                                 f"logical of weight {ub} by the board's check (weight {weight}, valid {ok})")
        blk.update(exact=False, status="SAT", witness=[int(c) for c in rec["witness"]],
                   note=f"REFUTED: logical of weight {ub} exists")
        return blk
    if lb is not None and int(lb) > int(claim):
        raise TropidistError(f"{side} side: the tool proved d >= {lb} against a verified witness of weight "
                             f"{claim}; the problem it was handed is not this entry's")
    if lb is not None and int(lb) == int(claim):
        blk.update(exact=True, status="UNSAT", note=f"no logical < {claim} exists")
        return blk
    blk.update(exact=False, status="TIMEOUT", lower_bound=int(lb) if lb is not None else None,
               note=(f"lower bound {lb} after {tlim} s" if lb is not None else f"nothing proved in {tlim} s"))
    return blk


def certify(doc, *, root, tlim=600, threads=1, slug=None, kmin=None, runner=None):
    """Certify an entry's claimed distance with tropidist; return the certificate record.

    ``kmin`` maps a side to the threshold its search starts at. ``runner``
    replaces run_cdist (the tests' stand-in). The record is the #3666 shape:
    d_exact only when every side closed at the claim, per side the status and
    the proved lower bound otherwise, and a solver-level verification block.
    """
    probs, k = problems(doc)
    dist = doc["distance"]
    d = int(dist["d"])
    run = runner or run_cdist
    out = {"name": doc.get("name"), "d": d, "solver": solver_string(root) if root else f"tropidist ({PAPER})",
           "encoding": "pauli-mechanisms" if "P" in probs else "css-sides",
           "tlim_per_solve": tlim, "logical_classes": k, "sides": {}}
    for side, (H, L) in probs.items():
        claim = int((dist.get(side) or {}).get("value", d))
        t0 = time.time()
        rec = run(H, L, root=root, tlim=tlim, threads=threads,
                  kmin=(kmin or {}).get(side), tag=f"{slug or 'entry'}.{side}")
        blk = side_block(doc, side, claim, rec, tlim=tlim)
        blk.setdefault("secs", round(time.time() - t0, 1))
        out["sides"][side] = blk
    out["d_exact"] = all(b.get("exact") for b in out["sides"].values()) and \
        all(b["value"] == d for b in out["sides"].values())
    out["verification"] = {"level": LEVEL, "note": VERIFICATION_NOTE[:500]}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", help="codes/<slug>.json")
    ap.add_argument("--tropidist", default=None, help=f"the checkout to run (default: ${ENV_ROOT})")
    ap.add_argument("--tlim", type=float, default=600, help="seconds per side (default 600)")
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--json", action="store_true", help="print the record instead of a summary line")
    a = ap.parse_args(argv)
    root = tropidist_root(a.tropidist)
    if root is None:
        print(f"no tropidist checkout: pass --tropidist or set {ENV_ROOT}", file=sys.stderr)
        return 2
    with open(a.path, encoding="utf-8") as f:
        doc = json.load(f)
    slug = os.path.splitext(os.path.basename(a.path))[0]
    try:
        out = certify(doc, root=root, tlim=a.tlim, threads=a.threads, slug=slug)
    except (ValueError, TropidistError) as e:
        print(f"{slug}: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(out, indent=1, sort_keys=True))
    else:
        bits = [f"{s} {b['status']} {b['secs']} s" + (f" (d >= {b['lower_bound']})" if b.get("lower_bound") else "")
                for s, b in out["sides"].items()]
        print(f"{slug}: d_exact={out['d_exact']} " + "; ".join(bits))
    return 0 if out["d_exact"] else 1


if __name__ == "__main__":
    sys.exit(main())
