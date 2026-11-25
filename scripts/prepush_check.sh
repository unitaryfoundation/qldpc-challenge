#!/usr/bin/env bash
# Pre-push check that mirrors CI's data-only path for a submission PR.
# Runs, in order: submission scope, ruff on added Python files, family-tag
# consistency, board-marked tests, and prose. Exits non-zero on the first
# failure. Usage: scripts/prepush_check.sh [pr-body.md]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

BASE="${BASE:-}"
if [ -z "$BASE" ]; then
  if git remote get-url upstream >/dev/null 2>&1; then
    BASE="upstream/main"
  else
    echo "no upstream remote; set BASE=<remote>/main or add upstream" >&2
    exit 2
  fi
fi

echo "== submission scope =="
uv run python verify/check_submission_scope.py --root "$ROOT" --base "$BASE"

echo "== ruff on added Python files =="
mapfile -d '' -t added < <(git diff --name-only --no-renames --diff-filter=A -z "$BASE"...HEAD -- '*.py')
if [ "${#added[@]}" -gt 0 ]; then
  uv run --frozen --only-group dev ruff check "${added[@]}"
  uv run --frozen --only-group dev ruff format --check "${added[@]}"
fi

echo "== family-tag consistency =="
uv run --frozen --extra research python -m pytest -q verify/test_family_tag_consistency.py

echo "== board-marked tests =="
uv run --frozen --extra research python run_tests.py -m board

BODY="${1:-}"
if [ -n "$BODY" ]; then
  echo "== prose =="
  verify/prepush_prose_check.sh "$BODY"
fi

echo "prepush_check: OK"
