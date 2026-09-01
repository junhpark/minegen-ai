#!/usr/bin/env bash

set -Eeuo pipefail

cd /workspaces/minegen-ai

BRANCH="phase-16-navigation"
BUNDLE="phase-16-navigation.bundle"
EXPECTED_BASE="19d10bf615f8caa93b3af9c28b2e792ab8f4e9a7"
TEMP_BRANCH="phase-16-bundle-check"

STEP="START"

error_handler() {
    CODE=$?
    echo
    echo "=================================================="
    echo "❌ ERROR"
    echo "Step    : $STEP"
    echo "Line    : ${BASH_LINENO[0]}"
    echo "Command : $BASH_COMMAND"
    echo "Exit    : $CODE"
    echo "=================================================="
    echo
    echo "이 정보는 phase16-push.log에도 저장됩니다."
    exit "$CODE"
}

trap error_handler ERR

echo "=================================================="
echo " MineGen-AI Phase 16 Navigation Push"
echo " DEBUG MODE"
echo "=================================================="

STEP="1 - working tree"
echo
echo "=== $STEP ==="
git status --short

TRACKED_DIRTY="$(git status --porcelain --untracked-files=no)"

if [ -n "$TRACKED_DIRTY" ]; then
    echo
    echo "Tracked changes detected:"
    echo "$TRACKED_DIRTY"
    echo
    echo "❌ STOP: tracked working tree is not clean."
    exit 20
fi

echo "✅ tracked working tree clean"


STEP="2 - bundle exists"
echo
echo "=== $STEP ==="

if [ ! -f "$BUNDLE" ]; then
    echo "❌ $BUNDLE not found"
    pwd
    ls -lah
    exit 21
fi

ls -lh "$BUNDLE"
echo "✅ bundle exists"


STEP="3 - fetch origin"
echo
echo "=== $STEP ==="

git fetch origin --prune

CURRENT_MAIN="$(git rev-parse origin/main)"

echo "Expected main: $EXPECTED_BASE"
echo "Actual main  : $CURRENT_MAIN"

if [ "$CURRENT_MAIN" != "$EXPECTED_BASE" ]; then
    echo "❌ origin/main differs from expected Phase 15 merged base."
    exit 22
fi

echo "✅ main base correct"


STEP="4 - bundle verify"
echo
echo "=== $STEP ==="

git bundle verify "$BUNDLE"

echo
echo "--- bundle heads ---"
git bundle list-heads "$BUNDLE"


STEP="5 - inspect bundle refs"
echo
echo "=== $STEP ==="

BUNDLE_HEADS="$(git bundle list-heads "$BUNDLE")"
echo "$BUNDLE_HEADS"

echo
echo "Looking for branch:"
echo "refs/heads/$BRANCH"

if echo "$BUNDLE_HEADS" | grep -q "refs/heads/$BRANCH"; then
    echo "✅ expected branch exists in bundle"
else
    echo
    echo "❌ Bundle does NOT contain:"
    echo "   refs/heads/$BRANCH"
    echo
    echo "The actual refs are shown above."
    exit 23
fi


STEP="6 - import bundle"
echo
echo "=== $STEP ==="

git branch -D "$TEMP_BRANCH" 2>/dev/null || true

git fetch "./$BUNDLE" \
    "refs/heads/$BRANCH:refs/heads/$TEMP_BRANCH"

NEW_HEAD="$(git rev-parse "$TEMP_BRANCH")"

echo "Base       : $EXPECTED_BASE"
echo "Bundle HEAD: $NEW_HEAD"

echo "✅ bundle imported"


STEP="7 - ancestry"
echo
echo "=== $STEP ==="

if ! git merge-base --is-ancestor "$EXPECTED_BASE" "$TEMP_BRANCH"; then
    echo "❌ Phase 16 does not descend from the required Phase 15 merged main."
    exit 24
fi

MERGE_BASE="$(git merge-base "$EXPECTED_BASE" "$TEMP_BRANCH")"

echo "Merge base: $MERGE_BASE"

if [ "$MERGE_BASE" != "$EXPECTED_BASE" ]; then
    echo "❌ unexpected merge base"
    exit 25
fi

echo "✅ ancestry correct"


STEP="8 - commits"
echo
echo "=== $STEP ==="

git --no-pager log \
    --oneline \
    --decorate \
    "$EXPECTED_BASE..$TEMP_BRANCH"

COUNT="$(git rev-list --count "$EXPECTED_BASE..$TEMP_BRANCH")"

echo
echo "Phase 16 commits: $COUNT"

if [ "$COUNT" -lt 1 ]; then
    echo "❌ No new Phase 16 commit."
    exit 26
fi


STEP="9 - changed files"
echo
echo "=== $STEP ==="

git --no-pager diff \
    --name-status \
    "$EXPECTED_BASE...$TEMP_BRANCH"

echo
echo "--- diff stat ---"

git --no-pager diff \
    --stat \
    "$EXPECTED_BASE...$TEMP_BRANCH"


