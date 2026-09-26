"""
Transversal-gate claims (issue #1850, stage 1): the GF(2) check behind
`circuit.gates`.

A transversal gate on a CSS code is a qubit permutation, optionally composed
with one single-qubit Clifford applied to every qubit (H or S), or a CX from
each qubit of one code block to a qubit of a second block. Every one of these
maps Paulis to Paulis, so its action is a linear map on symplectic vectors
(x | z) over GF(2), and the two facts a claim rests on are linear algebra:

  preserves   the image of every stabilizer generator lies in the stabilizer
              group (x-part in rowspace(H_X), z-part in rowspace(H_Z), per
              block). The gate is invertible on Paulis and the group is
              finite, so this is equality of groups, not containment. For S
              the GF(2) image cannot see the phase: S maps X on a support of
              weight w to i^w (XZ) on that support, so every X-check must
              have weight 0 mod 4 or the gate sends a stabilizer to minus a
              stabilizer and leaves the code space.
  action      the image of each logical generator, reduced modulo the
              stabilizers, equals the claimed product of logical generators
              exactly. The check is up to stabilizers only: a logical factor
              the gate introduces belongs in the claim's product list. The
              GF(2) image does not see phases, so S and S^dagger share a
              claim: the symplectic action is what the board can verify
              without trusting anything.

The submitter supplies the logical basis the claim is written in
(`circuit.logicals`, k X-type and k Z-type representatives with identity
pairing) and the verifier checks that basis first, so a claim cannot rest on
operators that are not logicals of this code. Nothing here ranks: a verified
gate is a listed property, a wrong claim fails verification.
"""

import re

import numpy as np

import gf2

GATES = ("permutation", "H", "S", "CX")
_LABEL = re.compile(r"^([XZ])([0-9]+)('?)$")


class _Reducer:
    """Reduce vectors modulo the GF(2) row space of one matrix, with the RREF
    computed once (gf2.in_rowspace re-echelonizes per call, which is fine for
    two witnesses and too slow for every check row of a large code)."""

    def __init__(self, M):
        self.R, self.piv = gf2.rref(M)

    def reduce(self, V):
        V = (np.asarray(V, dtype=np.int8) % 2).astype(np.int8).copy()
        for i, c in enumerate(self.piv):
            mask = V[:, c].astype(bool)
            if mask.any():
                V[mask] ^= self.R[i]
        return V

    def contains_rows(self, V):
        return not self.reduce(V).any()


def _supports_to_matrix(rows, n):
    M = np.zeros((len(rows), n), dtype=np.int8)
    for r, sup in enumerate(rows):
        for q in sup:
            M[r, q] ^= 1
    return M


def _basis_errors(logicals, n, k, HX, HZ):
    """[] iff `logicals` is a symplectic logical basis of the code: k
    supports per side, in range and without repeats, X_i in ker(H_Z), Z_i in
    ker(H_X), and X_i Z_j^T = [i == j] over GF(2). Identity pairing implies
    independence modulo the stabilizers (a combination of X_i lying in
    rowspace(H_X) would commute with every Z_j)."""
    errs = []
    for side in ("X", "Z"):
        rows = logicals[side]
        if len(rows) != k:
            errs.append(f"logicals.{side} has {len(rows)} operators; the "
                        f"code has k={k}")
        for i, sup in enumerate(rows):
            if len(set(sup)) != len(sup) or (sup and max(sup) >= n):
                errs.append(f"logicals.{side}[{i}] must list distinct qubit "
                            f"indices below n={n}")
    if errs:
        return errs, None, None
    LX = _supports_to_matrix(logicals["X"], n)
    LZ = _supports_to_matrix(logicals["Z"], n)
    bad_x = [i for i in range(k) if not gf2.commutes(LX[i], HZ)]
    bad_z = [i for i in range(k) if not gf2.commutes(LZ[i], HX)]
    if bad_x:
        errs.append(f"logicals.X{bad_x[:4]} do not commute with the Z checks")
    if bad_z:
        errs.append(f"logicals.Z{bad_z[:4]} do not commute with the X checks")
    pairing = (LX @ LZ.T) % 2
    if not np.array_equal(pairing, np.eye(k, dtype=np.int8)):
        errs.append("logicals are not a symplectic basis: X_i and Z_j must "
                    "anticommute exactly when i = j (pairing matrix is not "
                    "the identity)")
    return errs, LX, LZ


