# Polymarket Arbitrage Bot

An automated arbitrage trading bot for Polymarket that implements a 98.5 cent settlement arbitrage strategy. The bot monitors markets for opportunities where the price is between $0.985 and $1.00, executes trades 1-2 seconds before market close, and tracks wins/losses with comprehensive P&L monitoring.

## Features

- **98.5 Cent Settlement Arbitrage Strategy**: Automatically detects opportunities in the 98.5-100 cent range
- **Paper Trading Mode**: Simulates trading with fake currency ($10,000 starting balance)
- **Real-time Monitoring**: Web dashboard with live P&L, positions, and trade history
- **Comprehensive Alerts**: Email and Discord notifications for trades, wins, and losses
- **P&L Tracking**: Detailed win/loss statistics, drawdown monitoring, and profit analysis
- **Configurable Timing**: Adjust execution timing (default: 2 seconds before market close)
- **Risk Management**: Max 5 positions with equal 20% capital allocation
- **Error Handling**: Alert and continue on errors - never stop trading

## Strategy Overview

The 98.5 cent settlement arbitrage strategy works as follows:

1. **Monitor Markets**: Continuously scan crypto markets for price opportunities
2. **Price Filter**: Only consider markets with YES token price in [0.985, 1.00]
3. **Timing**: Execute trades 1-2 seconds before market close (configurable)
4. **Position**: Buy the winning outcome (YES token when price > 98.5 cents)
5. **Settlement**: Automatically settle positions when market resolves
6. **Profit**: Small edge on each trade (typically 0.5-1.5% per position)

### Why This Strategy Works

- **Price Confirmation**: Price > 98.5 cents indicates high probability of YES outcome
- **No External Data Needed**: Price threshold itself provides confirmation
- **Fast Execution**: Trading 1-2 seconds before close ensures correct side
- **Consistent Edge**: Each trade has a small mathematical advantage

## Installation

### Prerequisites
- uv brew install uv https://docs.astral.sh/uv/getting-started/installation/#installation-methods
- Python 3.11 or higher
- pip (Python package manager)

### Setup

1. **Clone repository**:
```bash
cd Polymarket_trading
```

2. **Create a virtual environment**:
Install UV
```bash
Powershell: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
Curl: curl -LsSf https://astral.sh/uv/install.sh | sh
```

3. **Create a virtual environment**:
```bash
uv venv
source venv/bin/activate  # On Windows: .venv\Scripts\activate
```

4. **Install dependencies**:
```bash
pip install -r requirements.txt
```

5. **Configure environment variables**:
```bash
cp .env.example .env
# Edit .env with your configuration
```

