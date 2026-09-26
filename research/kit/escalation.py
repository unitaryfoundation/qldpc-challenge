"""The escalation gate: budget policy for a candidate's RIS ladder.

Deep confirmation is the bottleneck
(../../fieldnotes/2026-07-01-confirmation-is-the-bottleneck.md): screens run in
seconds, deep rungs in minutes to hours, and exact certification can outrun a
campaign entirely. fieldnotes/2026-09-20-screening-traps-at-n-900.md records
the cost of getting the rung decision wrong: 5.3M trials spent on a ladder
whose first fresh deep rungs had already settled below the cell bar. This
module is the rung-boundary gate against exactly that failure.

The division of labor is strict:

  * ``rung_brief`` computes the facts, deterministically, from the ladder;
  * a judgment model (Jev, via its MCP ``jev_decide`` tool) weighs them --
    the brief carries a ready ``jev_request`` for that call;
  * ``apply_verdict`` enforces the policy in code. A verdict tilts the choice
    inside the fences; it can never open them.

The fences: the default action is HOLD, and any missing, malformed, escaped,
or low-confidence verdict holds. ABANDON is honored only when the ladder
itself proves it safe -- the cumulative best bound already scores below the
cell bar AND at least ``MIN_FLAT_RUNGS`` fresh-seed rungs agree at that bound
AND the caller has not flagged frontier membership worth protecting. A
still-descending ladder can never be abandoned: the inflation between a
screen reading and the settled value is unbounded (the 2026-09-20 note's
"factor of two is a lower bound on the gap"). PROMOTE additionally requires
remaining budget to cover the next rung.

Why the abandon fence is sound: every rung reading is a found low-weight
logical, so the cumulative best bound is a proved ``d <=`` and the
efficiency at that bound is a proved ``kd^2/n <=``. If it already scores
below the bar, deeper trials can only find something lighter, never rescue
the candidate; flat agreement across fresh seeds rules out seed-correlated
readings. A hold destroys nothing -- the witnessed logicals stay valid
whatever the gate says.

Jev verdicts are advisory model output, not repo evidence: they live in the
staging journal (``research/candidates/`` is gitignored) and are never cited
in notes, fieldnotes, or PR bodies. Skipping this gate is always sound; it
changes where budget goes, never what can be claimed. Each journaled record
is one JSONL line -- the brief, the raw verdict, and the enforced decision --
so a session ledger can audit what was judged and what the fences did.

Stdlib only: the kit's numpy modules are not needed to decide where budget
goes, and keeping this module dependency-free lets an agent harness run it
anywhere.
"""
import hashlib
import json
import math
import os
from datetime import datetime, timezone

# Policy constants. HOLD is the default; the fences are enforced in code so no
# verdict, however confident, can open them.
HOLD_CONFIDENCE = 0.60   # below this a verdict is not trusted to choose
MIN_FLAT_RUNGS = 2       # fresh-seed rungs flat at the best bound before abandon is legal

ACTIONS = ("promote-next-rung", "hold-deepen", "abandon-ladder")

# The jev_decide MCP tool's input limits; test_escalation pins the brief to them.
JEV_LIMITS = {"decision": 1500, "evidence": 12000, "priorities": 2000,
              "candidate_description": 2000, "requirement": 500}

_DECISION = (
    "Ladder escalation for a screened qLDPC candidate: should the next RIS "
    "budget go to a deeper rung on this candidate (promote), a same-depth "
    "fresh-seed rung (hold), or stopping this ladder (abandon)? The trusted "
    "verifier remains the only judge of a code; this choice only allocates "
    "trial budget."
)

_PRIORITIES = (
    "False positives are the expensive failure: a promoted screen artifact "
    "eats confirmation budget that honest survivors need. Uncertain is not "
    "false: uncertainty must hold and deepen, never guess. Trial budget is "
    "the scarcest resource; trials spent on a doomed ladder are denied to the "
    "rest of the sweep. Witnesses are never discarded: a hold destroys "
    "nothing, and abandon is only meaningful when the upper bounds already "
    "prove nothing of value remains on this ladder."
)

_CANDIDATES = [
    {"id": "promote-next-rung",
     "description": "Spend the next, deeper rung on this candidate. Justified "
                    "when the ladder still has room above the bar or the "
                    "trend is promising and the remaining budget covers the "
                    "cost."},
    {"id": "hold-deepen",
     "description": "Repeat the current rung depth on fresh seeds before "
                    "deciding. The honest default when readings are unstable, "
                    "the ladder is still descending, or the verdict itself is "
                    "uncertain."},
    {"id": "abandon-ladder",
     "description": "Stop spending on this candidate. Only defensible when "
                    "the cumulative best bound already scores below the cell "
                    "bar on flat fresh-seed rungs, so deeper trials cannot "
                    "rescue it (an upper bound can only fall)."},
]

