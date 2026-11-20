"""Maintainer-only: list or squash-merge open code PRs whose current CI and provenance qualify.

A maintainer tool, not part of the contributor flow: it reads every open PR,
and with --merge it both posts comments to and squash-merges other people's
pull requests, so it needs `gh` auth with merge rights on the repository and
should only be run by a maintainer. Report-only by default. Every merge is
pinned to the head SHA that was rechecked immediately beforehand.

Scope is one entry per PR: the unit the board files under a slug is
`codes/<slug>.json` plus `notes/<slug>.md`, so a PR carrying several code
records is a batch to read rather than one to merge, and it is reported and
skipped.
"""

import argparse
import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlencode

DEFAULT_REPO = "unitaryfoundation/qldpc-challenge"
DEFAULT_BASE = "main"
PAGE_SIZE = 100
REQUIRED_CHECKS = ("verify", "prose", "codes-format", "ruff")
# One entry per PR. Everything the board files for an entry hangs off its slug
# (`notes/<slug>.md`, `circuits/<slug>/`, `certs/<slug>.json`), so a PR touching
# two records is a batch whose provenance has to be read one entry at a time.
MAX_CODES_PER_PR = 1


class GitHubCLIError(RuntimeError):
    """A gh CLI request failed or returned invalid JSON."""


def _run_gh(args: list[str]) -> str:
    """Run gh without a shell and return stdout, raising on any error."""
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise GitHubCLIError(f"gh {' '.join(args)} failed: {detail}")
    return result.stdout


def _api_json(endpoint: str) -> Any:
    output = _run_gh(["api", endpoint])
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise GitHubCLIError(f"GitHub returned invalid JSON for {endpoint}: {exc}") from exc


def _api_text(endpoint: str) -> str:
    return _run_gh(
        [
            "api",
            "--header",
            "Accept: application/vnd.github.raw+json",
            endpoint,
        ]
    )


def _api_pages(endpoint: str, collection: str | None = None) -> list[dict[str, Any]]:
    """Fetch every page of a GitHub endpoint returning a list or named list."""
    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        separator = "&" if "?" in endpoint else "?"
        payload = _api_json(f"{endpoint}{separator}{urlencode({'per_page': PAGE_SIZE, 'page': page})}")
        page_rows = payload if collection is None else payload.get(collection)
        if not isinstance(page_rows, list):
            raise GitHubCLIError(f"GitHub response has no list field {collection!r} for {endpoint}")
        rows.extend(row for row in page_rows if isinstance(row, dict))
        if len(page_rows) < PAGE_SIZE:
            return rows
        page += 1


def list_open_prs(repo: str, base: str) -> list[dict[str, Any]]:
    endpoint = f"repos/{repo}/pulls?{urlencode({'state': 'open', 'base': base})}"
    return _api_pages(endpoint)


def list_pr_files(repo: str, number: int) -> list[dict[str, Any]]:
    return _api_pages(f"repos/{repo}/pulls/{number}/files")


def list_check_runs(repo: str, head_sha: str) -> list[dict[str, Any]]:
    endpoint = f"repos/{repo}/commits/{quote(head_sha, safe='')}/check-runs"
    return _api_pages(endpoint, collection="check_runs")


def _claim_paths(files: list[dict[str, Any]]) -> list[str]:
    """Return code records touched, including the source side of renames."""
    paths: set[str] = set()
    for item in files:
        for filename in (item.get("filename"), item.get("previous_filename")):
            if not isinstance(filename, str):
                continue
            if filename.startswith("codes/") and filename.endswith(".json"):
                paths.add(filename)
            elif filename.startswith("circuits/") and filename.count("/") >= 2:
                slug = filename.split("/", 2)[1]
                if slug:
                    paths.add(f"codes/{slug}.json")
    return sorted(paths)


def changed_code_paths(files: list[dict[str, Any]]) -> list[str]:
    """Return current code JSON paths touched directly or through circuits."""
    paths: set[str] = set()
    for item in files:
        filename = item.get("filename")
        if not isinstance(filename, str) or item.get("status") == "removed":
            continue
        if filename.startswith("codes/") and filename.endswith(".json"):
            paths.add(filename)
        elif filename.startswith("circuits/") and filename.count("/") >= 2:
            slug = filename.split("/", 2)[1]
            if slug:
                paths.add(f"codes/{slug}.json")
    return sorted(paths)


