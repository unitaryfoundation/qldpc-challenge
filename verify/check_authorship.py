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

One more binding exists for layouts, and it mirrors the refutation binding's
credit model exactly: a change that ONLY adds a first `locality` block (the
code had none) binds when the block's `contributed_by.by` lists the PR author.
`provenance` must be byte-identical apart from an append to notes -- in
particular `authors` and `model` never change, so layout credit lives beside
the artifact (like witness_provenance.found_by) and can never widen the
contributor's edit rights over the code: they are still not a listed author
on the next PR, and any later change must itself pass a binding.

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
             f"{base}...HEAD", "--", "codes"],
            cwd=root, text=True)
    except Exception as e:
        print(f"(could not diff vs {base}: {e}); skipping authorship check")
        return None
    changes = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0][:1]
        if status == "R" and len(parts) >= 3:
            if parts[1].endswith(".json"):
                changes[parts[1]] = "D"
            if parts[2].endswith(".json"):
                changes[parts[2]] = "A"
        elif parts[1].endswith(".json"):
            changes[parts[1]] = status
    return changes


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


def contributed_by_handles(loc):
    cb = (loc or {}).get("contributed_by") or {}
    out = []
    for a in cb.get("by") or []:
        m = HANDLE.match(str(a).strip())
        if m:
            out.append(m.group(1).lower())
    return out


def layout_binding(author, base_doc, new_doc):
    """Does new_doc differ from base_doc by exactly the addition of a first
    layout credited to author? Returns (ok, reason-if-not).

    Allowed: add `locality` where none existed, with the PR author listed in
    locality.contributed_by.by; append to provenance.notes; change `name` and
    `schema_version`. Everything else -- checks, distance, and ALL other
    provenance including authors and model -- must be byte-identical. Credit
    lives beside the artifact (as witness_provenance.found_by does for
    refutations), so the binding never widens the contributor's edit rights
    over the code (issue #611). The layout's own validity (spacing, layers,
    radius, class) is the verifier's job, not this gate's."""
    if "locality" in (base_doc or {}):
        return False, ("the entry already has a layout; replacing one is "
                       "reserved to its listed authors")
    if "locality" not in new_doc:
        return False, "no locality block was added"
    for key in (set(base_doc) | set(new_doc)) - {"locality", "name",
                                                 "schema_version",
                                                 "provenance"}:
        if base_doc.get(key) != new_doc.get(key):
            return False, (f"field '{key}' changed (a layout addition may "
                           "only add locality)")

    bp, np_ = base_doc.get("provenance") or {}, new_doc.get("provenance") or {}
    for key in (set(bp) | set(np_)) - {"notes"}:
        if bp.get(key) != np_.get(key):
            return False, (f"provenance.{key} changed (layout credit lives in "
                           "locality.contributed_by, not in provenance)")
    old_notes, new_notes = bp.get("notes", ""), np_.get("notes", "")
    if not new_notes.startswith(old_notes):
        return False, "provenance.notes may only be appended to"

    if author not in contributed_by_handles(new_doc.get("locality")):
        return False, ("locality.contributed_by.by does not list the PR "
                       f"author @{author}")
    return True, ""


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
            print(f"ok    {f}: no @handle authors (baseline/anonymous), exempt")
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
            ok, why = refutation_binding(author, base_doc, doc)
            if ok:
                print(f"ok    {f}: @{author} binds via witness_provenance "
                      f"(refutation of {base_path})")
                continue
            ok2, why2 = layout_binding(author, base_doc, doc)
            if ok2:
                print(f"ok    {f}: @{author} binds via layout addition "
                      f"(first locality block on {base_path})")
                continue
            # Lead with the binding the change was evidently aiming for, so a
            # plain unauthorized edit reads one relevant rejection, not two.
            layoutish = ("locality" in doc) and ("locality" not in base_doc)
            first, second = ((f"layout binding failed: {why2}",
                              f"refutation binding failed: {why}")
                             if layoutish else
                             (f"refutation binding failed: {why}",
                              f"layout binding failed: {why2}"))
            violations.append((f, hs, f"{first} ({second})"))
        else:
            violations.append((f, hs, None))

    if violations:
        print("\nAuthorship mismatch: the PR author must be one of a code's "
              "@handle authors, or the change must be exactly a refutation "
              "credited to them in witness_provenance.found_by (issue #611), "
              "or exactly a first-layout addition credited to them in "
              "locality.contributed_by.by.")
        for f, hs, extra in violations:
            print(f"  {f}: authors {['@' + h for h in hs]} do not include "
                  f"@{author}" + (f"; {extra}" if extra else ""))
        print("If you are submitting on someone's behalf, add yourself as a "
              "co-author, or have them open the PR.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