_REQUIREMENTS = [
    "Never select abandon unless the evidence shows the cumulative best bound "
    "below the cell bar, at least 2 flat fresh-seed rungs, and no frontier "
    "flag.",
    "If the ladder is still descending (the last rung improved the bound), "
    "prefer hold-deepen or promote over abandon.",
    "Weigh trial cost against information gain; the harness holds anyway on "
    "low confidence.",
]


def _efficiency(n, k, d):
    # Deliberately identical to search.efficiency (the board's kd^2/n);
    # test_escalation pins the agreement so the two cannot drift. Kept local
    # so this module stays stdlib-only.
    return (k * d * d / n) if n else 0.0


def _norm_rung(r):
    """Accept a dict or a ``(trials, d[, fresh][, label])`` tuple."""
    if isinstance(r, dict):
        trials, d = r["trials"], r["d"]
        fresh = r.get("fresh", True)
        label = r.get("label")
    else:
        trials, d = r[0], r[1]
        fresh = r[2] if len(r) > 2 else True
        label = r[3] if len(r) > 3 else None
    if not isinstance(trials, int) or isinstance(trials, bool) or trials < 1:
        raise ValueError(f"rung trials must be a positive integer, got {trials!r}")
    if not isinstance(d, int) or isinstance(d, bool) or d < 1:
        raise ValueError(f"rung d must be a positive integer reading, got {d!r}")
    return {"trials": trials, "d": d, "fresh": bool(fresh), "label": label}


