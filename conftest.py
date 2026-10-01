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
