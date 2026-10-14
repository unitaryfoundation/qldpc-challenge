"""Tests for cli/merge_eligible_prs.py, the maintainer-only merge helper.

The behaviors worth pinning are the fail-closed ones: metadata and current-head
check requirements, the one-code-and-its-note scope, overlap blocking between
PRs claiming the same code record, the head-SHA pin on the merge command, and
that comments are only ever posted in --merge mode.
"""

from typing import Any

from cli import merge_eligible_prs


def _code_document(model: Any = "Claude Opus 5", authors: list[Any] | None = None):
    return {
        "provenance": {
            "model": model,
            "authors": authors if authors is not None else ["@submitter"],
        }
    }


def _successful_checks(head_sha="abc123"):
    return [
        {
            "id": 1,
            "name": "verify",
            "head_sha": head_sha,
            "status": "completed",
            "conclusion": "success",
            "started_at": "2026-09-25T10:00:00Z",
        },
        {
            "id": 2,
            "name": "prose",
            "head_sha": head_sha,
            "status": "completed",
            "conclusion": "success",
            "started_at": "2026-09-25T10:01:00Z",
        },
    ]


def _pr():
    return {
        "number": 17,
        "title": "Add a code",
        "html_url": "https://github.com/example/repo/pull/17",
        "draft": False,
        "state": "open",
        "user": {"login": "submitter"},
        "head": {"sha": "abc123"},
        "base": {"ref": "main"},
    }


def test_metadata_requires_model_and_declared_authors():
    assert merge_eligible_prs.metadata_error(_code_document()) is None
    assert merge_eligible_prs.metadata_error(_code_document(model="  ")) == ("missing or empty provenance.model")
    assert merge_eligible_prs.metadata_error(_code_document(authors=[])) == ("missing or empty provenance.authors")
    assert (
        merge_eligible_prs.metadata_error(_code_document(authors=["@submitter", None]))
        == "provenance.authors must contain non-empty strings"
    )


def test_metadata_accepts_a_nonempty_model_ensemble():
    assert merge_eligible_prs.metadata_error(_code_document(model=["Claude Opus 5", "GPT-5.6 Luna"])) is None
    assert merge_eligible_prs.metadata_error(_code_document(model=[])) == ("missing or empty provenance.model")


def test_claim_paths_tracks_both_sides_of_a_code_rename():
    files = [
        {
            "filename": "codes/666-150-48.json",
            "previous_filename": "codes/666-150-66.json",
            "status": "renamed",
        }
    ]
    assert merge_eligible_prs._claim_paths(files) == [
        "codes/666-150-48.json",
        "codes/666-150-66.json",
    ]


def test_metadata_comment_explains_missing_provenance_fields():
    result = merge_eligible_prs.Evaluation(
        17,
        "Add a code",
        "",
        "abc123",
        metadata_errors=[
            ("codes/10-2-3.json", "missing or empty provenance.model"),
            ("codes/10-2-3.json", "missing or empty provenance.authors"),
        ],
    )

    body = merge_eligible_prs.metadata_comment_body(result)

    assert body is not None
    assert "Auto-merge was skipped" in body
    assert "codes/10-2-3.json" in body
    assert "provenance.model" in body
    assert "provenance.authors" in body
    assert "merge-eligibility-metadata:abc123" in body


def test_metadata_comment_is_deduplicated_per_pr_head(monkeypatch):
    result = merge_eligible_prs.Evaluation(
        17,
        "Add a code",
        "",
        "abc123",
        metadata_errors=[("codes/10-2-3.json", "missing or empty provenance.model")],
    )
    calls = []
    monkeypatch.setattr(merge_eligible_prs, "_api_pages", lambda _endpoint: [])
    monkeypatch.setattr(merge_eligible_prs, "_run_gh", lambda args: calls.append(args) or "")

    assert merge_eligible_prs.post_metadata_comment("example/repo", result)
    assert len(calls) == 1
    marker = "merge-eligibility-metadata:abc123"
    monkeypatch.setattr(
        merge_eligible_prs,
        "_api_pages",
        lambda _endpoint: [{"body": f"Already commented <!-- {marker} -->"}],
    )
    assert not merge_eligible_prs.post_metadata_comment("example/repo", result)
    assert len(calls) == 1


