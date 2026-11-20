"""A revision must not be reported as someone filing the same code twice.

A distance revision has the same checks as the entry it corrects, so it
fingerprints as an exact duplicate. That is right: `validate_candidate` is the
new-candidate path and a revision is not a new candidate. What was wrong is
what it said. "duplicate: identical to board entry X" is indistinguishable
from a double submission, so an agent that followed the audit loop, earned a
`redirect`, and packaged the revision was told its work was redundant and
discarded the most expensive data in the loop (issue #2583).

The fingerprint is deliberately unchanged. It is computed from the matrices
because the matrices are the code, and a claim about a code is not part of its
identity; widening it to include `d` would stop dedup catching a re-labelled
copy that claims a different distance, which is the case it exists for.

Everything here runs against the pinned fixture and a synthetic board, never
against `codes/`. Board data moves, and a test that reads it tests the board
rather than the rule (the lesson of #946 and #986). `refute=False` as well:
nothing here is about the distance search.
"""

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import validate_candidate as V  # noqa: E402
from qldpc_verify import verify  # noqa: E402

FIXTURE = os.path.join(_HERE, "fixtures", "72-6-6.json")


def _doc():
    """Load the fixture, unmodified.

    The candidate's claim is never edited: a witness is only valid at the
    weight it has, so lowering `d` here would make the document fail the
    structural checks and never reach dedup at all. Every case below moves
    the BOARD entry's claim instead, which is the comparison the branch
    actually makes.
    """
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def _identity(doc):
    """Return the fingerprint and signature a colliding board row needs."""
    rep = verify(doc, refute=False)
    return rep["fingerprint"], rep["signature"]["hash"]


def _board_row(doc, d):
    """One synthetic board entry: the same code, claiming `d`."""
    fp, sig = _identity(doc)
    rep = verify(doc, refute=False)
    return {
        "name": "the-entry.json",
        "n": doc["n"],
        "k": doc["k"],
        "d": d,
        "code_type": "CSS",
        "fingerprint": fp,
        "sig": sig,
        "css_fingerprints": [],
        "css_sigs": [],
        "weight_class": rep["computed"]["weight_class"],
        "w": rep["computed"]["max_check_weight"],
        "locality_class": rep["computed"]["locality_class"],
    }


def _against(board_d):
    """Validate the fixture against a board entry that claims `board_d`."""
    doc = _doc()
    real = V._board_entries
    V._board_entries = lambda: [_board_row(_doc(), board_d)]
    try:
        v = V.validate_candidate(doc, seed=0, refute=False)
    finally:
        V._board_entries = real
    assert v["gates"]["verify"]["ok"], v["gates"]["verify"]
    return v


def test_a_lower_claim_reads_as_a_revision():
    """Same checks, board claims more: this is a correction, and says so."""
    v = _against(board_d=9)
    labels = " ".join(v["labels"])
    assert "distance revision, not a duplicate" in labels
    assert "File it as a correction" in labels
    assert "claims d = 9" in labels and "candidate's d = 6" in labels
    assert v["gates"]["dedup"]["revision_of"] == "the-entry.json"
    assert not v["passed"], "it still must not pass the new-candidate path"


def test_an_equal_claim_is_still_a_duplicate():
    """The case dedup exists for keeps its old, blunt verdict."""
    v = _against(board_d=6)
    labels = " ".join(v["labels"])
    assert "duplicate: identical to board entry" in labels
    assert "revision" not in labels
    assert "revision_of" not in v["gates"]["dedup"]


def test_a_higher_claim_is_not_a_revision():
    """Claiming MORE than the board on identical checks is not a correction.

    A revision lowers a claim. Raising one on the same matrices is either a
    mistake or an over-claim, and must not be handed language that invites
    filing it as a correction.
    """
    v = _against(board_d=4)
    labels = " ".join(v["labels"])
    assert "duplicate: identical to board entry" in labels
    assert "revision" not in labels


def test_the_claim_is_not_part_of_the_code_s_identity():
    """Why #2583's proposal to fold `d` into the fingerprint was refused.

    The earlier version of this test called css_fingerprint twice on the same
    two matrices after editing `doc["distance"]["d"]`, which that function
    never reads, so it could not have failed. The property worth pinning is
    that the collision survives a differing claim: one candidate matches the
    SAME board entry whether that entry claims more, the same, or less, which
    is what catches a re-labelled copy filed under a new distance.
    """
    fps, dups = set(), set()
    for board_d in (9, 6, 4):
        v = _against(board_d)
        fps.add(v["candidate"]["fingerprint"])
        dups.add(v["gates"]["dedup"]["exact_duplicate_of"])
    assert len(fps) == 1, "the claim must not move the fingerprint"
    assert dups == {"the-entry.json"}, "and must not break the collision"
