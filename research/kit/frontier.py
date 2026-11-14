"""frontier -- the board-advancing rule, as the refusal both packaging paths make.

AGENTS.md draws the line this module enforces. A candidate the gate passes is a
valid code: it verifies, a fresh refutation did not lower its distance, and it is
not already on the board. A valid code that no entry in its track cell dominates
on (n, k, d, w) is a board-advancing one. The gate answers the second question
as a label, ``gates.novelty.board_advancing`` with ``dominated_by`` naming the
entries, and never refuses on it, by design: ``passed`` certifies the code, not
its place on the board, and a dominated code is still worth recording.

The code-calculus greedy campaign of issue #5700 read the label as a pass
condition the other way round: it promoted every ``passed: true`` candidate and
filed dozens of dominated codes as frontier submissions. So the decision now
lives where the frontier claim gets written into a PR body, in the two packaging
paths. ``research/kit/promote.py`` reads the gate's own ``dominated_by``;
``./qldpc submit`` runs the verifier rather than the gate and computes the same
list from the board the site sees with :func:`dominators`. Both refuse a
dominated candidate with its dominators named, and both accept it again with
``--allow-non-frontier``, which files it as a non-frontier record and says so in
the PR body. :func:`within_batch` is the same rule over the candidates of one
batch, for a driver that is about to open several PRs at once.

Rows are shaped like ``site/build.load_entries`` and ``cli/qldpc._entry_for``:
``n``, ``k``, ``d``, ``w``, ``code_type``, ``weight_class``, ``locality_class``,
and ``slug``. Nothing here touches ``verify/`` or changes a verdict.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
_VERIFY = os.path.join(_ROOT, "verify")
if _VERIFY not in sys.path:
    sys.path.insert(0, _VERIFY)

from validate_candidate import _LOCAL_ORDER, _WEIGHT_ORDER  # noqa: E402

RULE = "AGENTS.md, The motto"
FLAG = "--allow-non-frontier"


def describe(entry):
    """Return a row as the gate's novelty block describes an entry.

    ``[[n,k,d]] w=6 72-6-6.json``, the form ``verify/validate_candidate.py``
    writes into ``dominated_by``. A row with no slug or name (a batch candidate
    that is not on the board yet) is named by its parameters.
    """
    slug = entry.get("slug")
    if not slug:
        name = os.path.basename(str(entry.get("name") or "").split()[-1]) \
            if entry.get("name") else ""
        slug = name[:-5] if name.endswith(".json") else name
    if not slug:
        slug = f"{entry['n']}-{entry['k']}-{entry['d']}"
    return f"[[{entry['n']},{entry['k']},{entry['d']}]] w={entry['w']} {slug}.json"


def in_cell(candidate, entry):
    """Return True when ``entry`` competes in the candidate's track cell.

    The gate's cell filter: the same board (CSS against CSS, stabilizer against
    stabilizer) and a weight class and a locality class each no looser than the
    candidate's. A w = 32 code is not a rival of a w = 8 candidate; a planar
    entry is a rival of an unrestricted candidate but not the reverse.
    """
    if entry.get("code_type", "CSS") != candidate.get("code_type", "CSS"):
        return False
    wc = _WEIGHT_ORDER.get(candidate.get("weight_class"), 9)
    lc = _LOCAL_ORDER.get(candidate.get("locality_class"), 9)
    return (_WEIGHT_ORDER.get(entry.get("weight_class"), 9) <= wc
            and _LOCAL_ORDER.get(entry.get("locality_class"), 9) <= lc)


def dominators(candidate, board):
    """Return the board entries that dominate the candidate, as the gate names them.

    An entry dominates when it is in the candidate's cell and no worse on every
    axis (n no larger, k no smaller, d no smaller, max check weight no larger)
    and strictly better on at least one. A tie on all four is not dominance:
    two codes at the same point share the frontier. A row with no recorded
    weight cannot be compared and is skipped, as the peer-audit rule skips it.
    """
    n, k, d, w = candidate["n"], candidate["k"], candidate["d"], candidate.get("w")
    out = []
    if w is None:
        return out
    for b in board:
        if not in_cell(candidate, b) or b.get("w") is None:
            continue
        bw = b["w"]
        if (b["n"] <= n and b["k"] >= k and b["d"] >= d and bw <= w
                and (b["n"] < n or b["k"] > k or b["d"] > d or bw < w)):
            out.append(describe(b))
    return out


def blockers(dominated_by, board_advancing, *, allowed=False, attach=""):
    """Return why the candidate may not be packaged as a frontier submission.

    An empty list means it may. ``dominated_by`` and ``board_advancing`` are
    the gate's (``gates.novelty``) or :func:`dominators`'s reading. ``allowed``
    is the ``--allow-non-frontier`` opt-in: it clears a dominated code, whose
    caller then records it as a non-frontier result, and nothing else. A
    verdict that never answered the frontier question (no label at all) is
    refused either way, because the opt-in is a decision about a known
    dominator and not a way past a missing one. ``attach`` names what the
    caller's path takes to opt in.
    """
    doms = list(dominated_by or [])
    tail = f"; {attach}" if attach else ""
    if board_advancing is None and not doms:
        return ["the verdict carries no gates.novelty.board_advancing, so whether "
                "this code advances its cell was never decided; re-run "
                "verify/validate_candidate.py against the current board"]
    if board_advancing is True and not doms:
        return []
    if allowed:
        return []
    named = (f"dominated in its track cell by {', '.join(doms)}" if doms
             else "the gate reports board_advancing: false")
    return [f"not board-advancing: {named}. {RULE}: a dominated code passes the "
            f"gate and is a non-frontier result, recorded and not submitted as a "
            f"frontier code{tail}"]


def body_line(dominated_by):
    """Return the PR-body line for an entry filed with ``--allow-non-frontier``.

    One sentence, the same in both packaging paths: who dominates the entry,
    and that it is a record of a valid code rather than a frontier claim.
    """
    names = ", ".join(dominated_by) or "an entry in its track cell"
    return (f"- Non-frontier result: dominated in its track cell by {names}. "
            f"Filed with {FLAG} as a record of a valid code, not as a frontier "
            f"claim ({RULE}).")


def within_batch(rows):
    """Return ``{index: [descriptors]}`` for each row another row of the batch dominates.

    The same rule as :func:`dominators`, with the batch standing in for the
    board, so a driver about to open one PR per survivor can drop the ones its
    own batch already beats (issue #5700, two PRs where one dominates the other
    make a frontier claim only one of them can keep). Rows that tie are kept
    both; a row the board dominates is :func:`dominators`'s business.
    """
    out = {}
    for i, cand in enumerate(rows):
        others = [r for j, r in enumerate(rows) if j != i]
        doms = dominators(cand, others)
        if doms:
            out[i] = doms
    return out
