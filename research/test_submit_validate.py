"""`submit.validate` says "valid" or raises; it never says `[]` for "not checked" (issue #3616).

Before this the schema path pointed one directory too high, at
``research/schema/code.schema.json``, which does not exist, and the bare
``except Exception: return []`` hid it, so the kit's schema check passed every
document since the kit moved into ``research/kit/``.
"""
import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "kit"))

from submit import _SCHEMA_PATH, validate  # noqa: E402

GOOD = {
    "schema_version": "0.1",
    "name": "[[4,2,2]] validate test code",
    "code_type": "CSS",
    "n": 4,
    "k": 2,
    "checks": {"X": [[0, 1, 2, 3]], "Z": [[0, 1, 2, 3]]},
    "distance": {
        "d": 2,
        "X": {"value": 2, "confidence": "upper_bound", "witness": [0, 1]},
        "Z": {"value": 2, "confidence": "upper_bound", "witness": [0, 2]},
    },
    "provenance": {"authors": ["@tester"], "construction": "a test fixture",
                   "date": "2026-10-17", "references": [], "notes": ""},
}


def test_the_schema_it_reads_exists():
    assert os.path.exists(_SCHEMA_PATH), _SCHEMA_PATH


def test_a_valid_document_has_no_violations():
    assert validate(GOOD) == []


def test_a_violation_is_reported_where_it_is():
    bad = json.loads(json.dumps(GOOD))
    del bad["n"]
    errs = validate(bad)
    assert errs == ["<root>: 'n' is a required property"]


def test_without_jsonschema_it_raises_rather_than_passing(monkeypatch):
    monkeypatch.setitem(sys.modules, "jsonschema", None)
    with pytest.raises(RuntimeError, match="jsonschema"):
        validate(GOOD)
