#!/usr/bin/env bash
# push_private.sh
# Syncs everything to the private repo — framework code, private strategies, and logs.
# .env is NEVER included.
#
# Usage:
#   ./push_private.sh            # sync current main to private/main
#
# What gets pushed:
#   - All tracked public files (framework, tests, docs)
#   - Private strategies: crypto_5min_mm, paper_demo, demo_buy, enhanced_market_scanner
#   - logs/sessions/  — per-session JSON exports (P&L, equity curve, trade records)
#   - logs/trade_history_*.csv — per-day trade history
#   - logs/trades.log — trade execution log
#
# What is always excluded:
#   - .env (credentials — never committed anywhere)
#   - storage/ (SQLite DB — large binary, not suitable for git)
#   - logs/polymarket_trading_*.log (raw app debug logs — too large for GitHub)

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

echo "Adding logs..."
add_if_exists "logs/sessions"
# Glob trade history CSVs individually (daily app logs are too large for GitHub)
for f in logs/trade_history_*.csv logs/trades.log; do
    add_if_exists "$f"
done

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

echo ""
echo "✓ Private repo updated: https://github.com/Thomas-quinn7/Polymarket_private"
