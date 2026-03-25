# Remaining Tasks & Checks

## ✅ Completed

### 1. ~~Wire up real order execution~~ — Done
`PAPER_TRADING_ONLY` is now a `.env` setting (default `true`). When set to `false`,
`execute_buy` submits a real FOK market order via `PolymarketClient.create_market_order`
and aborts if the exchange does not fill it. `execute_sell` added for early exits.

### 2. ~~Settlement arbitrage edge vs fees~~ — Done
`MIN_PRICE_THRESHOLD` lowered from `0.985` → `0.95`. With 2% taker fee the strategy
already filters `net_edge <= 0`, so the wider scan window `[0.95, 1.00]` is needed
to find markets where price ≤ 0.98 and net edge > 0.

### 3. ~~Add an early-exit / SELL path~~ — Done
`STOP_LOSS_PERCENT` config added (default `0` = disabled). `execute_sell` submits
a real SELL order in live mode, then settles the internal books at the filled price.
`_check_stop_losses()` runs every loop iteration and triggers it automatically.

### 4. ~~Add retry logic for API calls~~ — Done
`_with_retry()` helper added to `polymarket_client.py`. Gamma API market fetches
and CLOB `post_order` calls both retry 3× with 0.1s / 0.5s / 2.0s backoff.

---

## 🟡 Before Running Paper Mode (Real Prices, No Real Money)

### 5. Set API credentials in `.env`
Paper mode (`TRADING_MODE=paper`) requires real Polymarket credentials:
```
POLYMARKET_PRIVATE_KEY=0x...
POLYMARKET_FUNDER_ADDRESS=0x...
```
Without these, `ClobClient` falls back to `client = None` and all price
fetches return `0.0`, so the strategy never finds opportunities.

### 6. Set `SCAN_INTERVAL_MS` correctly
- **Unverified** (no builder creds): 200 req/day → minimum `1728000` ms (~29 min)
- **Builder mode** (`BUILDER_ENABLED=true`): 3000 req/day → minimum `30000` ms (30s)

Current `.env` default is `30000` — safe only if you have builder credentials.

### 7. Get Builder credentials (optional but recommended)
Without them you're limited to 200 API requests per day which allows roughly
6 scans. Apply for verified/builder status on Polymarket to get 3000 req/day.
Set `BUILDER_ENABLED=true` and fill `BUILDER_API_KEY`, `BUILDER_SECRET`,
`BUILDER_PASSPHRASE` in `.env`.

---

## 🟠 Infrastructure

### 8. Enable Docker / WSL2 for ScyllaDB
ScyllaDB order-book snapshot storage requires Docker. On Windows 10 Home:
1. Enable virtualisation in BIOS (Intel VT-x / AMD-V)
2. Install WSL2: `wsl --install` in an admin PowerShell, then reboot
3. Install Docker Desktop and ensure the WSL2 backend is selected
4. Run `docker compose up -d` — ScyllaDB will start alongside the bot

Until Docker is running, `SCYLLA_ENABLED=false` (current default) is the
correct setting and the bot runs fine with SQLite only.

### 9. Verify SQLite persistence end-to-end
`DB_ENABLED=true` and `DB_PATH=./storage/trading.db` are set but the database
write path has not been exercised in tests. Confirm that trades, positions, and
PnL history are actually written and readable after a restart.

---

## 🟢 Nice to Have

### 10. Risk / confidence scoring
`SettlementArbitrage` hardcodes `confidence=1.0` for every opportunity. A real
confidence score could factor in: time to close, order book depth, historical
win rate for that market category, and current balance drawdown.

### 11. Alert configuration
Discord webhook and email alerts are wired up but untested with real credentials.
Fill in `DISCORD_WEBHOOK_URL`, `DISCORD_MENTION_USER`, and SMTP settings in
`.env` and do a manual alert test before relying on them for live monitoring.

### 12. Review `internal/` directory
`internal/core/execution/service/executor_service.py` (~390 lines) appears to be
an alternative execution engine that duplicates some of the `main.py` logic. Decide
whether to keep it, integrate it, or remove it to reduce confusion.

---

## Current State Summary

| Area | Status |
|------|--------|
| Simulation mode | ✅ Fully working — 146/146 tests pass |
| Paper mode (real prices) | ⚠️ Needs credentials in `.env` |
| Real order execution | ✅ Implemented — set `PAPER_TRADING_ONLY=false` to enable |
| Stop-loss / early exit | ✅ Implemented — set `STOP_LOSS_PERCENT` to enable |
| API retry logic | ✅ 3× backoff on all market fetches and order submission |
| Settlement arbitrage logic | ✅ Price window fixed — finds opportunities with 2% fee |
| Position tracking / PnL | ✅ Fixed and verified |
| Docker / ScyllaDB | ⚠️ Needs WSL2 + Docker Desktop on Windows |
| SQLite persistence | ⚠️ Configured but unverified |
| Alerts | ⚠️ Wired up — credentials not set |
