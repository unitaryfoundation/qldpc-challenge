"""A construction that names its family must carry that family's tag.

`family` is self-declared and used to filter, never to rank, so a wrong tag
never invalidates a claim. What it does is hide the entry: every query by
family misses it, including the ones that set campaign targets.

That is not hypothetical. 21 pair-partition CPM codes were tagged
`lifted-product` while their own construction text named the family and cited
its paper. One of them, `904-230-22`, is the `unrestricted x weight-8` leader
at kd^2/n 123.14, and a campaign was scoped to hunt d=21 in that family for a
target near 112, i.e. to look for something strictly worse than the board
already held, because the leader was invisible to the query that set the
target.

This checks the direction that costs something: if the construction names a
family unambiguously, the tag has to agree. It deliberately does not check the
converse, because a construction is free not to mention its family, so a
missing tag is a gap rather than a contradiction.
"""
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)

from qldpc_verify import _FAMILIES  # noqa: E402

# How far into the construction counts as naming the family. Long enough for
# the usual "<family> CSS code (<paper>)" lead, short enough that a mechanism
# mentioned later in the sentence does not trip the rule. The window is
# measured in characters and can cut mid-token, so every pattern below is
# written to match on its own rather than to rely on where the cut lands.
OPENING = 90

# (tag, how a construction names that family). Anchored on the citation as
# well as the prose, because one family is written several ways:
# "Pair-partition CPM", "Cyclic all-one pair-partition CPM" and "Okada-Kasai
# pair-partition CPM" are one thing. The pair-partition pattern also matches
# the symplectic-halved variant of arXiv:2609.30069 on purpose: it is a
# pair-partition CPM code built by a different recipe and belongs in the same
# filter.
RULES = [
    ("pair-partition-cpm",
     re.compile(r"pair[- ]partition|2607\.14091|2609\.30069", re.I)),
    ("bivariate-bicycle", re.compile(r"\bbivariate[- ]bicycle\b", re.I)),
    ("generalized-bicycle", re.compile(r"\bgenerali[sz]ed[- ]bicycle\b", re.I)),
]
assert all(f in _FAMILIES for f, _ in RULES), \
    "a rule names a family the verifier does not accept"

# Two families can both be true of one code, and then the more specific tag is
# the right one. A construction naming F excuses tag T only when T is at least
# as specific as F. The open-boundary tile codes keep `tile` over
# `bivariate-bicycle`, and a derived code keeps `check-deletion` over the
# family of the entry it came from.
#
# Checking instead that the construction merely mentions T anywhere lets a
# method note excuse a wrong tag: "Pair-partition CPM CSS code (lifted product
# of a 3x8 base matrix)" passes under `lifted-product` that way. That version
# caught 19 of the 21 codes above, including neither 632-162-18 nor
# 664-170-18, which is why specificity is explicit here rather than inferred
# from the text.
MORE_SPECIFIC = {
    "pair-partition-cpm": {"lifted-product", "hypergraph-product", "other"},
    "tile": {"bivariate-bicycle", "generalized-bicycle", "topological",
             "other"},
    "2bga-coset": {"generalized-bicycle", "other"},
    "check-deletion": {"bivariate-bicycle", "generalized-bicycle",
                       "pair-partition-cpm", "lifted-product",
                       "hypergraph-product", "tile", "other"},
}


def _entries():
    root = os.path.join(_ROOT, "codes")
    for fname in sorted(os.listdir(root)):
        if not fname.endswith(".json"):
            continue
        with open(os.path.join(root, fname), encoding="utf-8") as f:
            yield fname[:-5], json.load(f)


def _excused(tag, family):
    """Report whether `tag` describes the code at least as specifically."""
    return tag == family or family in MORE_SPECIFIC.get(tag, ())


def _contradictions(slug, doc):
    con = str((doc.get("provenance") or {}).get("construction") or "")
    tag = doc.get("family")
    if not con or not tag:
        return []
    out = []
    for family, pat in RULES:
        if _excused(tag, family):
            continue          # `continue`, not `break`: later rules apply too
        m = pat.search(con[:OPENING])
        if m:
            out.append(
                f"  {slug}: construction names {family!r} "
                f"(matched {m.group(0)!r}) but family={tag!r}\n"
                f"      {con[:OPENING].strip()}")
    return out


def test_a_construction_that_names_its_family_carries_that_tag():
    problems = []
    for slug, doc in _entries():
        problems.extend(_contradictions(slug, doc))
    assert not problems, (
        f"{len(problems)} entries whose family tag contradicts their own "
        "construction text; a filter by family will not find them:\n"
        + "\n".join(problems[:20]))


def test_every_rule_family_has_a_site_label():
    """A tag the site cannot label or filter hides the entry a different way.

    The 21 codes this test exists for were tagged `lifted-product`, and the
    correct tag was outside the verifier's vocabulary, so fixing the data
    alone would have traded a wrong filter for a missing one.
    """
    sys.path.insert(0, os.path.join(_ROOT, "site"))
    from build import FAMILY_LABEL, FAMILY_TERM
    for family, _ in RULES:
        assert family in _FAMILIES, f"{family} missing from _FAMILIES"
        assert family in FAMILY_LABEL, f"{family} has no site label"
        assert family in FAMILY_TERM, f"{family} has no filter pill"
