#!/usr/bin/env bash
# Run the circuit tier backfill over a list of board slugs.
#
# Usage:
#   scripts/bulk_circuit_backfill.sh --by @handle slug1 slug2 ...
#
# Wraps research/circuit_backfill.py so a second, deliberate pass can add
# circuits to several code-only entries without mixing them into code PRs.
# Slugs that already carry a circuit are reported and skipped by the
# underlying tool.
#
# Tier 0: touches only scripts/ and the entry data it is invoked on.
set -euo pipefail

if [ "$#" -lt 3 ]; then
    echo "usage: $0 --by @handle slug1 [slug2 ...]" >&2
    exit 2
fi

uv run python research/circuit_backfill.py "$@"
