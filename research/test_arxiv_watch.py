"""Tests for the arXiv watch (#2106), offline.

Everything the acceptance criteria turn on is behaviour under repolling: a paper
already seen must not come back as new, a version bump must come back as
updated, and a human verdict must survive both. Those are invariants of poll()
against a feed, so the feed here is canned Atom XML and no test touches the
network -- an autouse fixture breaks sockets, so an accidental live fetch fails
loudly instead of quietly hitting export.arxiv.org, which throttles.

The other property under test is that triage stays triage: a screened-in row
means "a human should read this", and a parameter set read out of an abstract
stays labelled as a claim, attributed to whoever the abstract attributes it to.
"""
import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arxiv_watch as W

NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)
TODAY = "2026-09-26"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Make any outbound connection fail the test that attempted it."""
    def boom(*_a, **_k):
        raise AssertionError("this test tried to reach the network")

    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    # the transport is a curl subprocess, which breaking sockets in this
    # process would not stop: without this the guard passes while the test
    # quietly queries arXiv
    monkeypatch.setattr(subprocess, "run", boom)


class _FrozenDatetime(datetime):
    """datetime with now() pinned to NOW, so a test that drives main() does not
    read the wall clock. The fixtures are dated 2026-09-25; against the real
    date they fall out of every --days window once a week has passed, which
    is how these tests began failing on 2026-10-03.
    """

    @classmethod
    def now(cls, tz=None):
        return NOW if tz is None else NOW.astimezone(tz)


def freeze_clock(monkeypatch):
    monkeypatch.setattr(W, "datetime", _FrozenDatetime)


def entry(arxiv_id, version=1, submitted="2026-09-25", updated=None,
          title="A code", summary="An abstract.", comment="",
          authors=("A. Author",), dates=True):
    """Build one Atom feed entry as arXiv serves it."""
    raw = f"{arxiv_id}v{version}"
    when = updated or submitted
    parts = [f"    <id>http://arxiv.org/abs/{raw}</id>"]
    if dates:
        parts.append(f"    <published>{submitted}T00:00:00Z</published>")
        parts.append(f"    <updated>{when}T00:00:00Z</updated>")
    parts.append(f"    <title>{title}</title>")
    parts.append(f"    <summary>{summary}</summary>")
    for a in authors:
        parts.append(f"    <author><name>{a}</name></author>")
    parts.append('    <arxiv:primary_category term="quant-ph"/>')
    parts.append('    <category term="quant-ph"/>')
    parts.append('    <category term="cs.IT"/>')
    if comment:
        parts.append(f"    <arxiv:comment>{comment}</arxiv:comment>")
    return "  <entry>\n" + "\n".join(parts) + "\n  </entry>"


def feed(entries, total=None, start=0):
    """Wrap entries in a feed, with the opensearch counts arXiv sends."""
    total = len(entries) if total is None else total
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<feed xmlns="http://www.w3.org/2005/Atom"\n'
            '      xmlns:arxiv="http://arxiv.org/schemas/atom"\n'
            '      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">\n'
            f"  <opensearch:totalResults>{total}</opensearch:totalResults>\n"
            f"  <opensearch:startIndex>{start}</opensearch:startIndex>\n"
            + "\n".join(entries) + "\n</feed>\n")


def pager(pages):
    """Return a fetcher serving `pages` (a list of XML strings) by start index."""
    calls = []

    def fetcher(query, start, batch):
        calls.append((query, start, batch))
        index = start // batch
        return pages[index] if index < len(pages) else feed([], total=0)

    fetcher.calls = calls
    return fetcher


def one_page(entries, total=None):
    """Return a fetcher serving a single page of `entries`."""
    return pager([feed(entries, total=total)])


def run(fetcher, ledger=None, days=7, **kw):
    """Poll with a canned fetcher, a fixed clock and no real sleeping."""
    kw.setdefault("now", NOW)
    kw.setdefault("sleep", lambda _s: None)
    return W.poll(days, ledger if ledger is not None else {}, fetcher=fetcher, **kw)


# --- the feed request itself -------------------------------------------------

def test_the_feed_is_ordered_by_last_update():
    """The cutoff is only sound if the feed is monotone in `updated`."""
    assert W.SORT_BY == "lastUpdatedDate"
    url = W.page_url("cat:quant-ph", 0, 100)
    assert "sortBy=lastUpdatedDate" in url
    assert "sortOrder=descending" in url


def test_the_network_guard_is_live():
    """The guard must actually be able to catch a stray fetch."""
    with pytest.raises(AssertionError, match="tried to reach the network"):
        W.fetch("cat:quant-ph", 0, 10)


def test_the_guard_covers_the_curl_transport():
    """Breaking sockets alone would not stop a subprocess from querying arXiv."""
    assert W.CURL, "curl is the transport; without it http_get cannot get a " \
                   "cache miss served"
    with pytest.raises(AssertionError, match="tried to reach the network"):
        W.http_get("https://export.arxiv.org/api/query?search_query=all:x")


def test_a_throttled_page_is_retried_then_raises(monkeypatch):
    """A 406 is waited out, not treated as fatal on the first sight of it."""
    codes = [406, 406, 200]
    waits = []
    monkeypatch.setattr(W, "http_get", lambda _u, _t=60: (codes.pop(0), "<x/>"))
    assert W.fetch("cat:quant-ph", 0, 10, sleep=waits.append) == "<x/>"
    assert waits == [W.BACKOFF_SECONDS, 2 * W.BACKOFF_SECONDS]

    monkeypatch.setattr(W, "http_get", lambda _u, _t=60: (406, ""))
    with pytest.raises(urllib.error.HTTPError):
        W.fetch("cat:quant-ph", 0, 10, retries=1, sleep=lambda _s: None)


def test_query_holds_the_vocabulary_the_board_is_built_from():
    """A paper that never writes "qLDPC" still has to enter the candidate set."""
    q = W.build_query()
    for term in ('abs:"qLDPC"', 'abs:"bivariate bicycle"', 'abs:"2BGA"',
                 'abs:"quasi-cyclic"', 'abs:"tile code"', 'abs:"twisted tori"'):
        assert term in q
    # classical-sounding wording stays gated to quant-ph, or it drags in the
    # whole cs.IT coding feed
    wide = q.split("OR ((cat:quant-ph OR cat:cs.IT")[1]
    assert "quasi-cyclic" not in wide.split("(cat:quant-ph) AND")[0]


# --- dedup and version updates ----------------------------------------------

def test_first_poll_announces_everything_then_a_repoll_announces_nothing():
    """The ledger is the dedup state: the same feed twice is one announcement."""
    f = one_page([entry("2609.00001", title="Bivariate bicycle codes"),
                  entry("2609.00002", title="Quantum Tanner codes")])
    new, updated, ledger, scan = run(f)
    assert sorted(r["id"] for r in new) == ["2609.00001", "2609.00002"]
    assert updated == []
    assert scan["complete"] is True

    new2, updated2, ledger2, _ = run(one_page([
        entry("2609.00001", title="Bivariate bicycle codes"),
        entry("2609.00002", title="Quantum Tanner codes")]), ledger)
    assert new2 == []
    assert updated2 == []
    assert set(ledger2) == {"2609.00001", "2609.00002"}


def test_a_version_bump_comes_back_as_updated_and_stays_on_the_row():
    """A v2 is announced once, and the row remembers it was ever bumped."""
    _, _, ledger, _ = run(one_page([entry("2609.00001", version=1)]))
    new, updated, ledger, _ = run(
        one_page([entry("2609.00001", version=2, updated="2026-09-26")]), ledger)
    assert new == []
    assert [(r["id"], r["prior_version"], r["version"]) for r in updated] == \
        [("2609.00001", 1, 2)]

    # the next poll does not re-announce it, and the history survives
    new, updated, ledger, _ = run(
        one_page([entry("2609.00001", version=2, updated="2026-09-26")]), ledger)
    assert (new, updated) == ([], [])
    row = ledger["2609.00001"]
    assert [h["version"] for h in row["version_history"]] == [1, 2]
    assert row["prior_version"] == 1


def test_a_new_version_of_an_old_submission_is_found():
    """The common case: v1 is from 2024, v3 landed yesterday."""
    old = entry("2401.99999", version=3, submitted="2024-01-15",
                updated="2026-09-25", title="Generalized bicycle codes")
    new, _, ledger, scan = run(one_page([old, entry("1801.00001",
                                                    submitted="2018-01-01",
                                                    updated="2018-01-01")]))
    assert [r["id"] for r in new] == ["2401.99999"]
    assert ledger["2401.99999"]["submitted"] == "2024-01-15"
    assert scan["complete"] is True
    assert "cutoff" in scan["stopped"]


def test_an_entry_with_no_dates_is_skipped_not_fatal():
    """A malformed entry must not end the scan and lose the rest of the page."""
    f = one_page([entry("2609.00001", dates=False), entry("2609.00002")])
    new, _, _, scan = run(f)
    assert [r["id"] for r in new] == ["2609.00002"]
    assert scan["complete"] is True


# --- metadata and provenance -------------------------------------------------

def test_the_row_records_the_metadata_used_for_triage():
    """Each alert has to carry the link, version and metadata it was judged on."""
    f = one_page([entry("2609.00001", version=2, title="Tile codes",
                        summary="We construct a [[144,12,12]] tile code.",
                        comment="Code at https://github.com/x/y",
                        authors=("A. One", "B. Two", "C. Three", "D. Four"))])
    new, _, _, _ = run(f)
    row, = new
    assert row["id"] == "2609.00001"
    assert row["version"] == 2
    assert row["link"] == "https://arxiv.org/abs/2609.00001v2"
    assert row["primary"] == "quant-ph"
    assert row["categories"] == ["quant-ph", "cs.IT"]
    assert len(row["authors"]) == 4
    assert "github" in row["comment"]
    assert row["first_seen"] == TODAY and row["last_seen"] == TODAY
    assert row["triage"]["screen"] == W.criteria_fingerprint()


def test_an_old_style_id_keeps_its_archive_prefix():
    """quant-ph/0601001 must key and link as itself, not as 0601001."""
    entries, _ = W.parse_feed(feed([entry("quant-ph/0601001", version=3)]))
    p, = entries
    assert p["id"] == "quant-ph/0601001"
    assert p["version"] == 3
    assert p["link"] == "https://arxiv.org/abs/quant-ph/0601001v3"
    assert W.split_arxiv_id("math/0601001") == ("math/0601001", 1)


# --- triage tiers ------------------------------------------------------------

def screen(title, abstract, comment=""):
    """Triage a title and abstract without going near a feed."""
    return W.triage({"title": title, "abstract": abstract, "comment": comment})


def test_screen_terms_keys_are_all_normalised():
    """A key with a capital or a hyphen can never match, so its weight is dead."""
    assert all(t == W._norm(t) for t in W.SCREEN_TERMS)


def test_generic_error_correction_vocabulary_does_not_screen_a_paper_in():
    """"construction" plus "distance" plus "parity-check" is every QEC paper."""
    t = screen("An explicit construction of quantum codes",
               "We give an explicit construction with improved distance and a "
               "sparse parity-check matrix.")
    assert t["matched"]
    assert t["tier"] == "background"
    assert t["screened_in"] is False


def test_a_decoder_paper_is_pushed_down_not_screened_in():
    """Papers that use codes rather than introduce one score below zero help."""
    t = screen("A belief propagation decoder for the surface code",
               "We benchmark a BP+OSD decoder and report the logical error "
               "rate under circuit-level noise, and the threshold.")
    assert t["tier"] == "background"
    assert t["screened_in"] is False


def test_a_family_name_screens_a_paper_in():
    """A construction family is a hard signal even with no parameters given."""
    t = screen("Quantum Tanner codes from expanders",
               "We construct quantum Tanner codes over a square complex.")
    assert "quantum tanner" in t["matched"]
    assert t["tier"] == "candidate"
    assert t["screened_in"] is True


def test_check_weight_and_locality_screen_a_paper_in():
    """The board's own axes are hard signals too."""
    t = screen("Geometrically local codes",
               "A geometrically local family with weight-6 checks.")
    assert t["tier"] == "candidate"
    assert t["screened_in"] is True


