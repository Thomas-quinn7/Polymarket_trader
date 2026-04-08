# Project Status & Task Tracker

## Completed

### Core Execution
- **Real order execution** — `PAPER_TRADING_ONLY` env flag gates live orders. `execute_buy` submits FOK market orders via `PolymarketClient.create_market_order` and aborts on non-fill. `execute_sell` added for early exits.
- **Stop-loss / early exit** — `STOP_LOSS_PERCENT` config added (default 0 = disabled). `_check_stop_losses()` runs every loop and triggers `execute_sell` automatically.
- **API retry logic** — `_with_retry()` on all Gamma market fetches and CLOB order submission (3× with 0.1s / 0.5s / 2.0s backoff).
- **Rollback on failure** — balance fully restored if position creation raises after capital is deducted.

### Authentication
- **Relayer API key support** — `RELAYER_ENABLED=True` submits orders to `https://relayer-v2.polymarket.com/` with L2 CLOB headers merged with `RELAYER_API_KEY` / `RELAYER_API_KEY_ADDRESS`. Unlimited transactions, no tier approval required.
- **Builder API support** — `BUILDER_ENABLED=True` attaches builder attribution headers via `py_builder_signing_sdk`. Auth priority: Relayer > Builder > Standard.

### Data & Models
- **`time_to_close` removed from framework** — was strategy-specific logic (settlement arbitrage) that had leaked into config, DB models, alerts, and logging. Strategies now set `opportunity.expires_at` as an absolute `datetime`; the framework reads it via `getattr(..., None)`.
- **SQLite persistence** — write → close → reconnect → read cycle verified. PnL snapshots survive restarts. `DB_ENABLED=True` and `DB_PATH=./storage/trading.db` confirmed working.

### Testing
- **455 unit tests passing** — covers order executor, position tracker, fake currency tracker, PnL tracker, data models, market schema, simulation markets, strategies, config, dashboard API, data validation, and data pipeline.
- **`test_data_pipeline.py`** — buy/win, buy/loss, balance invariants, capital sizing, rollback, multi-position, settlement price clamping.
- **`test_data_validation.py`** — field parsing edge cases, price rejection, currency tracker invariants, PnL statistics, liquidity checks.

### Infrastructure
- **`internal/` tree removed** — was a fully disconnected async framework (never imported by `main.py`). 9 unit tests for dead code also removed.
- **SQLite persistence** — confirmed working end-to-end.
- **Alerts** — Discord webhook and email (SMTP) both tested and confirmed working.

---

## Pending / To Do

### Before Running Live (Real Money)

1. **Set API credentials in `.env`**
   Paper mode (`TRADING_MODE=paper`) requires real Polymarket credentials:
   ```
   POLYMARKET_PRIVATE_KEY=0x...
   POLYMARKET_FUNDER_ADDRESS=0x...
   ```
   Without these, `ClobClient` falls back to `client = None` and all price fetches return `0.0`.

2. **Configure authentication mode**
   - **Recommended**: Enable Relayer keys — unlimited transactions, no approval needed:
     ```
     RELAYER_ENABLED=True
     RELAYER_API_KEY=...
     RELAYER_API_KEY_ADDRESS=...
     ```
   - **Alternative**: Apply for Builder Verified status by emailing [builder@polymarket.com](mailto:builder@polymarket.com) with your `BUILDER_API_KEY`, use case, and expected volume. Once approved, set `BUILDER_ENABLED=True` and `SCAN_INTERVAL_MS=30000`.
   - Without either: unverified accounts are limited to **100 relay transactions/day** (~1 scan every 57 min). Set `SCAN_INTERVAL_MS=3456000`.

### Infrastructure

3. **Enable Docker / WSL2 for ScyllaDB** (optional)
   ScyllaDB order-book snapshot storage requires Docker. On Windows 10 Home:
   1. Enable virtualisation in BIOS (Intel VT-x / AMD-V)
   2. Install WSL2: `wsl --install` in an admin PowerShell, then reboot
   3. Install Docker Desktop and ensure the WSL2 backend is selected
   4. Run `docker compose up -d` — ScyllaDB starts alongside the bot

   Until Docker is running, `SCYLLA_ENABLED=False` (current default) is correct. The bot runs fine with SQLite only.

### Nice to Have

4. **Confidence scoring for settlement arbitrage**
   `SettlementArbitrage` hardcodes `confidence=1.0` for every opportunity. A real score could factor in: order book depth, historical win rate for that market category, and current balance drawdown.

5. **Additional strategies**
   The `strategies/examples/enhanced_market_scanner.py` is implemented but not yet connected to the registry as a selectable strategy.

---

## Current State Summary

| Area | Status |
|------|--------|
| Unit tests | 455 / 455 passing |
| Simulation mode (offline) | Fully working |
| Paper mode (real prices) | Needs credentials in `.env` |
| Real order execution | Implemented — set `PAPER_TRADING_ONLY=False` |
| Relayer API key auth | Implemented — set `RELAYER_ENABLED=True` |
| Builder API auth | Implemented — set `BUILDER_ENABLED=True` |
| Stop-loss / early exit | Implemented — set `STOP_LOSS_PERCENT` to enable |
| API retry logic | 3× backoff on all market fetches and order submission |
| Position tracking / PnL | Verified — rollback, settlement clamping, multi-position |
| SQLite persistence | Verified end-to-end |
| Alerts (email + Discord) | Wired up and tested |
| Web dashboard | Working — `http://localhost:8080` |
| Docker / ScyllaDB | Needs WSL2 + Docker Desktop on Windows |
