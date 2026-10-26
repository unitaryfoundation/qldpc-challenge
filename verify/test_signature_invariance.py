"""The WL signature must be a function of the code, not of its claims (#1650).

The defect this pins was not in the colour refinement. The refinement was
correct; the hash payload carried `doc["distance"]["d"]`, so the signature of a
set of matrices changed whenever someone tightened a distance, and two
permutation-equivalent codes submitted at different claimed distances never
collided. That is how the board came to hold equivalent entries its own
duplicate check could not see.

The twin the issue reports, 390-82-31-b, left the board when #4143 removed
the permutation-equivalent duplicates, which is the outcome this file
protects, so the tests that need both documents read the removed one from
verify/fixtures/equivalence/, as the board held it.
"""
import copy
import glob
import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)

from qldpc_verify import signature  # noqa: E402
from two_block_equivalence import equivalent, scan  # noqa: E402


def load(slug):
    with open(os.path.join(_ROOT, "codes", f"{slug}.json"), encoding="utf-8") as f:
        return json.load(f)


FIXTURES = os.path.join(_HERE, "fixtures", "equivalence")


def fixture(slug):
    with open(os.path.join(FIXTURES, f"{slug}.json"), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def code():
    return load("390-82-31")


def test_a_tightened_distance_does_not_change_the_signature(code):
    """A refutation moves the claim, not the code."""
    before = signature(code)["hash"]
    lower = copy.deepcopy(code)
    lower["distance"]["d"] -= 1
    assert signature(lower)["hash"] == before


def test_a_wrong_k_claim_does_not_change_the_signature(code):
    """K is recomputed from the matrices, so a claim cannot move the hash."""
    before = signature(code)["hash"]
    wrong = copy.deepcopy(code)
    wrong["k"] -= 1
    assert signature(wrong)["hash"] == before


def test_two_permutation_equivalent_entries_collide(code):
    """The pair the issue reports, the twin as the board held it until #4143."""
    assert signature(code)["hash"] == signature(fixture("390-82-31-b"))["hash"]


def test_the_signature_still_separates_different_codes(code):
    """Removing the claim must not make the invariant useless.

    The check-weight profile and the recomputed k replace the discrimination
    the claimed distance was accidentally providing: without them, every
    cyclic two-block code at one blocklength collides, because WL refinement on
    a regular Tanner graph is close to trivial.
    """
    other = load("390-82-38")
    assert signature(code)["hash"] != signature(other)["hash"]


def test_the_equivalence_test_decides_rather_than_flags():
    """A WL collision is necessary, not sufficient; this closes the question."""
    a, b = load("390-82-31"), fixture("390-82-31-b")
    found = equivalent(a, b)
    assert found is not None, "a known equivalent pair was not decided"
    unit, _swapped = found
    assert unit > 1
    assert equivalent(a, load("390-82-38")) is None


def test_the_board_scan_names_the_pairs_it_finds():
    """The scan names the known pair, and the real board holds none since #4143."""
    pair = [os.path.join(_ROOT, "codes", "390-82-31.json"), os.path.join(FIXTURES, "390-82-31-b.json")]
    hits = scan(pair)
    assert {tuple(sorted((a, b))) for a, b, _ in hits} == {("390-82-31", "390-82-31-b")}
    for a, b, (unit, _sw) in hits:
        assert unit >= 1 and a != b
    # Over the real board, so a new permutation-equivalent duplicate fails here
    # instead of landing unnoticed.
    board = scan(sorted(glob.glob(os.path.join(_ROOT, "codes", "*.json"))))
    assert board == [], f"permutation-equivalent entries on the board: {board}"


def test_two_block_shape_without_the_circulant_structure_is_refused():
    """Refuse a code that has the two-block shape without the structure.

    The search reads one row per code, so it must not answer for a code that
    merely looks like a two-block code. Corrupting a single row of a genuine GB
    code leaves n, the row count and the first row intact, and must be refused.
    """
    import copy

    from two_block_equivalence import equivalent, is_generalised_bicycle

    a, b = load("390-82-31"), fixture("390-82-31-b")
    assert is_generalised_bicycle(a) and is_generalised_bicycle(b)
    assert equivalent(a, b) is not None            # the genuine pair still decides

    broken = copy.deepcopy(a)
    n = broken["n"]
    last = sorted(broken["checks"]["X"][-1])
    broken["checks"]["X"][-1] = sorted(set(last) ^ {(last[0] + 1) % (n // 2)})
    assert not is_generalised_bicycle(broken)
    assert equivalent(broken, b) is None
    assert equivalent(a, broken) is None
