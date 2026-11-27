#!/usr/bin/env bash
# Triage a batch of staged candidates without opening PRs.
#
# Usage:
#   scripts/bulk_candidate_triage.sh candidate1.json candidate2.json ...
#
# Runs the kit's duplicate collapse first, then the trusted validation gate
# (research/kit/coordination.py gate) on each candidate, writing
# <candidate>.verdict.json beside it. Prints a one-line status per candidate
# so a bulk run can be screened before any PR is opened.
#
# Tier 0: touches only research/ and scripts/. Does not modify verify/.
set -euo pipefail

if [ "$#" -eq 0 ]; then
    echo "usage: $0 <candidate.json>..." >&2
    exit 2
fi

echo "=== duplicate collapse ==="
uv run python research/kit/dedup_submissions.py "$@" || true
echo

if ! uv run --extra research python -c "import sys; sys.path.insert(0, 'verify'); import gf2_fast" >/dev/null 2>&1; then
    echo "WARNING: verify/gf2_fast is not importable; the gate runs shallow Python passes only." >&2
    echo "         Copy verify/gf2_fast.cpython-*.so into verify/ (see AGENTS.md worktree recipe)." >&2
fi

echo "=== per-candidate gate ==="
rc=0
for f in "$@"; do
    echo "--- $f ---"
    if uv run --extra research python research/kit/coordination.py gate "$f"; then
        echo "PASSED: $f"
    else
        echo "BLOCKED: $f"
        rc=1
    fi
done

exit "$rc"