def _brief_id(n, k, bar, family, spec, rungs):
    payload = json.dumps({"n": n, "k": k, "bar": bar, "family": family,
                          "spec": spec, "rungs": rungs},
                         sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def rung_brief(n, k, rungs, *, bar, family="", spec=None,
               budget_remaining=None, next_rung_trials=None, context=None):
    """Build the rung-boundary brief: deterministic facts plus a jev_request.

    ``rungs`` is the ladder so far, oldest first: dicts (``trials``, ``d``,
    optional ``fresh``, ``label``) or ``(trials, d)`` pairs. ``d`` is that
    rung's reading (an upper bound on distance, witnessed by the found
    logical); ``fresh`` marks an independent seed and defaults to True.
    ``bar`` is the cell's kd^2/n bar. ``next_rung_trials`` is the cost of the
    rung being decided. ``context`` may carry ``frontier=True`` when the
    candidate's (n, k, d) frontier membership is separately worth protecting
    (as ``screen_adaptive`` treats its frontier).
    """
    if not isinstance(n, int) or n < 1 or not isinstance(k, int) or k < 1:
        raise ValueError("n and k must be positive integers")
    if not isinstance(bar, (int, float)) or isinstance(bar, bool) or bar <= 0:
        raise ValueError("bar must be a positive kd^2/n value")
    rungs = [_norm_rung(r) for r in rungs]
    if not rungs:
        raise ValueError("at least one rung is required")

    best = min(r["d"] for r in rungs)
    fresh_rungs = [r for r in rungs if r["fresh"]]
    flat = 0
    for r in reversed(fresh_rungs):
        if r["d"] == best:
            flat += 1
        else:
            break
    descending = len(fresh_rungs) >= 2 and fresh_rungs[-1]["d"] < fresh_rungs[-2]["d"]
    eff = round(_efficiency(n, k, best), 4)
    d_needed = math.ceil(math.sqrt(bar * n / k))
    context = dict(context or {})

    facts = {
        "n": n,
        "k": k,
        "cumulative_best_bound": best,
        "ladder": [{"trials": r["trials"], "d": r["d"], "fresh": r["fresh"],
                    **({"label": r["label"]} if r["label"] else {})}
                   for r in rungs],
        "flat_fresh_rungs_at_best": flat,
        "ladder_still_descending": descending,
        "efficiency_at_best": eff,
        "cell_bar": bar,
        "d_needed_for_bar": d_needed,
        "best_at_or_above_bar": best >= d_needed,
        "margin_to_bar": round(eff - bar, 4),
        "frontier_flagged": bool(context.get("frontier", False)),
        "family": family,
        "spec": spec,
        "rungs_total": len(rungs),
        "fresh_rungs_total": len(fresh_rungs),
        "trials_spent": sum(r["trials"] for r in rungs),
        "next_rung_trials": next_rung_trials,
        "budget_remaining": budget_remaining,
    }
    request = {
        "decision": _DECISION,
        "evidence": json.dumps(facts, sort_keys=True),
        "priorities": _PRIORITIES,
        "candidates": _CANDIDATES,
        "requirements": _REQUIREMENTS,
    }
    # A brief that does not fit the tool cannot be judged; fail loudly here
    # rather than silently truncating the facts the verdict will rest on.
    for key in ("decision", "evidence", "priorities"):
        assert len(request[key]) <= JEV_LIMITS[key], f"jev_request.{key} too long"
    for c in _CANDIDATES:
        assert len(c["description"]) <= JEV_LIMITS["candidate_description"]
    for r in _REQUIREMENTS:
        assert len(r) <= JEV_LIMITS["requirement"]
    return {"kind": "rung-escalation",
            "id": _brief_id(n, k, bar, family, spec, facts["ladder"]),
            "facts": facts, "jev_request": request}


def _parse_verdict(verdict):
    """Extract (action, confidence, escaped) from the jev_decide response shape.

    Returns None instead of guessing on anything unexpected; the caller then
    holds. Malformed verdicts are the model's problem to notice later from the
    journal, never a reason to guess here.
    """
    if not isinstance(verdict, dict):
        return None
    rec = verdict.get("recommendation")
    if not isinstance(rec, dict):
        return None
    action, conf = rec.get("selected"), rec.get("confidence")
    if not isinstance(action, str) or not isinstance(conf, (int, float)) \
            or isinstance(conf, bool):
        return None
    return action, float(conf), bool(rec.get("escaped", False))


def _abandon_is_proven_safe(facts):
    """The arithmetic fence: the ladder itself must prove abandonment safe.

    True only when the cumulative best bound (a proved d<=, since every rung
    is a witnessed logical) already scores below the bar, enough fresh rungs
    agree at that bound to rule out seed-correlated readings, and nothing
    frontier-flagged is being thrown away.
    """
    return (not facts["best_at_or_above_bar"]
            and facts["flat_fresh_rungs_at_best"] >= MIN_FLAT_RUNGS
            and not facts["frontier_flagged"])


def apply_verdict(brief, verdict=None, *, budget_remaining=None):
    """Enforce the policy: turn a brief + verdict into an audited decision.

    The fences, in order of authority:

    1. no/missing/malformed verdict -> hold-deepen;
    2. an escaped verdict (the tool declined to rank) -> hold-deepen;
    3. confidence below HOLD_CONFIDENCE -> hold-deepen;
    4. abandon requires ``_abandon_is_proven_safe`` regardless of the verdict;
    5. promote requires budget to cover ``next_rung_trials``; and
    6. an unknown action string -> hold-deepen.

    A decision never suppresses data: hold and abandon both leave every
    witness in place, and abandoning a ladder stops spending, it does not
    delete the candidate's record. Returns
    ``{action, reason, confidence, escaped, brief_id, advisories}`` where
    ``advisories`` lists every fence the raw verdict ran into (empty when the
    fences agreed with the verdict and it was acted on as-is).
    """
    facts = brief["facts"]
    if budget_remaining is not None:
        facts = dict(facts, budget_remaining=budget_remaining)
    parsed = _parse_verdict(verdict) if verdict is not None else None
    advisories = []

    if parsed is None:
        return {"action": "hold-deepen",
                "reason": "no parsable verdict; default holds and deepens",
                "confidence": None, "escaped": False, "brief_id": brief["id"],
                "advisories": ["no-verdict"]}
    action, conf, escaped = parsed

    if escaped:
        advisories.append("escaped-verdict")
    if conf < HOLD_CONFIDENCE:
        advisories.append("low-confidence")
    if action == "promote-next-rung" and facts["next_rung_trials"] is not None \
            and facts["budget_remaining"] is not None \
            and facts["budget_remaining"] < facts["next_rung_trials"]:
        advisories.append("budget-exhausted")
    if action == "abandon-ladder" and not _abandon_is_proven_safe(facts):
        advisories.append("abandon-unproven")

    if action not in ACTIONS:
        advisories.append("unknown-action")
        action = "hold-deepen"
    elif escaped or conf < HOLD_CONFIDENCE:
        action = "hold-deepen"
    elif action == "abandon-ladder" and not _abandon_is_proven_safe(facts):
        action = "hold-deepen"
    elif action == "promote-next-rung" and facts["next_rung_trials"] is not None \
            and facts["budget_remaining"] is not None \
            and facts["budget_remaining"] < facts["next_rung_trials"]:
        action = "hold-deepen"

    reason = ("verdict honored inside the fences" if not advisories else
              "fenced: " + ", ".join(advisories))
    return {"action": action, "reason": reason, "confidence": conf,
            "escaped": escaped, "brief_id": brief["id"],
            "advisories": advisories}


def append_journal(decision, brief, *, path):
    """Append one JSONL audit record to the staging journal.

    ``research/candidates/`` is gitignored working output, so the journal
    records what was judged and what the fences did without ever entering the
    repository's evidence trail. Jev verdicts are advisory model output, not
    repo evidence; nothing in this record is citable in notes or PR bodies.
    """
    record = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "decision": decision, "brief_id": brief["id"],
              "facts": brief["facts"]}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")
