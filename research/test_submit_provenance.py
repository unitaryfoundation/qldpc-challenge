"""make_submission records the witness search it ran (issue #2779).

The budget a bound was found at and has survived is what the next refuter
needs to beat, and the schema has carried a field for it since #611. The kit
spent the budget on every packaging call and wrote none of it. What is pinned
here: the block is written on both sides, it validates, the credit defaults
to the authors as handles and can be overridden, and an author that is not a
handle does not produce an invalid document.
"""

import os
import sys

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_HERE, "kit"))
sys.path.insert(0, os.path.join(_ROOT, "verify"))

from bb import build_bb  # noqa: E402
from submit import make_submission, validate  # noqa: E402

pytest.importorskip("jsonschema")


@pytest.fixture(scope="module")
def code():
    return build_bb(6, 6, [(3, 0), (0, 1), (0, 2)], [(0, 3), (1, 0), (2, 0)])


def _doc(code, **kw):
    HX, HZ = code
    args = dict(
        name="[[72,12,6]] test", construction="bb", authors=["tester"], family="bivariate-bicycle", trials=300, seed=5
    )
    args.update(kw)
    return make_submission(HX, HZ, **args)


def test_both_sides_carry_the_search_that_found_them(code):
    doc = _doc(code)
    assert not validate(doc), validate(doc)
    assert doc["schema_version"] == "0.2"
    for side, seed in (("X", 5), ("Z", 6)):
        wp = doc["distance"][side]["witness_provenance"]
        assert wp["found_by"] == ["@tester"]
        assert wp["found_at_samples"] == 300 and wp["survived_samples"] == 300
        assert wp["seeds"] == [seed]
        assert wp["tool"] == "research/kit/surrogate.lightest_logical"
        assert wp["date"] == doc["provenance"]["date"]


def test_credit_can_name_someone_other_than_the_packager(code):
    doc = _doc(code, found_by=["@finder", "helper"])
    for side in ("X", "Z"):
        assert doc["distance"][side]["witness_provenance"]["found_by"] == ["@finder", "@helper"]
    assert doc["provenance"]["authors"] == ["tester"]
    assert not validate(doc)


def test_authors_that_are_not_handles_do_not_break_the_document(code):
    doc = _doc(code, authors=["Magic State Labs"])
    assert "witness_provenance" not in doc["distance"]["X"]
    assert doc["schema_version"] == "0.1"
    assert not validate(doc)
    mixed = _doc(code, authors=["Magic State Labs", "@vprusso"])
    assert mixed["distance"]["X"]["witness_provenance"]["found_by"] == ["@vprusso"]


def test_the_budget_recorded_is_the_budget_spent(code):
    """Two packagings of one code at different budgets are no longer identical."""
    a, b = _doc(code, trials=200), _doc(code, trials=400)
    assert a["distance"]["X"]["witness_provenance"]["found_at_samples"] == 200
    assert b["distance"]["X"]["witness_provenance"]["found_at_samples"] == 400
    assert a["checks"] == b["checks"]


def test_the_verifier_accepts_the_block(code):
    import qldpc_verify

    doc = _doc(code)
    rep = qldpc_verify.verify(doc, refute=False)
    assert rep["ok"], [c for c in rep["checks"] if not c["ok"]]
    assert isinstance(np.asarray(doc["distance"]["X"]["witness"]), np.ndarray)
