# Security Guide

This guide helps you keep your credentials and sensitive data secure when using this project.

## 🔒 Critical Security Rules

### NEVER Commit These Files

❌ **NEVER commit to Git:**
- `.env` - Contains real API keys, passwords, credentials
- `.env.local` - Local environment variables
- `.env.production` - Production credentials
- Any file with `.key` extension
- Any file with `.secret` extension
- `credentials.json` - API credentials
- `passwords.txt` - Stored passwords
- `wallet_mnemonic.txt` - Blockchain wallet seeds

✅ **SAFE to commit:**
- `.env.example` - Contains only placeholders (e.g., `your_key_here`)
- `.gitignore` - Protects sensitive files
- `README.md` - Documentation only
- `BUILDER_VERIFICATION.md` - Public documentation

## ✅ Pre-Push Checklist

Before pushing to GitHub, verify ALL of these:

### 1. Verify .gitignore is Working
```bash
# Check .gitignore exists
ls -la | grep gitignore

# Test .gitignore blocks .env
git check-ignore -v .env
# Should output: .env is ignored
```

**Expected Output:**
```
.env is ignored
```

### 2. Verify What Will Be Committed
```bash
# Check what files will be committed
git status
```

**RED FLAGS - Stop if you see:**
- `.env` - Contains real credentials
- `.key` files - Private keys
- `secret` files - Secrets
- `credentials` files - API credentials

**GREEN FLAGS - These should be visible:**
- `.env.example` - Template with placeholders
- `README.md` - Documentation
- `.gitignore` - Security configuration
- Python files (`*.py`) - Code only
- Setup scripts (`*.py`) - Safe scripts

### 3. Check for Accidental Credential Exposure
```bash
# Search for any accidental credentials in code
grep -r "your_.*_here" . --include="*.py" --include="*.json"

# Should return nothing (unless it's in .env.example)
```

### 4. Check for Hardcoded Secrets
```bash
# Search for common credential patterns
grep -rE "(PRIVATE_KEY|SECRET|PASSWORD|API_KEY|WEBHOOK)" . --include="*.py" | grep -v "\.env\.example"
```

**Should only match comments or example values, not real credentials.**

### 5. Verify No Sensitive Data in History
```bash
# Check git history for credentials
git log --all --full-history --source -- "*env*" | grep "your_.*_here"

# Should find nothing (unless in .env.example which is safe)
```

### 6. Test Repository After Push
After pushing to GitHub:
1. Go to your repository
2. Try to access `.env` file
3. Should get **404 Not Found** error
4. Verify `.env.example` is visible

## 🛡 Security Best Practices

### Credential Management

1. **Use Environment Variables**
   ```python
   # ✅ GOOD - Load from environment
   import os
   private_key = os.getenv("POLYMARKET_PRIVATE_KEY")

   # ❌ BAD - Hardcoded in code
   private_key = "0xabc123..."
   ```

2. **Store Credentials in .env File**
   ```env
   # ✅ GOOD - .env file (ignored by git)
   POLYMARKET_PRIVATE_KEY=0xabc123...

   # ❌ BAD - In Python files
   private_key = "0xabc123..."
   ```

3. **Use Placeholder Values in Examples**
   ```env
   # ✅ GOOD - Placeholder value
   POLYMARKET_PRIVATE_KEY=your_polymarket_private_key_here

   # ❌ BAD - Real credential in example
   POLYMARKET_PRIVATE_KEY=0xabc123...
   ```

### API Key Security

1. **Rotate Keys Periodically**
   - Change API keys every 90 days
   - Revoke old keys
   - Generate new keys

2. **Use Different Keys per Environment**
   ```env
   # Development
   POLYMARKET_PRIVATE_KEY=dev_key_here

   # Production
   POLYMARKET_PRIVATE_KEY=prod_key_here
   ```

3. **Monitor Key Usage**
   - Check Polymarket Builder Profile regularly
   - Look for unauthorized access
   - Revoke suspicious keys immediately

### Discord Webhook Security

1. **Use Separate Webhooks for Testing**
   - Test webhook URL vs production URL
   - Don't mix environments

2. **Limit Webhook Permissions**
   - Bot only needs send messages permission
   - Revoke when not needed

3. **Monitor Webhook Usage**
   - Check Discord server audit logs
   - Look for unauthorized webhooks

### Email Security

1. **Use App Passwords (Gmail)**
   - Never use regular Gmail password
   - Create App Password: https://myaccount.google.com/apppasswords
   - Revoke if compromised

2. **Use Secure SMTP Ports**
   - Use TLS/SSL (port 587 or 465)
   - Never use port 25 without encryption

3. **Limit Email Access**
   - Only send from authorized email addresses
   - Monitor sent folder for unauthorized emails

## 🚨 Common Security Mistakes

### Mistake 1: Committing .env File
**Problem:**
```bash
git add .env        # ❌ NEVER DO THIS
git commit -m "Update config"
git push origin main
```

**Solution:**
```bash
# Use .env.example instead
cp .env .env.example
# Then add only the example file
git add .env.example
```

### Mistake 2: Hardcoding Credentials in Code
**Problem:**
```python
# ❌ BAD - Real credentials in code
class PolymarketClient:
    def __init__(self):
        self.private_key = "0xabc123..."  # Real key!
```