def too_many_codes_reason(code_paths: list[str]) -> str | None:
    """Return why a PR is out of scope for auto-merge, naming every record."""
    if len(code_paths) <= MAX_CODES_PER_PR:
        return None
    return (
        f"{len(code_paths)} code records in one PR ({', '.join(code_paths)}); "
        "auto-merge covers one code and its note per PR, so a maintainer reviews this one"
    )


def metadata_error(document: Any) -> str | None:
    """Validate that a code declares a model and at least one author."""
    if not isinstance(document, dict):
        return "code document is not a JSON object"
    provenance = document.get("provenance")
    if not isinstance(provenance, dict):
        return "missing provenance object"

    model = provenance.get("model")
    if isinstance(model, str):
        has_model = bool(model.strip())
    elif isinstance(model, list):
        has_model = bool(model) and all(isinstance(value, str) and value.strip() for value in model)
    else:
        has_model = False
    if not has_model:
        return "missing or empty provenance.model"

    authors = provenance.get("authors")
    if not isinstance(authors, list) or not authors:
        return "missing or empty provenance.authors"
    if any(not isinstance(author, str) or not author.strip() for author in authors):
        return "provenance.authors must contain non-empty strings"
    return None


def check_failures(runs: list[dict[str, Any]], head_sha: str) -> list[str]:
    """Require the latest validation, prose, format, and Ruff runs on this SHA."""
    failures: list[str] = []
    for check_name in REQUIRED_CHECKS:
        matching = [run for run in runs if run.get("name") == check_name and run.get("head_sha") == head_sha]
        if not matching:
            failures.append(f"missing {check_name} check on current head")
            continue
        latest = max(
            matching,
            key=lambda run: (run.get("started_at") or "", run.get("id") or 0),
        )
        if latest.get("status") != "completed" or latest.get("conclusion") != "success":
            status = latest.get("status", "unknown")
            conclusion = latest.get("conclusion") or "no conclusion"
            failures.append(f"{check_name} is {status}/{conclusion}")
    return failures


def _read_code_document(repo: str, path: str, head_sha: str) -> Any:
    encoded_path = quote(path, safe="/")
    endpoint = f"repos/{repo}/contents/{encoded_path}?{urlencode({'ref': head_sha})}"
    try:
        return json.loads(_api_text(endpoint))
    except json.JSONDecodeError as exc:
        raise GitHubCLIError(f"{path} at {head_sha} is not valid JSON: {exc}") from exc


_CACHE_MISS = object()
_THREAD_LOCAL = threading.local()


def _code_doc_cache() -> dict[tuple[int, str, str, str], Any]:
    cache = getattr(_THREAD_LOCAL, "cache", None)
    if cache is None:
        cache = {}
        _THREAD_LOCAL.cache = cache
    return cache


def _cached_read_code_document(repo: str, path: str, ref: str) -> Any:
    reader = _read_code_document
    key = (id(reader), repo, path, ref)
    cache = _code_doc_cache()
    cached = cache.get(key, _CACHE_MISS)
    if cached is not _CACHE_MISS:
        return cached
    result = reader(repo, path, ref)
    cache[key] = result
    return result


def _inherited_metadata_gap(
    repo: str, path: str, document: Any, error: str, base: str, base_path: str | None = None
) -> bool:
    """Report whether the PR inherited this provenance gap from the base entry rather than introducing it.

    True when the entry exists on ``base`` with the same missing field and the
    PR left ``provenance`` as it was, apart from appending to ``notes``. The base entry is
    read under ``base_path`` when the PR renamed the record: a distance revision
    files the entry under its new slug (CONTRIBUTING.md, "Correcting a distance
    already on the board"), so under ``path`` the base has nothing and the
    revision would pass for a new entry. A contribution to another author's
    entry (a circuit tier, a layout, a lowered circuit distance) passes
    verify/check_authorship.py only if it touches nothing in provenance but an
    appended note, so its author cannot add the field; requiring it would block
    every such PR on an omission the entry's author has to fix. A PR that adds
    the entry, or that changed provenance, is still held to the rule.
    """
    try:
        base_doc = _cached_read_code_document(repo, base_path or path, base)
    except GitHubCLIError:
        return False                      # no base entry: the PR adds it
    if not isinstance(base_doc, dict) or not isinstance(document, dict):
        return False
    if metadata_error(base_doc) != error:
        return False
    base_prov = base_doc.get("provenance") if isinstance(base_doc.get("provenance"), dict) else {}
    head_prov = document.get("provenance") if isinstance(document.get("provenance"), dict) else {}
    # The one provenance change the bindings admit from a non-author is an
    # appended sentence in notes (a refutation's credit, a contribution's
    # remark); everything else in provenance has to match the base.
    if {k: v for k, v in base_prov.items() if k != "notes"} != {k: v for k, v in head_prov.items() if k != "notes"}:
        return False
    old_notes, new_notes = str(base_prov.get("notes") or ""), str(head_prov.get("notes") or "")
    return new_notes.startswith(old_notes)


