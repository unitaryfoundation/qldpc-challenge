"""The ignore rules are a policy per path (issue #3380); this pins it.

certs/ is wholly committed and stays unignored; the research/ working
directories that check_prose refuses as evidence are ignored; agent
scaffolding and machine-local config never reach the tree.
"""
import os
import subprocess
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)

import check_prose  # noqa: E402

IGNORED = [
    "research/candidates/700-10-20.json", "research/claims/weight-6.json",
    "research/out/run.jsonl", "research/runs/2026-10-14/ledger.jsonl",
    "research/board.json", "research/board-cache.json", "research/_scratch.py",
    "verify/_sweep_ub.py", ".prs/3380.md", ".pr-body-3380.md", "session-ses_abc.md",
    "opencode.json", "gap.deb", "build/gf2_fast313/x.o", "verify/gf2_fast.so", "run.log",
]
COMMITTED = [
    "certs/700-10-20.json", "certs/heuristic/700-10-20.json", "certs/proof_log_batch.jsonl",
    "codes/700-10-20.json", "notes/700-10-20.md", "research/kit/search.py",
    "research/campaigns/sweep/run.py", "research/campaigns/sweep/summary.json",
    "research/build_dense_surface.py", "verify/check_prose.py",
]


def ignored(path):
    r = subprocess.run(["git", "check-ignore", "-q", "--no-index", path],
                       cwd=ROOT, check=False, capture_output=True)
    return r.returncode == 0


@pytest.mark.parametrize("path", IGNORED)
def test_working_output_and_scaffolding_are_ignored(path):
    assert ignored(path)


@pytest.mark.parametrize("path", COMMITTED)
def test_committed_homes_are_not_ignored(path):
    assert not ignored(path)


def test_every_directory_check_prose_refuses_as_evidence_is_ignored():
    for d in check_prose.GITIGNORED:
        assert ignored(d.rstrip("/") + "/x.json"), d
