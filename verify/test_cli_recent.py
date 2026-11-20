"""Tests for `qldpc recent`.

The command is the "read before you search" step, so an agent or a newcomer
pays its output in context on every run. A busy fortnight adds hundreds of
codes, and printing all of them makes the command too expensive to run, which
is the same as not having it. What is tested here is that the default output
stays bounded regardless of history size, that the filters narrow both
sections, and that --full still reaches everything.
"""

import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stdout

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "cli"))
import qldpc  # noqa: E402


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    """Build a throwaway board.

    25 codes across two families, one with a research note, and three
    fieldnotes carrying frontmatter.
    """
    r = tmp_path_factory.mktemp("board")
    for d in ("codes", "notes", "fieldnotes"):
        (r / d).mkdir()
    for i in range(25):
        fam = "bivariate-bicycle" if i % 2 else "lifted-product"
        (r / "codes" / f"{100 + i}-4-6.json").write_text(
            json.dumps({"n": 100 + i, "k": 4, "family": fam, "name": f"test code {i}"})
        )
    (r / "notes" / "100-4-6.md").write_text("# note\n")
    # two committed campaign summaries (item 4 of issue #2314): one closed
    # lifted-product family with nothing surviving, one bicycle sweep with a
    # survivor; a third directory without a summary must not appear
    camp = r / "research" / "campaigns"
    for cid, fam, surv, neg in (("lp-sweep", "lifted-product", 0, 2), ("bb-sweep", "bivariate-bicycle", 1, 0)):
        (camp / cid).mkdir(parents=True)
        (camp / cid / "summary.json").write_text(
            json.dumps(
                {
                    "summary_version": 1,
                    "campaign_id": cid,
                    "campaign_name": f"{fam} sweep",
                    "status": "completed",
                    "stopped_by": {"type": "budget_exhausted", "detail": "done"},
                    "budget": {"consumed": {"candidates_screened": 40}},
                    "experiments": [{"family": fam, "seed": s, "survivors": surv} for s in range(3)],
                    "survivors": [{"slug": "200-8-10"}] * surv,
                    "frontier_advances": surv,
                    "negative_results": [{"what": "gate rejected"}] * neg,
                    "report": f"research/campaigns/{cid}/REPORT.md",
                }
            )
        )
    (camp / "no-summary").mkdir()
    (camp / "no-summary" / "campaign.json").write_text("{}")
    for name, topics in (("a", "[bivariate-bicycle, calibration]"), ("b", "[lifted-product]"), ("c", "[budgeting]")):
        (r / "fieldnotes" / f"2026-01-0{ord(name) - 96}-{name}.md").write_text(
            f"---\ntitle: fieldnote {name}\ntopics: {topics}\n---\n\nbody\n"
        )
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "t")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "board")
    return r


@pytest.fixture(autouse=True)
def _at(repo, monkeypatch):
    monkeypatch.setattr(qldpc, "_ROOT", str(repo))


def _run(*argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert qldpc.main(["recent", *argv]) == 0
    return buf.getvalue()


def test_default_output_is_bounded_and_says_what_it_held_back():
    out = _run()
    assert "25 codes (1 with a research note), 3 fieldnotes" in out
    assert out.count("[[") == 10  # the --limit default
    assert "... 15 more" in out


def test_limit_bounds_both_sections():
    out = _run("--limit", "2")
    assert out.count("[[") == 2
    assert "... 23 more" in out
    assert "... 1 more" in out  # fieldnotes: 3 shown as 2


def test_full_prints_every_row():
    out = _run("--full")
    assert out.count("[[") == 25
    assert "more (--limit" not in out


def test_family_filter_narrows_every_section():
    out = _run("--family", "lifted-product", "--full")
    assert out.count("[[") == 13
    assert "fieldnote b" in out
    assert "fieldnote a" not in out
    assert "lp-sweep: completed, 3 experiments, 0 survivors" in out
    assert "bb-sweep" not in out
    assert ("(of 25 codes, 3 fieldnotes, and 2 campaign summaries in the window)") in out


def test_committed_campaign_summaries_are_listed_as_data():
    out = _run("--full")
    assert "3 fieldnotes, 2 campaign summaries" in out
    assert "campaign summaries (committed research/campaigns/*/summary.json):" in out
    assert "research/campaigns/bb-sweep/summary.json" in out
    assert (
        "bb-sweep: completed, 3 experiments, 1 survivor, 1 frontier advance, 0 negative results  [bivariate-bicycle]"
    ) in out
    assert (
        "lp-sweep: completed, 3 experiments, 0 survivors, 0 frontier advances, 2 negative results  [lifted-product]"
    ) in out
    assert "no-summary" not in out  # a directory without a summary


def test_limit_bounds_the_campaign_section_too():
    out = _run("--limit", "1")
    assert out.count("-sweep/summary.json") == 1
    assert "... 1 more (--limit N, --full)" in out


def test_json_record_carries_all_three_sections():
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert qldpc.main(["recent", "--json", "--family", "lifted-product"]) == 0
    rec = json.loads(buf.getvalue())
    assert rec["ok"] and rec["days"] == 14 and rec["filters"] == ["lifted-product"]
    assert rec["counts"] == {"codes": 25, "fieldnotes": 3, "campaigns": 2, "codes_with_note": 1}
    assert len(rec["codes"]) == 13 and all("hay" not in c for c in rec["codes"])
    assert [f["title"] for f in rec["fieldnotes"]] == ["fieldnote b"]
    (c,) = rec["campaigns"]
    assert c["campaign_id"] == "lp-sweep" and c["negative_results"] == 2
    assert c["families"] == ["lifted-product"] and c["survivors"] == 0
    assert c["budget_consumed"] == {"candidates_screened": 40}
    assert c["path"] == "research/campaigns/lp-sweep/summary.json"


def test_topic_filter_matches_fieldnote_topics():
    out = _run("--topic", "budgeting", "--full")
    assert out.count("[[") == 0
    assert "fieldnote c" in out
    assert "0 codes" in out


def test_fieldnote_summary_carries_the_title_and_topics():
    out = _run("--full")
    assert "fieldnote a  [bivariate-bicycle, calibration]" in out
