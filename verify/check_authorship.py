"""Bind a submission to the person opening the PR.

Author handles in a code's provenance are self-reported, so without a check
anyone could submit a code under someone else's @handle. This asserts that the
GitHub user opening the PR is listed among the @handle authors of every code
they add or change. Literature baselines (no @handle authors) are exempt, and a
maintainer submitting on someone's behalf just adds themselves as a co-author.

Refutation binding (issue #611): a PR author who is NOT an author of a code may
still tighten its distance claim, provided the change is exactly a refutation
and nothing else. The alternative binding holds when every difference from the
base version is confined to the distance block (plus the name string and an
append to provenance.notes), every witness_provenance the PR adds lists the PR
author in found_by, and at least one side's value strictly decreases. Together
these mean the path can only ever be used to tighten a claim, never to alter a
construction or its authorship -- the witness itself is machine-verified by the
distance checks, so a bogus claim cannot pass regardless.

Relatedly, on a change to an existing code the author list itself may only be
edited by someone already on it: without that, adding (or swapping in) your own
handle would grant edit rights over anyone's entry, which is the hole the
refutation binding exists to avoid. A refuted 'exact' claim must demote to
upper_bound, and no correction may claim 'exact' at the new value without going
through certification. New submissions are unaffected.

Two more bindings exist for contributed artifacts, and they mirror the
refutation binding's credit model exactly: a change that ONLY adds a first
`locality` block, or ONLY a first `circuit` block (the code had neither),
binds when that block's `contributed_by.by` lists the PR author. `provenance`
must be byte-identical apart from an append to notes -- in particular
`authors` and `model` never change, so the credit lives beside the artifact
(like witness_provenance.found_by) and can never widen the contributor's edit
rights over the code: they are still not a listed author on the next PR, and
any later change must itself pass a binding.

Replacing an existing artifact stays with the code's listed authors either
way, which matters more for circuits than for layouts: the circuit tier is
penalty-only (d_circ is clamped to <= d), so a donated schedule can lower an
entry's score where a donated layout can only improve its class. Reserving
replacement means a mediocre donated schedule is always the authors' to beat
with a better one.

The artifacts under `circuits/<slug>/` are part of that entry's claim surface,
so a diff there counts as a change to `codes/<slug>.json` -- the same mapping
gate_changed.py prices the circuit search on. Otherwise someone's committed
.stim/.dem files could be swapped with their JSON left untouched, and this
gate, which diffs only `codes/`, would never see it.

Fails CLOSED only on a definite author/PR-author mismatch. Anything ambiguous
(no author info, git/parse error) fails OPEN with a warning -- a bug here must
not block legitimate contributions, since impersonation is lower-stakes than the
distance checks and is also caught in human review.

Usage:
  python verify/check_authorship.py --author <github-login> [--root PATH] [--base origin/main]
  python verify/check_authorship.py --author <login> codes/a.json codes/b.json
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HANDLE = re.compile(r"^@([A-Za-z0-9-]+)$")


def changed_codes(base, root=ROOT):
    """{path: status} for codes changed vs base; status is A, M, or D.

    --no-renames matters: a refutation renames codes/<n>-<k>-<d>.json to the
    new d while changing only the distance block, which git otherwise folds
    into a single R line (98% similar on a real board file) that used to
    parse as neither added nor modified -- the gate then checked nothing at
    all. Splitting renames back into D + A keeps every path visible; the R
    branch below is belt-and-braces in case the flag is ever lost."""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-status", "--no-renames",
             f"{base}...HEAD", "--", "codes", "circuits"],
            cwd=root, text=True)
    except Exception as e:
        print(f"(could not diff vs {base}: {e}); skipping authorship check")
        return None
    changes, from_circuits = {}, set()
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0][:1]
        if status == "R" and len(parts) >= 3:
            paths = parts[1:3]
            if parts[1].endswith(".json"):
                changes[parts[1]] = "D"
            if parts[2].endswith(".json"):
                changes[parts[2]] = "A"
        else:
            paths = parts[1:2]
            if parts[1].endswith(".json"):
                changes[parts[1]] = status
        from_circuits.update(p for p in map(code_for_circuit_path, paths) if p)
    # A diff under circuits/<slug>/ is a change to that entry's circuit-tier
    # claim, so bind it to the code even when the JSON is untouched: swapping
    # someone's committed circuits is an edit to their entry. An explicit
    # status on the JSON always wins (a rename's D/A, a real modification).
    for path in from_circuits:
        changes.setdefault(path, "M")
    return changes


def code_for_circuit_path(path):
    """codes/<slug>.json for a path under circuits/<slug>/, else None."""
    if path.startswith("circuits/") and path.count("/") >= 2:
        return f"codes/{path.split('/')[1]}.json"
    return None


def handles(doc):
    auth = (doc.get("provenance") or {}).get("authors") or []
    out = []
    for a in auth:
        m = HANDLE.match(str(a).strip())
        if m:
            out.append(m.group(1).lower())
    return out


def load_base_doc(base, path, root):
    """The base-revision content of path, or None if unavailable."""
    try:
        out = subprocess.check_output(["git", "show", f"{base}:{path}"],
                                      cwd=root, text=True,
                                      stderr=subprocess.DEVNULL)
        return json.loads(out)
    except Exception:
        return None


def base_counterpart(path, doc, changes):
    """The base-revision path this file revises: itself when modified, or the
    deleted codes/<n>-<k>-*.json when a refutation renamed the file."""
    if changes.get(path) == "M":
        return path
    prefix = os.path.join(os.path.dirname(path),
                          f"{doc.get('n')}-{doc.get('k')}-")
    matches = [p for p, s in changes.items()
               if s == "D" and p.startswith(prefix)]
    return matches[0] if len(matches) == 1 else None


def found_by_handles(side):
    wp = (side or {}).get("witness_provenance") or {}
    out = []
    for a in wp.get("found_by") or []:
        m = HANDLE.match(str(a).strip())
        if m:
            out.append(m.group(1).lower())
    return out


def refutation_binding(author, base_doc, new_doc):
    """Does new_doc differ from base_doc by exactly a refutation credited to
    author? Returns (ok, reason-if-not)."""
    keys = set(base_doc) | set(new_doc)
    for key in keys - {"distance", "name", "schema_version", "provenance"}:
        if base_doc.get(key) != new_doc.get(key):
            return False, f"field '{key}' changed (only the distance claim may change)"

    bp, np_ = base_doc.get("provenance") or {}, new_doc.get("provenance") or {}
    for key in set(bp) | set(np_):
        if key == "notes":
            continue
        if bp.get(key) != np_.get(key):
            return False, f"provenance.{key} changed (authors and construction are the constructor's)"
    old_notes, new_notes = bp.get("notes", ""), np_.get("notes", "")
    if not new_notes.startswith(old_notes):
        return False, "provenance.notes may only be appended to"

    bd, nd = base_doc.get("distance") or {}, new_doc.get("distance") or {}
    for side in ("X", "Z"):
        if not (bd.get(side) and nd.get(side)):
            return False, f"distance.{side} is missing"
    tightened = 0
    for side in ("X", "Z"):
        bs, ns = bd[side], nd[side]
        if bs == ns:
            continue
        if author not in found_by_handles(ns):
            return False, (f"distance.{side} changed but its witness_provenance"
                           f".found_by does not list @{author}")
        if ns.get("value", 0) < bs.get("value", 0):
            # A falsified claim can only be an upper bound now: a refuted
            # 'exact' must demote, and nothing may claim 'exact' at the new
            # value without going through certification.
            if ns.get("confidence") != "upper_bound":
                return False, (f"distance.{side}.confidence must become "
                               "upper_bound when the value is corrected")
            tightened += 1
        elif (ns.get("value") == bs.get("value")
              and ns.get("witness") == bs.get("witness")
              and ns.get("confidence") == bs.get("confidence")):
            pass  # survival stamp: witness_provenance recorded, claim untouched
        else:
            return False, (f"distance.{side}.value did not strictly decrease "
                           "and its witness or confidence changed")
    if tightened == 0:
        return False, "no side's distance strictly decreased"
    if nd.get("d") != min(nd[s].get("value", 0) for s in ("X", "Z")):
        return False, "distance.d is not min(dX, dZ)"
    return True, ""


def contributed_by_handles(block):
    """@handles credited in a contributed artifact's contributed_by block."""
    cb = (block or {}).get("contributed_by") or {}
    out = []
    for a in cb.get("by") or []:
        m = HANDLE.match(str(a).strip())
        if m:
            out.append(m.group(1).lower())
    return out


