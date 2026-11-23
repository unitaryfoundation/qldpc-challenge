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

Stage 2 (issue #2894) adds the `match` type: a W <= 2 diagonal layer, S on a
subset `support` of the qubits together with CZ on a disjoint `pairs`
matching (clifford "S"), or its Hadamard mirror, SHS on the subset with
CZ# = (H x H) CZ (H x H) on the matching (clifford "SHS"). The S family is
Z-diagonal and fixes every Z check exactly; the SHS family is X-diagonal
and fixes every X check. On the other side the GF(2) image of a check row
a is a itself plus a Z-part (a AND 1_support) XOR (P a), with P the
adjacency matrix of the matching, and that part must lie in the opposite
row space. The phase the GF(2) image cannot see has two sources: S sends
X_q to i X_q Z_q, one factor of i per supported qubit of a, and CZ sends
X_i X_j on a matched pair inside a to X_i Z_j X_j Z_i = -X_i X_j Z_i Z_j,
one factor of -1 per pair inside a. The image is +1 times a stabilizer iff

    |a AND support| + 2 #{(i, j) in pairs : a_i = a_j = 1}  ==  0  (mod 4),

which reduces to the uniform-S rule |a| == 0 (mod 4) when the support is
every qubit and there are no pairs. SHS sends Z_q to i X_q Z_q and CZ#
sends Z_i Z_j to -X_i X_j Z_i Z_j, so the SHS rule is the same count on the
Z-check rows; HSH, which sends Z_q to -i X_q Z_q, satisfies the same
congruence because 2p == -2p (mod 4). Checked against dense conjugation on
[[4,2,2]], the weight-6 [[6,4,2]] test code, and the Steane code (every
support, every matching) in test_transversal_gates.py.

`computed["action"]` in the report is the claim as the verifier accepted
it (sorted), not an independent recomputation: it is only populated when
the induced action matched the claim modulo stabilizers, so it is safe to
display and useless as an oracle for filling in a claim.
"""

import re

import gf2
import numpy as np

GATES = ("permutation", "H", "S", "CX", "match")
MATCH_CLIFFORDS = ("S", "SHS")
_LABEL = re.compile(r"^([XZ])([0-9]+)('?)$")


class _Reducer:
    """Reduce vectors modulo the GF(2) row space of one matrix, with the RREF
    computed once (gf2.in_rowspace re-echelonizes per call, which is fine for
    two witnesses and too slow for every check row of a large code).
    """

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
    rowspace(H_X) would commute with every Z_j).
    """
    errs = []
    for side in ("X", "Z"):
        rows = logicals[side]
        if len(rows) != k:
            errs.append(f"logicals.{side} has {len(rows)} operators; the code has k={k}")
        for i, sup in enumerate(rows):
            if len(set(sup)) != len(sup) or (sup and max(sup) >= n):
                errs.append(f"logicals.{side}[{i}] must list distinct qubit indices below n={n}")
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
        errs.append(
            "logicals are not a symplectic basis: X_i and Z_j must "
            "anticommute exactly when i = j (pairing matrix is not "
            "the identity)"
        )
    return errs, LX, LZ


def _parse_label(label, k, blocks):
    """(pauli, index, block) for a generator label, or None if it names no
    generator of this claim (index out of range, or a primed label on a
    single-block gate).
    """
    m = _LABEL.match(label)
    if not m:
        return None
    pauli, idx, prime = m.group(1), int(m.group(2)), m.group(3) == "'"
    if idx >= k or (prime and blocks == 1):
        return None
    return pauli, idx, int(prime)


def _generator_labels(k, blocks):
    return [f"{p}{i}{prime}" for prime in ([""] if blocks == 1 else ["", "'"]) for p in ("X", "Z") for i in range(k)]


def _image(gate, pinv, p, X, Z, blocks, match=None):
    """Symplectic image of the operators whose x- and z-parts are the rows of
    X and Z, each of shape (m, blocks, n). Qubit i is sent to p[i], so a
    support vector v becomes v[pinv] (v'[p[i]] = v[i]); the Clifford acts
    after the permutation, and being uniform it commutes with it anyway.
    For `match`, `match` is (clifford, indicator, P): S on the indicated
    qubits and CZ on the matching P send X^x to X^x Z^{(x & ind) ^ P x};
    SHS and CZ# send Z^z to X^{(z & ind) ^ P z} Z^z (no permutation).
    """
    if gate == "match":
        clifford, ind, P = match
        if clifford == "S":
            extra = ((X[:, 0] & ind) ^ ((X[:, 0] @ P) % 2)).astype(np.int8)
            Z2 = Z.copy()
            Z2[:, 0] ^= extra
            return X, Z2
        extra = ((Z[:, 0] & ind) ^ ((Z[:, 0] @ P) % 2)).astype(np.int8)
        X2 = X.copy()
        X2[:, 0] ^= extra
        return X2, Z
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


def _match_errors(g, idx, n):
    """([errors], (clifford, indicator, P)) for a `match` claim: the
    clifford names the family, `support` lists distinct qubits below n, and
    `pairs` is a matching (distinct endpoints, no qubit in two pairs, every
    endpoint below n). The matching condition is what makes the layer
    W <= 2 and what the phase count assumes.
    """
    errs = []
    clifford = g.get("clifford")
    if clifford not in MATCH_CLIFFORDS:
        errs.append(f"gates[{idx}].clifford must be one of {list(MATCH_CLIFFORDS)}")
    support = g.get("support")
    pairs = g.get("pairs")
    if not isinstance(support, list) or not isinstance(pairs, list):
        errs.append(f"gates[{idx}] (match) needs `support` and `pairs` lists")
        return errs, None
    if len(set(support)) != len(support) or any(not isinstance(q, int) or q < 0 or q >= n for q in support):
        errs.append(f"gates[{idx}].support must list distinct qubit indices below n={n}")
    seen = set()
    for pr in pairs:
        if not isinstance(pr, list) or len(pr) != 2 or any(not isinstance(q, int) or q < 0 or q >= n for q in pr):
            errs.append(f"gates[{idx}].pairs entries must be two distinct qubit indices below n={n}")
            break
        i, j = pr
        if i == j or i in seen or j in seen:
            errs.append(
                f"gates[{idx}].pairs is not a matching: qubit "
                f"{i if (i == j or i in seen) else j} appears in two "
                f"pairs or is paired with itself"
            )
            break
        seen.update(pr)
    if not support and not pairs:
        errs.append(f"gates[{idx}] (match) has an empty support and no pairs: the identity")
    if errs:
        return errs, None
    ind = np.zeros(n, dtype=np.int8)
    ind[support] = 1
    P = np.zeros((n, n), dtype=np.int8)
    for i, j in pairs:
        P[i, j] = P[j, i] = 1
    return [], (clifford, ind, P)


def _gate_errors(g, idx, n, k, HX, HZ, LX, LZ, red_x, red_z):
    """([preservation errors], [action errors], computed) for one claim."""
    gate = g["gate"]
    blocks = 2 if gate == "CX" else 1
    computed = {"gate": gate, "blocks": blocks, "name": g.get("name"), "verified": False, "action": {}}
    p = g.get("permutation")
    match = None
    if gate == "match":
        merrs, match = _match_errors(g, idx, n)
        if merrs:
            return merrs, [], computed
        computed["clifford"] = match[0]
        computed["support_size"] = int(match[1].sum())
        computed["pairs"] = int(match[2].sum() // 2)
        if p is not None:
            return (
                [f"gates[{idx}] (match) does not take a permutation; file the permutation as its own gate"],
                [],
                computed,
            )
    if p is None:
        p = list(range(n))
    if sorted(p) != list(range(n)):
        return ([f"gates[{idx}].permutation is not a permutation of 0..{n - 1}"], [], computed)
    p = np.asarray(p, dtype=np.int64)
    pinv = np.empty_like(p)
    pinv[p] = np.arange(n)
    computed["permutation_trivial"] = bool(np.array_equal(p, np.arange(n)))

    def in_group(X, Z):
        """Do the operators (X, Z), shape (m, blocks, n), all lie in the
        stabilizer group of `blocks` copies of the code?
        """
        return all(red_x.contains_rows(X[:, b]) and red_z.contains_rows(Z[:, b]) for b in range(blocks))

    def zeros(m):
        return np.zeros((m, blocks, n), dtype=np.int8)

    # preservation: images of the X- and Z-check rows on every block
    perrs = []
    for b in range(blocks):
        SX, SZ = zeros(len(HX)), zeros(len(HX))
        SX[:, b] = HX
        if not in_group(*_image(gate, pinv, p, SX, SZ, blocks, match)):
            perrs.append(
                f"gates[{idx}] ({gate}) maps an X check"
                f"{' of block ' + str(b) if blocks > 1 else ''} "
                f"outside the stabilizer group"
            )
        SX, SZ = zeros(len(HZ)), zeros(len(HZ))
        SZ[:, b] = HZ
        if not in_group(*_image(gate, pinv, p, SX, SZ, blocks, match)):
            perrs.append(
                f"gates[{idx}] ({gate}) maps a Z check"
                f"{' of block ' + str(b) if blocks > 1 else ''} "
                f"outside the stabilizer group"
            )
    if gate == "S":
        odd = [int(i) for i in np.flatnonzero(HX.sum(axis=1) % 4)]
        if odd:
            perrs.append(
                f"gates[{idx}] (S): X checks {odd[:4]} have weight "
                f"not 0 mod 4, so S on every qubit sends them to "
                f"minus a stabilizer (phase the GF(2) image cannot "
                f"see)"
            )
    if gate == "match":
        clifford, ind, P = match
        rows, side = (HX, "X") if clifford == "S" else (HZ, "Z")
        # phase of the image of each check row on the side the layer does
        # not fix: i^{|a & support|} from the single-qubit gates, (-1) per
        # matched pair inside the row from the entangler (module docstring)
        inside = ((rows @ P) * rows).sum(axis=1) // 2
        count = (rows & ind).sum(axis=1) + 2 * inside
        bad = [int(i) for i in np.flatnonzero(count % 4)]
        if bad:
            perrs.append(
                f"gates[{idx}] (match, {clifford}): {side} checks "
                f"{bad[:4]} pick up a phase of i^k with k = "
                f"|check & support| + 2 (matched pairs inside the "
                f"check) not 0 mod 4, so the layer sends them to a "
                f"stabilizer times -1 or +-i and leaves the code "
                f"space (phase the GF(2) image cannot see)"
            )

    # action: image of each logical generator against the claim
    labels = _generator_labels(k, blocks)
    claim = g["logical_action"]
    aerrs = []
    unknown = [lab for lab in claim if _parse_label(lab, k, blocks) is None]
    if unknown:
        aerrs.append(
            f"gates[{idx}].logical_action names generators "
            f"{unknown[:4]} this code does not have (k={k}, "
            f"{'primed labels need a CX' if blocks == 1 else ''})"
        )
    for lab, prod in claim.items():
        bad = [t for t in prod if _parse_label(t, k, blocks) is None]
        if bad:
            aerrs.append(f"gates[{idx}].logical_action[{lab}] names unknown generators {bad[:4]}")
        if len(set(prod)) != len(prod):
            aerrs.append(f"gates[{idx}].logical_action[{lab}] repeats a generator; list each factor once")
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
        IX, IZ = _image(gate, pinv, p, X, Z, blocks, match)
        for t in prod:
            TX, TZ = vec(t)
            IX ^= TX
            IZ ^= TZ
        if not in_group(IX, IZ):
            wrong.append(lab)
        action[lab] = sorted(prod, key=lambda t: (t.endswith("'"), t[0], int(t.rstrip("'")[1:])))
    if wrong:
        aerrs.append(
            f"gates[{idx}] ({gate}) does not induce the claimed "
            f"action on {wrong[:4]}: image differs from the claim "
            f"by more than a stabilizer"
        )
    elif all(action[lab] == [lab] for lab in labels):
        aerrs.append(
            f"gates[{idx}] ({gate}) acts trivially on every logical operator: a code automorphism, not a logical gate"
        )
    computed["action"] = action
    computed["verified"] = not perrs and not aerrs
    return perrs, aerrs, computed


def verify_gates(doc, HX, HZ):
    """Check every claim in doc['circuit']['gates'] against the code's
    check matrices. Returns (checks, computed): `checks` is a list of
    (label, ok, detail) in the verifier's record() shape, `computed` the
    per-gate dicts for the report's computed block (gate, blocks, name,
    permutation_trivial, action, verified). Returns ([], None) when the
    submission declares no gates.
    """
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
        checks.append(
            (
                "transversal_logicals_valid",
                False,
                "circuit.gates needs circuit.logicals, the symplectic logical basis the claims are written in",
            )
        )
        return checks, computed
    berrs, LX, LZ = _basis_errors(logicals, n, k, HX, HZ)
    checks.append(
        (
            "transversal_logicals_valid",
            not berrs,
            "; ".join(berrs[:4]) or f"k={k} X and Z logical representatives with identity pairing over GF(2)",
        )
    )
    if berrs:
        return checks, computed
    for idx, g in enumerate(gates):
        perrs, aerrs, comp = _gate_errors(g, idx, n, k, HX, HZ, LX, LZ, red_x, red_z)
        computed.append(comp)
        what = comp["gate"]
        if comp["gate"] == "match" and "clifford" in comp:
            what = (
                f"{comp['clifford']} on {comp['support_size']} qubits "
                f"with {'CZ' if comp['clifford'] == 'S' else 'CZ#'} on "
                f"{comp['pairs']} pairs"
            )
        if comp["blocks"] == 2:
            what += " between two blocks"
        if not comp.get("permutation_trivial", True):
            what += " with a qubit permutation"
        checks.append(
            (
                f"gate_{idx}_preserves_stabilizers",
                not perrs,
                "; ".join(perrs[:4]) or f"{what}: every stabilizer generator maps into the stabilizer group",
            )
        )
        checks.append(
            (
                f"gate_{idx}_logical_action",
                not aerrs,
                "; ".join(aerrs[:4])
                or "induced action on the logical generators matches the claim modulo stabilizers: "
                + ", ".join(f"{a} -> {' '.join(b)}" for a, b in comp["action"].items() if b != [a]),
            )
        )
    return checks, computed