def test_metadata_comment_rechecks_pr_head_and_metadata(monkeypatch):
    stale = merge_eligible_prs.Evaluation(
        17,
        "Add a code",
        "",
        "abc123",
        metadata_errors=[("codes/10-2-3.json", "missing or empty provenance.model")],
    )
    posted = []
    monkeypatch.setattr(merge_eligible_prs, "_refresh_pr", lambda _repo, _number: _pr())
    monkeypatch.setattr(
        merge_eligible_prs,
        "evaluate_pr",
        lambda _repo, _pr_data, _base: merge_eligible_prs.Evaluation(
            17,
            "Add a code",
            "",
            "abc123",
            metadata_errors=[("codes/10-2-3.json", "missing or empty provenance.model")],
        ),
    )
    monkeypatch.setattr(
        merge_eligible_prs,
        "post_metadata_comment",
        lambda _repo, result: posted.append(result.number) or True,
    )
    assert merge_eligible_prs.comment_if_metadata_is_still_missing("example/repo", "main", stale)
    assert posted == [17]

    monkeypatch.setattr(
        merge_eligible_prs,
        "_refresh_pr",
        lambda _repo, _number: {**_pr(), "head": {"sha": "new-sha"}},
    )
    assert not merge_eligible_prs.comment_if_metadata_is_still_missing("example/repo", "main", stale)
    assert posted == [17]


def test_block_overlapping_eligible_prs_for_same_code():
    first = merge_eligible_prs.Evaluation(17, "first", "", "a", eligible=True, claim_paths=["codes/x.json"])
    second = merge_eligible_prs.Evaluation(18, "second", "", "b", eligible=True, claim_paths=["codes/x.json"])
    unrelated = merge_eligible_prs.Evaluation(19, "other", "", "c", eligible=True, claim_paths=["codes/y.json"])

    merge_eligible_prs.block_overlapping_prs([first, second, unrelated])

    assert not first.eligible
    assert not second.eligible
    assert first.reasons == ["overlaps code record codes/x.json with PR(s) #18"]
    assert second.reasons == ["overlaps code record codes/x.json with PR(s) #17"]
    assert unrelated.eligible


def test_changed_code_paths_includes_circuit_entries_but_not_deleted_codes():
    files = [
        {"filename": "codes/10-2-3.json", "status": "modified"},
        {"filename": "codes/20-4-5.json", "status": "removed"},
        {"filename": "circuits/30-6-7/memory_x.stim", "status": "added"},
        {"filename": "notes/10-2-3.md", "status": "modified"},
    ]
    assert merge_eligible_prs.changed_code_paths(files) == [
        "codes/10-2-3.json",
        "codes/30-6-7.json",
    ]


def test_one_code_with_its_note_is_the_unit_of_auto_merge(monkeypatch):
    assert merge_eligible_prs.too_many_codes_reason(["codes/10-2-3.json"]) is None
    monkeypatch.setattr(
        merge_eligible_prs,
        "list_pr_files",
        lambda _repo, _number: [
            {"filename": "codes/10-2-3.json", "status": "added"},
            {"filename": "notes/10-2-3.md", "status": "added"},
        ],
    )
    monkeypatch.setattr(
        merge_eligible_prs,
        "_read_code_document",
        lambda _repo, _path, _sha: _code_document(),
    )
    monkeypatch.setattr(
        merge_eligible_prs,
        "list_check_runs",
        lambda _repo, _sha: _successful_checks(),
    )

    result = merge_eligible_prs.evaluate_pr("example/repo", _pr(), "main")

    assert result.eligible
    assert result.reasons == []


