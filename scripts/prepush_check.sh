#!/usr/bin/env bash
# Pre-push check that mirrors CI's data-only path for a submission PR.
# Thin wrapper around `./qldpc preflight` so there is a single step list
# (see cli/qldpc.py:cmd_preflight). Runs, in order: submission scope, ruff
# on added Python files, family-tag consistency, board-marked tests, and
# prose. Exits non-zero on the first failure.
# Usage: scripts/prepush_check.sh [pr-body.md]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

BASE_ARGS=()
if [ -n "${BASE:-}" ]; then
  BASE_ARGS=(--base-ref "$BASE")
fi

BODY="${1:-}"
BODY_ARGS=()
if [ -n "$BODY" ]; then
  BODY_ARGS=(--body-file "$BODY")
fi

exec ./qldpc preflight "${BASE_ARGS[@]}" "${BODY_ARGS[@]}"
