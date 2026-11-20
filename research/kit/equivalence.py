"""Decide a Weisfeiler-Leman equivalence flag at packaging time (issue #6186).

The gate has two dedup outcomes for a candidate: a shared fingerprint, which is
the same code and is refused, and a shared WL signature with a different
fingerprint, which it labels ``possibly equivalent`` and leaves to a human:
``research/kit/promote.py`` holds the bundle until ``provenance.notes`` records
the comparison, and ``./qldpc submit`` leaves the equivalence box unticked with
the entry named. Both paths asked a person to do what
``research/audits/permutation_audit.py`` decides for board pairs: it exhibits a
qubit permutation (nauty on the typed Tanner graph, then on the hypergraph of
the light row-space vectors) or separates the codes by a basis-independent
invariant, and only when both fail does it say ``undecided``.

This module runs that decision on the candidate against the board entry the
gate named, so the flag is resolved where it is raised:

* ``equivalent``: the permutation is exhibited and re-verified, so the
  candidate is that entry and both packaging paths refuse it as a duplicate;
* ``inequivalent``: an invariant differs or the light-vector hypergraphs are
  not isomorphic, so the box is ticked with that reason and no note is owed;
* ``gb_family_no`` and ``undecided``: the human rule stays as it was.

The record is the audit's pair record, saved beside the candidate as
``<stem>.equivalence.json`` so the trail exists after the PR, and the board
pair records themselves live under ``research/audits/permutation_audit-*.json``
from the campaign run. The light-vector budget here is a hundredth of the
audit's default, since this runs inside a packaging command; an entry the
smaller budget leaves ``undecided`` is one the full audit decides later.
Nothing here touches ``verify/`` or changes a verdict.
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (os.path.join(_ROOT, "research", "audits"), os.path.join(_ROOT, "verify")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

PACKAGING_BUDGET = 10 ** 7     # row sums the light-vector enumeration may plan per row space
RECORD_SUFFIX = ".equivalence.json"


def _slug(name):
    name = os.path.basename(str(name))
    return name[:-5] if name.endswith(".json") else name


def decide_pair(doc, against, *, root=_ROOT, budget=PACKAGING_BUDGET):
    """Return the audit's pair record for ``doc`` against board entry ``against``.

    ``against`` is the entry the gate named (``72-12-6.json`` or ``72-12-6``).
    The record carries ``verdict`` (``equivalent``, ``inequivalent``,
    ``gb_family_no``, or ``undecided``), ``reason`` or the exhibited
    ``permutation`` and ``swap``, the invariants, ``against`` as a slug, and
    the entry's blob hash. A board entry that cannot be read gives
    ``verdict: undecided`` with the reason, so a missing file never reads as
    a decision either way.
    """
    import permutation_audit as PA
    slug = _slug(against)
    path = os.path.join(root, "codes", slug + ".json")
    try:
        with open(path, encoding="utf-8") as fh:
            other = json.load(fh)
    except (OSError, ValueError) as e:
        return {"first": "candidate", "second": slug, "against": slug, "verdict": "undecided",
                "reason": f"board entry {path} could not be read ({type(e).__name__})"}
    a = PA.code_from_doc("candidate", doc)
    b = PA.code_from_doc(slug, other)
    rec = PA.decide(a, b, doc, other, budget=budget)
    rec["against"] = slug
    rec["enum_budget"] = int(budget)
    try:
        rec["second_blob"] = PA.blob_sha(path)
    except Exception:  # noqa: BLE001 - the hash is a convenience for the trail
        pass
    return rec


def finding(record):
    """Return ``(ticked, text)`` for the equivalence checklist box, or ``(None, reason)``.

    ``None`` means the audit did not decide (``gb_family_no`` or ``undecided``)
    and the caller keeps its human rule. The text names the entry and the
    evidence, so a reader of the PR body sees what settled the flag.
    """
    slug = record.get("against") or record.get("second")
    verdict = record.get("verdict")
    if verdict == "equivalent":
        how = record.get("found_by") or "the audit"
        return False, (f"a qubit permutation carries this code onto board entry {slug} "
                       f"(found by {how}, re-verified by row-space mapping): it is that "
                       "code, not a new one; withdraw it, or file a correction to that entry")
    if verdict == "inequivalent":
        return True, (f"`research/audits/permutation_audit.py` separates it from board entry "
                      f"{slug}, which shares its Weisfeiler-Leman signature: "
                      f"{record.get('reason', 'a basis-independent invariant differs')}")
    return None, (record.get("reason") or f"the audit could not decide against {slug}")


def record_path(candidate_path):
    """``<stem>.equivalence.json`` beside the candidate."""
    base = str(candidate_path)
    if base.endswith(".json"):
        base = base[:-5]
    return base + RECORD_SUFFIX


def save_record(record, path):
    """Write the record (``json.dump``, indent 1); the directory must exist."""
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(record, fh, indent=1, sort_keys=True, default=str)
        fh.write("\n")
    return path
