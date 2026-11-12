"""peer_audit -- the matched-depth audit a d-only gain owes before it is packaged.

AGENTS.md and research/AUTORESEARCH.md section 5b require that a candidate whose
only strict gain over a board entry is d (same n, k, and max check weight) be
re-measured beside that entry at one budget with ``research/audits/leader_audit.py
pair`` before it is packaged: both distances are witness-backed upper bounds, and
a gain on d alone is where an inflated bound shows up. A d = 1 entry is a
placeholder, not a suspect distance claim, so it is never a d-only peer: beating
one on d alone owes no audit. Two paths package a
candidate, ``research/kit/promote.py`` and ``./qldpc submit``, and both call this
module, so the rule cannot drift between them (issue #4236).

Nothing here touches ``verify/`` or changes a verdict. The gate decides whether the
code passes; this decides whether a d-only gain has been re-measured before it is
filed, and refuses with the exact command to run when it has not.

The record ``leader_audit.py pair --json-out`` writes, and :func:`blockers` reads::

    {"schema": "qldpc-peer-audit/1", "candidate": "<path>",
     "peers": ["codes/72-6-6.json"], "trials": 2000000, "seeds": [51, 52],
     "pair_depth": 64, "threads": 8,
     "decision": "credible: both claims held at matched depth -- the gain survives",
     "exit_code": 0, "results": [{"entry": ..., "stem": ..., "n": ..., "k": ...,
     "w": ..., "claim": ..., "weight": ..., "verdict": ...}], "recorded": "2026-11-05"}

Only a ``credible`` decision at a depth no shallower than the one the claim rests
on, covering every d-only peer the gate named, discharges the audit. A prose
``evidence.peer_audit`` is still accepted by ``promote.py`` for notes written
before the record existed; it is reported as unchecked rather than refused.
"""
import datetime
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
_VERIFY = os.path.join(_ROOT, "verify")
if _VERIFY not in sys.path:
    sys.path.insert(0, _VERIFY)

from validate_candidate import _LOCAL_ORDER, _WEIGHT_ORDER  # noqa: E402

AUDIT_SCHEMA = "qldpc-peer-audit/1"
CREDIBLE = "credible"
RULE = "research/AUTORESEARCH.md section 5b"
DEFAULT_TRIALS = 2_000_000
DEFAULT_SEEDS = (51, 52)
DEFAULT_PAIR_DEPTH = 10

# What each non-credible decision asks of the submitter, in the words of
# research/audits/README.md.
_MEANING = {
    "drop": "the candidate's own claim came down at that budget; do not package it",
    "redirect": "the board peer's claim came down; the submission to make is that "
                "entry's distance revision (research/audits/README.md, Filing a "
                "distance revision), not this candidate",
    "inconclusive": "neither claim was reached at that budget, which is no "
                    "information; audit deeper or not at all",
}


class PeerAuditError(ValueError):
    """A peer-audit record this module will not read."""


def peer_slug(desc):
    """Return the board slug a peer descriptor names, in any of its forms.

    The gate writes ``[[72,6,6]] w=6 72-6-6.json``; ``leader_audit.py`` records
    the path it measured, ``codes/72-6-6.json``; a human types ``72-6-6``.
    """
    text = str(desc or "").strip()
    token = os.path.basename(text.split()[-1]) if text else ""
    return token[:-5] if token.endswith(".json") else token


def describe(entry):
    """Return a board row as the gate's novelty block describes a peer."""
    slug = entry.get("slug") or peer_slug(entry.get("name", ""))
    return f"[[{entry['n']},{entry['k']},{entry['d']}]] w={entry['w']} {slug}.json"


def d_only_peers(candidate, board):
    """Return the board entries the candidate beats on d and on nothing else.

    The rule is the gate's (``verify/validate_candidate.py``, novelty): an entry
    on the same board, in a cell no looser than the candidate's, with the same
    n, k, and max check weight and a lower claimed d. Rows are shaped like
    ``site/build.load_entries`` and ``cli/qldpc._entry_for``; a row with no
    recorded weight cannot be compared and is skipped.
    """
    n, k, d, w = candidate["n"], candidate["k"], candidate["d"], candidate.get("w")
    if d is None or d <= 1:
        return []
    code_type = candidate.get("code_type", "CSS")
    wc = _WEIGHT_ORDER.get(candidate.get("weight_class"), 9)
    lc = _LOCAL_ORDER.get(candidate.get("locality_class"), 9)
    out = []
    for b in board:
        if b.get("code_type", "CSS") != code_type or b.get("w") is None or w is None:
            continue
        if _WEIGHT_ORDER.get(b.get("weight_class"), 9) > wc \
                or _LOCAL_ORDER.get(b.get("locality_class"), 9) > lc:
            continue
        # a d = 1 entry is a placeholder, not a real distance claim: beating it
        # on d alone is not the suspect (inflated-bound) pattern.
        if (b["n"], b["k"], b["w"]) == (n, k, w) and b.get("d", 0) > 1 and b["d"] < d:
            out.append(describe(b))
    return out