def _circuit_sides(document: Any) -> dict[str, int]:
    """Return {side: d_circ value} of a document's circuit block, empty when it has none."""
    circuit = document.get("circuit") if isinstance(document, dict) else None
    d_circ = circuit.get("d_circ") if isinstance(circuit, dict) else None
    out: dict[str, int] = {}
    for side in ("X", "Z"):
        value = ((d_circ or {}).get(side) or {}).get("value")
        if isinstance(value, int) and not isinstance(value, bool):
            out[side] = value
    return out


def circuit_regression(repo: str, path: str, document: Any, files: list[dict[str, Any]], base: str) -> str | None:
    """Name the side whose circuit fault distance this PR lowers while replacing the circuit.

    verify/check_authorship.py lets an entry's listed author replace its
    circuit with any other, and the gate only checks the new circuit's own
    claim, so on 2026-11-17 two circuit-tier PRs (#5911, #5934) merged with
    d_circ below the committed schedule's. A PR that changes a file under
    circuits/<slug>/ has filed a new circuit; its reading may not fall on any
    side. A lowered reading on the unchanged circuit is a refutation and is
    left to the refutation binding.
    """
    slug = path[len("codes/"):-len(".json")] if path.startswith("codes/") and path.endswith(".json") else None
    if slug is None:
        return None
    prefix = f"circuits/{slug}/"
    if not any(isinstance(item.get("filename"), str) and item["filename"].startswith(prefix) for item in files):
        return None
    try:
        base_doc = _cached_read_code_document(repo, path, base)
    except GitHubCLIError:
        return None                       # a new entry: nothing to regress from
    before, after = _circuit_sides(base_doc), _circuit_sides(document)
    fallen = [f"{side} {before[side]} -> {after[side]}" for side in ("X", "Z")
              if side in before and side in after and after[side] < before[side]]
    if not fallen:
        return None
    return f"{path}: the replacement circuit lowers d_circ ({', '.join(fallen)}); the committed circuit is better"


@dataclass
class Evaluation:
    number: int
    title: str
    url: str
    head_sha: str
    eligible: bool = False
    reasons: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    authors: list[str] = field(default_factory=list)
    metadata_errors: list[tuple[str, str]] = field(default_factory=list)
    inherited_gaps: list[tuple[str, str]] = field(default_factory=list)
    pr_author: str = ""
    claim_paths: list[str] = field(default_factory=list)


def evaluate_pr(repo: str, pr: dict[str, Any], base: str) -> Evaluation:
    _code_doc_cache().clear()
    number = int(pr["number"])
    head_sha = (pr.get("head") or {}).get("sha") or ""
    result = Evaluation(
        number=number,
        title=str(pr.get("title") or "(untitled)"),
        url=str(pr.get("html_url") or ""),
        head_sha=head_sha,
        pr_author=str((pr.get("user") or {}).get("login") or ""),
    )
    if pr.get("draft"):
        result.reasons.append("draft PR")
    if not result.pr_author:
        result.reasons.append("missing PR author identity")
    if (pr.get("base") or {}).get("ref") != base:
        result.reasons.append(f"base is not {base}")
    if not head_sha:
        result.reasons.append("missing PR head SHA")
        return result

    try:
        files = list_pr_files(repo, number)
        result.claim_paths = _claim_paths(files)
        code_paths = changed_code_paths(files)
        if not code_paths:
            result.reasons.append("no changed code JSON or associated circuit artifacts")
        else:
            # Blocked on scope, but still read every record: a batch PR's author
            # needs the same provenance feedback a single-entry PR gets.
            too_many = too_many_codes_reason(code_paths)
            if too_many:
                result.reasons.append(too_many)
            added = {item.get("filename") for item in files if item.get("status") == "added"}
            # a distance revision renames the record, so its base entry lives
            # under the name the PR replaced
            renamed_from = {
                item.get("filename"): item.get("previous_filename")
                for item in files
                if item.get("status") == "renamed" and isinstance(item.get("previous_filename"), str)
            }
            for path in code_paths:
                document = _cached_read_code_document(repo, path, head_sha)
                error = metadata_error(document)
                if error:
                    # a record this PR adds declares its own provenance; only a
                    # record that existed on base can have inherited a gap
                    inherited = path not in added and _inherited_metadata_gap(
                        repo, path, document, error, base, base_path=renamed_from.get(path)
                    )
                    if inherited:
                        # The field was already missing on the base entry and
                        # this PR left provenance alone: a contribution to an
                        # existing entry (a circuit tier, a layout, a lowered
                        # claim) whose author verify/check_authorship.py forbids
                        # from editing provenance. The gap is the entry
                        # author's to close and does not block the PR.
                        result.inherited_gaps.append((path, error))
                        result.models.append("(entry predates provenance.model)")
                        authors = (document.get("provenance") or {}).get("authors") or []
                        result.authors.extend(str(a) for a in authors)
                        continue
                    result.metadata_errors.append((path, error))
                    result.reasons.append(f"{path}: {error}")
                    continue
                provenance = document["provenance"]
                model = provenance["model"]
                result.models.extend([model] if isinstance(model, str) else model)
                result.authors.extend(provenance["authors"])
            for path in code_paths:
                head_doc = _cached_read_code_document(repo, path, head_sha)
                regression = circuit_regression(repo, path, head_doc, files, base)
                if regression:
                    result.reasons.append(regression)

        runs = list_check_runs(repo, head_sha)
        result.reasons.extend(check_failures(runs, head_sha))
    except (GitHubCLIError, KeyError, ValueError) as exc:
        result.reasons.append(f"could not verify PR: {exc}")

    result.eligible = not result.reasons
    return result


