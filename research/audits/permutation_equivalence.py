#!/usr/bin/env python3
"""Check that two board entries are the same code up to a qubit permutation.

A WL-signature collision only flags a possible duplicate (issue #1650). This
settles the question for a pair when someone has exhibited the permutation: it
applies the permutation to the first entry's check matrices and tests that the
X and Z row spaces land exactly on the second entry's. Row-space equality is
the board's notion of "the same code": the stabilizer group, not the
particular generating set, so two files that differ by row operations and a
relabelling of qubits are one code.

Entries are read from git by blob hash rather than from codes/, so a record
stays checkable after the duplicate it names has been removed from the board,
and the citation cannot drift when a file is edited (issue #2643 cited a blob
that a later layout addition superseded; the matrices had not changed, but a
hash pins exactly what was checked). A negative control runs on every pair:
the same permutation with one transposition composed in must fail, which it
does unless the code has a nontrivial automorphism swapping those two qubits,
in which case the control is skipped and said so.

    uv run python research/audits/permutation_equivalence.py              # every pair in the ledger
    uv run python research/audits/permutation_equivalence.py A.json B.json --perm "[1,0,...]"
"""

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
LEDGER = os.path.join(HERE, "permutation_equivalences.json")


def rows_as_ints(checks):
    return [sum(1 << i for i in r) for r in checks]


def rank(vectors):
    basis = {}
    for v in vectors:
        x = v
        while x:
            k = x.bit_length() - 1
            if k in basis:
                x ^= basis[k]
            else:
                basis[k] = x
                break
    return len(basis)


def same_row_space(a, b):
    ra, rb = rank(a), rank(b)
    return ra == rb == rank(a + b), (ra, rb, rank(a + b))


def permute(vectors, perm):
    out = []
    for x in vectors:
        y = 0
        for i, j in enumerate(perm):
            if (x >> i) & 1:
                y |= 1 << j
        out.append(y)
    return out


def check_pair(a, b, perm, swap=False):
    """(verdict, {'X': (rank A, rank B, rank stacked), 'Z': ...}) for A -> B under perm."""
    n = a["n"]
    if not (len(perm) == n == b["n"] and sorted(perm) == list(range(n))):
        return False, {"error": "permutation is not a bijection on the qubits"}
    sides = {"X": "X", "Z": "Z"} if not swap else {"X": "Z", "Z": "X"}
    detail, ok = {}, True
    for sa, sb in sides.items():
        same, triple = same_row_space(permute(rows_as_ints(a["checks"][sa]), perm), rows_as_ints(b["checks"][sb]))
        detail[sa] = triple
        ok = ok and same
    return ok, detail


def negative_control(a, b, perm):
    """Compose one transposition into the permutation and require it to fail.

    Returns True when the control fails as it should, False when the perturbed
    permutation also maps the code onto itself (an automorphism), None when
    the code has fewer than two qubits.
    """
    if len(perm) < 2:
        return None
    for i in range(len(perm) - 1):
        p = list(perm)
        p[i], p[i + 1] = p[i + 1], p[i]
        ok, _ = check_pair(a, b, p)
        if not ok:
            return True
    return False


def load_blob(sha):
    out = subprocess.check_output(["git", "cat-file", "-p", sha], cwd=ROOT)
    return json.loads(out)


def load_path(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run_ledger(ledger=LEDGER, quiet=False):
    rec = load_path(ledger)
    failures = 0
    for p in rec["pairs"]:
        a, b = load_blob(p["first_blob"]), load_blob(p["second_blob"])
        ok, detail = check_pair(a, b, p["permutation"])
        ctrl = negative_control(a, b, p["permutation"]) if ok else None
        failures += 0 if ok else 1
        if not quiet:
            tag = "EQUIVALENT" if ok else "NOT EQUIVALENT"
            ctrl_s = {
                True: "control rejects a perturbed permutation",
                False: "control skipped: the perturbation is an automorphism",
                None: "",
            }[ctrl]
            print(f"{tag}  {p['first']} -> {p['second']}  X {detail.get('X')}  Z {detail.get('Z')}  {ctrl_s}")
    return failures


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="*", help="two code files; omit to check the ledger")
    ap.add_argument("--perm", help="JSON list, qubit i of the first file is qubit perm[i] of the second")
    ap.add_argument(
        "--swap", action="store_true", help="compare X rows of the first against Z rows of the second and vice versa"
    )
    args = ap.parse_args(argv)
    if not args.files:
        return 1 if run_ledger() else 0
    if len(args.files) != 2 or not args.perm:
        ap.error("give two files and --perm")
    a, b = load_path(args.files[0]), load_path(args.files[1])
    ok, detail = check_pair(a, b, json.loads(args.perm), swap=args.swap)
    print(("EQUIVALENT" if ok else "NOT EQUIVALENT"), detail)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