STEP="10 - backend check"
echo
echo "=== $STEP ==="

BACKEND_CHANGED="$(
    git diff --name-only "$EXPECTED_BASE...$TEMP_BRANCH" |
    grep '^backend/' || true
)"

if [ -n "$BACKEND_CHANGED" ]; then
    echo
    echo "❌ Backend changes found:"
    echo "$BACKEND_CHANGED"
    exit 27
fi

echo "✅ no backend changes"


STEP="11 - dependency check"
echo
echo "=== $STEP ==="

DEPENDENCY_CHANGED="$(
    git diff --name-only "$EXPECTED_BASE...$TEMP_BRANCH" |
    grep -E '(^|/)(package\.json|package-lock\.json|pyproject\.toml)$' || true
)"

if [ -n "$DEPENDENCY_CHANGED" ]; then
    echo
    echo "❌ Dependency files changed:"
    echo "$DEPENDENCY_CHANGED"
    exit 28
fi

echo "✅ no dependency changes"


STEP="12 - remote branch check"
echo
echo "=== $STEP ==="

if git ls-remote --exit-code --heads origin \
    "refs/heads/$BRANCH" >/dev/null 2>&1; then

    echo "⚠️ origin/$BRANCH already exists."
    REMOTE_EXISTING="$(git rev-parse origin/$BRANCH 2>/dev/null || true)"
    echo "Remote HEAD: $REMOTE_EXISTING"

    if [ "$REMOTE_EXISTING" = "$NEW_HEAD" ]; then
        echo "✅ It already matches this bundle."
        echo
        echo "Nothing needs to be pushed."
        exit 0
    fi

    echo
    echo "❌ Remote Phase 16 branch exists with another HEAD."
    echo "Stopping — no force push."
    exit 29
fi

echo "✅ remote Phase 16 branch does not yet exist"


STEP="13 - prepare local main"
echo
echo "=== $STEP ==="

git switch main
git merge --ff-only origin/main

LOCAL_MAIN="$(git rev-parse HEAD)"

if [ "$LOCAL_MAIN" != "$EXPECTED_BASE" ]; then
    echo "❌ local main mismatch"
    exit 30
fi

echo "✅ local main correct"


STEP="14 - create Phase 16 local branch"
echo
echo "=== $STEP ==="

if git show-ref --verify --quiet "refs/heads/$BRANCH"; then

    EXISTING_LOCAL="$(git rev-parse "$BRANCH")"

    echo "Existing local branch: $EXISTING_LOCAL"

    if [ "$EXISTING_LOCAL" = "$NEW_HEAD" ]; then

        git switch "$BRANCH"

    elif [ "$EXISTING_LOCAL" = "$EXPECTED_BASE" ]; then

        git switch "$BRANCH"
        git merge --ff-only "$TEMP_BRANCH"

    else

        echo
        echo "❌ Existing local Phase 16 branch has unexpected history."
        echo "No branch will be deleted automatically."
        exit 31

    fi

else

    git switch -c "$BRANCH" "$EXPECTED_BASE"
    git merge --ff-only "$TEMP_BRANCH"

fi


STEP="15 - local verification"
echo
echo "=== $STEP ==="

LOCAL_HEAD="$(git rev-parse HEAD)"

echo "Bundle HEAD: $NEW_HEAD"
echo "Local HEAD : $LOCAL_HEAD"

if [ "$LOCAL_HEAD" != "$NEW_HEAD" ]; then
    echo "❌ local HEAD != bundle HEAD"
    exit 32
fi

echo "✅ local Phase 16 branch ready"


STEP="16 - final pre-push summary"
echo
echo "=== $STEP ==="

git --no-pager log --graph --decorate --oneline -8

echo
echo "=================================================="
echo " ALL PRE-PUSH CHECKS PASSED"
echo "=================================================="
echo
echo "Base   : $EXPECTED_BASE"
echo "Branch : $BRANCH"
echo "HEAD   : $LOCAL_HEAD"
echo
echo "Now pushing to GitHub..."
echo


STEP="17 - push"
git push -u origin "$BRANCH"


STEP="18 - verify remote"
echo
echo "=== $STEP ==="

git fetch origin --prune

REMOTE_HEAD="$(git rev-parse "origin/$BRANCH")"

echo "Local : $LOCAL_HEAD"
echo "Remote: $REMOTE_HEAD"

if [ "$LOCAL_HEAD" != "$REMOTE_HEAD" ]; then
    echo "❌ local/remote mismatch"
    exit 33
fi

echo "✅ local and remote match"


STEP="19 - cleanup"
echo
echo "=== $STEP ==="

git branch -D "$TEMP_BRANCH" 2>/dev/null || true


STEP="COMPLETE"

echo
echo "=================================================="
echo "✅ PHASE 16 NAVIGATION PUSH COMPLETE"
echo "Branch : $BRANCH"
echo "Base   : $EXPECTED_BASE"
echo "HEAD   : $REMOTE_HEAD"
echo "=================================================="
