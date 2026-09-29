"""Derived provenance has to be honest about what it does not know.

The failure this guards against is not a wrong bucket, it is a confident one:
an index match against our own search reported as literature, or a no-match
read as proof that a code is new.
"""
import csv
import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import derive_provenance as dp  # noqa: E402

COLS = ["board_slug", "other_id", "other_source", "xz_swapped",
        "permutation_verified"]


def matches(tmp_path, rows):
    p = tmp_path / "m.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({**{c: "" for c in COLS}, **r})
    return str(p)


def a_board_slug():
    return dp.board_slugs()[0]


def test_a_match_against_our_own_search_is_not_literature(tmp_path):
    """The index carries this project's deep-search output as well as papers.

    Tagging one of those as literature would report a code we found as a code
    someone published, which is the exact claim the tag exists to make.
    """
    slug = a_board_slug()
    csvp = matches(tmp_path, [
        {"board_slug": slug, "other_id": "deepsearch:x",
         "other_source": "deep_search_2026-09", "permutation_verified": "True"}])
    table, unknown = dp.derive(csvp)
    assert table[slug]["bucket"] == "no_match"
    assert not unknown, "a classified non-literature source is not 'unknown'"


def test_an_unclassified_source_is_never_promoted(tmp_path):
    """A source nobody has classified must not default to literature.

    Adding an index source should be a deliberate act, not something that
    silently reclassifies board entries on the next run.
    """
    slug = a_board_slug()
    csvp = matches(tmp_path, [
        {"board_slug": slug, "other_id": "z", "other_source": "brand_new_index",
         "permutation_verified": "True"}])
    table, unknown = dp.derive(csvp)
    assert table[slug]["bucket"] == "no_match"
    assert unknown["brand_new_index"] == 1, "the source must be reported"


def test_an_unverified_permutation_does_not_count(tmp_path):
    """Equivalence is the verified permutation, not the canonical form alone."""
    slug = a_board_slug()
    csvp = matches(tmp_path, [
        {"board_slug": slug, "other_id": "2bga:x",
         "other_source": "lin_pryadko_2bga_abelian",
         "permutation_verified": "False"}])
    table, _ = dp.derive(csvp)
    assert table[slug]["bucket"] == "no_match"


def test_a_published_match_carries_its_reference(tmp_path):
    slug = a_board_slug()
    csvp = matches(tmp_path, [
        {"board_slug": slug, "other_id": "2bga:x",
         "other_source": "lin_pryadko_2bga_abelian",
         "permutation_verified": "True"}])
    table, _ = dp.derive(csvp)
    assert table[slug]["bucket"] == "literature"
    m = table[slug]["matches"][0]
    assert m["ref"] == "arXiv:2306.16400" and m["id"] == "2bga:x"


def test_a_bounds_only_source_lands_in_parameters_only(tmp_path):
    """codetables.de gives bounds and no construction, so nothing is decided."""
    slug = a_board_slug()
    csvp = matches(tmp_path, [
        {"board_slug": slug, "other_id": "ct:[[64,8,4]]",
         "other_source": "codetables", "permutation_verified": "True"}])
    table, _ = dp.derive(csvp)
    assert table[slug]["bucket"] == "parameters_only"


def test_every_board_slug_is_bucketed(tmp_path):
    """No entry may be missing from the table; absence would read as zero."""
    table, _ = dp.derive(matches(tmp_path, []))
    assert set(table) == set(dp.board_slugs())
    assert all(v["bucket"] in dp.BUCKETS for v in table.values())


def test_the_committed_table_matches_the_board():
    """The shipped table must describe today's codes/, or say so loudly."""
    assert dp.check() == 0


def test_the_committed_table_states_its_own_limits():
    """no_match must not be readable as a novelty claim."""
    with open(dp.DERIVED, encoding="utf-8") as f:
        payload = json.load(f)
    assert "not a proof" in payload["caveat"] or \
           "not that the code is unpublished" in payload["caveat"]
    assert payload["counts"] == dp.counts(payload["entries"])


def test_literature_entries_all_carry_evidence():
    with open(dp.DERIVED, encoding="utf-8") as f:
        table = json.load(f)["entries"]
    lit = [(s, v) for s, v in table.items() if v["bucket"] == "literature"]
    assert lit, "the board has published reproductions on it"
    for slug, v in lit:
        assert v["matches"], f"{slug}: literature with no match"
        for m in v["matches"]:
            assert m["ref"] and m["source"] and m["id"], f"{slug}: thin evidence"


def test_no_entry_is_literature_via_an_excluded_source():
    """The exclusion list is load-bearing; nothing may slip past it."""
    _, not_lit, _ = dp.load_sources()
    with open(dp.DERIVED, encoding="utf-8") as f:
        table = json.load(f)["entries"]
    for slug, v in table.items():
        for m in v["matches"]:
            assert m["source"] not in not_lit, \
                f"{slug}: bucketed from an excluded source {m['source']}"