6. **Set up your Polymarket credentials**:
   - Get your Polymarket private key from [polymarket.com](https://polymarket.com)
   - Add to `.env` file: `POLYMARKET_PRIVATE_KEY=your_key_here`

7. **[Optional but Recommended]** Get Builder Verification:
   - Follow the [Builder Verification Guide](BUILDER_VERIFICATION.md)
   - Get 3000 requests/day (vs 200 unverified)
   - Enable builder features and leaderboard access

## Configuration

Edit `.env` file to configure the bot:

### Essential Configuration

```env
# Polymarket API
POLYMARKET_PRIVATE_KEY=your_polymarket_private_key_here
POLYMARKET_FUNDER_ADDRESS=your_funder_address_here

# Builder Configuration (recommended for 3000 req/day)
BUILDER_ENABLED=False
BUILDER_API_KEY=your_builder_api_key_here
BUILDER_SECRET=your_builder_secret_here
BUILDER_PASSPHRASE=your_builder_passphrase_here

# Paper Trading
PAPER_TRADING_ENABLED=True
PAPER_TRADING_ONLY=True  # Safety: Set to True to ensure ONLY paper trading (never real money)
FAKE_CURRENCY_BALANCE=10000.00
```

### Alert Configuration (Optional)

```env
# Email Alerts
ENABLE_EMAIL_ALERTS=True
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your_email@gmail.com
SMTP_PASSWORD=your_app_password_here
ALERT_EMAIL_TO=your_email@gmail.com

# Discord Alerts
ENABLE_DISCORD_ALERTS=True
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN
DISCORD_MENTION_USER=your_discord_username
```

### Strategy Configuration

```env
# Timing
EXECUTE_BEFORE_CLOSE_SECONDS=2

# Price Thresholds
MIN_PRICE_THRESHOLD=0.985
MAX_PRICE_THRESHOLD=1.00

# Position Management
MAX_POSITIONS=5
CAPITAL_SPLIT_PERCENT=0.2

# Scanning
SCAN_INTERVAL_MS=500
```

### Dashboard Configuration

```env
# Dashboard
DASHBOARD_ENABLED=True
DASHBOARD_PORT=8080
DASHBOARD_HOST=0.0.0.0
```

### Logging Configuration

```env
# Logging
LOG_LEVEL=INFO
LOG_TO_FILE=True
```

### Rate Limits

The bot respects Polymarket API rate limits:

| Mode | Rate Limit | Builder Status |
|------|------------|----------------|
| Unverified | 200 requests/day | No |
| Verified | 3000 requests/day | Yes |

**Recommendation**: Enable Builder credentials (`BUILDER_ENABLED=True`) for 15x higher rate limit and access to builder features.

## Testing Your Setup

We've provided several scripts to help you validate your setup:

### 1. Quick Start Script

The fastest way to get started:

```bash
# Run quick start script
python quick_start.py
```

This will:
- Create a virtual environment
- Install all dependencies
- Create `.env` from template
- Guide you through configuration

### 2. Validate Everything

Before starting the bot, run the validation script:

```bash
python validate_setup.py
```

This will check:
- ✅ Project structure
- ✅ All dependencies installed
- ✅ Polymarket credentials configured
- ✅ Builder credentials (optional)
- ✅ Paper trading mode enabled
- ✅ Strategy configuration correct
- ✅ Email alerts configured (optional)
- ✅ Discord webhook working (optional)

**All checks must pass before running the bot.**

### 3. Test Email Alerts

If you've configured email alerts, test them:

```bash
python test_email.py
```

This will:
- Test SMTP connection
- Test authentication
- Send a test email to verify setup

**For Gmail users**: You must use an App Password, not your regular password
- Get one at: https://myaccount.google.com/apppasswords

### 4. Test Discord Alerts

If you've configured Discord alerts, test them:

```bash
python test_discord.py
```

This will:
- Test webhook connection
- Send a test message with user mention
- Verify message format

### Safety Features

The bot includes multiple safety features to ensure paper trading only:

#### 1. Paper Trading Mode

The bot has two paper trading settings in `.env`:

```env
PAPER_TRADING_ENABLED=True      # Enables paper trading features
PAPER_TRADING_ONLY=True       # Safety: Blocks any real money trades
```

**When `PAPER_TRADING_ONLY=True`**:
- ✅ All trades use fake currency only
- ✅ No real money can be spent
- ✅ P&L is tracked in fake currency
- ✅ Safety warning on bot startup
- ✅ Cannot accidentally switch to real trading

#### 2. Fake Currency Tracking

The bot tracks all trades with fake currency:
- Starting balance: $10,000
- 20% allocation per position
- Automatic return on settlements
- P&L tracking and reporting

#### 3. Safety Warnings

When the bot starts in safety mode, you'll see:
```
🔒 SAFETY MODE: Only paper trading is allowed - no real money trades
```

This confirms you're protected from real-money trades.

## Usage

### Start the Trading Bot

```bash
python main.py
```

The bot will:
1. Initialize all components (Polymarket client, strategy, portfolio, alerts)
2. Start scanning for arbitrage opportunities
3. Execute trades at optimal timing
4. Track all positions and P&L
5. Send alerts on important events
6. Handle errors gracefully (alert and continue)

### Access the Dashboard

Open your browser and navigate to:
```
http://localhost:8080
```

The dashboard provides:
- Real-time P&L display
- Open positions with details
- Trade history with wins/losses
- System status and uptime
- Portfolio summary
- Auto-refresh every 5 seconds

## Project Structure

```
Polymarket_trading/
├── config/                    # Configuration
│   ├── __init__.py
│   └── polymarket_config.py
├── data/                      # Data layer
│   ├── __init__.py
│   ├── polymarket_client.py   # Polymarket API client
│   └── polymarket_models.py   # Database models
├── database/                  # Database
│   ├── __init__.py
│   └── init_db.py            # Database initialization
├── dashboard/                 # Web dashboard
│   ├── __init__.py
│   ├── api.py                # FastAPI REST API
│   └── static/
│       ├── index.html        # Dashboard UI
│       ├── style.css         # Dashboard styles
│       └── app.js           # Dashboard logic
├── execution/                # Trade execution
│   ├── __init__.py
│   └── order_executor.py    # Order execution
├── julia/                    # Julia implementation (future)
├── portfolio/                # Portfolio management
│   ├── __init__.py
│   ├── fake_currency_tracker.py  # Fake currency tracking
│   └── position_tracker.py   # Position tracking
├── strategies/               # Trading strategies
│   ├── __init__.py
│   └── settlement_arbitrage.py  # 98.5 cent strategy
├── utils/                    # Utilities
│   ├── __init__.py
│   ├── alerts.py            # Alert management
│   ├── email_sender.py      # Email notifications
│   ├── logger.py            # Logging
│   ├── pnl_tracker.py       # P&L tracking
│   └── webhook_sender.py    # Discord notifications
├── logs/                     # Log files
├── main.py                   # Main bot entry point
├── requirements.txt          # Python dependencies
├── .env.example             # Configuration template
├── .gitignore              # Git ignore rules
├── README.md               # This file
└── SECURITY.md              # Security guide
```

## Key Components

### Trading Bot (`main.py`)

The main orchestrator that:
- Initializes all components
- Runs the trading loop
- Scans for opportunities
- Executes trades at optimal timing
- Handles errors gracefully

### Strategy (`strategies/settlement_arbitrage.py`)

Implements the 98.5 cent arbitrage strategy:
- Scans markets for price opportunities
- Filters by price range [0.985, 1.00]
- Prioritizes by edge (profit potential)
- Calculates position sizes

### Portfolio Management (`portfolio/`)

- `fake_currency_tracker.py`: Tracks paper trading balance
- `position_tracker.py`: Tracks individual positions and settlements

### Execution (`execution/order_executor.py`)

Handles paper trading execution:
- Simulates buy orders
- Tracks settlements
- Calculates P&L

### P&L Tracking (`utils/pnl_tracker.py`)

Comprehensive profit/loss tracking:
- Win/loss statistics
- Drawdown monitoring
- Profit factor calculation
- Trade history

### Alerts (`utils/alerts.py`)

Alert management system:
- Email notifications
- Discord webhooks with user mentions
- Rate limiting
- Alert history

### Dashboard (`dashboard/`)

Web-based monitoring:
- Real-time P&L display
- Open positions table
- Trade history
- System status
- Auto-refresh (5 seconds)

## Risk Management

The bot implements several risk controls:

1. **Max Positions**: Maximum 5 open positions
2. **Equal Allocation**: 20% of capital per position
3. **Price Threshold**: Only trade in [0.985, 1.00] range
4. **Timing Control**: Execute 1-2 seconds before close
5. **Paper Trading**: Test with fake currency first

## Monitoring and Alerts

### Alert Types

- **Trade Executed**: When a trade is executed
- **Position Opened**: When a new position is opened
- **Position Settled**: When a position settles (WIN/LOSS)
- **Position Loss**: When a position results in a loss
- **System Start/Stop**: When the bot starts or stops
- **System Error**: When an error occurs

### Alert Channels

- **Email**: SMTP-based email notifications
- **Discord**: Webhook-based Discord messages with user mentions

## Troubleshooting

### Common Issues

**Bot won't start**:
- Check your Polymarket credentials in `.env`
- Ensure `py-clob-client` is installed
- Check logs in `logs/` directory

**Builder credentials not working**:
- Verify `BUILDER_ENABLED=True` in `.env`
- Ensure `py-builder-signing-sdk` is installed
- Check that all builder credentials (key, secret, passphrase) are correct
- Verify credentials match what's shown in [Builder Profile](https://polymarket.com/settings?tab=builder)
- Check logs for specific error messages

**Rate limit errors (429)**:
- Enable builder credentials for 3000 req/day (vs 200)
- Check your current tier in [Builder Profile](https://polymarket.com/settings?tab=builder)
- Wait for rate limit to reset (daily reset at midnight UTC)

**Email not working**:
- For Gmail: Must use App Password (not regular password)
- Get App Password: https://myaccount.google.com/apppasswords
- Check 2FA settings
- Test with: `python test_email.py`

**Discord not working**:
- Verify webhook URL is correct
- Check bot has permission to send messages
- Test with: `python test_discord.py`
- Check webhook doesn't have rate limiting

**Not seeing opportunities**:
- Ensure markets are available on Polymarket
- Check price thresholds in configuration (0.985 - 1.00)
- Verify internet connection
- Check Polymarket API status

**Dashboard not accessible**:
- Check dashboard port (default 8080)
- Ensure `DASHBOARD_ENABLED=True` in `.env`
- Check firewall settings

## Quick Reference

### One-Line Setup

```bash
python quick_start.py && python validate_setup.py && python main.py
```

### Common Commands

```bash
# Setup
python quick_start.py              # Full setup automation

# Validate
python validate_setup.py           # Check everything
python test_email.py              # Test email alerts
python test_discord.py           # Test Discord alerts

# Run
python main.py                   # Start trading bot

# Dashboard
http://localhost:8080            # Access web dashboard
```

## Support

For issues, questions, or contributions, please refer to:
- Project documentation
- Builder Verification Guide: `BUILDER_VERIFICATION.md`
- Check logs in `logs/` directory
- Create an issue in the repository

## Disclaimer

This bot is for educational purposes only. Trading on Polymarket involves financial risk. Always:
1. Start with paper trading
2. Understand the strategy thoroughly
3. Only trade with money you can afford to lose
4. Comply with all applicable laws and regulations

## License

This project is provided as-is for educational purposes.


uv sync 
.venv\Scripts\activate
uv run python main.py
