# Windows Setup Guide

This guide provides Windows-specific setup instructions for the Polymarket Arbitrage Bot.

## Quick Setup (One Command)

```powershell
# Open PowerShell and run:
.\quick_start.py
```

## Step-by-Step Setup

### Step 1: Open PowerShell

**Option A: Right-click menu**
1. Navigate to project folder in File Explorer
2. Right-click in empty space
3. Select "Open in Terminal" or "PowerShell here"

**Option B: Start menu**
1. Press `Win + R`
2. Type `powershell`
3. Press Enter
4. Navigate to project: `cd C:\Users\tq343\Quant_projects\Polymarket_trading`

### Step 2: Run Quick Start

```powershell
.\quick_start.py
```

This will:
- Create virtual environment
- Install all dependencies
- Create `.env` from template
- Guide you through configuration

### Step 3: Edit .env File

After quick start completes, edit `.env` with your credentials:

```powershell
# Open in Notepad
notepad .env

# Or open in VS Code
code .env
```

**Add these values:**
```env
# Polymarket API
POLYMARKET_PRIVATE_KEY=your_actual_private_key_here
POLYMARKET_FUNDER_ADDRESS=your_funder_address_here

# Optional: Builder credentials (for 3000 req/day)
BUILDER_ENABLED=True
BUILDER_API_KEY=your_builder_api_key_here
BUILDER_SECRET=your_builder_secret_here
BUILDER_PASSPHRASE=your_builder_passphrase_here

# Optional: Email alerts
ENABLE_EMAIL_ALERTS=True
SMTP_USERNAME=your_email@gmail.com
SMTP_PASSWORD=your_app_password_here
ALERT_EMAIL_TO=your_email@gmail.com

# Optional: Discord alerts
ENABLE_DISCORD_ALERTS=True
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN
DISCORD_MENTION_USER=your_discord_username
```

### Step 4: Run Validation (Windows)

```powershell
# Run PowerShell verification script
powershell -ExecutionPolicy Bypass -File .\Verify-GitHubSafety.ps1
```

**Expected output:**
```
========================================
GitHub Safety Verification
========================================

Check 1: .gitignore exists
✅ .gitignore found

Check 2: .env is ignored by git
✅ .env is ignored by git

Check 3: .env not in git status
✅ .env not in git status

Check 6: .env.example contains only placeholder values
✅ .env.example contains only placeholder values

========================================
✅ All checks passed! Safe to push to GitHub.
```

### Step 5: Test Email Alerts (Windows)

If you configured email alerts, test them:

```powershell
# Test email configuration
python test_email.py
```

### Step 6: Test Discord Alerts (Windows)

If you configured Discord alerts, test them:

```powershell
# Test Discord webhook
python test_discord.py
```

## Using Git on Windows

### Option A: Git Bash (Recommended)

```bash
# Use Git Bash (comes with Git for Windows)
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

### Option B: PowerShell with Git Commands

```powershell
# Initialize git repository
git init

# Check what will be committed
git status

# Add all files
git add .

# Commit changes
git commit -m "Initial commit: Polymarket Arbitrage Bot"

# Add remote
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git

# Push to GitHub
git branch -M main
git push -u origin main
```

### Option C: GitHub Desktop (Easiest)

1. Download and install [GitHub Desktop](https://desktop.github.com/)
2. Sign in to your GitHub account
3. File → Clone repository (or create new)
4. Open repository in file explorer
5. Copy your project files to repository folder
6. GitHub Desktop will show changes ready to commit
7. Review changes, add commit message, commit
8. Click "Publish branch"

## Verify After Push to GitHub

### 1. Check Repository on GitHub

Go to: `https://github.com/YOUR_USERNAME/YOUR_REPO`

**Verify:**
- ✅ `.env.example` is visible (should see template file)
- ✅ `README.md` is visible
- ✅ Python files are visible
- ✅ Configuration files are visible

**Should NOT see:**
- ❌ `.env` file (should return 404 Not Found)
- ❌ Any `.key`, `.secret`, `.password` files
- ❌ Any `credentials` or `secrets` files
- ❌ Database files (*.db, *.sqlite)
- ❌ Log files (*.log)

### 2. Try to Access .env File

Try to access: `https://github.com/YOUR_USERNAME/YOUR_REPO/blob/main/.env`

**Expected result:** 
```
404 Not Found
```

This confirms `.gitignore` is working correctly.

### 3. Check .gitignore is Working

In your repository, the `.gitignore` file should be visible and contain:
```
# Environment variables (NEVER commit these to git!)
.env
.env.local
*.key
*.secret
*.password
logs/
*.db
```

## Windows-Specific Security

### PowerShell Execution Policy

If you get errors running PowerShell scripts:

**Error:** "running scripts is disabled on this system"

**Fix:**
```powershell
# Allow running of the current script only
Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process -File .\Verify-GitHubSafety.ps1

# Or allow all scripts (less secure, more convenient)
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned
```

### File Path Issues

**Issue:** PowerShell doesn't recognize file paths with backslashes

**Fix:** Always use quotes around paths or forward slashes:
```powershell
# Good
python "C:\Users\tq343\Quant_projects\Polymarket_trading\test_email.py"

# Also good
python .\test_email.py

# Avoid
python C:\Users\tq343\Quant_projects\Polymarket_trading\test_email.py
```

### Long Path Issues

**Issue:** Windows path length limit (260 characters)

**Fix:** Keep project folder near root:
```
Good:  C:\Users\tq343\Quant_projects\Polymarket_trading
Bad:  C:\Users\tq343\Documents\GitHub\Polymarket Arbitrage Bot\Version 2.0
```

## Virtual Environment on Windows

### Using Python venv

```powershell
# Create virtual environment
python -m venv venv

# Activate (PowerShell)
.\venv\Scripts\Activate.ps1

# Or activate (Command Prompt)
venv\Scripts\activate.bat

# Install dependencies
pip install -r requirements.txt

# Deactivate when done
deactivate
```

### Using Conda (Alternative)

```powershell
# Create conda environment
conda create -n polymarket python=3.11

# Activate
conda activate polymarket

# Install dependencies
pip install -r requirements.txt

# Deactivate
conda deactivate
```

## Common Windows Issues

### Issue 1: Python Not Found in PowerShell

**Error:** `'python' is not recognized as an internal or external command`

**Fix:** Add Python to PATH or use full path:
```powershell
# Add to PATH temporarily
$env:Path += ";C:\Python311\Scripts\"

# Or use full path
C:\Python311\python.exe .\quick_start.py
```

### Issue 2: Git Not Found

**Error:** `'git' is not recognized as an internal or external command`

**Fix:** Install Git or use full path:
```powershell
# Install Git for Windows
# Download from: https://git-scm.com/download/win

# Or use Git Bash (includes git)
# Launch "Git Bash" from Start menu
```

### Issue 3: Script Execution Blocked

**Error:** "running scripts is disabled on this system"

**Fix:** Use bypass flag:
```powershell
powershell -ExecutionPolicy Bypass -File .\verify_github_safety.sh
```

## Running the Bot on Windows

### Start the Bot

```powershell
# Activate virtual environment
.\venv\Scripts\Activate.ps1

# Start bot
python main.py
```

### Start Bot in Background

```powershell
# Using Start-Process (recommended)
Start-Process -FilePath python -ArgumentList "main.py" -WindowStyle Normal

# Or using a separate PowerShell window
Start-Process powershell -ArgumentList "-NoExit", "-Command", ".\venv\Scripts\Activate.ps1; python main.py"
```

## Quick Reference Commands

```powershell
# Setup
.\quick_start.py                                      # Quick setup

# Validate
powershell -ExecutionPolicy Bypass -File .\Verify-GitHubSafety.ps1
python test_email.py                                    # Test email
python test_discord.py                                  # Test Discord

# Run
python main.py                                         # Start bot

# Git
git init                                              # Init repo
git add .                                             # Add files
git commit -m "message"                                 # Commit
git push origin main                                  # Push to GitHub
```

## Troubleshooting

### Virtual Environment Issues

**Problem:** Can't activate venv
```powershell
# Fix 1: Use full path
C:\Users\tq343\Quant_projects\Polymarket_trading\venv\Scripts\Activate.ps1

# Fix 2: Use Command Prompt instead
venv\Scripts\activate.bat
```

### Dependencies Installation Issues

**Problem:** pip install fails
```powershell
# Fix 1: Upgrade pip first
python -m pip install --upgrade pip

# Fix 2: Use specific Python executable
.\venv\Scripts\python.exe -m pip install -r requirements.txt

# Fix 3: Install from wheel files
pip install --no-index --find-links=dependencies/ -r requirements.txt
```

### Git Authentication Issues

**Problem:** Git asks for username/password when pushing
```powershell
# Use Personal Access Token instead of password
# Generate at: https://github.com/settings/tokens

# Set up credential helper
git config --global credential.helper manager-core

# Push (will ask for token)
git push -u origin main
```

## Summary

| Platform | Script Type | Command |
|----------|-------------|----------|
| Windows | PowerShell | powershell -File .\Verify-GitHubSafety.ps1 |
| Windows | Python (if in PATH) | python script.py |
| Windows | Git (if in PATH) | git command |
| Windows | Virtual env | .\venv\Scripts\Activate.ps1 |

You're ready to set up on Windows! 🎉