def test_parameters_plus_a_family_name_is_the_strong_tier():
    """The top of the reading queue: a stated code and a named construction."""
    t = screen("Bivariate bicycle codes with low weight",
               "We construct a [[144,12,12]] bivariate bicycle code.")
    assert t["tier"] == "strong"
    assert t["claimed_params"][0] == {"n": 144, "k": 12, "d": 12,
                                     "context": "We construct a [[144,12,12]] "
                                                "bivariate bicycle code",
                                     "comparison": False}


def test_parameters_attributed_to_other_work_are_not_this_papers_claim():
    """A comparison against a published code is not evidence about this paper."""
    t = screen("A decoder study",
               "We benchmark decoders, improving on the [[72,12,6]] code of "
               "prior work.")
    claim, = t["claimed_params"]
    assert claim["comparison"] is True
    assert "prior work" in claim["context"]
    assert t["screened_in"] is False
    assert t["score"] < W.PARAMS_BONUS


def test_a_claim_is_rendered_as_a_claim(capsys):
    """A distance out of an abstract is printed as claimed, never bare."""
    _, _, ledger, _ = run(one_page([entry(
        "2609.00001", title="Bicycle codes",
        summary="A [[400,16,24]] generalized bicycle code.")]))
    W.render(list(ledger.values()), "new", 10)
    out = capsys.readouterr().out
    assert "claims d = 24" in out
    assert "claimed in abstract" in out
    assert "review: unreviewed" in out


