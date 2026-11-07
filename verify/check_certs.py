#!/usr/bin/env python3
"""Validate certs/ against schema/cert.schema.json, and refuse an unearned level.

A `certs/<slug>.json` with `d_exact: true` upgrades a board entry from a
witnessed upper bound to an exact distance, so it is the strongest thing the
board asserts and, until #2511, the least checkable. The upper bound ships an
explicit logical operator anyone can re-verify in seconds. The lower bound
shipped a solver's verdict and a sentence.

`verification.level` records how much that verdict is worth:

    solver     a solver said UNSAT or optimal. No artifact a third party can
               check without re-running our encoding.
    proof_log  a machine-checkable refutation artifact accompanies the run.
    formal     a machine-checked proof of the distance statement, with the
               reduction verified too.

The distinction between the last two is the load-bearing one and is easy to
blur. A DRAT proof establishes that the CNF we handed the solver is
unsatisfiable; it says nothing about whether that CNF asks the distance
question. #2273 is exactly that failure: the CNF was fine and it asked the
wrong thing, because the pairing set spanned the wrong space. Only `formal`
closes that, because the reduction is part of what is proved.

So this checker enforces the one rule that keeps the tier honest: a
certificate may not claim a level it carries no evidence for. Claiming
`proof_log` or `formal` requires an artifact that exists and a checker that
produced it.

A certificate with `d_exact: false` is a partial certificate (issue #4230):
it proves `d >= d_lower`, the bound an ascending ladder of UNSAT verdicts
reached below the claim, and the board shows the entry as an interval. The
second rule is that the bound is backed and consistent: `d_lower` is the
minimum of the sides' `proved_min`, each `proved_min` is one above the top
UNSAT rung of that side's ladder, the certificate is bound to the entry's
matrices by `checks_sha256` (so a correction of the claim cannot strand it),
and the entry's witnessed distance is not below it. That last one is the
free consistency check the issue asked for: a verified witness lighter than
a proven bound means the witness verifier or the certificate is wrong, and
it fails here rather than waiting for a reader to notice. A stabilizer
entry's partial certificate has the single Pauli-weight side `P` instead of
`X` and `Z`, and its binding hash names the generator presentation
(`checks.S`), since the tropidist backend is the only certifier it has
(issue #4718).

    python verify/check_certs.py            # validate every certificate
    python verify/check_certs.py --level    # print the level mix
"""
import argparse
import glob
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCHEMA = os.path.join(ROOT, "schema", "cert.schema.json")
LEVELS = ("solver", "proof_log", "formal")


def load_schema():
    with open(SCHEMA, encoding="utf-8") as f:
        return json.load(f)


def _inside_tree(art):
    """True when `art` is a file inside the repository.

    os.path.join discards the root when the second argument is absolute, and
    `..` walks out of it, so joining and calling os.path.exists accepts
    "/etc/hosts" and "certs/../verify/check_certs.py". This is the field whose
    entire job is pointing at committed evidence, so it is resolved and
    required to land under ROOT, and to be a file rather than a directory.
    """
    if os.path.isabs(art):
        return False
    # "certs/../verify/x.py" resolves in-tree and is still wrong to store: the
    # recorded path should name where the evidence is, so a reader can find it
    # without normalising it first.
    if os.path.normpath(art) != art.rstrip("/"):
        return False
    full = os.path.realpath(os.path.join(ROOT, art))
    root = os.path.realpath(ROOT)
    if os.path.commonpath([full, root]) != root:
        return False
    return os.path.isfile(full)


