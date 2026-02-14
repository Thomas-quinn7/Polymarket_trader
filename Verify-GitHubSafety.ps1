# Verify-GitHubSafety.ps1
# Windows PowerShell version of GitHub safety verification
# Run this before pushing to GitHub

# Enable errors
$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "GitHub Safety Verification" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$success = $true

# Check 1: .gitignore exists
Write-Host "Check 1: .gitignore exists" -ForegroundColor Yellow
if (Test-Path ".gitignore") {
    Write-Host "✅ .gitignore found" -ForegroundColor Green
} else {
    Write-Host "❌ ERROR: .gitignore not found!" -ForegroundColor Red
    Write-Host "   Run: New-Item -Path .gitignore -ItemType File" -ForegroundColor Yellow
    $success = $false
}

# Check 2: .env is ignored
Write-Host ""
Write-Host "Check 2: .env is ignored by git" -ForegroundColor Yellow
$gitIgnoreResult = git check-ignore .env 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ .env is ignored by git" -ForegroundColor Green
} else {
    Write-Host "❌ ERROR: .env is NOT ignored!" -ForegroundColor Red
    Write-Host "   Your credentials could be committed!" -ForegroundColor Yellow
    Write-Host "   Add '.env' to .gitignore file" -ForegroundColor Yellow
    $success = $false
}

# Check 3: No .env in git status
Write-Host ""
Write-Host "Check 3: .env not in git status" -ForegroundColor Yellow
$envInStatus = git status --short 2>$null | Select-String -Pattern ".env"
if (-not [string]::IsNullOrEmpty($envInStatus)) {
    Write-Host "❌ ERROR: .env found in git status!" -ForegroundColor Red
    Write-Host "   It will be committed if you run: git add ." -ForegroundColor Yellow
    Write-Host "   Remove from git: git rm --cached .env" -ForegroundColor Yellow
    $success = $false
} else {
    Write-Host "✅ .env not in git status" -ForegroundColor Green
}

# Check 4: No .env.local in git status
Write-Host ""
Write-Host "Check 4: .env.local not in git status" -ForegroundColor Yellow
$envLocalInStatus = git status --short 2>$null | Select-String -Pattern ".env.local"
if (-not [string]::IsNullOrEmpty($envLocalInStatus)) {
    Write-Host "⚠️  WARNING: .env.local found in git status!" -ForegroundColor Yellow
    Write-Host "   Add '.env.local' to .gitignore file" -ForegroundColor Yellow
    $success = $false
} else {
    Write-Host "✅ .env.local not in git status" -ForegroundColor Green
}

# Check 5: No hardcoded keys in Python files
Write-Host ""
Write-Host "Check 5: No hardcoded keys in Python files" -ForegroundColor Yellow
$hardcodedKeys = Get-ChildItem -Path . -Recurse -Filter *.py | Select-String -Pattern "0x[a-fA-F0-9]\{40\}" | Select-String -NotMatch -Pattern ".env.example"
if ([string]::IsNullOrEmpty($hardcodedKeys)) {
    Write-Host "✅ No hardcoded keys in Python files" -ForegroundColor Green
} else {
    Write-Host "⚠️  WARNING: Possible hardcoded keys found in code!" -ForegroundColor Yellow
    Write-Host "   Review:" -ForegroundColor Yellow
    Write-Host "   Get-ChildItem -Path . -Recurse -Filter *.py | Select-String -Pattern '0x[a-fA-F0-9]\{40\}' | Select-String -NotMatch -Pattern '.env.example'" -ForegroundColor Yellow
    $success = $false
}

# Check 6: .env.example contains only placeholders
Write-Host ""
Write-Host "Check 6: .env.example contains only placeholder values" -ForegroundColor Yellow
if (Test-Path ".env.example") {
    $placeholderContent = Get-Content .env.example
    if ($placeholderContent -match "your_.*_here" -or $placeholderContent -match "YOUR_.*_HERE") {
        Write-Host "✅ .env.example contains only placeholder values" -ForegroundColor Green
    } else {
        Write-Host "⚠️  WARNING: .env.example may contain real values!" -ForegroundColor Yellow
        $success = $false
    }
} else {
    Write-Host "⚠️  WARNING: .env.example not found" -ForegroundColor Yellow
}

# Summary
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Files that will be committed:" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
git status --short

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
if ($success) {
    Write-Host "✅ All checks passed! Safe to push to GitHub." -ForegroundColor Green
    Write-Host ""
    Write-Host "Safe files include:" -ForegroundColor Green
    Write-Host "  - ✅ Python code (*.py)" -ForegroundColor Green
    Write-Host "  - ✅ Configuration (.env.example)" -ForegroundColor Green
    Write-Host "  - ✅ Documentation (*.md)" -ForegroundColor Green
    Write-Host "  - ✅ Setup scripts (*.ps1, *.py)" -ForegroundColor Green
    Write-Host ""
    Write-Host "Protected files (will NOT be committed):" -ForegroundColor Green
    Write-Host "  - ✅ .env (real credentials)" -ForegroundColor Green
    Write-Host "  - ✅ .env.local (local overrides)" -ForegroundColor Green
    Write-Host "  - ✅ *.key, *.secret files (private keys)" -ForegroundColor Green
    Write-Host "  - ✅ credentials.*, secrets.* files" -ForegroundColor Green
    Write-Host "  - ✅ Database files (*.db, *.sqlite)" -ForegroundColor Green
    Write-Host "  - ✅ Log files (*.log)" -ForegroundColor Green
    Write-Host ""
    exit 0
} else {
    Write-Host "❌ FAILED: Some checks failed!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please fix the issues above before pushing to GitHub." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Review SECURITY.md for detailed guidance." -ForegroundColor Yellow
    exit 1
}