def addition_binding(author, base_doc, new_doc, field, noun):
    """Does new_doc differ from base_doc by exactly the addition of a first
    `field` artifact credited to author? Returns (ok, reason-if-not).

    Allowed: add `field` where none existed, with the PR author listed in
    <field>.contributed_by.by; append to provenance.notes; change `name` and
    `schema_version`. Everything else -- checks, distance, and ALL other
    provenance including authors and model -- must be byte-identical. Credit
    lives beside the artifact (as witness_provenance.found_by does for
    refutations), so the binding never widens the contributor's edit rights
    over the code (issue #611). The artifact's own validity -- a layout's
    spacing, layers, radius and class; a circuit's noise recipe, parallelism
    and witnesses -- is the verifier's job, not this gate's."""
    if field in (base_doc or {}):
        return False, (f"the entry already has {noun}; replacing one is "
                       "reserved to its listed authors")
    if field not in new_doc:
        return False, f"no {field} block was added"
    for key in (set(base_doc) | set(new_doc)) - {field, "name",
                                                 "schema_version",
                                                 "provenance"}:
        if base_doc.get(key) != new_doc.get(key):
            return False, (f"field '{key}' changed (adding {noun} may "
                           f"only add {field})")

    bp, np_ = base_doc.get("provenance") or {}, new_doc.get("provenance") or {}
    for key in (set(bp) | set(np_)) - {"notes"}:
        if bp.get(key) != np_.get(key):
            return False, (f"provenance.{key} changed (credit for {noun} "
                           f"lives in {field}.contributed_by, not in "
                           "provenance)")
    old_notes, new_notes = bp.get("notes", ""), np_.get("notes", "")
    if not new_notes.startswith(old_notes):
        return False, "provenance.notes may only be appended to"

    if author not in contributed_by_handles(new_doc.get(field)):
        return False, (f"{field}.contributed_by.by does not list the PR "
                       f"author @{author}")
    return True, ""