def test_pr_carrying_more_than_one_code_is_blocked(monkeypatch):
    monkeypatch.setattr(
        merge_eligible_prs,
        "list_pr_files",
        lambda _repo, _number: [
            {"filename": "codes/10-2-3.json", "status": "added"},
            {"filename": "notes/10-2-3.md", "status": "added"},
            {"filename": "codes/20-4-5.json", "status": "added"},
            {"filename": "notes/20-4-5.md", "status": "added"},
        ],
    )
    monkeypatch.setattr(
        merge_eligible_prs,
        "_read_code_document",
        lambda _repo, _path, _sha: _code_document(),
    )
    monkeypatch.setattr(
        merge_eligible_prs,
        "list_check_runs",
        lambda _repo, _sha: _successful_checks(),
    )

    result = merge_eligible_prs.evaluate_pr("example/repo", _pr(), "main")

    assert not result.eligible
    assert result.reasons == [
        "2 code records in one PR (codes/10-2-3.json, codes/20-4-5.json); "
        "auto-merge covers one code and its note per PR, so a maintainer reviews this one"
    ]
    assert result.metadata_errors == []
    assert result.models == ["Claude Opus 5", "Claude Opus 5"]


def test_a_second_code_reached_only_through_circuits_also_blocks(monkeypatch):
    monkeypatch.setattr(
        merge_eligible_prs,
        "list_pr_files",
        lambda _repo, _number: [
            {"filename": "codes/10-2-3.json", "status": "modified"},
            {"filename": "circuits/20-4-5/memory_z.stim", "status": "added"},
        ],
    )
    monkeypatch.setattr(
        merge_eligible_prs,
        "_read_code_document",
        lambda _repo, _path, _sha: _code_document(),
    )
    monkeypatch.setattr(
        merge_eligible_prs,
        "list_check_runs",
        lambda _repo, _sha: _successful_checks(),
    )

    result = merge_eligible_prs.evaluate_pr("example/repo", _pr(), "main")

    assert not result.eligible
    assert len(result.reasons) == 1
    assert "codes/20-4-5.json" in result.reasons[0]


def test_blocked_batch_pr_still_reports_its_missing_metadata(monkeypatch):
    monkeypatch.setattr(
        merge_eligible_prs,
        "list_pr_files",
        lambda _repo, _number: [
            {"filename": "codes/10-2-3.json", "status": "added"},
            {"filename": "codes/20-4-5.json", "status": "added"},
        ],
    )
    monkeypatch.setattr(
        merge_eligible_prs,
        "_read_code_document",
        lambda _repo, path, _sha: _code_document(model=None) if path == "codes/20-4-5.json" else _code_document(),
    )
    monkeypatch.setattr(
        merge_eligible_prs,
        "list_check_runs",
        lambda _repo, _sha: _successful_checks(),
    )

    result = merge_eligible_prs.evaluate_pr("example/repo", _pr(), "main")

    assert not result.eligible
    assert result.metadata_errors == [("codes/20-4-5.json", "missing or empty provenance.model")]
    assert merge_eligible_prs.metadata_comment_body(result) is not None


def test_a_batch_pr_is_never_merged(monkeypatch):
    result = merge_eligible_prs.Evaluation(
        17,
        "Add two codes",
        "",
        "abc123",
        reasons=[
            "2 code records in one PR (codes/10-2-3.json, codes/20-4-5.json); "
            "auto-merge covers one code and its note per PR, so a maintainer reviews this one"
        ],
    )
    merges = []
    monkeypatch.setattr(merge_eligible_prs, "list_open_prs", lambda _repo, _base: [_pr()])
    monkeypatch.setattr(merge_eligible_prs, "evaluate_pr", lambda _repo, _pr, _base: result)
    monkeypatch.setattr(
        merge_eligible_prs,
        "merge_pr",
        lambda _repo, _number, _sha: merges.append(_number),
    )

    assert merge_eligible_prs.main(["--merge"]) == 0
    assert merges == []


