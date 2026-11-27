#!/usr/bin/env bash
# Submit a batch of codes, one PR per code, as the contract requires.
#
# Usage:
#   scripts/bulk_submit.sh --authors @handle --no-circuit --fast-trials 0 --open-pr -- file1.npz file2.npz ...
#
# Everything before "--" is passed unchanged to each `./qldpc submit` call;
# everything after "--" is treated as a candidate file. Each candidate gets its
# own branch and PR (via --base-ref origin/main, which you may include in the
# common flags), and a failure on one candidate does not stop the rest.
#
# Tier 0: touches only scripts/. Does not modify verify/.
set -uo pipefail

common=()
files=()
mode=common
for arg in "$@"; do
    if [ "$arg" = "--" ]; then
        mode=files
        continue
    fi
    if [ "$mode" = "common" ]; then
        common+=("$arg")
    else
        files+=("$arg")
    fi
done

if [ "${#files[@]}" -eq 0 ]; then
    echo "usage: $0 <qldpc flags...> -- <candidate.npz>..." >&2
    exit 2
fi

rc=0
for f in "${files[@]}"; do
    echo "=== submitting $f ==="
    if ! ./qldpc submit "$f" "${common[@]}"; then
        echo "FAILED: $f" >&2
        rc=1
    fi
done
exit "$rc"