def layout_binding(author, base_doc, new_doc):
    """Exactly a first `locality` block credited to author (addition_binding).
    A contributed layout can only sharpen the entry's locality class."""
    return addition_binding(author, base_doc, new_doc, "locality", "a layout")


def circuit_binding(author, base_doc, new_doc):
    """Exactly a first `circuit` block credited to author (addition_binding).

    The tier is penalty-only -- d_circ is clamped to <= d and can only
    discount a score -- so unlike a layout, a donated schedule can lower the
    entry's standing. It is still a true fact about the code (the same
    principle that lets a non-author refute a distance), and reserving
    REPLACEMENT to the listed authors leaves a mediocre donated schedule
    theirs to beat. The committed circuits/<slug>/ artifacts are checked by
    verify/circuit_verify.py and re-gated by gate_changed.py, so a donated
    tier cannot under-claim d_circ without a valid witness at that weight."""
    return addition_binding(author, base_doc, new_doc, "circuit",
                            "a circuit tier")


# The bindings a PR author who is not a listed author may still pass, with the
# phrase each prints on success. Declaration order is report order, except for
# the one `evident_binding` says the change was aiming for.
BINDINGS = (
    ("refutation", refutation_binding, "witness_provenance credit, refuting"),
    ("layout", layout_binding, "adding a first locality block to"),
    ("circuit", circuit_binding, "adding a first circuit block to"),
)


def evident_binding(base_doc, new_doc):
    """Which binding a rejected change was evidently aiming for, so the report
    leads with one relevant rejection instead of three."""
    if "circuit" in new_doc and "circuit" not in base_doc:
        return "circuit"
    if "locality" in new_doc and "locality" not in base_doc:
        return "layout"
    return "refutation"


