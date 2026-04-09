# Polymarket Trading Framework

A Python framework for building and running automated trading bots on [Polymarket](https://polymarket.com). Provides the infrastructure for market scanning, order execution, portfolio tracking, real-time monitoring, and alerting — so you can focus on your own trading logic.

## Features

- **Market Scanner**: Continuously scans Polymarket markets across configurable categories with keyword and liquidity filters
- **Paper Trading Mode**: Full simulation with fake currency before going live — enabled by default
- **Simulation Mode**: Fully offline with synthetic market data — no API calls required
- **Web Dashboard**: Real-time monitoring of positions, P&L, and trade history
- **Alert System**: Email and Discord notifications for trades and system events
- **Portfolio Tracking**: Position management, P&L calculation, and trade history with SQLite persistence
- **Relayer API Support**: Unlimited order relay transactions via Polymarket Relayer keys (no tier approval required)
- **Builder API Support**: Tiered order attribution with rate limits (unverified → verified → partner)
- **Modular Strategy Architecture**: Plug in your own strategy — the framework handles the rest
- **455 unit tests** covering execution, portfolio, data models, validation, and pipeline

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
cp .env.template .env
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

The framework calculates the safe scan interval automatically. Override via `SCAN_INTERVAL_MS` in `.env`.

### Trading Mode

```env
# TRADING_MODE: paper | simulation
# paper      — real Polymarket API prices, simulated order execution
# simulation — fully offline, synthetic market data, no API calls
TRADING_MODE=paper

# Block all real-money trades regardless of other settings (recommended during testing)
PAPER_TRADING_ONLY=True
FAKE_CURRENCY_BALANCE=10000.00
```

### Strategy

```env
# Strategy to load from strategies/registry.py
# Built-in options: settlement_arbitrage | paper_demo | demo_buy
STRATEGY=settlement_arbitrage
```

### Position Sizing

```env
MAX_POSITIONS=5                # Maximum concurrent open positions
CAPITAL_SPLIT_PERCENT=0.20     # Fraction of balance allocated per position (0.0–1.0)
STOP_LOSS_PERCENT=0.0          # Exit position if price drops this % below entry (0 = disabled)
MIN_CONFIDENCE=0.5             # Minimum strategy confidence score to enter (0.0–1.0)
MIN_VOLUME_USD=1000.0          # Skip markets below this USD volume
```

### Market Scanner

```env
# Categories to scan (comma-separated)
SCAN_CATEGORIES=crypto,fed,regulatory,other

# Scan interval in milliseconds (see rate limits table above)
SCAN_INTERVAL_MS=30000

# Paper demo strategy tuning (used by paper_demo strategy)
PAPER_DEMO_HOLD_SECONDS=60
PAPER_DEMO_MIN_VOLUME=1000.0
PAPER_DEMO_CATEGORY=crypto
```

### Execution

```env
ORDER_TYPE=FOK                 # Fill or Kill (only supported type)
SLIPPAGE_TOLERANCE_PERCENT=5.0
MAX_RETRIES=3
RETRY_DELAY_MS=100
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
DASHBOARD_HOST=0.0.0.0
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

### Logging

```env
LOG_LEVEL=INFO    # DEBUG | INFO | WARNING | ERROR
LOG_TO_FILE=True
```

## Usage

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
3. Start scanning configured market categories on each tick
4. Pass discovered markets to your strategy for signal generation
5. Execute orders (paper or live) and track positions
6. Send alerts on trades and system events
7. Serve the web dashboard on the configured port

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

455 tests covering order execution, position tracking, P&L calculation, data models, validation, and pipeline logic.

## Project Structure

```
Polymarket_Trading/
├── config/
│   └── polymarket_config.py       # All settings, env var loading, rate-limit helpers
├── data/
│   ├── polymarket_client.py       # Gamma + CLOB API client (Relayer/Builder/Standard auth)
│   ├── polymarket_models.py       # SQLAlchemy database models
│   ├── market_schema.py           # Normalised market data model (PolymarketMarket)
│   └── simulation_markets.py      # Synthetic market generator for offline testing
├── strategies/
│   ├── base.py                    # Abstract base strategy class
│   ├── registry.py                # Strategy loader (STRATEGY env var selects strategy)
│   └── examples/
│       ├── settlement_arbitrage.py  # Near-settled market arbitrage strategy
│       ├── paper_demo.py            # Paper trading demo with configurable hold time
│       ├── demo_buy.py              # Single-buy demo strategy
│       └── enhanced_market_scanner.py # Enhanced multi-signal scanner
├── execution/
│   └── order_executor.py          # Order creation, submission, rollback, and history
├── portfolio/
│   ├── position_tracker.py        # Open position lifecycle management
│   └── fake_currency_tracker.py   # Paper trading balance (allocation / return)
├── utils/
│   ├── alerts.py                  # Unified email + Discord alerting with rate limiting
│   ├── logger.py                  # Structured logging
│   ├── pnl_tracker.py             # P&L statistics (win rate, profit factor, drawdown)
│   ├── execution_timer.py         # Execution timing utilities
│   └── webhook_sender.py          # Discord webhook implementation
├── api/
│   └── router.py                  # FastAPI REST endpoints for dashboard data
├── dashboard/                     # Web dashboard (HTML/CSS/JS)
├── pkg/
│   ├── config.py                  # Pydantic settings model (used by tests)
│   ├── errors.py                  # Typed exception hierarchy
│   └── logger.py                  # Structured logger setup
├── database/                      # SQLAlchemy session and migration helpers
├── tests/
│   ├── unit/                      # 455 pytest unit tests
│   │   ├── test_order_executor.py
│   │   ├── test_position_tracker.py
│   │   ├── test_fake_currency_tracker.py
│   │   ├── test_pnl_tracker.py
│   │   ├── test_polymarket_models.py
│   │   ├── test_market_schema.py
│   │   ├── test_data_pipeline.py  # Buy/sell/settle cycle tests
│   │   ├── test_data_validation.py # Data integrity and edge-case tests
│   │   ├── test_config.py
│   │   └── ...
│   ├── integration/               # Integration tests
│   └── scripts/                   # Manual validation and alert test scripts
│       ├── validate_setup.py
│       ├── test_email.py
│       ├── test_discord.py
│       └── quick_start.py
├── cmd/                           # CLI entry points
├── storage/                       # SQLite database (auto-created)
├── logs/                          # Log files (auto-created)
├── main.py                        # Bot entry point
├── pyproject.toml
├── requirements.txt
├── docker-compose.yml             # ScyllaDB container
└── .env                           # Your configuration (not committed)
```

## Key Components

### API Client (`data/polymarket_client.py`)

Wraps the Polymarket Gamma and CLOB APIs. Auth priority: **Relayer > Builder > Standard**.

- **Relayer mode**: submits signed orders to `https://relayer-v2.polymarket.com/` with L2 CLOB headers merged with `RELAYER_API_KEY` / `RELAYER_API_KEY_ADDRESS` headers. Unlimited transactions, no approval required.
- **Builder mode**: attaches builder attribution headers via `py_builder_signing_sdk`. Tiered daily limits.
- **Standard mode**: L2 CLOB authentication with wallet private key only.

All API calls retry 3× with exponential backoff (0.1s / 0.5s / 2.0s).

### Market Schema (`data/market_schema.py`)

Normalises raw Gamma API responses into a consistent `PolymarketMarket` model. Resolves field name differences between endpoints and provides helpers for category classification and liquidity checks.

### Strategy System (`strategies/`)

Strategies inherit from `BaseStrategy` in `strategies/base.py`. The active strategy is selected via the `STRATEGY` env var and loaded by `strategies/registry.py`.

**Built-in strategies:**

| Strategy | Description |
|----------|-------------|
| `settlement_arbitrage` | Scans for near-settled markets (price ≥ 0.985) with positive net edge after fees |
| `paper_demo` | Buys a configurable market category, holds for `PAPER_DEMO_HOLD_SECONDS`, then exits |
| `demo_buy` | Single demonstration buy — useful for validating execution end-to-end |

To add your own strategy, implement `BaseStrategy`, register it in `strategies/registry.py`, and set `STRATEGY=your_strategy` in `.env`.

### Order Executor (`execution/order_executor.py`)

Manages the full order lifecycle:
- Calculates position size from `CAPITAL_SPLIT_PERCENT` and available balance
- In paper mode: records the trade internally with no API calls
- In live mode: signs and submits a FOK market order, rolls back balance on failure
- Records all order history with timestamps and position IDs
- `execute_sell()` supports early exits; `settle_position()` handles settlement at a final price

### Portfolio Management (`portfolio/`)

- `PositionTracker`: tracks open positions, enforces `MAX_POSITIONS` limit, handles settlement
- `FakeCurrencyTracker`: paper trading balance with allocation slots per position
- `PnLTracker`: running statistics — total P&L, win rate, profit factor, max drawdown

### Alert System (`utils/alerts.py`)

Unified alerting with email (SMTP) and Discord (webhook) support. Alerts are fired on opportunity detection, trade execution, position settlement, and system errors.

### Web Dashboard (`dashboard/`)

FastAPI-backed dashboard serving real-time portfolio data via a browser UI at `http://localhost:8080`. Displays positions, P&L, trade history, and system status.

## Paper Trading

Enabled by default. Set `PAPER_TRADING_ONLY=True` in `.env` to ensure no real orders are ever submitted regardless of other settings.

In paper trading mode:
- All trades use fake currency (configured via `FAKE_CURRENCY_BALANCE`)
- P&L is tracked and reported identically to live mode
- Position sizing, stop-losses, and settlement all behave as in live mode
- No interaction with your real Polymarket balance

## Writing a Strategy

```python
from strategies.base import BaseStrategy
from data.market_schema import PolymarketMarket

class MyStrategy(BaseStrategy):
    def analyze(self, market: PolymarketMarket):
        """Return a TradeOpportunity if the market meets your criteria, else None."""
        if market.yes_price >= 0.90 and market.volume_usd >= 5000:
            from data.polymarket_models import TradeOpportunity, TradeStatus
            return TradeOpportunity(
                market_id=market.market_id,
                market_slug=market.market_slug,
                question=market.question,
                category=market.category,
                token_id_yes=market.token_id_yes,
                token_id_no=market.token_id_no,
                winning_token_id=market.token_id_yes,
                side="YES",
                opportunity_type="single",
                current_price=market.yes_price,
                edge_percent=(1.0 - market.yes_price) * 100,
                confidence=0.8,
                status=TradeStatus.DETECTED,
            )
        return None
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
- Check firewall rules for the configured port

**ScyllaDB errors**
- Leave `SCYLLA_ENABLED=False` (default) unless you have Docker running with `docker compose up -d`
- The bot runs fine with SQLite only

## Disclaimer

This framework is provided for educational purposes. Trading on prediction markets carries financial risk. Always test thoroughly in paper trading mode before using real funds. Comply with all applicable laws and regulations in your jurisdiction.

## License

This project is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0-only)**.

Copyright (C) 2026 Thomas Quinn (github.com/Thomas-quinn7)

You may use, study, and modify this software for non-commercial and educational purposes. Any distribution or network deployment of this software, or derivative works, must be released under the same AGPL-3.0 license with full source code and attribution intact.

Commercial use — including deploying this framework as a service or incorporating it into a commercial product — is not permitted without explicit written permission from the author.

See the [LICENSE](LICENSE) file for the full license text.
