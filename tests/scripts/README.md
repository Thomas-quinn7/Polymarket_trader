# Test and Validation Scripts

This folder contains test and validation scripts for the Polymarket Trading Bot.

## Files

### `test_dashboard.py`
Simple standalone dashboard runner for testing. Not recommended for production use.

**Usage:**
```bash
uv run python test_dashboard.py
```

### `start_dashboard.bat`
Quick launcher for running the dashboard in a new terminal.

**Usage:**
Double-click to run

### `validate_setup.py`
Validates your configuration and checks that all required settings are present.

**Usage:**
```bash
uv run python validate_setup.py
```

### `test_email.py`
Tests email notification configuration by sending a test email.

**Usage:**
```bash
uv run python test_email.py
```

### `test_discord.py`
Tests Discord webhook configuration by sending a test notification.

**Usage:**
```bash
uv run python test_discord.py
```

### `run_dashboard.py`
Alternative dashboard runner script.

**Usage:**
```bash
uv run python run_dashboard.py
```

### `quick_start.py`
Helper script for quick project setup and validation.

**Usage:**
```bash
uv run python quick_start.py
```

## Important Notes

1. **Dashboard Integration**: For production use, run `uv run main.py` instead of test_dashboard.py to ensure the dashboard and trading bot communicate properly.

2. **Configuration**: Make sure your `.env` file has all required variables configured before running test scripts.

3. **Test Files**: These scripts are designed for testing and validation purposes. They use absolute imports from the main project structure, so they work correctly from this subfolder.

## Running Tests

After activating the virtual environment with `.\\venv\\Scripts\\Activate.ps1`, you can run any test file from the project root:

```bash
# Validate setup
uv run python test_setup/validate_setup.py

# Test email
uv run python test_setup/test_email.py

# Test Discord
uv run python test_setup/test_discord.py
```
