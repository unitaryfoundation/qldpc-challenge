#!/bin/sh
# Pre-push gate: reproduce CI's view of a submission branch before pushing.
#
# CI checks the PR body and changed notes against a tree containing ONLY
# committed files. This script runs the check inside a clean worktree of
# HEAD, so it fails exactly when CI would. It first runs the submission
# scope check (one new code, nothing outside the submission surface, and
# under repro/ only the entry's own manifest), which diffs committed content
# against the base and so already sees what CI will.
#
# Usage: [BASE=<remote>/main] [PR_AUTHOR=<login>] verify/prepush_prose_check.sh <pr-body-file>
#   The PR body must be given as a file; pass /dev/null if you have none yet.
#   Set PR_AUTHOR to your GitHub login to also reproduce CI's fieldnote
#   author-attribution check (every fieldnote added by the branch must
#   credit that handle in its frontmatter).
#   BASE defaults to upstream/main when an `upstream` remote exists and to
#   origin/main otherwise. In a fork, origin IS the fork, and its origin/main
#   is whatever the fork last synced (issue #2762): a stale one makes every
#   note in the repository look changed, and one ahead of upstream makes a
#   branch with broken citations look clean. Add the canonical repository as
#   `upstream`, or pass BASE explicitly.
#
# Exit 0 = safe to push. Anything else = fix the reported paths first.

set -e

BODY=${1:?usage: verify/prepush_prose_check.sh <pr-body-file>}
ROOT=$(git rev-parse --show-toplevel)
UPSTREAM_REPO="unitaryfoundation/qldpc-challenge"

# Resolve the base the way CI does: against the canonical repository's main.
# An `upstream` remote wins when present. Without one, origin/main is only
# right when origin is the canonical repository, so say so when it is not.
if [ -z "$BASE" ]; then
    if git remote get-url upstream >/dev/null 2>&1; then
        BASE=upstream/main
    else
        BASE=origin/main
        ORIGIN_URL=$(git remote get-url origin 2>/dev/null || echo "")
        case "$ORIGIN_URL" in
            *"$UPSTREAM_REPO"*) ;;
            *)
                echo "ERROR: origin is '$ORIGIN_URL', not $UPSTREAM_REPO, so" >&2
                echo "       origin/main is your fork's main and not what CI diffs against." >&2
                echo "       Add the canonical repository as a remote and fetch it:" >&2
                echo "         git remote add upstream https://github.com/$UPSTREAM_REPO.git" >&2
                echo "         git fetch upstream" >&2
                echo "       or pass BASE=<remote>/main explicitly." >&2
                exit 2 ;;
        esac
    fi
fi

# Verify the base ref exists BEFORE degrading behavior on it.
if ! git rev-parse --verify --quiet "$BASE" >/dev/null; then
    echo "ERROR: base ref '$BASE' not found; fetch or set BASE=<ref>." >&2
    exit 2
fi

# A base the caller forced that disagrees with upstream/main is the stale
# case the default now avoids; it is reported rather than silently diffed.
if [ "$BASE" != "upstream/main" ] \
        && git rev-parse --verify --quiet upstream/main >/dev/null \
        && [ "$(git rev-parse "$BASE")" != "$(git rev-parse upstream/main)" ]; then
    echo "WARNING: $BASE is not upstream/main; CI diffs against the canonical" >&2
    echo "         repository, so what follows may not match CI." >&2
fi

# The worktree shows committed content only, so uncommitted notes would not
# be seen and the verdict would not be about what you are going to push.
# Other uncommitted work (another session's, a scratch file) does not
# change the verdict and is only mentioned.
DIRTY=$(git status --porcelain)
if [ -n "$DIRTY" ]; then
    DIRTY_NOTES=$(printf '%s\n' "$DIRTY" | awk '{print $NF}' \
                  | grep -E '^(notes|fieldnotes)/' || true)
    if [ -n "$DIRTY_NOTES" ]; then
        echo "ERROR: uncommitted notes/fieldnotes; commit (or stash) them before running the gate:" >&2
        printf '%s\n' "$DIRTY_NOTES" | sed 's/^/  /' >&2
        exit 2
    fi
    echo "note: working tree has uncommitted changes outside notes/ and fieldnotes/;" \
         "the gate checks committed content only" >&2
fi

WT=$(mktemp -d "${TMPDIR:-/tmp}/prose-check.XXXXXX")

cleanup() { git worktree remove --force "$WT" >/dev/null 2>&1 || rm -rf "$WT"; }
trap cleanup EXIT

git worktree add --detach "$WT" HEAD >/dev/null 2>&1

CHANGED=$(git diff --name-only --diff-filter=AMR "$BASE...HEAD" \
          -- notes/ fieldnotes/ || true)

PY=${QLDPC_PYTHON:-python3}

AUTHOR_ARGS=""
if [ -n "$PR_AUTHOR" ]; then
    AUTHOR_ARGS="--pr-author $PR_AUTHOR"
fi

echo "base: $BASE ($(git rev-parse --short "$BASE"))"

# Scope first: it is cheap, and a stray file under research/ or a directory
# under repro/ is a different fix from a broken citation (issue #3810).
"$PY" "$ROOT/verify/check_submission_scope.py" --base "$BASE"

# No exec here: exec would skip the EXIT trap and leak the worktree.
if [ -z "$CHANGED" ]; then
    echo "no changed notes/fieldnotes vs $BASE; checking PR body only"
    # shellcheck disable=SC2086
    "$PY" "$ROOT/verify/check_prose.py" \
        --root "$WT" --base "$BASE" --body-file "$BODY" $AUTHOR_ARGS
else
    # shellcheck disable=SC2086
    "$PY" "$ROOT/verify/check_prose.py" \
        --root "$WT" --base "$BASE" --body-file "$BODY" --files $CHANGED $AUTHOR_ARGS
fi