def _metadata_marker(head_sha: str) -> str:
    """Identify our auto-comment so one is posted per PR head at most."""
    return f"<!-- merge-eligibility-metadata:{head_sha} -->"


def metadata_comment_body(result: Evaluation) -> str | None:
    """Build an explanatory comment only for missing/empty model or authors."""
    relevant = [
        (path, error)
        for path, error in result.metadata_errors
        if "provenance.model" in error or "provenance.authors" in error
    ]
    if not relevant:
        return None

    marker = _metadata_marker(result.head_sha)
    lines = [
        "Auto-merge was skipped because this PR is missing required provenance metadata:",
    ]
    for path, error in relevant:
        lines.append(f"- `{path}`: `{error}`.")
    if any("provenance.model" in error for _, error in relevant):
        lines.append("Add a non-empty `provenance.model` value (an exact model version, or omit it; "
             "`human` claims a person, not a model, produced the code) to the code JSON.")
    if any("provenance.authors" in error for _, error in relevant):
        lines.append(
            "Add one or more non-empty names to `provenance.authors`; the `verify` check validates the author binding."
        )
    lines.extend(("", marker))
    return "\n".join(lines)


def post_metadata_comment(repo: str, result: Evaluation) -> bool:
    """Comment once per PR head when required model/author metadata is missing."""
    body = metadata_comment_body(result)
    if body is None:
        return False
    marker = _metadata_marker(result.head_sha)
    comments = _api_pages(f"repos/{repo}/issues/{result.number}/comments")
    if any(marker in str(comment.get("body") or "") for comment in comments):
        return False
    _run_gh(
        [
            "api",
            "--method",
            "POST",
            f"repos/{repo}/issues/{result.number}/comments",
            "--field",
            f"body={body}",
        ]
    )
    return True


def comment_if_metadata_is_still_missing(repo: str, base: str, result: Evaluation) -> bool:
    """Recheck a PR head before commenting on its missing provenance fields."""
    current = _refresh_pr(repo, result.number)
    current_sha = (current.get("head") or {}).get("sha")
    if current.get("state") != "open" or current_sha != result.head_sha:
        return False
    current_result = evaluate_pr(repo, current, base)
    if not current_result.metadata_errors:
        return False
    return post_metadata_comment(repo, current_result)


def block_overlapping_prs(evaluations: list[Evaluation]) -> None:
    """Fail closed when eligible PRs touch the same underlying code record."""
    owners: dict[str, list[Evaluation]] = {}
    for result in evaluations:
        if result.eligible:
            for path in result.claim_paths:
                owners.setdefault(path, []).append(result)

    for path, results in owners.items():
        if len(results) < 2:
            continue
        numbers = sorted(result.number for result in results)
        for result in results:
            others = [number for number in numbers if number != result.number]
            result.reasons.append(
                f"overlaps code record {path} with PR(s) " + ", ".join(f"#{number}" for number in others)
            )
            result.eligible = False


