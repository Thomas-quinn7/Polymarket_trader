# Polymarket Trading Framework

A production-quality Python framework for algorithmic trading on [Polymarket](https://polymarket.com) prediction markets. Handles market data, order execution, portfolio management, backtesting, and real-time monitoring — so strategy development is the only focus.

Built around the Polymarket CLOB (Central Limit Order Book) with support for both market orders and limit orders, fractional Kelly position sizing, per-trade session recording, and a live web dashboard.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                     Strategy Layer                       │
│   scan_for_opportunities() → get_best_opportunities()   │
│   should_exit() → get_exit_price()                      │
└────────────────────┬────────────────────────────────────┘
                     │
         ┌───────────▼────────────┐
         │    MarketProvider       │   Gamma API + 60s TTL cache
         │  filter → price resolve │   MarketCriteria pre-filters
         └───────────┬────────────┘
                     │
         ┌───────────▼────────────┐
         │    OrderExecutor        │   Slippage gate → Kelly sizing
         │    PaperPortfolio       │   Balance allocation / return
         │    PositionTracker      │   Open position lifecycle
         └───────────┬────────────┘
                     │
         ┌───────────▼────────────┐
         │  SQLite + Session Store │   Trade history, equity curve
         │  FastAPI Dashboard      │   Real-time P&L at :8080
         └────────────────────────┘
```

---

## Key Features

- **CLOB limit & market orders** — GTC limit orders and FOK market orders via the Polymarket CLOB SDK; Relayer and Builder API auth modes supported
- **Pre-trade slippage gate** — walks the live order book (10 levels) to estimate VWAP impact before each market order; aborts if slippage exceeds tolerance
- **Fractional Kelly sizing** — position size = full Kelly × configurable fraction, capped at `CAPITAL_SPLIT_PERCENT`; `override_capital` bypasses Kelly for fixed-size strategies
- **Category concentration limits** — caps open positions per market category to prevent correlated overexposure
- **Backtesting engine** — wall-clock timeline replay, side-aware YES/NO positions, half-spread model, configurable fees; strategies run unmodified against historical data
- **Session recording** — every settled trade persisted to SQLite and JSON: price, hold time, edge %, fees, gross/net P&L, outcome, equity curve
- **Ollama strategy review** — on shutdown a local LLM generates a natural-language session review; runs entirely on-device, no cloud API
- **Hot-reload config** — most `.env` settings apply without restart via `/api/reload`
- **776 unit tests** — execution, portfolio, data models, slippage estimation, config reload, backtest engine, metrics

---

## Installation

### Prerequisites

- Python 3.11 or higher
- [uv](https://docs.astral.sh/uv/getting-started/installation/) — fast Python package manager

**Install uv:**

```bash
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Setup

**1. Clone the repository**

```bash
git clone https://github.com/Thomas-quinn7/Polymarket_trader.git
cd Polymarket_trader
```

**2. Create a virtual environment**

```bash
uv venv
```

**3. Activate the virtual environment**

```bash
# Windows (Command Prompt)
.venv\Scripts\activate.bat

# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate
```

You should see `(.venv)` at the start of your terminal prompt.

**4. Install the project and all dependencies**

```bash
uv pip install -e ".[dev]"
```

This installs the framework in editable mode along with all development dependencies (pytest, black, flake8, etc.).

**5. Configure your environment**

```bash
cp .env.example .env
```

Open `.env` and fill in the required values:

```env
# Your Polymarket wallet credentials
POLYMARKET_PRIVATE_KEY=your_private_key_here
POLYMARKET_FUNDER_ADDRESS=your_wallet_address_here

# Set a strategy to run
STRATEGY=example_strategy

# Paper trading is enabled by default — no real money
TRADING_MODE=paper
PAPER_TRADING_ONLY=True
```

> **Getting your Polymarket credentials:** log in to [polymarket.com](https://polymarket.com), go to **Settings → Profile → Export Private Key**. Your funder address is the wallet address shown on the same page.

**6. Validate your setup**

```bash
python tests/scripts/validate_setup.py
```

This checks credentials, dependencies, and configuration before you run the bot.

**7. Run the bot**

```bash
python main.py
```

Then open `http://localhost:8080` in your browser to access the dashboard.

---

## API Authentication

The framework supports three authentication modes for submitting orders. They are applied in priority order: **Relayer → Builder → Standard**.

### Relayer API (recommended — unlimited)

Relayer keys provide unlimited relay transactions with no tier approval required. Generate one at [polymarket.com/settings?tab=api-keys](https://polymarket.com/settings?tab=api-keys).

```env
RELAYER_ENABLED=True
RELAYER_API_KEY=your_relayer_api_key
RELAYER_API_KEY_ADDRESS=your_wallet_address
```

When `RELAYER_ENABLED=True`, all signed orders are submitted to the Polymarket Relayer endpoint. Builder settings are ignored.

### Builder API (tiered rate limits)

Builder keys provide order attribution and higher rate limits. Apply for verification at [builder@polymarket.com](mailto:builder@polymarket.com).

```env
BUILDER_ENABLED=True
BUILDER_TIER=unverified        # unverified | verified | partner
BUILDER_API_KEY=your_api_key
BUILDER_SECRET=your_secret
BUILDER_PASSPHRASE=your_passphrase
```

### Rate limits

| Mode | Relay Transactions / Day | Recommended `SCAN_INTERVAL_MS` |
|------|--------------------------|-------------------------------|
| Standard / Unverified Builder | 100 | 3,456,000 ms (~57 min) |
| Builder Verified | 3,000 | 115,200 ms (~2 min) |
| Builder Partner / Relayer | Unlimited | 5,000 ms (5 s) |

Each full scan cycle makes approximately 4 API calls (one per market category). Adjust `SCAN_INTERVAL_MS` in `.env` based on your tier.

---

## Alerts

The bot sends notifications on trade execution, position settlement, and system errors. Both channels are optional and independent.

### Discord

**1. Create a webhook in Discord:**
- Open your server → channel settings → **Integrations** → **Webhooks** → **New Webhook**
- Copy the webhook URL

**2. Add to `.env`:**

```env
ENABLE_DISCORD_ALERTS=True
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN
DISCORD_MENTION_USER=<@YOUR_DISCORD_USER_ID>   # optional — tags you in alerts
```

> To find your Discord user ID: enable Developer Mode in Discord settings, then right-click your username and select **Copy User ID**.

**3. Test it:**

```bash
python tests/scripts/test_discord.py
```

### Email (SMTP)

**1. For Gmail — create an App Password:**
- Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
- Select **Mail** and your device, then generate the password
- Use the generated password in `.env`, not your account password

**2. Add to `.env`:**

```env
ENABLE_EMAIL_ALERTS=True
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your_email@gmail.com
SMTP_PASSWORD=xxxx xxxx xxxx xxxx   # App Password (spaces are fine)
ALERT_EMAIL_FROM=your_email@gmail.com
ALERT_EMAIL_TO=your_email@gmail.com
```

For other providers replace `SMTP_SERVER` and `SMTP_PORT` accordingly (e.g. Outlook uses `smtp.office365.com:587`).

**3. Test it:**

```bash
python tests/scripts/test_email.py
```

---

## Database

### SQLite (default — no setup required)

SQLite is used by default and requires no external process. The database file is created automatically at `./storage/trading.db` on first run.

```env
DB_ENABLED=True
DB_PATH=./storage/trading.db
```

The database stores positions, trades, and P&L history. It survives restarts — open positions are restored automatically on startup. The `storage/` directory is gitignored; back it up separately if you need to preserve trade history across machines.

### ScyllaDB (optional — order book snapshots)

ScyllaDB is used to store order book snapshots for market microstructure analysis. It is disabled by default and requires Docker.

```env
SCYLLA_ENABLED=True
SCYLLA_HOST=127.0.0.1
SCYLLA_PORT=9042
SCYLLA_KEYSPACE=polymarket
```

Start ScyllaDB with Docker:

```bash
docker run -d --name polymarket-scylla \
  -p 9042:9042 \
  scylladb/scylla:5.4 \
  --smp 1 --memory 750M --overprovisioned 1 --developer-mode 1
```

Or use Docker Compose (see below) which starts ScyllaDB alongside the bot automatically.

---

## Docker Compose (full stack)

Docker Compose starts three services together: the trading bot, ScyllaDB (order book storage), and Ollama (local LLM for post-session strategy reviews).

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows/macOS) or Docker Engine (Linux)

### Start the full stack

```bash
docker compose up -d
```

On first run this builds the bot image and pulls the ScyllaDB and Ollama images (~2 GB for Ollama). Subsequent starts are fast.

```bash
# Follow live logs
docker compose logs -f trading-bot

# Stop everything (data volumes are preserved)
docker compose down

# Stop and remove all data volumes (full reset)
docker compose down -v
```

### Services

| Service | Container | Port | Purpose |
|---------|-----------|------|---------|
| `trading-bot` | `polymarket-trading-bot` | `8080` | Bot + FastAPI dashboard |
| `scylla` | `polymarket-scylla` | `9042` | Order book snapshot storage |
| `ollama` | `polymarket-ollama` | `11434` | Local LLM for session reviews |

### Data persistence

Two host directories are mounted into the bot container:

| Host path | Container path | Contents |
|-----------|---------------|----------|
| `./logs` | `/app/logs` | Log files, session JSON exports, trade history |
| `./storage` | `/app/storage` | SQLite database (`trading.db`) |

Both directories are gitignored. Back them up manually if needed.

ScyllaDB and Ollama data are stored in Docker named volumes (`scylla_data`, `ollama_data`) and persist across container restarts automatically.

### GPU acceleration for Ollama (optional)

If you have an NVIDIA GPU and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) installed, uncomment the `deploy` block in `docker-compose.yml`:

```yaml
# ollama service — uncomment to enable GPU
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: all
          capabilities: [gpu]
```

---

## Ollama Strategy Review

After each session, the bot can generate a natural-language review of the strategy's performance using a local LLM. No data leaves your machine.

### Setup

**Without Docker** — install Ollama directly:

```bash
# macOS / Linux
curl -fsSL https://ollama.com/install.sh | sh

# Windows
# Download the installer from https://ollama.com/download
```

Pull the model (one-time, ~2 GB):

```bash
ollama pull llama3.2:3b
```

Enable in `.env`:

```env
OLLAMA_ENABLED=True
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b
```

**With Docker Compose** — Ollama starts automatically and pulls the model on first use. No extra steps needed.

### What the review covers

When the bot shuts down it sends the session summary (win rate, P&L, average hold time, market list) to Ollama and saves the generated review to both SQLite and the session JSON export. Reviews are accessible via:

```
GET /api/sessions/{session_id}        → full session including review text
POST /api/sessions/{session_id}/review → re-generate the review for a past session
```

---

## Dashboard

The FastAPI dashboard runs at `http://localhost:8080` and provides real-time monitoring.

### Authentication (optional)

By default the dashboard is open on localhost. To secure it when exposed on a network:

```env
DASHBOARD_API_KEY=your_secret_key_here
```

When set, all endpoints except `/api/health` require the header:

```
X-API-Key: your_secret_key_here
```

### Remote access

The default host is `127.0.0.1` (localhost only). To allow remote access:

```env
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=8080
```

> Only expose the dashboard publicly if it is behind a reverse proxy (nginx/Caddy) with HTTPS and authentication. Set `DASHBOARD_API_KEY` at minimum.

### Key endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/status` | Bot status, balance, open positions |
| `GET` | `/api/positions` | All open positions |
| `GET` | `/api/trades` | Trade history |
| `GET` | `/api/sessions` | All recorded sessions |
| `GET` | `/api/sessions/{id}` | Full session detail + Ollama review |
| `POST` | `/api/start` | Start the trading loop |
| `POST` | `/api/stop` | Stop the trading loop |
| `POST` | `/api/reload` | Hot-reload config from `.env` |
| `GET` | `/api/health` | Health check (no auth required) |

---

## Configuration Reference

All settings live in `.env`. Copy `.env.example` as a starting point.

```env
# ── Polymarket credentials ─────────────────────────────────────────────
POLYMARKET_PRIVATE_KEY=
POLYMARKET_FUNDER_ADDRESS=

# ── Trading mode ───────────────────────────────────────────────────────
TRADING_MODE=paper              # paper | simulation | live
PAPER_TRADING_ONLY=True         # hard block on real orders
FAKE_CURRENCY_BALANCE=10000.00  # starting balance in paper mode

# ── Strategy ───────────────────────────────────────────────────────────
STRATEGY=example_strategy

# ── Position sizing ────────────────────────────────────────────────────
MAX_POSITIONS=10
MAX_POSITIONS_PER_CATEGORY=4
CAPITAL_SPLIT_PERCENT=0.10      # fraction of balance per trade
KELLY_FRACTION=0.25             # Kelly multiplier (0.25 = quarter Kelly)
STOP_LOSS_PERCENT=0             # 0 = disabled

# ── Scanning ───────────────────────────────────────────────────────────
SCAN_INTERVAL_MS=5000
SCAN_CATEGORIES=crypto,fed,regulatory,other

# ── Execution ──────────────────────────────────────────────────────────
SLIPPAGE_TOLERANCE_PERCENT=5.0
TAKER_FEE_PERCENT=2.0

# ── Database ───────────────────────────────────────────────────────────
DB_ENABLED=True
DB_PATH=./storage/trading.db

# ── Dashboard ──────────────────────────────────────────────────────────
DASHBOARD_ENABLED=True
DASHBOARD_PORT=8080
DASHBOARD_HOST=127.0.0.1
DASHBOARD_API_KEY=              # leave empty to disable auth

# ── Alerts ─────────────────────────────────────────────────────────────
ENABLE_DISCORD_ALERTS=False
DISCORD_WEBHOOK_URL=
ENABLE_EMAIL_ALERTS=False
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
ALERT_EMAIL_TO=
```

---

## Usage

```bash
# Start the bot (waits for WebUI start command)
python main.py

# Auto-start the trading loop immediately
python main.py --auto-start

# Force paper mode regardless of .env
python main.py --paper --strategy example_strategy

# Live mode (interactive confirmation prompt required)
python main.py --live

# Headless run — no dashboard, auto-start
python main.py --auto-start --no-dashboard
```

---

## Writing a Strategy

Copy `strategies/example_strategy/` to a new folder and implement the three required blocks:

```python
class MyStrategy(BaseStrategy):

    def scan_for_opportunities(self, markets):
        for market in markets:
            price = market.resolved_price          # pre-resolved by MarketProvider
            gross_edge = your_signal(market)       # implement this
            net_edge = gross_edge - taker_fee

            if net_edge > 0:
                opp = TradeOpportunity(
                    market_id=market.market_id,
                    winning_token_id=market.token_ids[0],   # YES token
                    current_price=price,
                    edge_percent=net_edge,
                    confidence=your_confidence(market),
                    ...
                )
                yield opp

    def get_best_opportunities(self, opportunities, limit=5):
        return sorted(opportunities, key=lambda o: o.edge_percent, reverse=True)[:limit]

    def should_exit(self, position, current_price):
        return datetime.now(timezone.utc) >= position.expires_at
```

Register in `strategies/registry.py` and set `STRATEGY=my_strategy` in `.env`. The framework handles scanning, execution, sizing, persistence, and alerting automatically.

---

## Backtesting

```python
from backtesting import BacktestRunner, BacktestConfig

config = BacktestConfig(
    strategy_name="example_strategy",
    start_date="2025-01-01",
    end_date="2025-04-01",
    initial_balance=1000.0,
    taker_fee_pct=2.0,
    half_spread_pct=1.0,    # bid/ask spread model
    category="crypto",
)

runner = BacktestRunner(config)
results = runner.run()
print(results.metrics.sharpe_ratio, results.metrics.win_rate)
```

The backtest engine replays historical price series through the strategy's `scan_for_opportunities()` and `should_exit()` methods unmodified. Supports YES and NO side positions, configurable spread/fee model, and outputs an equity curve alongside full trade records.

---

## Project Structure

```
Polymarket_Trading/
├── config/
│   └── polymarket_config.py          # Settings, env var loading, hot-reload
├── data/
│   ├── polymarket_client.py          # Gamma + CLOB API client
│   ├── market_schema.py              # Normalised PolymarketMarket model
│   ├── market_provider.py            # Fetch → filter → price-resolve pipeline
│   ├── database.py                   # SQLite position/trade persistence
│   └── session_store.py              # Per-run session + equity curve recording
├── strategies/
│   ├── base.py                       # BaseStrategy abstract class
│   ├── registry.py                   # Strategy auto-discovery loader
│   ├── config_loader.py              # YAML config + env-var override loader
│   └── example_strategy/             # Fully-documented strategy template
├── backtesting/
│   ├── engine.py                     # Wall-clock timeline replay engine
│   ├── config.py                     # BacktestConfig (fees, spread, capital)
│   ├── metrics.py                    # Sharpe, Sortino, Calmar, drawdown
│   ├── fetcher.py                    # Historical price data fetcher
│   └── runner.py                     # High-level run() entry point
├── execution/
│   └── order_executor.py             # Slippage gate, Kelly sizing, order lifecycle
���── portfolio/
│   ├── position_tracker.py           # Open position management
│   ├── paper_portfolio.py            # Simulated capital allocation/return
│   └── fake_currency_tracker.py      # Backward-compatibility alias
├── utils/
│   ├── pnl_tracker.py                # Win rate, profit factor, max drawdown
│   ├── slippage.py                   # Order-book VWAP slippage estimator
│   ├── alerts.py                     # Email + Discord notifications
│   └── session_reviewer.py           # Ollama post-session review generator
├── dashboard/
│   └── api.py                        # FastAPI dashboard (positions, P&L, sessions)
├── tests/
│   └── unit/                         # 776 pytest unit tests
├── main.py                           # Bot entry point and trading loop
└── docker-compose.yml                # ScyllaDB + Ollama containers
```

---

## Paper Trading

Paper mode is enabled by default (`PAPER_TRADING_ONLY=True`). It uses real Polymarket prices with simulated execution — no real funds are involved.

- Slippage estimated from the live order book and recorded per position
- P&L, position sizing, stop-losses, and settlement behave identically to live mode
- Session JSON export works the same as live — ready to chart and analyse

---

## Running Tests

```bash
python -m pytest tests/unit/
```

776 tests covering order execution, portfolio management, P&L calculation, slippage estimation, data models, config reload, backtesting engine, and metrics.

---

## Disclaimer

For educational purposes. Trading on prediction markets carries financial risk. Always test thoroughly in paper mode before using real funds. Comply with all applicable laws in your jurisdiction.

## License

**GNU Affero General Public License v3.0 (AGPL-3.0-only)**

Copyright (C) 2026 [Thomas Quinn](https://github.com/Thomas-quinn7) ([LinkedIn](https://www.linkedin.com/in/thomassquinn/)) — primary author
               [Ciaran McDonnell](https://github.com/CiaranMcDonnell) — co-author

Non-commercial and educational use permitted. Any distribution or network deployment must be released under the same AGPL-3.0 license with full attribution. Commercial use requires explicit written permission from the authors.