def main(argv):
    author = None
    if "--author" in argv:
        i = argv.index("--author")
        author = argv[i + 1].lower().lstrip("@")
        argv = argv[:i] + argv[i + 2:]
    base = "origin/main"
    root = ROOT
    if "--root" in argv:
        i = argv.index("--root")
        root = os.path.abspath(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    if "--base" in argv:
        i = argv.index("--base")
        base = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    if not author:
        print("no --author given; skipping authorship check")  # fail open
        return 0

    explicit = [a for a in argv if a.endswith(".json")]
    changes = changed_codes(base, root)
    if explicit:
        files = explicit
        changes = changes or {}
    else:
        if changes is None:
            # A git failure means the check did not run; exit nonzero so a
            # broken diff cannot silently pass authorship (mirrors
            # gate_changed.py).
            print("failing closed: authorship cannot be checked without the diff")
            return 1
        files = [p for p, s in changes.items() if s in ("A", "M")]
    if not files:
        print("no added/changed code submissions to check")
        return 0

    violations = []
    for f in files:
        p = f if os.path.isabs(f) else os.path.join(root, f)
        if not os.path.exists(p):
            continue
        try:
            doc = json.load(open(p))
        except Exception as e:
            print(f"(could not parse {f}: {e}); skipping it")  # fail open
            continue
        hs = handles(doc)
        if not hs:
            # A new submission with no @handle binds to no account, so it
            # would be exempt from this check forever. Baselines keep the
            # exemption; edits to existing entries keep the binding paths
            # below.
            origin = (doc.get("provenance") or {}).get("origin", "submission")
            if base_counterpart(f, doc, changes) is None and origin != "baseline":
                violations.append(
                    (f, [], "no @handle author (new submissions must bind to "
                     "a GitHub account; provenance.origin 'baseline' is for "
                     "literature codes)"))
                continue
            print(f"ok    {f}: no @handle authors (baseline), exempt")
            continue
        base_path = base_counterpart(f, doc, changes)
        base_doc = load_base_doc(base, base_path, root) if base_path else None
        if author in hs:
            # Being listed binds -- but on a change to an existing code, the
            # author list itself may only be edited by an existing author.
            # Otherwise swapping (or first-claiming, on a no-handle baseline)
            # your own handle would grant edit rights (issue #611). A genuine
            # first @handle claim on a baseline needs a maintainer.
            base_hs = handles(base_doc) if base_doc is not None else None
            if (base_hs is not None and hs != base_hs
                    and author not in base_hs):
                pass  # fall through to the refutation binding
            else:
                print(f"ok    {f}: PR author @{author} is listed")
                continue
        if base_doc is not None:
            if doc == base_doc:
                # Nothing in the JSON moved, so the diff that brought this
                # entry here is in its other committed artifacts (its
                # circuits/<slug>/ files). No binding describes that: every
                # one of them is a change TO the JSON.
                violations.append(
                    (f, hs, "the JSON is unchanged, so the diff is in this "
                     "entry's committed circuits/ artifacts; replacing those "
                     "is reserved to its listed authors"))
                continue
            attempts = []
            for label, bind, phrase in BINDINGS:
                ok, why = bind(author, base_doc, doc)
                if ok:
                    print(f"ok    {f}: @{author} binds by {phrase} {base_path}")
                    break
                attempts.append((f"{label} binding failed: {why}",
                                 label != evident_binding(base_doc, doc)))
            else:
                attempts.sort(key=lambda a: a[1])  # stable: evident one first
                first, *rest = [why for why, _ in attempts]
                violations.append((f, hs, f"{first} ({'; '.join(rest)})"))
        else:
            violations.append((f, hs, None))

    if violations:
        print("\nAuthorship mismatch: the PR author must be one of a code's "
              "@handle authors, or the change must be exactly a refutation "
              "credited to them in witness_provenance.found_by (issue #611), "
              "or exactly a first-layout addition credited to them in "
              "locality.contributed_by.by, or exactly a first-circuit-tier "
              "addition credited to them in circuit.contributed_by.by.")
        for f, hs, extra in violations:
            print(f"  {f}: authors {['@' + h for h in hs]} do not include "
                  f"@{author}" + (f"; {extra}" if extra else ""))
        print("If you are submitting on someone's behalf, add yourself as a "
              "co-author, or have them open the PR.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
