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


# -- staleness is a state, not a failure (issue #2391) --------------------
def _payload():
    with open(dp.DERIVED, encoding="utf-8") as f:
        return json.load(f)


def _write(payload, tmp_path, monkeypatch):
    p = tmp_path / "derived.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    monkeypatch.setattr(dp, "DERIVED", str(p))
    return p


def test_a_table_missing_new_board_entries_does_not_fail(tmp_path,
                                                         monkeypatch, capsys):
    """The table cannot be regenerated in CI, so it must not gate on coverage.

    Regenerating needs the literature index, which is deliberately not
    shipped. Failing on coverage meant the first code PR merged after the
    check landed turned main red, and the people blocked were exactly the
    ones who could not fix it.
    """
    payload = _payload()
    dropped = sorted(payload["entries"])[0]
    del payload["entries"][dropped]
    payload["counts"] = dp.counts(payload["entries"])
    _write(payload, tmp_path, monkeypatch)
    assert dp.check() == 0
    out = capsys.readouterr().out
    assert "STALE" in out and dropped in out, "staleness must be reported"


def test_a_broken_table_still_fails(tmp_path, monkeypatch):
    """Integrity is not relaxed: only coverage is."""
    payload = _payload()
    slug = next(s for s, v in payload["entries"].items()
                if v["bucket"] == "literature")
    payload["entries"][slug]["matches"] = []
    _write(payload, tmp_path, monkeypatch)
    assert dp.check() == 1, "literature with no evidence must fail"

    payload = _payload()
    slug = sorted(payload["entries"])[0]
    payload["entries"][slug]["bucket"] = "definitely_new"
    _write(payload, tmp_path, monkeypatch)
    assert dp.check() == 1, "an unknown bucket must fail"


def test_a_bucket_added_later_is_not_read_as_corruption(tmp_path, monkeypatch):
    """A table written before a bucket existed omits it rather than lying."""
    payload = _payload()
    # the shape a table written before the bucket existed actually has:
    # no not_derived rows and no not_derived key
    payload["entries"] = {s: v for s, v in payload["entries"].items()
                          if v["bucket"] != "not_derived"}
    payload["counts"] = {b: v for b, v
                         in dp.counts(payload["entries"]).items()
                         if b != "not_derived"}
    _write(payload, tmp_path, monkeypatch)
    assert dp.check() == 0, "omitting a later bucket is not corruption"


def test_top_up_records_new_entries_without_the_index(tmp_path, monkeypatch):
    """Anyone merging a code PR can reconcile coverage; no index needed."""
    payload = _payload()
    dropped = sorted(payload["entries"])[0]
    del payload["entries"][dropped]
    payload["entries"]["9999-0-0"] = {"bucket": "no_match", "matches": []}
    payload["counts"] = dp.counts(payload["entries"])
    _write(payload, tmp_path, monkeypatch)

    assert dp.top_up() == 0
    after = json.load(open(dp.DERIVED, encoding="utf-8"))["entries"]
    assert after[dropped]["bucket"] == "not_derived", \
        "a board entry the index has not seen is not_derived"
    assert "9999-0-0" not in after, "a departed entry is dropped"
    assert dp.check() == 0


def test_top_up_never_promotes_an_underived_entry(tmp_path, monkeypatch):
    """It records what is unknown; it must not launder it into a verdict."""
    payload = _payload()
    slug = next(s for s, v in payload["entries"].items()
                if v["bucket"] == "literature")
    before = dict(payload["entries"][slug])
    _write(payload, tmp_path, monkeypatch)
    dp.top_up()
    after = json.load(open(dp.DERIVED, encoding="utf-8"))["entries"][slug]
    assert after == before, "an already-derived row must not change"


def test_not_derived_is_distinct_from_no_match(tmp_path):
    """The distinction is the point: unchecked is not the same as cleared."""
    assert "not_derived" in dp.BUCKETS
    csvp = matches(tmp_path, [])
    covered = set(dp.board_slugs()[:5])
    table, _ = dp.derive(csvp, covered=covered)
    buckets = {s: v["bucket"] for s, v in table.items()}
    assert all(buckets[s] == "no_match" for s in covered)
    assert any(v == "not_derived" for v in buckets.values())


def test_the_residual_body_lists_every_unchecked_entry(tmp_path, capsys):
    """The tracking issue is the published remainder (issue #4023).

    Every not_derived entry must appear, nothing the index has seen may, and
    the count the workflow reads has to match the list it publishes.
    """
    out = tmp_path / "body.md"
    assert dp.residual(str(out), "https://example.invalid/runs/1") == 0
    body = out.read_text(encoding="utf-8")
    with open(dp.DERIVED, encoding="utf-8") as f:
        table = json.load(f)["entries"]
    stab = dp.stabilizer_slugs()
    pending = {s for s, v in table.items() if v["bucket"] == "not_derived" and s not in stab}
    outside = {s for s, v in table.items() if v["bucket"] == "not_derived" and s in stab}
    seen = {s for s, v in table.items() if v["bucket"] != "not_derived"}
    blocks = body.split("<details>")[1:]
    listed = set(blocks[0].split("</details>", 1)[0].split())
    assert pending <= listed and not ((seen | outside) & listed)
    if outside:
        # the entries no index run can settle are listed apart and left out of the count
        apart = set(blocks[1].split("</details>", 1)[0].split())
        assert outside <= apart and not (pending & apart) and "does not wait on them" in body
    assert f"{len(pending):,} of the board's {len(table):,} entries" in body
    assert "https://example.invalid/runs/1" in body
    assert capsys.readouterr().out.strip() == \
        f"not_derived={len(pending)} stabilizer_outside_method={len(outside)} entries={len(table)}"
