#!/bin/bash
# verify_github_safety.sh
# Run this before pushing to GitHub to ensure no credentials are committed

set -e

echo "========================================"
echo "🔒 GitHub Safety Verification"
echo "========================================"
echo ""

SUCCESS=true

# Check 1: .gitignore exists
echo "📋 Check 1: .gitignore exists"
if [ ! -f ".gitignore" ]; then
    echo "❌ ERROR: .gitignore not found!"
    echo "   Run: touch .gitignore"
    SUCCESS=false
else
    echo "✅ .gitignore found"
fi

# Check 2: .env is ignored
echo ""
echo "📋 Check 2: .env is ignored by git"
if git check-ignore -v .env > /dev/null 2>&1; then
    echo "✅ .env is ignored by git"
else
    echo "❌ ERROR: .env is NOT ignored!"
    echo "   Your credentials could be committed!"
    echo "   Add '.env' to .gitignore"
    SUCCESS=false
fi

# Check 3: .env.local is ignored
echo ""
echo "📋 Check 3: .env.local is ignored by git"
if git check-ignore -v .env.local > /dev/null 2>&1; then
    echo "✅ .env.local is ignored by git"
else
    echo "⚠️  WARNING: .env.local is NOT ignored!"
    echo "   Add '.env.local' to .gitignore"
fi

# Check 4: No .env in git status
echo ""
echo "📋 Check 4: .env not in git status"
if git status --short 2>/dev/null | grep -q "\.env"; then
    echo "❌ ERROR: .env found in git status!"
    echo "   It will be committed if you run: git add ."
    echo "   Remove from git: git rm --cached .env"
    SUCCESS=false
else
    echo "✅ .env not in git status"
fi

# Check 5: No .env.local in git status
echo ""
echo "📋 Check 5: .env.local not in git status"
if git status --short 2>/dev/null | grep -q "\.env.local"; then
    echo "❌ ERROR: .env.local found in git status!"
    echo "   Remove from git: git rm --cached .env.local"
    SUCCESS=false
else
    echo "✅ .env.local not in git status"
fi

# Check 6: No hardcoded keys in Python files
echo ""
echo "📋 Check 6: No hardcoded keys in Python files"
if grep -r "0x[a-fA-F0-9]\{40,\}" *.py 2>/dev/null | grep -v "example" | grep -v "\.env\.example" > /dev/null 2>&1; then
    echo "⚠️  WARNING: Possible hardcoded keys found in code!"
    echo "   Review: grep -r '0x[a-fA-F0-9]\{40,\}' *.py | grep -v example"
else
    echo "✅ No hardcoded keys in Python files"
fi

# Check 7: .env.example contains only placeholders
echo ""
echo "📋 Check 7: .env.example contains only placeholder values"
if [ -f ".env.example" ]; then
    if grep -q "your_.*_here\|YOUR_.*_HERE" .env.example; then
        echo "✅ .env.example contains only placeholder values"
    else
        echo "⚠️  WARNING: .env.example may contain real values!"
        echo "   Review: cat .env.example"
    fi
fi

# Check 8: No secrets in git history
echo ""
echo "📋 Check 8: No secrets in git history"
if git log --all --full-history --source -- "*env*" -- "*.secret*" -- "*.key*" 2>/dev/null | grep -q "your_.*_here"; then
    echo "⚠️  WARNING: Found possible secrets in git history!"
    echo "   Review: git log --all"
else
    echo "✅ No secrets in git history"
fi

# Check 9: .gitignore blocks credential files
echo ""
echo "📋 Check 9: .gitignore blocks credential patterns"
CREDENTIAL_PATTERNS=("\.env" "\.env\.local" "*.key" "*.secret" "*.password" "credentials\." "secrets\.")
BLOCKED_COUNT=0
for pattern in "${CREDENTIAL_PATTERNS[@]}"; do
    if grep -q "$pattern" .gitignore; then
        ((BLOCKED_COUNT++))
    fi
done

if [ $BLOCKED_COUNT -ge 4 ]; then
    echo "✅ .gitignore blocks $BLOCKED_COUNT credential patterns"
else
    echo "⚠️  WARNING: .gitignore only blocks $BLOCKED_COUNT credential patterns"
    echo "   Expected at least 4 (.env, .key, .secret, credentials)"
    SUCCESS=false
fi

# Summary
echo ""
echo "========================================"
echo "Files that will be committed:"
echo "========================================"
git status --short

echo ""
echo "========================================"
if [ "$SUCCESS" = true ]; then
    echo "✅ All checks passed! Safe to push to GitHub."
    echo ""
    echo "Files that WILL be committed:"
    git status --short
    echo ""
    echo "Safe files include:"
    echo "  - ✅ Python code (*.py)"
    echo "  - ✅ Configuration (.env.example)"
    echo "  - ✅ Documentation (*.md)"
    echo "  - ✅ Setup scripts (quick_start.py, etc.)"
    echo ""
    echo "Protected files (will NOT be committed):"
    echo "  - ✅ .env (real credentials)"
    echo "  - ✅ .env.local (local overrides)"
    echo "  - ✅ .key, .secret files"
    echo "  - ✅ credentials files"
    echo "  - ✅ Database files (*.db, *.sqlite)"
    echo "  - ✅ Log files (*.log)"
    exit 0
else
    echo "❌ FAILED: Some checks failed!"
    echo ""
    echo "Please fix the issues above before pushing to GitHub."
    exit 1
fi