**Solution:**
```python
# ✅ GOOD - Load from environment
class PolymarketClient:
    def __init__(self):
        self.private_key = os.getenv("POLYMARKET_PRIVATE_KEY")
```

### Mistake 3: Debug Logging Credentials
**Problem:**
```python
# ❌ BAD - Logs credentials to console
logger.debug(f"Using private key: {private_key}")
```

**Solution:**
```python
# ✅ GOOD - Mask sensitive values
logger.debug(f"Using private key: {private_key[:8]}...{private_key[-4:]}")
# Or
logger.info("Private key loaded from environment")
```

### Mistake 4: Including Secrets in Error Messages
**Problem:**
```python
# ❌ BAD - Exposes credentials in errors
raise Exception(f"Failed to connect: {private_key}:{password}")
```

**Solution:**
```python
# ✅ GOOD - Mask or omit sensitive values
raise Exception("Failed to connect with credentials")
```

## 📋 Pre-Push Verification Script

Save this script as `verify_github_safety.sh` and run before pushing:

```bash
#!/bin/bash
# verify_github_safety.sh
# Run this before pushing to GitHub

echo "🔒 GitHub Safety Verification"
echo "==============================="
echo ""

# Check 1: .gitignore exists
if [ ! -f ".gitignore" ]; then
    echo "❌ ERROR: .gitignore not found!"
    exit 1
else
    echo "✅ .gitignore found"
fi

# Check 2: .env is ignored
if git check-ignore -v .env > /dev/null 2>&1; then
    echo "✅ .env is ignored by git"
else
    echo "❌ ERROR: .env is NOT ignored!"
    echo "   Your credentials could be committed!"
    exit 1
fi

# Check 3: No .env in git status
if git status | grep -q "\.env"; then
    echo "❌ ERROR: .env found in git status!"
    echo "   It will be committed if you run git add ."
    exit 1
else
    echo "✅ .env not in git status"
fi

# Check 4: No credentials in code
if grep -r "0x[a-fA-F0-9]" *.py | grep -v "\.env\.example" > /dev/null 2>&1; then
    echo "⚠️  WARNING: Possible hardcoded keys found in code"
    echo "   Review: grep -r '0x[a-fA-F0-9]' *.py"
else
    echo "✅ No hardcoded keys in Python files"
fi

# Check 5: .env.example is safe
if grep -q "your_.*_here" .env.example; then
    echo "✅ .env.example contains only placeholder values"
else
    echo "⚠️  WARNING: .env.example may contain real values"
fi

echo ""
echo "==============================="
echo "✅ All checks passed! Safe to push to GitHub."
echo ""
echo "Files that WILL be committed:"
git status --short
```

**Usage:**
```bash
chmod +x verify_github_safety.sh
./verify_github_safety.sh
```

## 🔐 GitHub Repository Security Features

### Enable Branch Protection
1. Go to repository Settings → Branches
2. Click "Add rule"
3. Require pull request before merge
4. Require status checks to pass

### Enable Security Alerts
1. Go to repository Settings → Security & analysis
2. Enable "Dependabot alerts"
3. Enable "Secret scanning"
4. Enable "Push protection"

### Use GitHub Secrets (for Actions)
If using GitHub Actions:
1. Go to repository Settings → Secrets
2. Add secrets there (never in code)
3. Access via: `${{ secrets.MY_SECRET }}`

## 📞 What to Do If You Accidentally Commit Credentials

1. **Immediately Remove from Repository**
   ```bash
   # Remove file from git
   git rm --cached .env

   # Commit removal
   git commit -m "Remove credentials"

   # Push removal
   git push origin main
   ```

2. **Rotate All Compromised Keys**
   - Go to Polymarket Builder Profile
   - Revoke compromised keys
   - Generate new keys
   - Update your local .env
   - Update Discord webhook if needed
   - Update email App Password

3. **Check Repository History**
   ```bash
   # Remove sensitive file from all history
   git filter-branch --force --index-filter \
       'git rm --cached --ignore-unmatch .env'

   # Force push
   git push origin --force --all
   ```

4. **Notify Platform Support**
   - Contact Polymarket support
   - Alert them to potential compromise
   - Monitor for unauthorized activity

## 🎯 Security Summary

| Item | Status | Action Required |
|------|--------|----------------|
| .gitignore configured | ✅ | Done - Comprehensive rules added |
| .env protected | ✅ | .gitignore blocks .env file |
| .env.example safe | ✅ | Contains only placeholders |
| Credentials in code | ✅ | None found (only env vars) |
| Pre-push script | ✅ | Created verification script |
| Paper trading safety | ✅ | PAPER_TRADING_ONLY=True blocks real money |

## 📞 Emergency Contact

If you discover a security issue:

1. **Immediate Actions:**
   - Stop the bot
   - Revoke all API keys
   - Rotate all passwords
   - Check GitHub repository history

2. **Report to:**
   - Polymarket support: [security@polymarket.com](mailto:security@polymarket.com)
   - GitHub security: [support@github.com](mailto:support@github.com)

3. **Document Incident:**
   - What happened
   - Timeline of events
   - What was exposed
   - Mitigation steps taken

---

**Remember:** It's always better to be overly cautious than to compromise your credentials. 🛡
