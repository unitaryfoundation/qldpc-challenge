"""Exact distance certification with a SAT solver.

Complements ``verify/certify.py`` (scipy/HiGHS MILP). The question is the same:
does a nontrivial logical operator of weight <= W exist? UNSAT on both sides at
W = d - 1 certifies d exactly.

The encoding matters more than the solver. Asking the question once per logical
generator, with that generator's anticommutation row fixed, costs one solve per
generator per side; asking it once with a selector variable per generator and a
clause requiring at least one of them costs a single solve. Measured on board
entries, certifying at W = d - 1:

    24-6-4    (k=6)    0.1 s  ->  0.04 s
    72-6-6    (k=6)    1.1 s  ->  0.4 s
    108-8-10  (k=8)    2228 s ->  408 s
    126-28-8  (k=28)   765 s (hit the cap, unfinished) -> 203-605 s

The gap widens with k, which is how many solves the per-generator form pays
for, and is where the board's high-rate entries live.

The single query is also what makes symmetry breaking legal. Two-block
circulant codes are invariant under the simultaneous rotation of both halves,
but the per-generator form is not, because fixing one generator's
anticommutation row breaks the symmetry the rotation acts on. With selectors
the constraint set is invariant, so lex-leader constraints (v >= its own
rotations, on a prefix) can be added. Measured on 126-28-8 at W = 7, on a host
quiesced to load 2.7 after a first attempt at load 15 produced numbers that
were mostly contention:

    with symmetry     203 s, 605 s
    without           913 s, 1001 s

Run-to-run spread within the symmetry arm is 3x, so the ratio is not worth
quoting to a decimal, but the arms do not overlap: the slowest run with
symmetry beats the fastest without. Off by default at small k, where it costs
clauses and buys nothing; the caller turns it on, and certify() does so
whenever the rotation is verified to fix both row spaces.

Parity constraints go to the solver as native XOR clauses rather than CNF
expansions; only the cardinality bound needs encoding, via pysat's sequential
counter. Needs pycryptosat and python-sat.

Pairing direction is the subtle part and got this wrong once. For the X side
(v in ker HZ) the generators must be Z-logicals: <v, t> = 1 against a Z-logical
is what certifies v is outside rowspace(HX), because X-stabilizers commute with
every Z-logical. Pairing against X-logicals instead admits stabilizers as
"solutions", and the giveaway was a reported weight-9 logical on a code whose
checks have weight 9.

With ``ladder`` (issue #4230) the same question is asked at W = 1, 2, ...
up to d - 1 rather than at d - 1 alone. UNSAT at W is the theorem d >= W + 1
whatever happens above it, so a ladder that times out still leaves a proven
lower bound, recorded per side as ``proved_min`` and overall as ``d_lower``;
the exact certificate is the case d_lower = d. Cost grows steeply with W
(roughly 3-5x per rung on board entries), so the ladder ascends and stops at
the first timeout rather than searching. The proof path runs per rung, and a
partial certificate at proof_log carries the hash of each side's top UNSAT
rung, which the replay regenerates at that side's proved_min - 1.

The pairing set itself is the other half of that, and got this wrong for
longer. It has to span all k logical classes. A set that misses a class
cannot constrain the operators in it, so a logical lighter than the claim
slips through and the side reports UNSAT; a set that is short by every class
makes the clause unsatisfiable outright, so the side reports UNSAT without
searching at all. Either way the certifier answers the wrong question and
calls it a proof. The earlier construction sliced rows out of
rref([H_same; ker H_opp]) at rank(H_same), which assumed RREF leaves the
stabilizer rows in the first block; RREF orders rows by pivot column, so the
slice could keep stabilizers and drop logical classes. certify() now counts
the classes the pairing set spans and refuses to solve unless it is all k.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import time

import gf2
import numpy as np


def _logicals(H_same, H_opp):
    """Basis of one side's logicals: ker(H_opp) modulo rowspace(H_same).

    One representative per logical class, built by reducing each kernel
    vector against the stabilizers and against the representatives already
    kept, so every row returned is independent of the stabilizers and of the
    other rows.
    """
    return np.asarray(gf2.logical_basis(H_opp, H_same), dtype=np.int8)


def _shift_perm(n):
    """Build the simultaneous rotation of both circulant halves."""
    m = n // 2
    p = np.empty(n, dtype=int)
    for j in range(m):
        p[j] = (j + 1) % m
        p[m + j] = m + (j + 1) % m
    return p


def _perm_fixes(H, p):
    """Report whether permuting columns by p preserves rowspace(H)."""
    return gf2.rank(np.vstack([H, H[:, p]])) == gf2.rank(H)


def _lex_leader_clauses(s, n, top, prefix):
    """Constrain v to be lex-greatest in its rotation orbit, on a prefix.

    Only a prefix is constrained: the full lex-leader encoding is quadratic in
    n per rotation and the tail contributes almost no pruning, so the bound is
    sound (it removes only orbit duplicates) but deliberately partial.
    """
    q = _shift_perm(n)
    pj = np.arange(n)
    for _ in range(1, n // 2):
        pj = q[pj]
        prev = None
        for i in range(min(prefix, n)):
            a, b = i + 1, int(pj[i]) + 1
            if a == b:
                continue
            if prev is None:
                s.add_clause([a, -b])
            else:
                s.add_clause([-prev, a, -b])
            top += 1
            e = top
            s.add_clause([-e, a, -b])
            s.add_clause([-e, -a, b])
            if prev is not None:
                s.add_clause([-e, prev])
            prev = e
    return top


def _solve_side(H_opp, L, W, tlim, use_symmetry=False, prefix=25):
    """Search for v with H_opp v = 0, |v| <= W, anticommuting with some t in L."""
    from pycryptosat import Solver
    from pysat.card import CardEnc, EncType

    n = H_opp.shape[1]
    s = Solver(threads=1)
    for row in H_opp:
        idx = [int(j) + 1 for j in np.nonzero(row)[0]]
        if idx:
            s.add_xor_clause(idx, False)
    top = n
    selectors = []
    for t in L:
        top += 1
        selectors.append(top)
        tidx = [int(j) + 1 for j in np.nonzero(t)[0]]
        # y <-> <v, t>: xor(t-support + [y]) = 0
        s.add_xor_clause(tidx + [top], False)
    if not selectors:
        return "UNSAT", None
    s.add_clause(selectors)                 # at least one anticommutation
    card = CardEnc.atmost(lits=list(range(1, n + 1)), bound=W,
                          top_id=top, encoding=EncType.seqcounter)
    top = max(top, card.nv)
    for cl in card.clauses:
        s.add_clause(cl)
    if use_symmetry:
        top = _lex_leader_clauses(s, n, top, prefix)
    sat, sol = s.solve(time_limit=tlim)
    if sat is None:
        return "TIMEOUT", None
    if not sat:
        return "UNSAT", None
    return "SAT", sorted(j - 1 for j in range(1, n + 1) if sol[j])


# ---------------------------------------------------------------------------
# proof-log path (issue #2728)
# ---------------------------------------------------------------------------
# A second emitter, not a flag on the first. pycryptosat exposes no proof
# logging, and CryptoMiniSat's Gaussian elimination over the XOR constraints
# is not DRAT-expressible as run, so a checkable refutation needs the same
# instance written as pure CNF and handed to a solver that logs. What this
# buys is one level: the CNF we handed the solver is independently confirmed
# unsatisfiable. It says nothing about whether that CNF asks the distance
# question, which is the #2273 failure, and is why the schema keeps
# proof_log and formal apart.
#
# Symmetry breaking is deliberately omitted from the proof instance. The
# lex-leader prefix is a pruning constraint; dropping it refutes the larger
# instance, which is the stronger statement, and keeps the artifact free of
# a constraint a checker would have to take on trust.

XOR_CHUNK = 5          # XOR arity per chunk; 2^(c-1) clauses each


def _xor_cnf(lits, parity, fresh):
    """CNF for XOR(lits) = parity, chunked through Tseitin auxiliaries.

    A direct expansion is 2^(m-1) clauses, unusable past about 20 literals;
    chunking at arity c costs about m/(c-1) chunks of 2^(c-1) clauses and one
    auxiliary each. Returns (clauses, fresh).
    """
    out, lits = [], list(lits)
    if not lits:
        return ([] if parity == 0 else [[]]), fresh
    while len(lits) > XOR_CHUNK:
        head = lits[:XOR_CHUNK - 1]
        fresh += 1
        # aux carries the parity of the chunk it replaces: XOR(head, aux) = 0.
        out.extend(_xor_expand(head + [fresh], 0))
        lits = [fresh] + lits[XOR_CHUNK - 1:]
    out.extend(_xor_expand(lits, parity))
    return out, fresh


def _xor_expand(lits, parity):
    """Direct CNF for a short XOR: one clause per falsifying assignment."""
    clauses = []
    for mask in range(1 << len(lits)):
        bits = [(mask >> i) & 1 for i in range(len(lits))]
        if sum(bits) % 2 == parity:
            continue
        clauses.append([-lit if b else lit for lit, b in zip(lits, bits)])
    return clauses


def side_cnf(H_opp, L, W):
    """Build the pure-CNF form of one side's question.

    Same question as :func:`_solve_side`: is there v with H_opp v = 0,
    |v| <= W, anticommuting with at least one pairing generator. Returns
    (clauses, nvars).
    """
    from pysat.card import CardEnc, EncType

    n = H_opp.shape[1]
    clauses, fresh = [], n
    for row in H_opp:
        idx = [int(j) + 1 for j in np.nonzero(row)[0]]
        if idx:
            cl, fresh = _xor_cnf(idx, 0, fresh)
            clauses.extend(cl)
    selectors = []
    for t in L:
        fresh += 1
        y = fresh
        selectors.append(y)
        tidx = [int(j) + 1 for j in np.nonzero(t)[0]]
        cl, fresh = _xor_cnf(tidx + [y], 0, fresh)
        clauses.extend(cl)
    if not selectors:
        return None, 0
    clauses.append(list(selectors))
    card = CardEnc.atmost(lits=list(range(1, n + 1)), bound=W,
                          top_id=fresh, encoding=EncType.seqcounter)
    clauses.extend([list(c) for c in card.clauses])
    fresh = max(fresh, card.nv)
    return clauses, fresh


def write_dimacs(clauses, nvars, path):
    """Write a CNF and return its sha256, which identifies the instance."""
    h = hashlib.sha256()
    with open(path, "w", encoding="ascii", newline="\n") as f:
        header = f"p cnf {nvars} {len(clauses)}\n"
        f.write(header)
        h.update(header.encode())
        for cl in clauses:
            line = " ".join(str(x) for x in cl) + " 0\n"
            f.write(line)
            h.update(line.encode())
    return h.hexdigest()


def _tool_version(cmd, args, pattern):
    """Return a stable identifier for a tool, or None when it cannot be run.

    A printed version when the tool has one, and the first 16 hex of the
    binary's sha256 when it does not. drat-trim prints only a usage banner,
    and "drat-trim" alone does not say which drat-trim checked the proof.
    """
    try:
        r = subprocess.run([cmd, *args], capture_output=True, text=True,
                           timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    text = (r.stdout or "") + (r.stderr or "")
    m = re.search(pattern, text)
    if m:
        return m.group(0)
    path = shutil.which(cmd)
    if not path:
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()[:16]}"


def tool_versions():
    """Report the proof toolchain, so a certificate names what checked it."""
    return {
        "kissat": _tool_version("kissat", ["--version"], r"\d+\.\d+\.\d+"),
        "drat_trim": _tool_version("drat-trim", [], r"\d{4}-\d{2}(-\d{2})?"),
    }


def prove_side(H_opp, L, W, outdir, tag, *, tlim=600, keep_proof=False):
    """Emit the CNF, refute it with kissat, and check the proof with drat-trim.

    Returns a record with the verdict and the artifact paths. A side counts
    as proved only when kissat reports UNSAT and drat-trim reports VERIFIED;
    anything else leaves it unproved and says why.
    """
    os.makedirs(outdir, exist_ok=True)
    cnf_path = os.path.join(outdir, f"{tag}.cnf")
    proof_path = os.path.join(outdir, f"{tag}.proof")
    trim_path = os.path.join(outdir, f"{tag}.trim.drat")

    clauses, nvars = side_cnf(H_opp, L, W)
    if clauses is None:
        return {"status": "NO_PAIRING", "proved": False,
                "detail": "no pairing generator, so there is nothing to ask"}
    t0 = time.time()
    cnf_sha = write_dimacs(clauses, nvars, cnf_path)
    rec = {"cnf": {"path": cnf_path, "sha256": cnf_sha, "vars": nvars,
                   "clauses": len(clauses),
                   "bytes": os.path.getsize(cnf_path)},
           "xor_chunk": XOR_CHUNK}
    try:
        r = subprocess.run(["kissat", "-q", "--no-binary", cnf_path,
                            proof_path],
                           capture_output=True, text=True, timeout=tlim,
                           check=False)
    except subprocess.TimeoutExpired:
        rec.update(status="TIMEOUT", proved=False,
                   detail=f"kissat did not finish in {tlim}s")
        return rec
    except OSError as e:
        rec.update(status="NO_SOLVER", proved=False, detail=str(e))
        return rec
    rec["solve_secs"] = round(time.time() - t0, 1)
    if r.returncode == 10:
        rec.update(status="SAT", proved=False,
                   detail="satisfiable: a logical under the bound exists")
        return rec
    if r.returncode != 20:
        rec.update(status="UNKNOWN", proved=False,
                   detail=f"kissat exit {r.returncode}")
        return rec
    rec["proof"] = {"path": proof_path, "bytes": os.path.getsize(proof_path)}

    t1 = time.time()
    try:
        c = subprocess.run(["drat-trim", cnf_path, proof_path, "-l",
                            trim_path],
                           capture_output=True, text=True, timeout=tlim,
                           check=False)
    except subprocess.TimeoutExpired:
        rec.update(status="UNSAT", proved=False,
                   detail=f"drat-trim did not finish in {tlim}s")
        return rec
    except OSError as e:
        rec.update(status="UNSAT", proved=False, detail=str(e))
        return rec
    out = (c.stdout or "") + (c.stderr or "")
    rec["check_secs"] = round(time.time() - t1, 1)
    rec["verified"] = "s VERIFIED" in out
    if os.path.exists(trim_path):
        rec["trimmed"] = {"path": trim_path,
                          "bytes": os.path.getsize(trim_path)}
    if not rec["verified"]:
        rec.update(status="UNSAT", proved=False,
                   detail="drat-trim did not verify the proof")
        return rec
    rec.update(status="UNSAT", proved=True)
    if not keep_proof and os.path.exists(proof_path):
        # The untrimmed proof is the working file; the trimmed core is what
        # a reviewer would read, and its size is what the batch log records.
        os.remove(proof_path)
        rec["proof"]["path"] = None
    return rec


def _rung(H_opp, L, W, tlim, sym, proof_dir, tag):
    """Ask one side's question at one weight, on both emitters when asked.

    Returns ``(status, witness, proof_record, settled)``. ``proof_record`` is
    None without ``proof_dir``; ``settled`` says the XOR path timed out and
    the checked pure-CNF refutation decided the rung.
    """
    status, wit = _solve_side(H_opp, L, W, tlim, use_symmetry=sym)
    pr, settled = None, False
    if proof_dir is not None:
        pr = prove_side(H_opp, L, W, proof_dir, tag, tlim=tlim)
        # The two emitters answer the same question. A real disagreement is
        # a bug in one of them and is reported rather than averaged. A
        # timeout is not a verdict, so it is not a disagreement: the XOR
        # path running out of budget where the proof path finishes is the
        # proof path being faster, which on this encoding it sometimes is.
        verdicts = {"SAT", "UNSAT"}
        if (pr.get("status") in verdicts and status in verdicts
                and pr["status"] != status):
            raise ValueError(
                f"W = {W}: the XOR encoding says {status} and the pure-CNF "
                f"encoding says {pr['status']}; one of the two is wrong and "
                f"neither verdict is usable until that is found")
        # A refutation drat-trim has checked is stronger evidence than the
        # incumbent path produces, so it settles a rung the incumbent left
        # open rather than being discarded for not matching it.
        if pr.get("proved") and status == "TIMEOUT":
            status, settled = "UNSAT", True
    return status, wit, pr, settled


def certify(doc, tlim=600, proof_dir=None, slug=None, *, ladder=False,
            budget=None, start=1):
    """Certify a submission doc's distance exactly, mirroring certify.certify.

    Returns per-side ``exact`` flags and an overall ``d_exact``. A SAT result
    means the claim is refuted and carries the witness that refutes it; a
    timeout at W = d - 1 proves nothing about exactness.

    With ``ladder`` the question is asked at W = ``start``, ``start`` + 1, ...
    up to d - 1 instead of at d - 1 alone, and each side stops at its first
    timeout, at a refutation, or once ``budget`` seconds have gone into it
    (issue #4230). UNSAT at W is the theorem d >= W + 1 whatever happens
    above it, so the record then carries per side ``proved_min`` and the
    ``ladder`` of rungs, and overall ``d_lower`` = min over sides, which is
    d exactly when ``d_exact``. ``start`` above 1 resumes a ladder a
    previous run left at ``start`` - 1 without re-proving the rungs below.
    A partial record (``d_exact`` false, ``d_lower`` >= 2) is bound to the
    entry's matrices by ``verification.checks_sha256`` so that a later
    correction of the claim cannot strand it. Without ``ladder`` the record
    is exactly what this function produced before.
    """
    n = doc["n"]
    HX = _matrix(doc["checks"]["X"], n)
    HZ = _matrix(doc["checks"]["Z"], n)
    d = int(doc["distance"]["d"])
    k = n - gf2.rank(HX) - gf2.rank(HZ)
    out = {"name": doc.get("name"), "d": d, "solver": "CryptoMiniSat 5.14 SAT",
           "encoding": "selector", "sides": {}, "tlim_per_solve": tlim,
           "logical_classes": int(k)}
    rungs = list(range(max(1, int(start)), d)) if ladder else [d - 1]
    if not rungs:
        rungs = [d - 1]
    if ladder:
        out["ladder"] = {"start": rungs[0], "budget_per_side": budget}
    # Symmetry breaking is applied only when the rotation is checked to fix
    # both row spaces, so a non-circulant entry degrades to the plain encoding
    # instead of being pruned by a constraint that does not hold for it.
    sym = (n % 2 == 0 and _perm_fixes(HX, _shift_perm(n))
           and _perm_fixes(HZ, _shift_perm(n)))
    out["symmetry"] = bool(sym)
    for side, H_same, H_opp in (("X", HX, HZ), ("Z", HZ, HX)):
        t0 = time.time()
        L = _logicals(H_opp, H_same)
        # An UNSAT from a pairing set that does not span every class is not a
        # proof of anything, so refuse rather than record one. Counting rows
        # is not enough: a row lying in the rowspace it was reduced against
        # is a stabilizer and constrains nothing, which is exactly how this
        # failed before. L is ker(H_same) modulo rowspace(H_opp), so H_opp is
        # what it has to be independent of. The check holds at every rung:
        # an UNSAT from a deficient pairing set is as meaningless at W = 5
        # as at W = d - 1.
        spanned = (gf2.rank(np.vstack([H_opp, L])) - gf2.rank(H_opp)
                   if len(L) else 0)
        if spanned != k:
            raise ValueError(
                f"{side} side: pairing set spans {spanned} of {k} logical "
                f"classes, so UNSAT here would not mean no light logical")
        history, proved, decider, last_pr = [], 1, None, None
        status, wit, stopped_at = None, None, None
        for W in rungs:
            if budget is not None and history and time.time() - t0 > budget:
                stopped_at = W
                break
            tag = (f"{n}-{k}-{d}-{side}-W{W}" if ladder
                   else f"{n}-{k}-{d}-{side}")
            r0 = time.time()
            status, wit, pr, settled = _rung(H_opp, L, W, tlim, sym,
                                             proof_dir, tag)
            rung = {"W": W, "status": status,
                    "secs": round(time.time() - r0, 1)}
            if pr is not None:
                rung["proof"] = ("verified" if pr.get("proved")
                                 else pr.get("detail") or pr.get("status") or "?")
                if (pr.get("cnf") or {}).get("sha256"):
                    # Which formula this rung refuted, so a raised ladder
                    # can carry the rung's proof forward without the block.
                    rung["cnf_sha256"] = pr["cnf"]["sha256"]
                if settled:
                    rung["note"] = ("the XOR encoding timed out and the "
                                    "checked pure-CNF refutation settled it")
            history.append(rung)
            last_pr = pr
            if status != "UNSAT":
                break
            proved, decider = W + 1, pr
        blk = {"value": d, "exact": proved >= d, "status": status,
               "secs": round(time.time() - t0, 1)}
        if ladder:
            blk["proved_min"] = proved
            blk["ladder"] = history
        if proof_dir is not None:
            # The proof the side rests on is the top UNSAT rung's; with no
            # UNSAT rung the record keeps the last attempt's, which says why.
            blk["proof"] = decider if decider is not None else last_pr
        if status == "UNSAT":
            blk["note"] = f"no logical < {proved} exists"
            if stopped_at is not None:
                blk["note"] += (f"; the {budget:g} s budget was spent before "
                                f"W = {stopped_at}")
        elif status == "SAT":
            blk["note"] = f"REFUTED: logical of weight <= {history[-1]['W']} exists"
            blk["witness"] = wit
        elif proved > 1:
            blk["note"] = (f"no logical < {proved} exists; W = "
                           f"{history[-1]['W']} {status}")
        out["sides"][side] = blk
        if status == "SAT":
            break
    out["d_exact"] = all(b.get("exact") for b in out["sides"].values()) \
        and len(out["sides"]) == 2
    if ladder:
        out["d_lower"] = min(b["proved_min"] for b in out["sides"].values())
    if proof_dir is not None or ladder:
        out["verification"] = _verification_block(
            out, slug=slug or f"{n}-{k}-{d}")
        if ladder and not out["d_exact"]:
            # A partial certificate is about these matrices, whatever the
            # entry claims later; the hash is what the site honors it by.
            from check_certs import checks_sha256
            out["verification"]["checks_sha256"] = checks_sha256(doc)
    return out


def _repo_root():
    """Return the checkout root, so paths are recorded repo-relative."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _verification_block(out, *, slug=None):
    """Decide the certificate's level from what the proof run produced.

    proof_log only when every side the certificate rests on carries a proof
    drat-trim verified: at W = d - 1 for an exact certificate, at each
    side's top UNSAT rung for a partial one. Anything else stays at solver
    with the reason, because a level is a claim about what a third party
    can check, not about how hard we tried.
    """
    proofs = [b.get("proof") or {} for b in out["sides"].values()]
    partial = not out.get("d_exact") and (out.get("d_lower") or 1) >= 2
    if not (out.get("d_exact") or partial):
        return {"level": "solver",
                "note": "no exact verdict, so there is nothing to carry a "
                        "proof for"}
    if not any(proofs):
        return {"level": "solver",
                "note": "no proof path was run; a solver verdict with no "
                        "artifact a third party can check"}
    if not all(p.get("proved") for p in proofs):
        why = "; ".join(sorted({p.get("detail") or p.get("status") or "?"
                                for p in proofs if not p.get("proved")}))
        return {"level": "solver",
                "note": f"proof path did not complete: {why}"[:500]}
    tools = tool_versions()
    sides = {side: blk["proof"] for side, blk in out["sides"].items()}
    return {
        "level": "proof_log",
        "checker": f"drat-trim {tools['drat_trim'] or 'unknown'}",
        "cnf_sha256": ";".join(f"{side}={rec['cnf']['sha256']}"
                               for side, rec in sorted(sides.items())),
        # The recipe rather than the refutation. The trimmed cores run to
        # tens of megabytes apiece, nothing in CI can audit a committed
        # blob, and a formula regenerated from this entry and re-checked is
        # the same evidence without either problem. cnf_sha256 is what
        # makes the regeneration honest: a formula that does not hash to
        # the recorded value is not the one that was refuted. The replay
        # regenerates each side at its proved_min - 1, which is d - 1 on an
        # exact certificate.
        "replay": {
            "emit": f"python verify/replay_proofs.py {slug}",
            "check": "kissat --no-binary <side>.cnf <side>.proof; "
                     "drat-trim <side>.cnf <side>.proof",
            "emitter": f"verify/sat_certify.py side_cnf, XOR chunk arity "
                       f"{XOR_CHUNK}, no symmetry prefix",
        },
        "note": (f"pure-CNF re-encoding refuted by kissat "
                 f"{tools['kissat'] or '?'} and checked by drat-trim; the "
                 f"XOR path agrees. Confirms the CNF is unsatisfiable, not "
                 f"that it asks the distance question")[:500],
    }


def _matrix(support_list, n):
    """Dense GF(2) matrix from a list of row supports."""
    H = np.zeros((len(support_list), n), dtype=np.int8)
    for i, row in enumerate(support_list):
        H[i, list(row)] = 1
    return H


def _cli(argv=None):
    """Certify one or more entries, optionally with a checkable proof log."""
    import argparse

    ap = argparse.ArgumentParser(
        description="Exact distance certification. With --proof, also emit a "
                    "pure-CNF re-encoding, refute it with kissat, and check "
                    "the refutation with drat-trim.")
    ap.add_argument("codes", nargs="+", help="code JSON files")
    ap.add_argument("--proof", metavar="DIR", default=None,
                    help="working directory for the CNF, the proof, and the "
                         "trimmed core")
    ap.add_argument("--tlim", type=int, default=600,
                    help="per-solve time limit in seconds (default 600)")
    ap.add_argument("--json", action="store_true",
                    help="print the certificate instead of a summary line")
    ap.add_argument("--ladder", action="store_true",
                    help="ask W = 1, 2, ... up to d - 1 instead of d - 1 "
                         "alone, so a timeout still leaves a proven lower "
                         "bound d_lower (issue #4230)")
    ap.add_argument("--budget", type=float, default=None,
                    help="with --ladder: seconds per side before the ladder "
                         "stops opening rungs (default: until a rung times out)")
    ap.add_argument("--start", type=int, default=1,
                    help="with --ladder: the first W to ask, to resume a "
                         "ladder a previous certificate left at start - 1")
    args = ap.parse_args(argv)

    rc = 0
    for path in args.codes:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        slug = os.path.splitext(os.path.basename(path))[0]
        out = certify(doc, tlim=args.tlim, proof_dir=args.proof, slug=slug,
                      ladder=args.ladder, budget=args.budget, start=args.start)
        if args.json:
            print(json.dumps(out, indent=2, sort_keys=True))
            continue
        v = out.get("verification") or {}
        line = (f"{os.path.basename(path)}: d_exact={out['d_exact']}"
                + (f" d_lower={out['d_lower']}" if "d_lower" in out else "")
                + f" level={v.get('level', 'solver')}")
        for side, blk in out["sides"].items():
            pr = blk.get("proof") or {}
            bits = [blk["status"]]
            if pr:
                bits.append("proof " + ("verified" if pr.get("proved")
                                        else pr.get("detail") or "no"))
                if pr.get("trimmed"):
                    bits.append(f"{pr['trimmed']['bytes']}B trimmed")
                if pr.get("solve_secs") is not None:
                    bits.append(f"{pr['solve_secs']}s solve")
            line += f"  [{side}: {', '.join(bits)}]"
        print(line)
        if not out["d_exact"]:
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(_cli())