def pair_command(candidate_path, *, trials=DEFAULT_TRIALS, seeds=DEFAULT_SEEDS,
                 pair_depth=DEFAULT_PAIR_DEPTH, out="peer-audit.json"):
    """Return the exact ``leader_audit.py pair`` invocation that produces the record."""
    seed_text = " ".join(str(s) for s in seeds)
    return (f"uv run --frozen python research/audits/leader_audit.py pair "
            f"{candidate_path} --trials {trials} --seeds {seed_text} "
            f"--pair-depth {pair_depth} --witness-dir <dir-for-witnesses> "
            f"--json-out {out}")


def record(candidate, peers, results, decision, *, trials, seeds, pair_depth,
           threads, exit_code, today=None):
    """Return the audit record ``leader_audit.py pair --json-out`` writes."""
    return {"schema": AUDIT_SCHEMA, "candidate": str(candidate),
            "peers": [str(p) for p in peers], "trials": int(trials),
            "seeds": [int(s) for s in seeds], "pair_depth": int(pair_depth),
            "threads": int(threads), "decision": str(decision),
            "exit_code": int(exit_code), "results": list(results),
            "recorded": today or datetime.date.today().isoformat()}


def load_audit(path):
    """Read a record written by ``leader_audit.py pair --json-out``."""
    try:
        with open(path, encoding="utf-8") as fh:
            obj = json.load(fh)
    except (OSError, ValueError) as e:
        raise PeerAuditError(f"--peer-audit {path}: not readable as JSON ({e})") from e
    if not isinstance(obj, dict):
        raise PeerAuditError(f"--peer-audit {path}: expected one JSON object")
    if obj.get("schema") != AUDIT_SCHEMA:
        raise PeerAuditError(
            f"--peer-audit {path}: schema is {obj.get('schema')!r}, expected "
            f"{AUDIT_SCHEMA!r}; write the record with research/audits/leader_audit.py "
            f"pair --json-out")
    return obj


def is_checkable(audit):
    """Return True when the audit is a record whose depth and decision can be read."""
    return isinstance(audit, dict)


def _positive_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def blockers(peers, audit, *, required_trials=None, required_pair_depth=None,
             candidate_path="<candidate>.json", attach=""):
    """Return why ``audit`` does not discharge the d-only gain over ``peers``.

    An empty list means it does. No peers means there is nothing to discharge.
    No audit is refused with the command that produces one. Prose (a string) is
    accepted unchecked. A record is held to a ``credible`` decision, a trial
    count no lower than ``required_trials`` (the depth the claim rests on), a
    pair depth no lower than ``required_pair_depth`` when one is known, recorded
    seeds, and coverage of every peer named.
    """
    peers = list(peers or [])
    if not peers:
        return []
    names = ", ".join(peers)
    if not audit:
        cmd = pair_command(candidate_path, trials=required_trials or DEFAULT_TRIALS,
                           pair_depth=required_pair_depth or DEFAULT_PAIR_DEPTH)
        tail = f", then {attach}" if attach else ""
        return [f"the gate reports a d-only gain over {names}; {RULE} requires a "
                f"matched-depth peer audit before packaging, and none is recorded. "
                f"Run {cmd}{tail}"]
    if not is_checkable(audit):
        return []
    problems = []
    decision = str(audit.get("decision") or "").strip()
    head = decision.split(":", 1)[0].strip().lower()
    if head != CREDIBLE:
        meaning = _MEANING.get(head, "only a `credible` decision discharges the audit")
        problems.append(f"the recorded peer audit's decision is "
                        f"{decision or 'missing'!r}: {meaning}")
    trials = audit.get("trials")
    if not _positive_int(trials):
        problems.append("the recorded peer audit carries no trials, so its depth "
                        "cannot be checked")
    elif required_trials and trials < required_trials:
        problems.append(f"the recorded peer audit was read at {trials:,} trials, "
                        f"shallower than the {required_trials:,} the claim rests on: "
                        f"an instrument artifact, not a distance difference ({RULE})")
    depth = audit.get("pair_depth")
    if not _positive_int(depth):
        problems.append("the recorded peer audit carries no pair_depth")
    elif required_pair_depth and depth < required_pair_depth:
        problems.append(f"the recorded peer audit used pair depth {depth}, shallower "
                        f"than the {required_pair_depth} the claim's own search used")
    seeds = audit.get("seeds")
    if not isinstance(seeds, list) or not seeds:
        problems.append("the recorded peer audit carries no seeds")
    audited = {peer_slug(p) for p in (audit.get("peers") or [])} - {""}
    missing = [p for p in peers if peer_slug(p) not in audited]
    if missing:
        problems.append(f"the recorded peer audit does not cover "
                        f"{', '.join(missing)}; it audited "
                        f"{', '.join(sorted(audited)) or 'no peer'}")
    return problems


def summary(audit):
    """Return one line describing a checkable audit, for a body or a log."""
    if not is_checkable(audit):
        return str(audit or "")
    seeds = ", ".join(str(s) for s in (audit.get("seeds") or [])) or "unrecorded"
    trials = audit.get("trials")
    depth = f"{trials:,}" if _positive_int(trials) else "unrecorded"
    return (f"{audit.get('decision', '')}; {depth} trials per seed, seeds {seeds}, "
            f"pair depth {audit.get('pair_depth', 'unrecorded')}")
