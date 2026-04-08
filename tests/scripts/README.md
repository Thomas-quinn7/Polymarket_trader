# Test and Validation Scripts

Manual scripts for validating setup, testing alerts, and running integration checks. These are not part of the automated test suite (`pytest tests/unit/`) — run them directly from the project root.

## Scripts

### `validate_setup.py`
Validates your `.env` configuration and checks that all required settings are present and reachable.

```bash
python tests/scripts/validate_setup.py
```

### `test_email.py`
Sends a test email using your configured SMTP settings. Useful for verifying alert credentials before going live.

```bash
python tests/scripts/test_email.py
```

> Gmail users: use an App Password, not your account password — [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).

### `test_discord.py`
Sends a test notification to your configured Discord webhook.

```bash
python tests/scripts/test_discord.py
```

### `test_dashboard.py`
Standalone dashboard runner for manual UI testing. For production use, run `python main.py` instead so the dashboard and trading loop are integrated.

```bash
python tests/scripts/test_dashboard.py
```

### `run_dashboard.py`
Alternative dashboard runner (starts FastAPI without the trading loop).

```bash
python tests/scripts/run_dashboard.py
```

### `quick_start.py`
Guided setup helper — walks through credential checks and fires a test run.

```bash
python tests/scripts/quick_start.py
```

### `test_simple_scanner.py`
Runs a single market scan pass and prints the results. Useful for verifying that the Gamma API is reachable and markets are being parsed correctly.

```bash
python tests/scripts/test_simple_scanner.py
```

### `test_enhanced_scanner.py`
Same as above but uses the enhanced market scanner with keyword filtering and category classification.

```bash
python tests/scripts/test_enhanced_scanner.py
```

## Running Automated Unit Tests

The full unit test suite (455 tests) is run with pytest from the project root:

```bash
python -m pytest tests/unit/
```

For a specific module:

```bash
python -m pytest tests/unit/test_order_executor.py
python -m pytest tests/unit/test_data_pipeline.py
python -m pytest tests/unit/test_data_validation.py
```

## Notes

- Scripts use absolute imports from the project root — run them from the project root directory, not from inside `tests/scripts/`.
- Ensure your virtual environment is active before running: `.venv\Scripts\activate` (Windows) or `source .venv/bin/activate` (macOS/Linux).
- Scripts that hit live APIs require `POLYMARKET_PRIVATE_KEY` and `POLYMARKET_FUNDER_ADDRESS` set in `.env`.