def _parse_label(label, k, blocks):
    """(pauli, index, block) for a generator label, or None if it names no
    generator of this claim (index out of range, or a primed label on a
    single-block gate)."""
    m = _LABEL.match(label)
    if not m:
        return None
    pauli, idx, prime = m.group(1), int(m.group(2)), m.group(3) == "'"
    if idx >= k or (prime and blocks == 1):
        return None
    return pauli, idx, int(prime)


def _generator_labels(k, blocks):
    return [f"{p}{i}{prime}" for prime in ([""] if blocks == 1 else ["", "'"])
            for p in ("X", "Z") for i in range(k)]


def _image(gate, pinv, p, X, Z, blocks):
    """Symplectic image of the operators whose x- and z-parts are the rows of
    X and Z, each of shape (m, blocks, n). Qubit i is sent to p[i], so a
    support vector v becomes v[pinv] (v'[p[i]] = v[i]); the Clifford acts
    after the permutation, and being uniform it commutes with it anyway."""
    if gate == "CX":
        # control block 0, target block 1: X_i -> X_i X'_{p[i]},
        # Z'_{p[i]} -> Z_i Z'_{p[i]}, Z on the control and X on the target
        # untouched.
        X2, Z2 = X.copy(), Z.copy()
        X2[:, 1] ^= X[:, 0][:, pinv]
        Z2[:, 0] ^= Z[:, 1][:, p]
        return X2, Z2
    Xp, Zp = X[:, :, pinv], Z[:, :, pinv]
    if gate == "H":
        return Zp, Xp
    if gate == "S":
        return Xp, (Xp ^ Zp).astype(np.int8)
    return Xp, Zp


def _gate_errors(g, idx, n, k, HX, HZ, LX, LZ, red_x, red_z):
    """([preservation errors], [action errors], computed) for one claim."""
    gate = g["gate"]
    blocks = 2 if gate == "CX" else 1
    computed = {"gate": gate, "blocks": blocks, "name": g.get("name"),
                "verified": False, "action": {}}
    p = g.get("permutation")
    if p is None:
        p = list(range(n))
    if sorted(p) != list(range(n)):
        return ([f"gates[{idx}].permutation is not a permutation of "
                 f"0..{n - 1}"], [], computed)
    p = np.asarray(p, dtype=np.int64)
    pinv = np.empty_like(p)
    pinv[p] = np.arange(n)
    computed["permutation_trivial"] = bool(np.array_equal(p, np.arange(n)))

    def in_group(X, Z):
        """Do the operators (X, Z), shape (m, blocks, n), all lie in the
        stabilizer group of `blocks` copies of the code?"""
        return all(red_x.contains_rows(X[:, b]) and red_z.contains_rows(Z[:, b])
                   for b in range(blocks))

    def zeros(m):
        return np.zeros((m, blocks, n), dtype=np.int8)

    # preservation: images of the X- and Z-check rows on every block
    perrs = []
    for b in range(blocks):
        SX, SZ = zeros(len(HX)), zeros(len(HX))
        SX[:, b] = HX
        if not in_group(*_image(gate, pinv, p, SX, SZ, blocks)):
            perrs.append(f"gates[{idx}] ({gate}) maps an X check"
                         f"{' of block ' + str(b) if blocks > 1 else ''} "
                         f"outside the stabilizer group")
        SX, SZ = zeros(len(HZ)), zeros(len(HZ))
        SZ[:, b] = HZ
        if not in_group(*_image(gate, pinv, p, SX, SZ, blocks)):
            perrs.append(f"gates[{idx}] ({gate}) maps a Z check"
                         f"{' of block ' + str(b) if blocks > 1 else ''} "
                         f"outside the stabilizer group")
    if gate == "S":
        odd = [int(i) for i in np.flatnonzero(HX.sum(axis=1) % 4)]
        if odd:
            perrs.append(f"gates[{idx}] (S): X checks {odd[:4]} have weight "
                         f"not 0 mod 4, so S on every qubit sends them to "
                         f"minus a stabilizer (phase the GF(2) image cannot "
                         f"see)")

    # action: image of each logical generator against the claim
    labels = _generator_labels(k, blocks)
    claim = g["logical_action"]
    aerrs = []
    unknown = [lab for lab in claim if _parse_label(lab, k, blocks) is None]
    if unknown:
        aerrs.append(f"gates[{idx}].logical_action names generators "
                     f"{unknown[:4]} this code does not have (k={k}, "
                     f"{'primed labels need a CX' if blocks == 1 else ''})")
    for lab, prod in claim.items():
        bad = [t for t in prod if _parse_label(t, k, blocks) is None]
        if bad:
            aerrs.append(f"gates[{idx}].logical_action[{lab}] names unknown "
                         f"generators {bad[:4]}")
        if len(set(prod)) != len(prod):
            aerrs.append(f"gates[{idx}].logical_action[{lab}] repeats a "
                         f"generator; list each factor once")
    if aerrs:
        return perrs, aerrs, computed

    def vec(lab):
        pauli, i, b = _parse_label(lab, k, blocks)
        X, Z = zeros(1), zeros(1)
        (X if pauli == "X" else Z)[0, b] = (LX if pauli == "X" else LZ)[i]
        return X, Z

    action = {}
    wrong = []
    for lab in labels:
        prod = list(claim.get(lab, [lab]))
        X, Z = vec(lab)
        IX, IZ = _image(gate, pinv, p, X, Z, blocks)
        for t in prod:
            TX, TZ = vec(t)
            IX ^= TX
            IZ ^= TZ
        if not in_group(IX, IZ):
            wrong.append(lab)
        action[lab] = sorted(prod, key=lambda t: (t.endswith("'"), t[0],
                                                  int(t.rstrip("'")[1:])))
    if wrong:
        aerrs.append(f"gates[{idx}] ({gate}) does not induce the claimed "
                     f"action on {wrong[:4]}: image differs from the claim "
                     f"by more than a stabilizer")
    elif all(action[lab] == [lab] for lab in labels):
        aerrs.append(f"gates[{idx}] ({gate}) acts trivially on every "
                     f"logical operator: a code automorphism, not a logical "
                     f"gate")
    computed["action"] = action
    computed["verified"] = not perrs and not aerrs
    return perrs, aerrs, computed


