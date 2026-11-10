"""Import paths for the test suite.

This repo is deliberately not installable (`[tool.uv] package = false`), so
`verify/` and `research/kit/` are plain directories rather than packages and
nothing in them is importable by name. Every test used to open with its own
`sys.path.insert` pair to work around that. pytest imports this file before
collecting anything, so the fix belongs here once instead of in every test.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))

for _rel in ("verify", os.path.join("research", "kit"), "research", "cli", "site"):
    _p = os.path.join(ROOT, _rel)
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

# Gitignored staging output, so never present in CI; the test_*.py files here are
# search scripts that collect zero tests but run their search at import, which can
# hang the suite or fail collection outright.
collect_ignore_glob = ["research/candidates", "research/candidates/*"]


@pytest.fixture(autouse=True)
def _no_board_memo(monkeypatch):
    """Keep the on-disk board memo out of every test that did not ask for it.

    `board_reports` gained a disk memo under research/candidates/.boardcache
    (issue #2582). It is keyed on each entry's bytes and on the pinned
    validation closure, so a hit is what a fresh call would compute, but a
    test suite that reads it is no longer hermetic: whether a given test pays
    for a structural pass would depend on what the developer's last campaign
    left behind, and the tests that count `verify` calls would pass or fail
    on that. CI never has the directory, so this is also what makes a local
    run resemble CI. A test that wants the memo sets the variable itself.
    """
    monkeypatch.setenv("QLDPC_BOARD_CACHE", "")


def pytest_configure(config):
    """Register `board`, the marker for a test that reads the committed data as a whole.

    Most of the suite tests code against fixtures it builds itself, and a pull
    request that changes only data cannot change what those tests do, so
    verify.yml skips the suite for it. A few tests are about the data: they
    walk every entry under codes/, or every certificate under certs/, and say
    whether the board as committed is consistent. A data-only pull request is
    exactly what can fail one of those, and with the suite skipped it merged
    and failed on main instead (#5249, #5250 and #5251 each added a code whose
    family tag verify/test_family_tag_consistency.py rejects; main stayed red
    until #5275). verify.yml now runs `run_tests.py -m board` for such a pull
    request.

    Mark a test `board` when its verdict depends on the committed contents of
    codes/, circuits/, certs/ or repro/ as a set rather than on entries it
    names, and it is cheap enough to run on every submission. A test that
    names the entries it reads needs no marker: the workflow finds it by slug
    (issue #2940). An unmarked test still runs on every push to main.

    Cheap means cheap in a process of its own, which is how the workflow runs
    the marked set: time it with `python run_tests.py -m board --durations=20`.
    The full suite hides the cost of a test that needs the whole board loaded
    and deduplicated, because an earlier test has usually paid for the load
    they share. Such a test takes minutes alone and does not belong here.

    Do not mark a test whose repair lies outside the data: a data-only pull
    request cannot carry it, since check_submission_scope.py refuses one that
    also touches verify/. verify/test_validation_gate.py compares the bytes of
    eleven pinned entries with goldens under verify/fixtures/, so a pull
    request that legitimately corrects one of those entries fails it, and only
    a maintainer's re-pin can turn it green (#4227 with #4288, #4818 with
    #4808, #4967 with #4963). That test stays unmarked; it still runs on main
    and on any pull request that touches code.
    """
    config.addinivalue_line(
        "markers",
        "board: reads the committed codes/, circuits/, certs/ or repro/ tree as a whole; "
        "verify.yml runs these in place of the suite for a data-only pull request")