def test_the_json_payload_carries_the_disclaimer(capsys, tmp_path, monkeypatch):
    """A machine consumer must not read `params` and `flag` with no caveat."""
    freeze_clock(monkeypatch)
    path = str(tmp_path / "ledger.jsonl")
    monkeypatch.setattr(W, "fetch", one_page([entry(
        "2609.00001", summary="A [[144,12,12]] bivariate bicycle code.")]))
    assert W.main(["--json", "--ledger", path]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "unverified claim" in payload["disclaimer"]
    assert payload["screen"] == W.criteria_fingerprint()
    row, = payload["new"]
    assert "params" not in row["triage"]
    assert row["triage"]["claimed_params"][0]["d"] == 12
    assert row["triage"]["screened_in"] is True


# --- the human review path ---------------------------------------------------

def review(path, arxiv_id, status, reason, extra=()):
    """Drive the review path through main(), as an operator would."""
    return W.main(["--review", arxiv_id, "--status", status, "--reason", reason,
                   "--ledger", path, *extra])


def seeded(tmp_path, entries=None):
    """Write a one-poll ledger to a temporary path and return that path."""
    path = str(tmp_path / "ledger.jsonl")
    entries = entries or [entry("2609.00001", title="Bivariate bicycle codes",
                                summary="A [[144,12,12]] code.")]
    _, _, ledger, _ = run(one_page(entries))
    W.save_ledger(ledger, path)
    return path


def test_a_verdict_is_recorded_and_survives_a_later_poll(tmp_path):
    """The verdict is the point of the ledger; a repoll must not erase it."""
    path = seeded(tmp_path)
    assert review(path, "2609.00001", "relevant", "GB family, n<=288") == 0
    rows = W.load_ledger(path)
    assert rows["2609.00001"]["review"]["status"] == "relevant"
    assert rows["2609.00001"]["review"]["reason"] == "GB family, n<=288"
    assert rows["2609.00001"]["review"]["version"] == 1

    _, _, rows, _ = run(one_page([entry("2609.00001",
                                        title="Bivariate bicycle codes",
                                        summary="A [[144,12,12]] code.")]), rows)
    assert rows["2609.00001"]["review"]["status"] == "relevant"
    assert rows["2609.00001"]["review"].get("stale") is not True


def test_a_verdict_older_than_the_current_version_is_marked_stale(tmp_path):
    """A v1 verdict must not pass for a reading of v2."""
    path = seeded(tmp_path)
    review(path, "2609.00001", "not-relevant", "no explicit matrices")
    rows = W.load_ledger(path)
    _, updated, rows, _ = run(one_page([entry("2609.00001", version=2,
                                              updated="2026-09-26")]), rows)
    row, = updated
    assert row["review"]["status"] == "not-relevant"
    assert row["review"]["stale"] is True
    assert row["review"]["version"] == 1


def test_render_says_a_carried_verdict_predates_the_version(tmp_path, capsys):
    """The human re-reading the updated section has to see the verdict is old."""
    path = seeded(tmp_path)
    review(path, "2609.00001", "uncertain", "needs the matrices")
    rows = W.load_ledger(path)
    _, updated, _, _ = run(one_page([entry("2609.00001", version=2,
                                           updated="2026-09-26")]), rows)
    capsys.readouterr()
    W.render(updated, "new versions of papers already seen", 10)
    out = capsys.readouterr().out
    assert "uncertain (on v1" in out
    assert "needs re-reading" in out


def test_a_bare_review_cannot_destroy_a_considered_verdict(tmp_path):
    """--review with no reason is a usage error, not an "uncertain" verdict."""
    path = seeded(tmp_path)
    review(path, "2609.00001", "relevant", "GB family, n<=288")
    with pytest.raises(SystemExit) as e:
        W.main(["--review", "2609.00001", "--ledger", path])
    assert e.value.code == 2
    assert W.load_ledger(path)["2609.00001"]["review"]["status"] == "relevant"


def test_a_superseded_verdict_is_kept_as_history(tmp_path):
    """Re-reviewing keeps the earlier verdict rather than dropping it."""
    path = seeded(tmp_path)
    review(path, "2609.00001", "uncertain", "abstract only")
    review(path, "2609.00001", "relevant", "matrices in the appendix")
    row = W.load_ledger(path)["2609.00001"]
    assert row["review"]["status"] == "relevant"
    assert [r["status"] for r in row["reviews"]] == ["uncertain"]


def test_review_accepts_every_form_of_the_id_it_prints(tmp_path):
    """The tool must not reject the link and version string it just printed."""
    path = seeded(tmp_path)
    for form in ("arXiv:2609.00001", "2609.00001v1",
                 "https://arxiv.org/abs/2609.00001v1"):
        assert review(path, form, "uncertain", "same paper") == 0
    assert W.normalise_key("arXiv:quant-ph/0601001v2") == "quant-ph/0601001"


def test_review_of_an_unknown_id_fails_without_a_poll(tmp_path, capsys):
    """Nothing here may suggest a live poll as the fix for a typo."""
    path = seeded(tmp_path)
    assert review(path, "9999.99999", "relevant", "x") == 1
    assert "not in the ledger" in capsys.readouterr().err


def test_a_dry_run_review_writes_nothing(tmp_path):
    """--dry-run has to mean the same thing on both paths."""
    path = seeded(tmp_path)
    assert review(path, "2609.00001", "relevant", "x", extra=("--dry-run",)) == 0
    assert W.load_ledger(path)["2609.00001"]["review"]["status"] == "unreviewed"


def test_an_empty_review_id_does_not_fall_through_to_a_poll(tmp_path):
    """`--review ""` must be a usage error, not a live fetch."""
    path = seeded(tmp_path)
    with pytest.raises(SystemExit) as e:
        W.main(["--review", "", "--status", "relevant", "--reason", "x",
                "--ledger", path])
    assert e.value.code == 2


def test_the_ledger_can_be_read_back_by_status(tmp_path, capsys):
    """Half of "a human can mark a paper" is seeing the marks afterwards."""
    path = seeded(tmp_path, [entry("2609.00001", title="Bicycle codes",
                                   summary="A [[144,12,12]] code."),
                             entry("2609.00002", title="A decoder study",
                                   summary="We benchmark decoders.")])
    review(path, "2609.00001", "relevant", "GB family")
    capsys.readouterr()
    assert W.main(["--list", "relevant", "--ledger", path]) == 0
    out = capsys.readouterr().out
    assert "1 matching relevant" in out
    assert "2609.00001" in out and "2609.00002" not in out
    assert W.main(["--list", "unreviewed", "--ledger", path]) == 0
    out = capsys.readouterr().out
    assert "2609.00002" in out and "arXiv:2609.00001" not in out


# --- the mechanism a paper carries, and whether it was tried here (#4235) ----

def tag(path, arxiv_id, *mechanisms, status=None, reason=None, extra=()):
    """Drive --review with --mechanism tags, with or without a fresh verdict."""
    argv = ["--review", arxiv_id, "--ledger", path, *extra]
    if status is not None:
        argv += ["--status", status, "--reason", reason]
    for m in mechanisms:
        argv += ["--mechanism", m]
    return W.main(argv)


def tried(path, arxiv_id, mechanism, where, outcome, extra=()):
    """Drive --tried as an operator would."""
    return W.main(["--tried", arxiv_id, "--mechanism", mechanism, "--where", where,
                   "--outcome", outcome, "--ledger", path, *extra])


def test_a_verdict_can_name_the_mechanisms_the_paper_carries(tmp_path):
    """The tag is the transferable idea, kept as typed up to whitespace and case repeats."""
    path = seeded(tmp_path)
    review(path, "2609.00001", "uncertain", "abstract only")
    assert '"mechanisms"' not in open(path, encoding="utf-8").read()
    assert '"tried"' not in open(path, encoding="utf-8").read()
    assert tag(path, "2609.00001", " Pair  partition ", "pair partition", "mirror fold",
               status="relevant", reason="templates for [[90,21]]") == 0
    row = W.load_ledger(path)["2609.00001"]
    assert row["review"]["status"] == "relevant"
    assert row["review"]["mechanisms"] == ["Pair partition", "mirror fold"]
    assert W.mechanisms_of(row) == ["Pair partition", "mirror fold"]
    assert W.untried_mechanisms(row) == ["Pair partition", "mirror fold"]
    assert row["tried"] == []


def test_a_mechanism_alone_restates_the_standing_verdict_as_a_new_review(tmp_path):
    """Tagging is a review in the history, never an edit of one, and tags accumulate."""
    path = seeded(tmp_path)
    review(path, "2609.00001", "relevant", "GB family, n<=288")
    assert tag(path, "2609.00001", "twisted torus") == 0
    row = W.load_ledger(path)["2609.00001"]
    assert (row["review"]["status"], row["review"]["reason"]) == ("relevant", "GB family, n<=288")
    assert row["review"]["mechanisms"] == ["twisted torus"]
    assert [r["status"] for r in row["reviews"]] == ["relevant"]
    assert "mechanisms" not in json.loads(open(path, encoding="utf-8").read())["reviews"][0]
    review(path, "2609.00001", "uncertain", "needs the matrices")
    row = W.load_ledger(path)["2609.00001"]
    assert row["review"]["status"] == "uncertain"
    assert row["review"]["mechanisms"] == ["twisted torus"]
    assert tag(path, "2609.00001", "Twisted Torus", "coset quotient") == 0
    assert W.load_ledger(path)["2609.00001"]["review"]["mechanisms"] == [
        "twisted torus", "coset quotient"]


def test_a_mechanism_cannot_be_tagged_on_an_unreviewed_paper(tmp_path, capsys):
    """A tag without a verdict would be a verdict by the back door."""
    path = seeded(tmp_path)
    assert tag(path, "2609.00001", "twisted torus") == 1
    assert "no verdict" in capsys.readouterr().err
    assert W.load_ledger(path)["2609.00001"]["review"]["status"] == "unreviewed"
    assert tag(path, "2609.00001", "twisted torus", status="relevant", reason="x",
               extra=("--dry-run",)) == 0
    assert W.load_ledger(path)["2609.00001"]["review"]["status"] == "unreviewed"


def test_tried_records_where_a_mechanism_was_applied_and_survives_a_poll(tmp_path, monkeypatch):
    """Application is tracked apart from relevance, and a version bump does not lose it."""
    freeze_clock(monkeypatch)
    path = seeded(tmp_path)
    tag(path, "2609.00001", "pair partition", "mirror fold", status="relevant", reason="templates")
    assert tried(path, "2609.00001", "pair partition", "smoke-bb-72",
                 "ladders settled below the bar at 2M trials", extra=("--by", "me")) == 0
    row = W.load_ledger(path)["2609.00001"]
    assert row["tried"] == [{"mechanism": "pair partition", "where": "smoke-bb-72",
                             "outcome": "ladders settled below the bar at 2M trials",
                             "by": "me", "date": TODAY}]
    assert W.untried_mechanisms(row) == ["mirror fold"]
    _, updated, rows, _ = run(one_page([entry("2609.00001", version=2,
                                              updated="2026-09-26")]), W.load_ledger(path))
    bumped, = updated
    assert bumped["tried"] == row["tried"]
    assert bumped["review"]["mechanisms"] == ["pair partition", "mirror fold"]
    assert bumped["review"]["stale"] is True
    W.save_ledger(rows, path)
    assert W.load_ledger(path)["2609.00001"]["tried"] == row["tried"]


def test_where_must_be_something_a_reader_can_open(tmp_path, capsys):
    """A backlog entry pointing at a vanished scratch directory records nothing."""
    path = seeded(tmp_path)
    for where in ("research/candidates/20260901-x/90-21-11.json",
                  "research/campaigns/no-such-campaign", "/Users/me/scratch/run.log",
                  "../outside", "9999-1-1"):
        assert tried(path, "2609.00001", "pair partition", where, "x") == 1, where
        assert "--where:" in capsys.readouterr().err
    assert "tried" not in open(path, encoding="utf-8").read()
    accepted = ("#4235", "https://github.com/unitaryfoundation/qldpc-challenge/pull/4235",
                "smoke-bb-72", "codes/72-12-6.json", "72-12-6",
                "fieldnotes/2026-09-20-screening-traps-at-n-900.md")
    for where in accepted:
        assert tried(path, "2609.00001", "pair partition", where, "x") == 0, where
    assert [t["where"] for t in W.load_ledger(path)["2609.00001"]["tried"]] == list(accepted)


def test_tried_needs_a_mechanism_a_place_and_an_outcome(tmp_path):
    """Each half-record is a usage error, and the new flags do not fall through to a poll."""
    path = seeded(tmp_path)
    for argv in (["--tried", "2609.00001", "--where", "#1", "--outcome", "x"],
                 ["--tried", "2609.00001", "--mechanism", "m", "--outcome", "x"],
                 ["--tried", "2609.00001", "--mechanism", "m", "--where", "#1"],
                 ["--tried", "2609.00001", "--mechanism", "m", "--where", "#1", "--outcome", " "],
                 ["--tried", "", "--mechanism", "m", "--where", "#1", "--outcome", "x"],
                 ["--review", "2609.00001", "--mechanism", "m", "--where", "#1"],
                 ["--list", "untried", "--tried", "2609.00001"],
                 ["--where", "#1"], ["--mechanism", "m"]):
        with pytest.raises(SystemExit) as e:
            W.main([*argv, "--ledger", path])
        assert e.value.code == 2, argv
    assert W.load_ledger(path)["2609.00001"]["tried"] == []


def test_the_backlog_lists_papers_whose_mechanism_was_never_tried(tmp_path, capsys):
    """Relevant-but-never-tried is distinguishable from tried-and-failed."""
    path = seeded(tmp_path, [entry("2609.00001", title="Pair partitions"),
                             entry("2609.00002", title="Mirror folds"),
                             entry("2609.00003", title="A decoder")])
    tag(path, "2609.00001", "pair partition", status="relevant", reason="a")
    tag(path, "2609.00002", "mirror fold", "pair partition", status="relevant", reason="b")
    review(path, "2609.00003", "not-relevant", "decoder")
    tried(path, "2609.00002", "mirror fold", "#4235",
          "the fold needs an involution the BB torus lacks")
    capsys.readouterr()
    assert W.main(["--list", "untried", "--ledger", path]) == 0
    out = capsys.readouterr().out
    assert "2 matching untried" in out and "2609.00003" not in out
    assert "mechanisms: pair partition  (not tried here)" in out
    assert "mechanisms: mirror fold; pair partition\n" in out
    assert "not tried here: pair partition" in out
    assert W.main(["--list", "tried", "--ledger", path]) == 0
    out = capsys.readouterr().out
    assert "1 matching tried" in out
    assert "tried: mirror fold in #4235" in out and "involution" in out
    assert W.main(["--list", "mechanisms", "--ledger", path]) == 0
    out = capsys.readouterr().out
    assert "2 mechanisms on 2 papers, 2 papers with one not tried here" in out
    assert "pair partition: 2 paper(s), 2 not tried here" in out
    assert "mirror fold: 1 paper(s), 0 not tried here" in out
    assert "tried in #4235" in out
    assert W.main(["--list", "relevant", "--mechanism", "FOLD", "--ledger", path]) == 0
    out = capsys.readouterr().out
    assert "1 matching relevant naming FOLD" in out
    assert "2609.00002" in out and "arXiv:2609.00001" not in out
    assert W.main(["--list", "untried", "--json", "--ledger", path]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in payload["rows"]] == ["2609.00002", "2609.00001"]
    assert payload["rows"][0]["untried"] == ["pair partition"]
    assert payload["rows"][0]["tried"][0]["where"] == "#4235"
    assert payload["rows"][1]["mechanisms"] == ["pair partition"]
    assert "unverified claim" in payload["disclaimer"]


def test_a_tagged_and_tried_row_stays_within_its_own_budget():
    """The opt-in fields are capped too, so a tagged row has a known ceiling."""
    row = {
        "id": "2601.00001", "version": 2, "updated": "2026-01-02",
        "title": "A paper", "first_seen": "2026-01-01", "last_seen": "2026-01-02",
        "review": {"status": "relevant", "reason": "r" * 900, "by": "me",
                   "date": "2026-01-02", "version": 2,
                   "mechanisms": ["m" * 200, "n" * 200, "o" * 200, "M" * 200]},
        "tried": [{"mechanism": "m" * 200, "where": "w" * 500, "outcome": "x" * 900,
                   "by": "me", "date": "2026-01-02"},
                  {"mechanism": "   ", "where": "dropped", "outcome": "no mechanism"}],
    }
    slim = W.slim_row(row)
    blob = json.dumps(slim)
    assert len(blob) <= W.TAGGED_ROW_BUDGET_BYTES, f"a tagged row grew to {len(blob)} bytes"
    assert [len(m) for m in slim["review"]["mechanisms"]] == [W.MECHANISM_MAX] * 3
    assert len(slim["tried"]) == 1
    assert len(slim["tried"][0]["where"]) == W.WHERE_MAX
    assert len(slim["tried"][0]["outcome"]) == W.REASON_MAX

# --- the polling window ------------------------------------------------------

def test_the_default_window_reaches_back_to_the_previous_poll():
    """A skipped run widens the next window instead of leaving a hole."""
    ledger = {"x": {"id": "x", "last_seen": "2026-09-10"}}
    days, why = W.window_days(ledger, None, now=NOW)
    assert days == 16 + W.LAG_SLACK_DAYS
    assert "2026-09-10" in why
    days, why = W.window_days({}, None, now=NOW)
    assert days == W.DEFAULT_DAYS
    assert "no previous poll" in why


def test_an_explicit_window_shorter_than_the_gap_warns():
    """--days is honoured, but it must say what it is skipping."""
    ledger = {"x": {"id": "x", "last_seen": "2026-09-10"}}
    days, why = W.window_days(ledger, 7, now=NOW)
    assert days == 7
    assert "WARNING" in why and "16 days since the last poll" in why


# --- truncation --------------------------------------------------------------

def test_the_page_cap_is_reported_as_a_truncated_window():
    """A scan that runs out of pages inside the window must not pass as whole."""
    page = feed([entry(f"2609.{i:05d}") for i in range(4)], total=99)
    f = pager([page, page, page])
    new, _, _, scan = run(f, batch=4, pages=2)
    assert len(new) == 4
    assert scan["complete"] is False
    assert "page cap" in scan["stopped"]
    assert scan["pages_fetched"] == 2


def test_a_short_page_inside_the_window_is_retried_once_then_reported():
    """A short page is transient, and believing one loses the papers behind it."""
    short = feed([entry("2609.00001")], total=99)
    full = feed([entry("2609.00001"), entry("2609.00002"),
                 entry("2609.00003"), entry("2609.00004")], total=99)
    rest = feed([entry(f"2609.{i:05d}") for i in range(5, 9)], total=99)
    seq = [short, full, rest]

    def fetcher(_query, _start, _batch):
        return seq.pop(0) if seq else feed([], total=99)

    slept = []
    new, _, _, scan = run(fetcher, batch=4, pages=2, sleep=slept.append)
    assert len(new) == 8                     # the retry recovered the page
    assert W.BACKOFF_SECONDS in slept        # and it backed off first
    assert scan["complete"] is False
    assert "page cap" in scan["stopped"]


def test_reaching_the_end_of_results_is_a_complete_scan():
    """A short last page is only the end when opensearch says so."""
    f = pager([feed([entry("2609.00001"), entry("2609.00002")], total=2)])
    slept = []
    _, _, _, scan = run(f, batch=100, pages=3, sleep=slept.append)
    assert scan["complete"] is True
    assert "end of results" in scan["stopped"]
    assert slept == []                       # no pointless 30s retry


def test_a_truncated_window_warns_on_stderr(capsys, tmp_path, monkeypatch):
    """The operator has to be told the window was not covered."""
    freeze_clock(monkeypatch)
    page = feed([entry(f"2609.{i:05d}") for i in range(4)], total=99)
    monkeypatch.setattr(W, "fetch", pager([page, page, page, page]))
    assert W.main(["--days", "7", "--batch", "4", "--pages", "2",
                   "--ledger", str(tmp_path / "l.jsonl")]) == 0
    assert "window truncated" in capsys.readouterr().err


# --- ledger I/O --------------------------------------------------------------

def test_the_ledger_round_trips_one_object_per_line(tmp_path):
    """The dedup state is a file a human also hand-edits, so it must be stable."""
    path = str(tmp_path / "ledger.jsonl")
    _, _, ledger, _ = run(one_page([entry("2609.00002"), entry("2609.00001")]))
    W.save_ledger(ledger, path)
    first = open(path, encoding="utf-8").read()
    assert len(first.strip().splitlines()) == 2
    W.save_ledger(W.load_ledger(path), path)
    assert open(path, encoding="utf-8").read() == first


def test_an_unreadable_ledger_line_is_skipped_not_fatal(tmp_path, capsys):
    """One bad hand-edit must not stop every later poll."""
    path = tmp_path / "ledger.jsonl"
    path.write_text('{"id": "2609.00001", "submitted": "2026-09-25"}\n'
                    "not json at all\n"
                    '{"no_id": true}\n', encoding="utf-8")
    rows = W.load_ledger(str(path))
    assert list(rows) == ["2609.00001"]
    assert capsys.readouterr().err.count("unreadable ledger line") == 2


def test_a_ledger_path_with_no_directory_part_is_writable(tmp_path, monkeypatch):
    """os.makedirs("") is a crash, and --ledger takes a bare filename."""
    monkeypatch.chdir(tmp_path)
    W.save_ledger({"x": {"id": "x", "submitted": "2026-09-25"}}, "bare.jsonl")
    assert W.load_ledger("bare.jsonl")["x"]["id"] == "x"


def test_a_legacy_row_is_migrated_on_read(tmp_path):
    """Rows written before the rename must not read as verified parameters."""
    path = tmp_path / "ledger.jsonl"
    path.write_text(json.dumps({
        "id": "2609.00001", "submitted": "2026-09-25",
        "triage": {"score": 9, "matched": [], "params": [[144, 12, 12]],
                   "flag": True}}) + "\n", encoding="utf-8")
    t = W.load_ledger(str(path))["2609.00001"]["triage"]
    assert "params" not in t
    assert t["claimed_params"] == [{"n": 144, "k": 12, "d": 12,
                                   "context": "", "comparison": False}]
    assert t["screened_in"] is True

# -- the ledger stays small -----------------------------------------------

def test_the_ledger_stores_decisions_not_a_mirror_of_arxiv():
    """A field added later must not quietly put the bulk back.

    arXiv is the durable copy of a paper. Mirroring abstracts and author lists
    into this repository costs about 2.4 KiB per paper forever, on a feed that
    runs at roughly a hundred papers a month, for text nobody reads from here.
    """
    row = {
        "id": "2601.00001", "version": 2, "updated": "2026-01-02",
        "title": "A paper", "first_seen": "2026-01-01",
        "last_seen": "2026-01-02",
        "abstract": "x" * 4000, "authors": ["A" * 40] * 12,
        "comment": "y" * 500, "categories": ["quant-ph"] * 5,
        "triage": {"tier": "strong", "matched": ["a"] * 40,
                   "score": 21,
                   "claimed_params": [{"n": 90, "k": 21, "d": 11,
                                       "comparison": False,
                                       "context": "z" * 400}]},
        "review": {"status": "relevant", "reason": "r" * 900,
                   "by": "me", "date": "2026-01-02", "version": 2},
    }
    slim = W.slim_row(row)
    blob = json.dumps(slim)
    assert len(blob) <= W.ROW_BUDGET_BYTES, (
        f"a ledger row grew to {len(blob)} bytes")
    for dropped in ("abstract", "authors", "comment", "categories", "triage"):
        assert dropped not in slim, f"{dropped} reached the ledger"
    assert "context" not in slim["claimed_params"][0]
    assert slim["claimed_params"][0]["n"] == 90
    assert len(slim["review"]["reason"]) == W.REASON_MAX


def test_an_unreviewed_row_writes_no_review_block():
    """Absence carries the default; writing it out says nothing at a cost."""
    slim = W.slim_row(
        {"id": "2601.00002", "version": 1, "updated": "2026-01-02",
         "title": "t", "first_seen": "a", "last_seen": "b",
         "review": {"status": "unreviewed", "reason": "", "by": "",
                    "date": "", "version": None},
         "reviews": [], "version_history": [{"version": 1}]})
    for absent in ("review", "reviews", "version_history", "claimed_params"):
        assert absent not in slim
    assert len(json.dumps(slim)) < 200


def test_the_link_is_derived_from_the_row():
    assert W.arxiv_link({"id": "2609.30069", "version": 2}) == (
        "https://arxiv.org/abs/2609.30069v2")