def test_checks_require_success_on_the_current_head():
    assert merge_eligible_prs.check_failures(_successful_checks(), "abc123") == []
    failures = merge_eligible_prs.check_failures(_successful_checks(), "new-sha")
    assert failures == [
        "missing verify check on current head",
        "missing prose check on current head",
    ]


def test_latest_check_run_must_be_successful():
    runs = _successful_checks()
    runs.append(
        {
            "id": 3,
            "name": "verify",
            "head_sha": "abc123",
            "status": "in_progress",
            "started_at": "2026-09-25T10:02:00Z",
        }
    )
    assert merge_eligible_prs.check_failures(runs, "abc123") == ["verify is in_progress/no conclusion"]


def test_pr_eligibility_requires_changed_code_metadata_and_required_checks(monkeypatch):
    monkeypatch.setattr(
        merge_eligible_prs,
        "list_pr_files",
        lambda _repo, _number: [{"filename": "codes/10-2-3.json", "status": "modified"}],
    )
    monkeypatch.setattr(
        merge_eligible_prs,
        "_read_code_document",
        lambda _repo, _path, _sha: _code_document(),
    )
    monkeypatch.setattr(
        merge_eligible_prs,
        "list_check_runs",
        lambda _repo, _sha: _successful_checks(),
    )
    result = merge_eligible_prs.evaluate_pr("example/repo", _pr(), "main")
    assert result.eligible
    assert result.reasons == []
    assert result.models == ["Claude Opus 5"]
    assert result.authors == ["@submitter"]
    assert result.pr_author == "submitter"


def test_pr_eligibility_fails_closed_for_missing_model_or_check(monkeypatch):
    monkeypatch.setattr(
        merge_eligible_prs,
        "list_pr_files",
        lambda _repo, _number: [{"filename": "codes/10-2-3.json", "status": "modified"}],
    )
    monkeypatch.setattr(
        merge_eligible_prs,
        "_read_code_document",
        lambda _repo, _path, _sha: _code_document(model=None),
    )
    monkeypatch.setattr(
        merge_eligible_prs,
        "list_check_runs",
        lambda _repo, _sha: _successful_checks()[:1],
    )
    result = merge_eligible_prs.evaluate_pr("example/repo", _pr(), "main")
    assert not result.eligible
    assert "codes/10-2-3.json: missing or empty provenance.model" in result.reasons
    assert "missing prose check on current head" in result.reasons


def test_metadata_comment_is_only_posted_in_merge_mode(monkeypatch):
    result = merge_eligible_prs.Evaluation(
        17,
        "Add a code",
        "",
        "abc123",
        reasons=["codes/10-2-3.json: missing or empty provenance.model"],
        metadata_errors=[("codes/10-2-3.json", "missing or empty provenance.model")],
    )
    comments = []
    monkeypatch.setattr(merge_eligible_prs, "list_open_prs", lambda _repo, _base: [_pr()])
    monkeypatch.setattr(merge_eligible_prs, "_refresh_pr", lambda _repo, _number: _pr())
    monkeypatch.setattr(merge_eligible_prs, "evaluate_pr", lambda _repo, _pr, _base: result)
    monkeypatch.setattr(
        merge_eligible_prs,
        "post_metadata_comment",
        lambda _repo, _result: comments.append(_result.number) or True,
    )

    assert merge_eligible_prs.main(["--dry-run"]) == 0
    assert comments == []
    assert merge_eligible_prs.main(["--merge"]) == 0
    assert comments == [17]


def test_merge_command_is_squash_and_pinned_to_inspected_head(monkeypatch):
    calls = []
    monkeypatch.setattr(merge_eligible_prs, "_run_gh", lambda args: calls.append(args) or "")
    merge_eligible_prs.merge_pr("example/repo", 17, "abc123")
    assert calls == [
        [
            "pr",
            "merge",
            "17",
            "--repo",
            "example/repo",
            "--squash",
            "--match-head-commit",
            "abc123",
        ]
    ]
