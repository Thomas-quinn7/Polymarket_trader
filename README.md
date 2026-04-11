# Polymarket Trading Framework

A Python framework for building and running automated trading bots on [Polymarket](https://polymarket.com). Provides the infrastructure for market scanning, order execution, portfolio tracking, real-time monitoring, and alerting — so you can focus on your own trading logic.

## Features

- **Market Scanner**: Continuously scans Polymarket markets across configurable categories with keyword and liquidity filters
- **Paper Trading Mode**: Full simulation with fake currency before going live — enabled by default
- **Simulation Mode**: Fully offline with synthetic market data — no API calls required
- **Live Trading Mode**: Real order submission with interactive confirmation prompt and pre-trade safety checks
- **Pre-Trade Slippage Gate**: Estimates market impact from the live order book before each order; aborts if slippage exceeds tolerance
- **Web Dashboard**: Real-time monitoring of positions, P&L, and trade history
- **Alert System**: Email and Discord notifications for trades and system events
- **Portfolio Tracking**: Position management, P&L calculation, and trade history with SQLite persistence
- **Hot-Reload Config**: Update `.env` and call `/api/reload` — most settings apply without a restart
- **Relayer API Support**: Unlimited order relay transactions via Polymarket Relayer keys (no tier approval required)
- **Builder API Support**: Tiered order attribution with rate limits (unverified → verified → partner)
- **Strategy Session Recording**: Every completed trade is saved per-run to SQLite and JSON — price, market, hold time, P&L, outcome, and equity curve — ready for charting or algorithmic analysis
- **Ollama Strategy Review**: On shutdown, a local LLM (`llama3.2:3b`) generates a human-readable performance review of the session; runs entirely on-device via Docker, no cloud API required
- **Modular Strategy Architecture**: Plug in your own strategy — the framework handles the rest
- **617 unit tests** covering execution, portfolio, data models, slippage estimation, config reload, and pipeline

## Installation

### Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) — fast Python package manager
- Python 3.11 or higher

**Install uv:**
```bash
# PowerShell (Windows)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Setup

1. **Clone the repository**:
```bash
git clone https://github.com/Thomas-quinn7/Polymarket_trader.git
cd Polymarket_trader
```

2. **Create and activate a virtual environment**:
```bash
uv venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

3. **Install the project and dependencies**:
```bash
uv pip install -e .
```

4. **Configure environment variables**:
```bash
cp .env.example .env
# Edit .env with your credentials
```

5. **Set up Polymarket credentials**:
   - Get your private key from [polymarket.com](https://polymarket.com)
   - Add to `.env`: `POLYMARKET_PRIVATE_KEY=your_key_here`

## Configuration

All configuration is done via the `.env` file.

### Core Credentials

```env
POLYMARKET_PRIVATE_KEY=your_polymarket_private_key_here
POLYMARKET_FUNDER_ADDRESS=your_funder_address_here
```

### Authentication Modes

The framework supports three authentication modes in priority order: **Relayer > Builder > Standard**.

#### Relayer API (Recommended — Unlimited)

Relayer keys provide unlimited relay transactions for a single wallet with no tier approval. Generate your key at [polymarket.com/settings?tab=api-keys](https://polymarket.com/settings?tab=api-keys).

```env
RELAYER_ENABLED=True
RELAYER_API_KEY=your_relayer_api_key
RELAYER_API_KEY_ADDRESS=your_wallet_address
```

When `RELAYER_ENABLED=True`, the framework submits signed orders directly to the Polymarket Relayer endpoint (`https://relayer-v2.polymarket.com/`) with your L2 CLOB signature plus relayer headers. Builder mode is ignored.

#### Builder API (Tiered rate limits)

Builder keys provide order attribution and tiered rate limits. Apply for verification at [builder@polymarket.com](mailto:builder@polymarket.com).

```env
BUILDER_ENABLED=True
BUILDER_TIER=unverified   # unverified | verified | partner
BUILDER_API_KEY=your_builder_api_key
BUILDER_SECRET=your_builder_secret
BUILDER_PASSPHRASE=your_builder_passphrase
```

#### Standard Mode (Default)

No additional configuration required. Uses L2 CLOB authentication with your wallet private key. Subject to standard API rate limits.

### API Rate Limits

| Mode | Relay Transactions/Day | Minimum Scan Interval |
|------|------------------------|----------------------|
| Standard / Unverified Builder | 100 | ~57 min (3,456,000 ms) |
| Builder Verified | 3,000 | ~2 min (115,200 ms) |
| Builder Partner | Unlimited | 30 s (30,000 ms) |
| Relayer | Unlimited | 30 s (30,000 ms) |

Each full scan consumes approximately 4 API calls (one per market category). Override via `SCAN_INTERVAL_MS` in `.env`.

### Trading Mode

```env
# TRADING_MODE: paper | simulation | live
# paper      — real Polymarket API prices, simulated order execution (no real money)
# simulation — fully offline, synthetic market data, no API calls
# live        — real prices, REAL orders submitted to Polymarket
TRADING_MODE=paper

# Block all real-money trades regardless of other settings (recommended during testing)
PAPER_TRADING_ONLY=True
FAKE_CURRENCY_BALANCE=10000.00
```

To start in live mode from the command line, use `--live` (see [CLI Reference](#cli-reference) below). An interactive confirmation prompt is always shown before live trading begins.

### Strategy

```env
# Strategy to load from strategies/registry.py
# Built-in options: settlement_arbitrage | paper_demo | demo_buy | enhanced_market_scanner
STRATEGY=settlement_arbitrage
```

### Position Sizing

```env
MAX_POSITIONS=5                # Maximum concurrent open positions
CAPITAL_SPLIT_PERCENT=0.20     # Fraction of available balance allocated per position (0.0–1.0)
STOP_LOSS_PERCENT=0.0          # Exit position if price drops this % below entry (0 = disabled)
MIN_CONFIDENCE=0.5             # Minimum strategy confidence score to enter (0.0–1.0)
MIN_VOLUME_USD=1000.0          # Skip markets below this USD volume
```

Capital is sized dynamically: each allocation uses `CAPITAL_SPLIT_PERCENT` of the *current available balance*, not the starting balance. Three consecutive allocations each reduce the available pot, so later positions are smaller — this limits over-exposure.

### Market Scanner

```env
# Categories to scan (comma-separated)
SCAN_CATEGORIES=crypto,fed,regulatory,other

# Scan interval in milliseconds (see rate limits table above)
SCAN_INTERVAL_MS=30000
```

### Execution

```env
ORDER_TYPE=FOK                 # Fill or Kill (only supported type)
SLIPPAGE_TOLERANCE_PERCENT=5.0 # Abort order if estimated slippage exceeds this %
TAKER_FEE_PERCENT=2.0          # Polymarket taker fee, deducted from edge calculations
MAX_RETRIES=3
RETRY_DELAY_MS=100             # Base delay; actual delay is jittered (base × 0.5–1.5)
```

### Alerts

```env
# Email
ENABLE_EMAIL_ALERTS=True
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your_email@gmail.com
SMTP_PASSWORD=your_app_password
ALERT_EMAIL_FROM=noreply@example.com
ALERT_EMAIL_TO=your_email@gmail.com

# Discord
ENABLE_DISCORD_ALERTS=True
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_WEBHOOK
DISCORD_MENTION_USER=your_discord_username
```

> **Gmail users**: Use an App Password, not your account password. Generate one at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).

### Dashboard

```env
DASHBOARD_ENABLED=True
DASHBOARD_PORT=8080
# Localhost only by default. Set to 0.0.0.0 only if you need remote access
# and have a reverse proxy with authentication in front of the dashboard.
DASHBOARD_HOST=127.0.0.1
```

### Database

```env
# SQLite — trades, positions, P&L history
DB_ENABLED=True
DB_PATH=./storage/trading.db

# ScyllaDB — order book snapshot storage (requires Docker)
SCYLLA_ENABLED=False
SCYLLA_HOST=127.0.0.1
SCYLLA_PORT=9042
SCYLLA_KEYSPACE=polymarket
```

### Session Tracking & Ollama Review

```env
# Directory where per-session JSON exports are written
SESSIONS_DIR=./logs/sessions

# Set to True to enable Ollama review generation on shutdown
OLLAMA_ENABLED=False
# URL of the Ollama server (use http://ollama:11434 inside Docker Compose)
OLLAMA_HOST=http://localhost:11434
# Model to use for review generation — llama3.2:3b is pulled automatically on first run
OLLAMA_MODEL=llama3.2:3b
```

Each bot run produces one JSON file per strategy in `SESSIONS_DIR`. The file contains the full session header, per-trade records (price, market, hold time, P&L, outcome), an equity-curve time series, and the Ollama review text. The dashboard exposes these at `GET /api/sessions` and `GET /api/sessions/{id}`, and lets you re-trigger a review via `POST /api/sessions/{id}/review`.

### Logging

```env
LOG_LEVEL=INFO    # DEBUG | INFO | WARNING | ERROR | CRITICAL
LOG_TO_FILE=True
```

## Usage

### Docker Compose (recommended for full stack)

`docker-compose.yml` starts three services together:

| Service | Purpose |
|---------|---------|
| `trading-bot` | The bot + FastAPI dashboard (`localhost:8080`) |
| `scylla` | ScyllaDB for order-book snapshot storage |
| `ollama` | Local LLM for post-session strategy review |

```bash
# Start everything (builds the bot image on first run)
docker compose up -d

# Tail logs
docker compose logs -f trading-bot

# Stop and remove containers (data volumes are preserved)
docker compose down
```

The Ollama container downloads `llama3.2:3b` (~2 GB) automatically on its first review generation. Model weights are stored in the `ollama_data` Docker volume and persist across restarts.

If you have an NVIDIA GPU, uncomment the `deploy` block in the `ollama` service in `docker-compose.yml` for faster inference.

### Validate Setup

Before running, check that everything is configured correctly:

```bash
python tests/scripts/validate_setup.py
```

Checks: credentials, dependencies, paper trading mode, alert configuration.

### Start the Bot

```bash
polymarket
```

Or directly:
```bash
python main.py
```

The framework will:
1. Connect to Polymarket via the CLOB and Gamma APIs (or run offline in simulation mode)
2. Load the configured strategy from `strategies/registry.py`
3. Start the web dashboard on the configured port
4. Wait for a start command from the WebUI (or start immediately if `--auto-start` is passed)
5. On each scan tick: check strategy exits, check stop-losses, scan for new opportunities
6. Execute orders (paper or live) with a pre-trade slippage check before each buy
7. Track positions and send alerts on trades and system events

### CLI Reference

All CLI arguments take priority over `.env` values. Most are optional — the bot runs fine with just `.env`.

```
polymarket [OPTIONS]
```

| Argument | Description |
|----------|-------------|
| `--config PATH` | Load an alternative `.env` file (e.g. for a second account). CLI args still override it. |
| `--paper` | Force paper trading mode (real prices, simulated execution) |
| `--simulation` | Force simulation mode (fully offline, synthetic data) |
| `--live` | Start in live trading mode. Requires `POLYMARKET_PRIVATE_KEY`. Shows a confirmation prompt before orders are submitted. |
| `--auto-start` | Start the trading loop immediately without waiting for the WebUI |
| `--strategy NAME` | Strategy to load (e.g. `settlement_arbitrage`) |
| `--scan-interval MS` | Scan interval in milliseconds |
| `--categories LIST` | Comma-separated market categories (e.g. `crypto,fed`) |
| `--max-positions N` | Maximum concurrent open positions |
| `--min-confidence 0.0-1.0` | Minimum confidence score to enter a trade |
| `--stop-loss PCT` | Stop-loss as a % drop from entry; 0 to disable |
| `--balance USD` | Starting paper-trading balance |
| `--no-dashboard` | Disable the web dashboard |
| `--port PORT` | Dashboard port |
| `--log-level LEVEL` | Log verbosity: `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` \| `CRITICAL` |

**Examples:**

```bash
# Paper trade with the enhanced scanner, scanning only crypto markets
polymarket --paper --strategy enhanced_market_scanner --categories crypto

# Live trading with a 5% stop-loss (confirmation required)
polymarket --live --stop-loss 5.0

# Load a separate .env for a second account
polymarket --config accounts/account2.env --paper

# Headless server run, auto-start, log to DEBUG
polymarket --auto-start --no-dashboard --log-level DEBUG
```

### Web Dashboard

Open in your browser:
```
http://localhost:8080
```

Displays:
- Real-time P&L and portfolio summary
- Open positions with entry price and expected return
- Full trade history with win/loss breakdown
- System status and uptime
- Auto-refreshes every 5 seconds

### Test Alerts

```bash
python tests/scripts/test_email.py    # Send a test email
python tests/scripts/test_discord.py  # Send a test Discord message
```

### Run Unit Tests

```bash
python -m pytest tests/unit/
```

617 tests covering order execution, position tracking, P&L calculation, data models, slippage estimation, config reload, market scanner, and pipeline logic.

## Project Structure

```
Polymarket_Trading/
├── config/
│   └── polymarket_config.py       # All settings, env var loading, rate-limit helpers, hot-reload
├── data/
│   ├── polymarket_client.py       # Gamma + CLOB API client (Relayer/Builder/Standard auth)
│   ├── polymarket_models.py       # SQLAlchemy database models (TradeOpportunity, TradePosition)
│   ├── market_schema.py           # Normalised market data model (PolymarketMarket)
│   ├── market_provider.py         # MarketProvider: fetch → filter → price resolve pipeline
│   ├── market_scanner.py          # Multi-category parallel scanner (Gamma API)
│   ├── database.py                # SQLite session and upsert helpers
│   ├── session_store.py           # Per-run session + trade persistence (SQLite tables + JSON export)
│   ├── order_book_store.py        # ScyllaDB order book snapshot writer
│   └── simulation_markets.py      # Synthetic market generator for offline testing
├── strategies/
│   ├── base.py                    # Abstract BaseStrategy class
│   ├── registry.py                # Strategy loader (STRATEGY env var selects strategy)
│   ├── config_loader.py           # YAML config loader for per-strategy tuning
│   ├── settlement_arbitrage/      # Near-settled market arbitrage strategy
│   ├── paper_demo/                # Paper trading demo with configurable hold time
│   ├── demo_buy/                  # Single-buy demo strategy
│   ├── enhanced_market_scanner/   # Enhanced multi-signal scanner
│   └── example_strategy/          # Minimal strategy template for new strategies
├── execution/
│   └── order_executor.py          # Order creation, slippage gate, submission, rollback, history
├── portfolio/
│   ├── position_tracker.py        # Open position lifecycle management
│   └── fake_currency_tracker.py   # Paper trading balance (allocation / return)
├── utils/
│   ├── alerts.py                  # Unified email + Discord alerting with rate limiting
│   ├── logger.py                  # Structured logging with thread-safe CSV trade log
│   ├── pnl_tracker.py             # P&L statistics (win rate, profit factor, drawdown)
│   ├── slippage.py                # Order-book VWAP slippage estimator
│   ├── session_reviewer.py        # Ollama HTTP client — generates post-session strategy review
│   ├── execution_timer.py         # Execution timing utilities
│   └── webhook_sender.py          # Discord webhook implementation
├── dashboard/
│   └── api.py                     # FastAPI REST endpoints + dashboard HTML/CSS/JS
├── tests/
│   ├── unit/                      # 617 pytest unit tests
│   │   ├── test_order_executor.py
│   │   ├── test_pretrade_slippage.py
│   │   ├── test_slippage.py
│   │   ├── test_config_reload.py
│   │   ├── test_market_scanner_timeout.py
│   │   ├── test_position_tracker.py
│   │   ├── test_pnl_tracker.py
│   │   ├── test_alerts.py
│   │   ├── test_data_pipeline.py
│   │   ├── test_data_validation.py
│   │   └── ...
│   ├── integration/               # Integration tests
│   └── scripts/                   # Manual validation and alert test scripts
│       ├── validate_setup.py
│       ├── test_email.py
│       ├── test_discord.py
│       └── quick_start.py
├── storage/                       # SQLite database (auto-created)
├── logs/                          # Log files (auto-created)
├── main.py                        # Bot entry point and orchestrator
├── pyproject.toml
├── requirements.txt
├── docker-compose.yml             # ScyllaDB + Ollama containers (full-stack Docker setup)
└── .env                           # Your configuration (not committed)
```

## Key Components

### API Client (`data/polymarket_client.py`)

Wraps the Polymarket Gamma and CLOB APIs. Auth priority: **Relayer > Builder > Standard**.

- **Relayer mode**: submits signed orders to `https://relayer-v2.polymarket.com/` with L2 CLOB headers merged with `RELAYER_API_KEY` / `RELAYER_API_KEY_ADDRESS` headers. Unlimited transactions, no approval required.
- **Builder mode**: attaches builder attribution headers via `py_builder_signing_sdk`. Tiered daily limits.
- **Standard mode**: L2 CLOB authentication with wallet private key only.

All API calls retry up to `MAX_RETRIES` times with jittered exponential backoff (base delay × random factor 0.5–1.5).

### Market Provider (`data/market_provider.py`)

`MarketProvider` is the data pipeline between the Gamma API and strategy code. On each scan cycle it:

1. Fetches raw market dicts from the Gamma API (results are TTL-cached to avoid redundant calls within a scan)
2. Converts each dict to a `PolymarketMarket` object once — not once per strategy
3. Applies `MarketCriteria` pre-filters: minimum volume, binary-only gate, time-to-close bounds
4. Resolves prices using the strategy's declared `price_source_preference` (embedded → CLOB REST → order book mid)
5. Returns a clean `List[PolymarketMarket]` with `resolved_price` set on every entry

Strategies implement only domain logic — all data plumbing is handled here.

### Market Schema (`data/market_schema.py`)

Normalises raw Gamma API responses into a consistent `PolymarketMarket` model. Resolves field name differences between endpoints and provides helpers for category classification and liquidity checks.

### Strategy System (`strategies/`)

Strategies inherit from `BaseStrategy` in `strategies/base.py`. The active strategy is selected via the `STRATEGY` env var and loaded by `strategies/registry.py`.

**Built-in strategies:**

| Strategy | Description |
|----------|-------------|
| `settlement_arbitrage` | Scans for near-settled markets (price ≥ 0.985) with positive net edge after fees. Ranks by edge × confidence. |
| `paper_demo` | Buys a configurable market category, holds for `PAPER_DEMO_HOLD_SECONDS`, then exits |
| `demo_buy` | Single demonstration buy — useful for validating execution end-to-end |
| `enhanced_market_scanner` | Multi-signal scanner with additional market filters |

To add your own strategy, implement `BaseStrategy`, register it in `strategies/registry.py`, and set `STRATEGY=your_strategy` in `.env`.

### Order Executor (`execution/order_executor.py`)

Manages the full order lifecycle:

1. **Pre-trade slippage gate**: fetches the live order book (10 levels), estimates VWAP impact for the intended capital amount, and aborts if estimated slippage exceeds `SLIPPAGE_TOLERANCE_PERCENT`
2. Calculates position size from `CAPITAL_SPLIT_PERCENT` and current available balance (dynamic, not fixed)
3. In paper mode: records the trade internally with no API calls
4. In live mode: signs and submits a FOK market order, rolls back balance on failure
5. Records all order history with timestamps, position IDs, and actual slippage

`execute_sell()` supports early exits; `settle_position()` handles settlement at a final price.

### Portfolio Management (`portfolio/`)

- `PositionTracker`: tracks open positions, enforces `MAX_POSITIONS` limit, handles settlement
- `FakeCurrencyTracker`: paper trading balance with per-position allocation slots
- `PnLTracker`: running statistics — total P&L, win rate, profit factor, max drawdown

### Slippage Estimator (`utils/slippage.py`)

`estimate_slippage(order_book, capital_usd, side)` walks the order book level-by-level, computes the volume-weighted average fill price (VWAP), and returns:
- `vwap` — expected average fill price
- `slippage_pct` — adverse deviation from best-available price (always ≥ 0)
- `fill_ratio` — fraction of the order the book can absorb
- `insufficient_liquidity` — True if the book cannot fully fill the order

This is used both as the pre-trade gate and as the simulated fill price recorded on paper trades.

### Alert System (`utils/alerts.py`)

Unified alerting with email (SMTP) and Discord (webhook) support. Alerts fire on opportunity detection, trade execution, position settlement, and system errors. The alert thread pool shuts down cleanly on process exit.

### Strategy Session Tracking (`data/session_store.py`, `utils/session_reviewer.py`)

Every bot run creates one session per strategy. On each settled trade, the session records:

- Market question, slug, token ID of the winning side
- Entry and exit price, hold time, edge %, fees
- Gross and net P&L, outcome (`WIN` / `LOSS` / `BREAK_EVEN`)
- Running balance after the trade (equity curve)

When the bot shuts down, `SessionStore.close_session()` computes aggregate stats (win rate, profit factor, max drawdown, average hold) and writes a JSON file to `SESSIONS_DIR`. If `OLLAMA_ENABLED=True`, `SessionReviewer` sends the session summary and trade log to the local Ollama server and the review text is embedded in the JSON and stored in SQLite.

JSON files are structured for downstream use:

```json
{
  "session": { "strategy_name": "...", "trading_mode": "paper", ... },
  "stats":   { "win_rate": 0.67, "profit_factor": 2.1, ... },
  "equity_curve": [{"time": "2026-04-11T10:00:00Z", "balance": 10050.0, "trade_count": 1}, ...],
  "trades":  [{ "market_id": "...", "entry_price": 0.985, "net_pnl": 14.70, ... }],
  "ollama_review": "Session showed strong edge capture on near-settled markets..."
}
```

### Web Dashboard (`dashboard/api.py`)

FastAPI-backed dashboard serving real-time portfolio data via a browser UI at `http://localhost:8080`. Displays positions, P&L, trade history, and system status.

**Session endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/sessions` | List all recorded sessions (optional `?strategy=` and `?limit=` filters) |
| `GET` | `/api/sessions/{id}` | Full session detail including trades array |
| `POST` | `/api/sessions/{id}/review` | Re-generate the Ollama review for a past session |

## Paper Trading

Enabled by default. Set `PAPER_TRADING_ONLY=True` in `.env` to ensure no real orders are ever submitted regardless of other settings.

In paper trading mode:
- All trades use fake currency (configured via `FAKE_CURRENCY_BALANCE`)
- Slippage is estimated from the live order book and recorded on the position
- P&L is tracked and reported identically to live mode
- Position sizing, stop-losses, and settlement all behave as in live mode
- No interaction with your real Polymarket balance

## Writing a Strategy

```python
from datetime import datetime, timezone
from typing import List
from strategies.base import BaseStrategy
from data.market_schema import PolymarketMarket
from data.polymarket_models import TradeOpportunity, TradeStatus

class MyStrategy(BaseStrategy):
    def scan_for_opportunities(self, markets: List[PolymarketMarket]) -> List[TradeOpportunity]:
        """Return TradeOpportunity objects for markets that meet your criteria."""
        results = []
        for market in markets:
            price = market.resolved_price or 0.0
            if price >= 0.90 and (market.volume_usd or 0) >= 5000:
                results.append(TradeOpportunity(
                    market_id=market.market_id,
                    market_slug=market.slug,
                    question=market.question,
                    category=market.category,
                    token_id_yes=market.token_ids[0],
                    token_id_no=market.token_ids[1],
                    winning_token_id=market.token_ids[0],
                    current_price=price,
                    edge_percent=(1.0 - price) * 100,
                    confidence=0.8,
                    detected_at=datetime.now(timezone.utc),
                    status=TradeStatus.DETECTED,
                ))
        return results

    def get_best_opportunities(self, opportunities, limit=5):
        return sorted(opportunities, key=lambda o: o.edge_percent, reverse=True)[:limit]
```

Register in `strategies/registry.py` and set `STRATEGY=my_strategy` in `.env`.

## Troubleshooting

**Bot won't start**
- Check credentials in `.env`
- Run `python tests/scripts/validate_setup.py`
- Check `logs/` directory for errors

**Rate limit errors (429)**
- Enable Relayer mode (`RELAYER_ENABLED=True`) for unlimited transactions
- Or enable Builder credentials (`BUILDER_ENABLED=True`) and apply for verification
- Increase `SCAN_INTERVAL_MS` — minimum ~115,000 ms for verified builder, ~3,456,000 ms for unverified

**All prices return 0.0**
- Your wallet private key is invalid or missing — `ClobClient` fell back to `client = None`
- Check `POLYMARKET_PRIVATE_KEY` and `POLYMARKET_FUNDER_ADDRESS` in `.env`

**Order aborted: slippage too high**
- The pre-trade gate rejected the order — the book was too thin for your position size
- Increase `SLIPPAGE_TOLERANCE_PERCENT` or reduce `CAPITAL_SPLIT_PERCENT`
- Check `MIN_VOLUME_USD` — low-liquidity markets will frequently trigger this

**Relayer orders failing**
- Verify `RELAYER_API_KEY` and `RELAYER_API_KEY_ADDRESS` are set correctly
- Generate a new key at [polymarket.com/settings?tab=api-keys](https://polymarket.com/settings?tab=api-keys)
- Check logs for the specific relayer error response

**Email alerts not working**
- Gmail requires an App Password: [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
- Test with `python tests/scripts/test_email.py`

**Discord alerts not working**
- Verify the webhook URL is correct and the channel allows webhooks
- Test with `python tests/scripts/test_discord.py`

**Dashboard not accessible**
- Check `DASHBOARD_ENABLED=True` and `DASHBOARD_PORT` in `.env`
- Default host is `127.0.0.1` (localhost only) — change to `0.0.0.0` only with a reverse proxy
- Check firewall rules for the configured port

**ScyllaDB errors**
- Leave `SCYLLA_ENABLED=False` (default) unless you have Docker running with `docker compose up -d`
- The bot runs fine with SQLite only

## Disclaimer

This framework is provided for educational purposes. Trading on prediction markets carries financial risk. Always test thoroughly in paper trading mode before using real funds. Comply with all applicable laws and regulations in your jurisdiction.

## License

This project is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0-only)**.

Copyright (C) 2026 [Thomas Quinn](https://github.com/Thomas-quinn7) ([LinkedIn](https://www.linkedin.com/in/thomassquinn/)) — primary author
               [Ciaran McDonnell](https://github.com/CiaranMcDonnell) — co-author

You may use, study, and modify this software for non-commercial and educational purposes. Any distribution or network deployment of this software, or derivative works, must be released under the same AGPL-3.0 license with full source code and attribution intact.

Commercial use — including deploying this framework as a service or incorporating it into a commercial product — is not permitted without explicit written permission from the authors.

See the [LICENSE](LICENSE) file for the full license text.
