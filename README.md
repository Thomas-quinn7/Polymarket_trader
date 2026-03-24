# Polymarket Trading Framework

A Python framework for building and running automated trading bots on [Polymarket](https://polymarket.com). Provides the infrastructure for market scanning, order execution, portfolio tracking, real-time monitoring, and alerting — so you can focus on your own trading logic.

## Features

- **Market Scanner**: Continuously scans Polymarket markets with configurable category and keyword filters
- **Paper Trading Mode**: Full simulation with fake currency before going live
- **Web Dashboard**: Real-time monitoring of positions, P&L, and trade history
- **Alert System**: Email and Discord notifications for trades and system events
- **Portfolio Tracking**: Position management, P&L calculation, and trade history
- **Rate-Aware API Client**: Respects Polymarket API limits with configurable scan intervals
- **Modular Architecture**: Plug in your own strategy — the framework handles the rest

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

6. **[Recommended] Get Builder Verification**:
   - Increases API limit from 200 to 3,000 requests/day
   - See [Builder Profile](https://polymarket.com/settings?tab=builder) on Polymarket

## Configuration

All configuration is done via the `.env` file.

### Core Credentials

```env
# Polymarket API
POLYMARKET_PRIVATE_KEY=your_polymarket_private_key_here
POLYMARKET_FUNDER_ADDRESS=your_funder_address_here

# Builder credentials (recommended — 15x higher rate limit)
BUILDER_ENABLED=False
BUILDER_API_KEY=your_builder_api_key_here
BUILDER_SECRET=your_builder_secret_here
BUILDER_PASSPHRASE=your_builder_passphrase_here
```

### Paper Trading

```env
PAPER_TRADING_ENABLED=True
PAPER_TRADING_ONLY=True     # Blocks all real-money trades — recommended during testing
FAKE_CURRENCY_BALANCE=10000.00
```

### Market Scanner

```env
# Categories to scan (all enabled by default)
ENABLE_CRYPTO_MARKETS=True
ENABLE_FED_MARKETS=True
ENABLE_REGULATORY_MARKETS=True
ENABLE_OTHER_MARKETS=True

# Liquidity filter — skip markets below this volume
MIN_VOLUME_USD=1000.0

# Scan interval (30s is the minimum safe interval for builder mode)
SCAN_INTERVAL_MS=30000
```

### Alerts

```env
# Email
ENABLE_EMAIL_ALERTS=True
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your_email@gmail.com
SMTP_PASSWORD=your_app_password
ALERT_EMAIL_TO=your_email@gmail.com

# Discord
ENABLE_DISCORD_ALERTS=True
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_WEBHOOK
DISCORD_MENTION_USER=your_discord_username
```

### Dashboard

```env
DASHBOARD_ENABLED=True
DASHBOARD_PORT=8080
DASHBOARD_HOST=0.0.0.0
```

### Logging

```env
LOG_LEVEL=INFO
LOG_TO_FILE=True
```

### API Rate Limits

| Mode | Requests/day |
|------|-------------|
| Unverified | 200 |
| Builder verified | 3,000 |

Enable builder credentials to avoid hitting rate limits in production.

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
1. Connect to Polymarket via the CLOB and Gamma APIs
2. Start scanning configured market categories
3. Pass discovered markets to your strategy
4. Execute orders (paper or live) and track positions
5. Send alerts on trades and system events

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

> **Gmail users**: Use an App Password, not your account password. Generate one at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).

## Project Structure

```
Polymarket_Trading/
├── config/                        # Configuration
│   └── polymarket_config.py       # All settings and env var loading
├── data/                          # Data layer
│   ├── polymarket_client.py       # Gamma + CLOB API client
│   ├── polymarket_models.py       # Database models (SQLAlchemy)
│   └── market_schema.py           # Normalised market data model
├── internal/                      # Domain-driven core modules
│   └── core/
│       ├── scanner/               # Market scanning service
│       ├── execution/             # Order execution service
│       ├── portfolio/             # Portfolio management service
│       └── notifications/         # Notification service
├── strategies/                    # Strategy implementations (demos included)
├── execution/                     # Order executor
├── portfolio/                     # Position and fake-currency tracking
├── api/                           # FastAPI REST endpoints
├── dashboard/                     # Web dashboard (HTML/CSS/JS)
├── utils/                         # Shared utilities (logger, alerts, P&L)
├── tests/
│   ├── unit/                      # Pytest unit tests
│   ├── integration/               # Pytest integration tests
│   └── scripts/                   # Manual setup and validation scripts
├── cmd/                           # CLI entry points
├── main.py                        # Bot entry point
├── requirements.txt
└── .env.template                  # Configuration template
```

## Key Components

### API Client (`data/polymarket_client.py`)
Wraps the Polymarket Gamma and CLOB APIs. Handles paginated market fetching, authentication, order placement, price queries, and order book access.

### Market Schema (`data/market_schema.py`)
Normalises raw API responses into a consistent `PolymarketMarket` model. Resolves field name differences between API endpoints and provides helpers for category classification, time-to-close, and liquidity checks.

### Market Scanner (`internal/core/scanner/`)
Domain-driven scanner service. Fetches markets across configured categories, applies keyword and liquidity filters, and tracks seen markets across restarts (persisted to disk).

### Portfolio Management (`portfolio/`)
Tracks open positions, paper trading balance, and settlement. Records all trade outcomes for P&L reporting.

### Execution (`execution/order_executor.py`)
Handles order creation and submission. In paper trading mode, simulates execution against fake currency with no real orders sent.

### Alert System (`utils/alerts.py`)
Unified alerting with email (SMTP) and Discord (webhook) support. Includes rate limiting and alert history.

### Web Dashboard (`dashboard/`)
FastAPI-backed dashboard serving real-time portfolio data and trade history via a browser UI.

## Paper Trading

Paper trading is fully supported and enabled by default. Set `PAPER_TRADING_ONLY=True` in `.env` to ensure no real orders are ever submitted regardless of other settings.

When running in paper trading mode:
- All trades use fake currency
- P&L is tracked and reported as normal
- No interaction with your real Polymarket balance

## Troubleshooting

**Bot won't start**
- Check credentials in `.env`
- Run `python tests/scripts/validate_setup.py`
- Check `logs/` directory for errors

**Rate limit errors (429)**
- Enable builder credentials (`BUILDER_ENABLED=True`)
- Increase `SCAN_INTERVAL_MS` — minimum ~115,000ms for builder, ~1,728,000ms for unverified

**Email alerts not working**
- Gmail requires an App Password: [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
- Test with `python tests/scripts/test_email.py`

**Discord alerts not working**
- Verify the webhook URL is correct and the channel allows webhooks
- Test with `python tests/scripts/test_discord.py`

**Dashboard not accessible**
- Check `DASHBOARD_ENABLED=True` and `DASHBOARD_PORT` in `.env`
- Check firewall rules for the configured port

## Disclaimer

This framework is provided for educational purposes. Trading on prediction markets carries financial risk. Always test thoroughly in paper trading mode before using real funds. Comply with all applicable laws and regulations in your jurisdiction.

## License

This project is provided as-is for educational purposes.