def _refresh_pr(repo: str, number: int) -> dict[str, Any]:
    payload = _api_json(f"repos/{repo}/pulls/{number}")
    if not isinstance(payload, dict):
        raise GitHubCLIError(f"GitHub returned invalid PR data for #{number}")
    return payload


def merge_pr(repo: str, number: int, head_sha: str) -> None:
    _run_gh(
        [
            "pr",
            "merge",
            str(number),
            "--repo",
            repo,
            "--squash",
            "--match-head-commit",
            head_sha,
        ]
    )


def _format_result(result: Evaluation, action: str) -> str:
    status = "ELIGIBLE" if result.eligible else "BLOCKED"
    if result.reasons:
        details = "; ".join(result.reasons)
    else:
        models = ", ".join(sorted(set(result.models)))
        authors = ", ".join(sorted(set(result.authors)))
        details = f"PR author=@{result.pr_author}; model={models}; authors={authors}"
        if result.inherited_gaps:
            details += "; inherited gap: " + ", ".join(f"{p} ({e})" for p, e in result.inherited_gaps)
    return f"{action:<10} {status:<8} #{result.number} {result.title} — {details}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Maintainer tool: report eligible code PRs. Report-only unless --merge is "
            "given; only current-head verify, prose, and codes-format successes are accepted."
        )
    )
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub owner/repo")
    parser.add_argument("--base", default=DEFAULT_BASE, help="target branch (default: main)")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--merge", action="store_true", help="squash-merge eligible PRs")
    action.add_argument("--dry-run", action="store_true", help="report only (the default)")
    args = parser.parse_args(argv)

    try:
        prs = list_open_prs(args.repo, args.base)
    except GitHubCLIError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    overall_error = False
    evaluations: list[Evaluation] = []

    # Drafts are reported (and skipped) up front so the parallel evaluation
    # below only handles PRs that actually need API work.
    for pr in prs:
        if pr.get("draft"):
            number = pr.get("number", "?")
            print(f"SKIP       BLOCKED  #{number} draft PR")

    non_draft_prs = [pr for pr in prs if not pr.get("draft")]

    def _safe_evaluate(pr: dict[str, Any]) -> tuple[str, Any]:
        try:
            return ("ok", evaluate_pr(args.repo, pr, args.base))
        except (GitHubCLIError, KeyError, ValueError) as exc:
            return ("error", exc)

    if non_draft_prs:
        max_workers = min(8, len(non_draft_prs))
        if max_workers < 1:
            max_workers = 1
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            outcomes = list(executor.map(_safe_evaluate, non_draft_prs))
        for pr, outcome in zip(non_draft_prs, outcomes):
            if outcome[0] == "ok":
                evaluations.append(outcome[1])
            else:
                overall_error = True
                print(f"ERROR      BLOCKED  #{pr.get('number', '?')} could not verify PR: {outcome[1]}")

    block_overlapping_prs(evaluations)
    for result in evaluations:
        if not result.eligible or not args.merge:
            if args.merge and result.metadata_errors:
                try:
                    posted = comment_if_metadata_is_still_missing(args.repo, args.base, result)
                    if posted:
                        print(f"COMMENTED  BLOCKED  #{result.number} missing provenance metadata")
                except (GitHubCLIError, KeyError, ValueError) as exc:
                    overall_error = True
                    print(f"ERROR      BLOCKED  #{result.number} metadata comment failed: {exc}")
            print(_format_result(result, "REPORT" if not args.merge else "SKIP"))
            continue

        try:
            refreshed = _refresh_pr(args.repo, result.number)
            refreshed_sha = (refreshed.get("head") or {}).get("sha")
            if refreshed_sha != result.head_sha or refreshed.get("state") != "open":
                print(f"SKIP       BLOCKED  #{result.number} PR changed or closed during evaluation")
                continue
            refreshed_result = evaluate_pr(args.repo, refreshed, args.base)
            if not refreshed_result.eligible:
                if refreshed_result.metadata_errors:
                    posted = post_metadata_comment(args.repo, refreshed_result)
                    if posted:
                        print(f"COMMENTED  BLOCKED  #{result.number} missing provenance metadata")
                print(_format_result(refreshed_result, "SKIP"))
                continue
            merge_pr(args.repo, result.number, result.head_sha)
            print(_format_result(result, "MERGED"))
        except (GitHubCLIError, KeyError, ValueError) as exc:
            overall_error = True
            print(f"ERROR      BLOCKED  #{result.number} merge failed: {exc}")

    return 1 if overall_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
