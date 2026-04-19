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
- **790 unit tests** — execution, portfolio, data models, slippage estimation, config reload, backtest engine, metrics

---

## Installation

### Prerequisites
- Python 3.11+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (fast package manager)

```bash
git clone https://github.com/Thomas-quinn7/Polymarket_trader.git
cd Polymarket_trader

uv venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

uv pip install -e .
cp .env.example .env
# edit .env with your credentials
```

---

## Configuration

All settings live in `.env`. The most important ones:

```env
# Auth
POLYMARKET_PRIVATE_KEY=your_key
POLYMARKET_FUNDER_ADDRESS=your_address

# Mode
TRADING_MODE=paper          # paper | simulation | live
PAPER_TRADING_ONLY=True
FAKE_CURRENCY_BALANCE=10000.00

# Strategy
STRATEGY=example_strategy   # folder name under strategies/

# Sizing
MAX_POSITIONS=10
MAX_POSITIONS_PER_CATEGORY=4
CAPITAL_SPLIT_PERCENT=0.10
KELLY_FRACTION=0.25

# Scanning
SCAN_INTERVAL_MS=5000
```

### API Rate Limits

| Auth Mode | Relay Transactions/Day | Minimum Safe Scan Interval |
|-----------|------------------------|---------------------------|
| Standard / Unverified Builder | 100 | ~57 min |
| Builder Verified | 3,000 | ~2 min |
| Builder Partner / Relayer | Unlimited | 5 s |

---

## Usage

```bash
# Start the bot (waits for WebUI start command)
python main.py

# Auto-start immediately
python main.py --auto-start

# Force paper mode
python main.py --paper --strategy example_strategy

# Live mode (confirmation prompt required)
python main.py --live
```

Open the dashboard at `http://localhost:8080` to monitor positions, P&L, and trade history.

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
├── portfolio/
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
│   └── unit/                         # 790 pytest unit tests
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

790 tests covering order execution, portfolio management, P&L calculation, slippage estimation, data models, config reload, backtesting engine, and metrics.

---

## Disclaimer

For educational purposes. Trading on prediction markets carries financial risk. Always test thoroughly in paper mode before using real funds. Comply with all applicable laws in your jurisdiction.

## License

**GNU Affero General Public License v3.0 (AGPL-3.0-only)**

Copyright (C) 2026 [Thomas Quinn](https://github.com/Thomas-quinn7) ([LinkedIn](https://www.linkedin.com/in/thomassquinn/)) — primary author
               [Ciaran McDonnell](https://github.com/CiaranMcDonnell) — co-author

Non-commercial and educational use permitted. Any distribution or network deployment must be released under the same AGPL-3.0 license with full attribution. Commercial use requires explicit written permission from the authors.
