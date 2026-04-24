#!/usr/bin/env bash
# push_private.sh
# Syncs everything to the private repo for the trading team.
# .env is the ONLY thing excluded.
#
# Usage:
#   ./push_private.sh            # sync current main to private/main
#
# What gets pushed:
#   - All tracked public files (framework, tests, docs)
#   - Private strategies: crypto_5min_mm, paper_demo, demo_buy, enhanced_market_scanner
#   - tools/ — proprietary research tooling (tick_recorder, price_target_tracker, configs)
#   - storage/ — SQLite DBs (trading.db, market_minimums.db) and their CSV exports
#   - logs/ — all app logs, per-session JSON exports, trade history CSVs
#   - *.csv at repo root — research exports (crossings.csv, my_export.csv, etc.)
#
# What is always excluded:
#   - .env (credentials — never committed anywhere)

set -e

PRIVATE_REMOTE="private"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
SYNC_BRANCH="private-sync-$(date +%s)"

echo ""
echo "=== Private repo sync ==="
echo "Source branch : $CURRENT_BRANCH"
echo "Sync branch   : $SYNC_BRANCH"
echo ""

# Ensure we are clean on the source branch before branching
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "⚠  Uncommitted changes detected on $CURRENT_BRANCH."
    echo "   Commit or stash them before running this script."
    exit 1
fi

git checkout -b "$SYNC_BRANCH"

add_if_exists() {
    local path="$1"
    if [ -e "$path" ]; then
        git add -f "$path" 2>/dev/null && echo "  + $path"
    fi
}

echo "Adding private strategies..."
add_if_exists "strategies/crypto_5min_mm"
add_if_exists "strategies/paper_demo"
add_if_exists "strategies/demo_buy"
add_if_exists "strategies/enhanced_market_scanner"

echo "Adding research tooling..."
add_if_exists "tools"

echo "Adding storage (SQLite DBs + CSV exports)..."
add_if_exists "storage"

echo "Adding logs..."
add_if_exists "logs"

echo "Adding root-level research CSVs..."
shopt -s nullglob
for f in *.csv; do
    add_if_exists "$f"
done
shopt -u nullglob

# Safety check: .env must NEVER be force-added. Bail out if anything matched it.
if git diff --cached --name-only | grep -qE '(^|/)\.env(\..*)?$'; then
    echo ""
    echo "✖  Refusing to push: .env (or variant) somehow got staged."
    git reset
    git checkout "$CURRENT_BRANCH"
    git branch -D "$SYNC_BRANCH"
    exit 1
fi

# Only commit if something was actually staged
if git diff --cached --quiet; then
    echo ""
    echo "  (no new private files to stage — framework code already up to date)"
else
    git commit -m "Private sync: strategies + logs ($(date +%Y-%m-%d))"
fi

echo ""
echo "Pushing to $PRIVATE_REMOTE..."
git push "$PRIVATE_REMOTE" "$SYNC_BRANCH:main" --force

echo ""
echo "Cleaning up sync branch..."
git checkout "$CURRENT_BRANCH"
git branch -D "$SYNC_BRANCH"

# Switching back to $CURRENT_BRANCH deletes gitignored paths that were tracked
# on the sync branch. Restore them from the freshly pushed private/main so the
# working tree keeps the strategies, tools, storage and CSVs between syncs.
echo ""
echo "Restoring private files to working tree..."
RESTORE_PATHS=(strategies/crypto_5min_mm strategies/paper_demo strategies/demo_buy strategies/enhanced_market_scanner tools storage)
EXISTING_PATHS=()
for p in "${RESTORE_PATHS[@]}"; do
    if git cat-file -e "$PRIVATE_REMOTE/main:$p" 2>/dev/null; then
        EXISTING_PATHS+=("$p")
    fi
done
# Root-level CSVs pushed by the sync — restore each one that exists on the remote.
while IFS= read -r csv; do
    [ -n "$csv" ] && EXISTING_PATHS+=("$csv")
done < <(git ls-tree --name-only "$PRIVATE_REMOTE/main" | grep -E '^[^/]+\.csv$' || true)

if [ ${#EXISTING_PATHS[@]} -gt 0 ]; then
    git checkout "$PRIVATE_REMOTE/main" -- "${EXISTING_PATHS[@]}"
    # These paths are gitignored on $CURRENT_BRANCH; unstage so they return to
    # the "untracked, ignored" state they had before the sync ran.
    git reset HEAD -- "${EXISTING_PATHS[@]}" > /dev/null
    for p in "${EXISTING_PATHS[@]}"; do
        echo "  ✓ $p"
    done
fi

echo ""
echo "✓ Private repo updated: https://github.com/Thomas-quinn7/Polymarket_private"
