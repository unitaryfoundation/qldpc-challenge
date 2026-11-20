#!/usr/bin/env sh
# Partial/sparse clone of qldpc-challenge to keep the working tree small.
# Usage: ./scripts/clone-sparse.sh [DIR] [--no-circuits]
set -eu

URL="https://github.com/unitaryfoundation/qldpc-challenge.git"
DIR="${1:-qldpc-challenge}"
NO_CIRCUITS=0
for arg in "$@"; do
  case "$arg" in
    --no-circuits) NO_CIRCUITS=1 ;;
  esac
done

git clone --filter=blob:none --sparse "$URL" "$DIR"
cd "$DIR"
if [ "$NO_CIRCUITS" = "1" ]; then
  git sparse-checkout set codes notes fieldnotes repro certs
else
  git sparse-checkout set codes circuits notes fieldnotes repro certs
fi
echo "Cloned into $DIR (sparse). Add paths with: git sparse-checkout add <path>"