def checks_sha256(doc):
    """Return the hash that binds a formal or partial certificate to one code.

    sha256 over the compact JSON of {"X": rows, "Z": rows} with every row's
    support sorted and the rows of each side sorted, so the hash names the
    stabilizer presentation (the set of check rows on the labeled qubits)
    and nothing about file formatting or row order. A formal proof is about
    a matrix pair defined inside a proof development; this is what ties
    that pair to codes/<slug>.json, and a certificate whose hash is not this
    entry's is a proof about some other code. A stabilizer entry (checks.S,
    one X and Z support per generator) hashes {"S": rows} with each
    generator's two supports sorted and the generators sorted (issue #4718);
    the CSS form is unchanged, so every committed hash still matches.
    """
    checks = doc["checks"]
    if "S" in checks and "X" not in checks:
        canon = {"S": sorted([sorted(int(q) for q in row.get("X", [])),
                              sorted(int(q) for q in row.get("Z", []))]
                             for row in checks["S"])}
    else:
        canon = {side: sorted(sorted(int(q) for q in row)
                              for row in checks[side])
                 for side in ("X", "Z")}
    blob = json.dumps(canon, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(blob.encode("ascii")).hexdigest()


def _code_doc(slug):
    """Return the board entry this certificate is about, or None."""
    path = os.path.join(ROOT, "codes", f"{slug}.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def evidence_problems(slug, cert):
    """Rules a schema cannot state: the evidence has to be reachable."""
    out = []
    v = cert.get("verification") or {}
    level = v.get("level")
    if level not in LEVELS:
        return [f"{slug}: verification.level {level!r} is not one of {LEVELS}"]
    if level == "solver":
        # The rule is "no evidence you cannot point at", so it has to cover
        # every field that asserts one. A checker or a reference on a bare
        # solver verdict claims a check that did not happen.
        for field in ("artifact", "checker", "reference"):
            if v.get(field):
                out.append(f"{slug}: level 'solver' names a {field}; if "
                           "something was checked, claim the level it earns")
        return out
    # A stronger level needs evidence a third party can act on. That can be
    # a file in the tree, or it can be the instance plus the recipe that
    # re-derives the check, which is what the proof tiers actually ship: a
    # refutation of a formula regenerated from the entry, and a theorem in
    # a development. A committed blob nobody opens is not better evidence
    # than a command anyone can run, and for these proofs it is 95.8 MB of
    # it, so the rule is "point at something checkable", not "attach a
    # file".
    art = v.get("artifact")
    replay = v.get("replay")
    if art and not _inside_tree(art):
        out.append(f"{slug}: level {level!r} names {art}, which is not a file "
                   "committed in this tree")
    if not art and not replay:
        out.append(f"{slug}: level {level!r} with neither an artifact in the "
                   "tree nor a replay recipe; one of the two has to be there "
                   "or the level claims a check nobody can repeat")
    if not v.get("checker"):
        out.append(f"{slug}: level {level!r} with no checker recorded")
    if level == "proof_log" and not art and not v.get("cnf_sha256"):
        out.append(f"{slug}: level 'proof_log' replayed rather than stored "
                   "needs cnf_sha256, since a regenerated formula that is "
                   "not the one that was refuted proves nothing about this "
                   "entry")
    if level == "formal":
        # The binding is checked, not just present. The theorem is about a
        # matrix pair inside the development; the hash says it is this
        # entry's pair, and a stale or copied hash is the #2273-shaped bug
        # this tier can still have.
        want = v.get("checks_sha256")
        doc = _code_doc(slug)
        if doc is None:
            out.append(f"{slug}: level 'formal' but codes/{slug}.json is not "
                       "on the board, so there is nothing for the proof to "
                       "be about")
        elif want != checks_sha256(doc):
            out.append(f"{slug}: level 'formal' checks_sha256 does not match "
                       f"codes/{slug}.json (recorded {str(want)[:16]}, the "
                       f"entry hashes to {checks_sha256(doc)[:16]}); the "
                       "theorem is bound to some other matrix pair")
    return out


def _top_unsat(ladder):
    """Return 1 + the largest W with an UNSAT verdict in a ladder, or 1."""
    tops = [int(r["W"]) for r in ladder if r.get("status") == "UNSAT"]
    return 1 + max(tops) if tops else 1


def bound_problems(slug, cert):
    """Rules for d_lower and the per-side bounds (issue #4230).

    An exact certificate may carry ``d_lower`` only as ``d``. A partial one
    (``d_exact`` false) must carry it, between 2 and ``d - 1``: proving
    ``d >= 1`` proves nothing and is not filed, and ``d_lower == d`` is what
    ``d_exact`` means. Each side's ``proved_min`` must be what its ladder
    says, ``d_lower`` must be the minimum over sides, a SAT rung is a
    refutation and not a certificate, the binding hash must be this entry's,
    and the entry's witnessed distances may not sit below the proven bounds.
    The sides are X and Z for a CSS entry and the single Pauli-weight side P
    for a stabilizer one (issue #4718).
    """
    out = []
    d = cert.get("d")
    d_lower = cert.get("d_lower")
    exact = bool(cert.get("d_exact"))
    sides = cert.get("sides") or {}
    if not isinstance(d, int):
        return out
    doc = _code_doc(slug)
    stab = doc is not None and doc.get("code_type") == "stabilizer"
    if exact:
        if d_lower is not None and d_lower != d:
            out.append(f"{slug}: d_exact with d_lower {d_lower} != d {d}; an exact "
                       "certificate's lower bound is its distance")
        for side, blk in sides.items():
            pm = (blk or {}).get("proved_min")
            if pm is not None and pm != d:
                out.append(f"{slug}: {side} side is exact but proved_min is {pm}, not {d}")
    else:
        if d_lower is None:
            return out                      # the schema already reports it
        if d_lower < 2:
            out.append(f"{slug}: partial certificate with d_lower {d_lower}; d >= 1 "
                       "proves nothing and is not a certificate")
        if d_lower >= d:
            out.append(f"{slug}: partial certificate with d_lower {d_lower} >= d {d}; "
                       "a bound that reaches the claim is d_exact, and one above it "
                       "contradicts the verified witness")
        if stab and set(sides) != {"P"}:
            out.append(f"{slug}: partial certificate on a stabilizer entry needs the Pauli "
                       f"side P, has {sorted(sides)}; a CSS side bounds nothing there")
        elif not stab and set(sides) != {"X", "Z"}:
            out.append(f"{slug}: partial certificate needs both sides, has "
                       f"{sorted(sides)}; a bound on one side bounds nothing")
        mins = []
        for side, blk in sides.items():
            blk = blk or {}
            pm = blk.get("proved_min")
            if pm is None:
                out.append(f"{slug}: {side} side of a partial certificate has no proved_min")
                continue
            mins.append(pm)
            if blk.get("exact") and pm != d:
                out.append(f"{slug}: {side} side is exact but proved_min is {pm}, not {d}")
            if blk.get("status") == "SAT":
                out.append(f"{slug}: {side} side is SAT; a logical lighter than the claim "
                           "is a refutation, not a certificate")
            ladder = blk.get("ladder")
            if ladder is not None:
                if any(r.get("status") == "SAT" for r in ladder):
                    out.append(f"{slug}: {side} side ladder has a SAT rung; a logical "
                               "lighter than the claim is a refutation, not a certificate")
                want = _top_unsat(ladder)
                if pm != want:
                    out.append(f"{slug}: {side} side proved_min {pm} is not backed by its "
                               f"ladder, whose top UNSAT rung gives {want}")
        if mins and min(mins) != d_lower:
            out.append(f"{slug}: d_lower {d_lower} is not the minimum of the sides' "
                       f"proved_min {sorted(mins)}")
        v = cert.get("verification") or {}
        want = v.get("checks_sha256")
        if doc is None:
            out.append(f"{slug}: partial certificate but codes/{slug}.json is not on the "
                       "board, so there is nothing for the bound to be about")
        else:
            if want and want != checks_sha256(doc):
                out.append(f"{slug}: partial certificate checks_sha256 does not match "
                           f"codes/{slug}.json (recorded {str(want)[:16]}, the entry "
                           f"hashes to {checks_sha256(doc)[:16]}); the bound is about "
                           "some other matrix pair")
            dist = doc.get("distance") or {}
            if isinstance(dist.get("d"), int) and dist["d"] < d_lower:
                out.append(f"{slug}: the entry's verified witness gives d <= {dist['d']} "
                           f"but the certificate proves d >= {d_lower}; the witness "
                           "verifier or the certificate is wrong (issue #4230)")
            for side, blk in sides.items():
                pm = (blk or {}).get("proved_min")
                sv = (dist.get(side) or {}).get("value") if isinstance(dist.get(side), dict) else None
                if isinstance(pm, int) and isinstance(sv, int) and sv < pm:
                    out.append(f"{slug}: the entry's {side} witness gives d_{side} <= {sv} "
                               f"but the certificate proves d_{side} >= {pm}; the "
                               "witness verifier or the certificate is wrong (issue #4230)")
    return out


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--level", action="store_true",
                    help="print the level mix and exit")
    ap.add_argument("--checks-sha256", metavar="SLUG",
                    help="print the binding hash of codes/<SLUG>.json for a "
                         "formal certificate and exit")
    a = ap.parse_args(argv)
    if a.checks_sha256:
        doc = _code_doc(a.checks_sha256)
        if doc is None:
            print(f"codes/{a.checks_sha256}.json not found")
            return 2
        print(checks_sha256(doc))
        return 0

    # Non-recursively, on purpose. certs/heuristic/ holds a different artifact
    # entirely (claimed_d / verdict / methods / seed) that this schema does not
    # describe and should not be made to; making the glob recursive would fail
    # all six wholesale. Heuristic evidence is also the weakest thing under
    # certs/ and has no level in the enum yet, which is its own question.
    certs = sorted(glob.glob(os.path.join(ROOT, "certs", "*.json")))
    if not certs:
        print("no certificates found")
        return 0

    try:
        import jsonschema
        validator = jsonschema.Draft202012Validator(load_schema())
    except ImportError:                       # pragma: no cover
        validator = None
        print("note: jsonschema unavailable; structural check skipped, "
              "evidence rules still enforced")

    problems, mix, partial = [], dict.fromkeys(LEVELS, 0), 0
    for path in certs:
        slug = os.path.splitext(os.path.basename(path))[0]
        with open(path, encoding="utf-8") as f:
            cert = json.load(f)
        if validator is not None:
            for e in sorted(validator.iter_errors(cert), key=lambda e: e.path):
                where = "/".join(str(p) for p in e.absolute_path) or "(root)"
                problems.append(f"{slug}: {where}: {e.message}")
        problems.extend(evidence_problems(slug, cert))
        problems.extend(bound_problems(slug, cert))
        lv = (cert.get("verification") or {}).get("level")
        if lv in mix:
            mix[lv] += 1
        if not cert.get("d_exact"):
            partial += 1

    if a.level:
        print(f"{len(certs)} certificates")
        for lv in LEVELS:
            print(f"  {mix[lv]:>4}  {lv}")
        print(f"  {partial:>4}  partial (d_exact false, d_lower < d)")
        return 0

    if problems:
        print(f"certificate problems ({len(problems)}):")
        for p in problems[:40]:
            print("  " + p)
        if len(problems) > 40:
            print(f"  ... and {len(problems) - 40} more")
        return 1
    print(f"ok: {len(certs)} certificates valid "
          + ", ".join(f"{mix[lv]} {lv}" for lv in LEVELS)
          + (f"; {partial} partial" if partial else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