def verify_gates(doc, HX, HZ):
    """Check every claim in doc['circuit']['gates'] against the code's
    check matrices. Returns (checks, computed): `checks` is a list of
    (label, ok, detail) in the verifier's record() shape, `computed` the
    per-gate dicts for the report's computed block (gate, blocks, name,
    permutation_trivial, action, verified). Returns ([], None) when the
    submission declares no gates."""
    cb = doc.get("circuit") or {}
    gates = cb.get("gates")
    if not gates:
        return [], None
    n, k = doc["n"], doc["k"]
    red_x, red_z = _Reducer(HX), _Reducer(HZ)
    checks = []
    computed = []
    logicals = cb.get("logicals")
    if logicals is None:
        checks.append(("transversal_logicals_valid", False,
                       "circuit.gates needs circuit.logicals, the symplectic "
                       "logical basis the claims are written in"))
        return checks, computed
    berrs, LX, LZ = _basis_errors(logicals, n, k, HX, HZ)
    checks.append(("transversal_logicals_valid", not berrs,
                   "; ".join(berrs[:4]) or
                   f"k={k} X and Z logical representatives with identity "
                   f"pairing over GF(2)"))
    if berrs:
        return checks, computed
    for idx, g in enumerate(gates):
        perrs, aerrs, comp = _gate_errors(g, idx, n, k, HX, HZ, LX, LZ,
                                          red_x, red_z)
        computed.append(comp)
        what = comp["gate"]
        if comp["blocks"] == 2:
            what += " between two blocks"
        if not comp.get("permutation_trivial", True):
            what += " with a qubit permutation"
        checks.append((f"gate_{idx}_preserves_stabilizers", not perrs,
                       "; ".join(perrs[:4]) or
                       f"{what}: every stabilizer generator maps into the "
                       f"stabilizer group"))
        checks.append((f"gate_{idx}_logical_action", not aerrs,
                       "; ".join(aerrs[:4]) or
                       "induced action on the logical generators matches "
                       "the claim modulo stabilizers: "
                       + ", ".join(f"{a} -> {' '.join(b)}"
                                   for a, b in comp["action"].items()
                                   if b != [a])))
    return checks, computed
