"""Tests for the single-block annihilator attack (issue #2706).

The attack files distance revisions against public board entries, so what is
tested hardest is that it cannot report a weight it does not hold an
operator for. Every finding is re-derived from its own support here, against
the live code file, rather than taken from the attack's own report.

What no test here does is pin a distance value off a board entry. Those
numbers tighten by design -- #2901 moved this entry's Z side from 48 to 26 --
and the invariant underneath them (a witness weighs exactly what the record
claims, and d is the smaller side) is the gate's to enforce, re-derived for
every entry on every CI run. The test that pinned it turned one legitimate
tightening into a red verify for every open PR, so an entry's checks are read
here and its claims are not.
"""

import json
import os
import sys

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_HERE, "kit"))
sys.path.insert(0, os.path.join(_ROOT, "verify"))

from annihilator import (  # noqa: E402
    attack,
    attack_side,
    block_columns,
    matrix,
    subspace,
    verify_finding,
)

AUDIT = os.path.join(_ROOT, "research", "audits", "annihilator-sweep-2026-09-29.json")


def _code(slug):
    with open(os.path.join(_ROOT, "codes", slug + ".json"), encoding="utf-8") as f:
        doc = json.load(f)
    n = doc["n"]
    return doc, matrix(doc["checks"]["X"], n), matrix(doc["checks"]["Z"], n)


def test_the_subspace_is_what_one_block_annihilates():
    """Every member must be in the kernel of the checks, by construction."""
    _, HX, HZ = _code("312-10-26")
    n = HX.shape[1]
    cols = block_columns(n, "left")
    K = subspace(HX, cols)
    assert len(K), "the left block annihilates nothing, so there is no attack"
    for row in K:
        v = np.zeros(n, dtype=np.uint8)
        v[cols] = row
        assert int((HX @ v % 2).sum()) == 0


@pytest.mark.parametrize(
    "slug,side,block,weight",
    [
        ("312-10-26", "Z", "left", 26),
        ("360-10-28", "Z", "right", 30),
        ("824-210-20", "Z", "left", 24),
    ],
)
def test_it_reproduces_the_committed_sweep(slug, side, block, weight):
    """The 2026-09-29 sweep's findings, re-found rather than trusted."""
    _, HX, HZ = _code(slug)
    got = attack_side(HX, HZ, side, block, trials=40_000, seed=11)
    assert got.get("weight") == weight


def test_every_reported_support_is_a_logical_of_the_reported_type():
    _, HX, HZ = _code("824-210-20")
    got = attack_side(HX, HZ, "Z", "left", trials=40_000, seed=11)
    ok, w = verify_finding(HX, HZ, "Z", got["support"])
    assert ok and w == got["weight"]


def test_a_stabilizer_is_not_reported_as_a_logical():
    """A row of the same-type checks is in the subspace and means nothing."""
    _, HX, HZ = _code("312-10-26")
    n = HX.shape[1]
    row = HZ[0]
    if int(row.sum()) and max(np.nonzero(row)[0]) < n // 2:
        ok, _ = verify_finding(HX, HZ, "Z", list(np.nonzero(row)[0]))
        assert not ok, "a Z check is not a Z logical"


def test_a_non_css_entry_is_skipped_rather_than_failed():
    doc = {"n": 10, "checks": {"S": [[0, 1]]}, "distance": {"d": 3}}
    out = attack(doc, trials=100)
    assert out["verdict"] == "skipped" and "not CSS" in out["detail"]


def test_an_odd_blocklength_is_skipped():
    doc = {"n": 7, "checks": {"X": [[0, 1]], "Z": [[0, 1]]}, "distance": {"d": 3}}
    assert attack(doc, trials=100)["verdict"] == "skipped"


def test_the_committed_audit_is_internally_consistent():
    """Counts, per-target times, and findings have to agree."""
    path = os.path.join(_ROOT, "research", "audits", "annihilator-sweep-2026-10-04.json")
    with open(path, encoding="utf-8") as f:
        a = json.load(f)
    assert a["targets_run"] == len(a["results"]) == len(a["seconds_per_target"])
    counts = {}
    for r in a["results"]:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    assert counts == a["counts"]
    for r in a["results"]:
        if r["verdict"] in ("refuted", "tightened"):
            assert r["findings"], f"{r['slug']}: a verdict with no finding"
