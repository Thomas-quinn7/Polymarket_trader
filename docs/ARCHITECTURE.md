# Architecture & Trading Logic — In-Depth Reference

This document explains the internal mechanics of each major component: how data flows through the system, how the example strategy makes decisions, and how execution, position management, and risk controls work together.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Market Data Pipeline](#2-market-data-pipeline)
3. [Settlement Arbitrage Strategy](#3-settlement-arbitrage-strategy)
4. [Confidence Scoring](#4-confidence-scoring)
5. [Edge Filtering Modes](#5-edge-filtering-modes)
6. [Order Execution Flow](#6-order-execution-flow)
7. [Pre-Trade Slippage Estimation](#7-pre-trade-slippage-estimation)
8. [Position Lifecycle](#8-position-lifecycle)
9. [Capital Sizing](#9-capital-sizing)
10. [Stop-Loss Mechanism](#10-stop-loss-mechanism)
11. [P&L Tracking](#11-pl-tracking)
12. [Hot-Reload Configuration](#12-hot-reload-configuration)
13. [Authentication Modes](#13-authentication-modes)
14. [Alert System](#14-alert-system)
15. [SQLite Persistence](#15-sqlite-persistence)
16. [Strategy Session Tracking](#16-strategy-session-tracking)
17. [Ollama Strategy Review](#17-ollama-strategy-review)

---

## 1. System Overview

The bot is a single Python process with four concurrent concerns:

```
┌─────────────────────────────────────────────────────────┐
│  main process                                           │
│                                                         │
│  ┌─────────────┐   ┌──────────────────────────────┐    │
│  │  Dashboard  │   │  Trading Loop (daemon thread) │    │
│  │  (uvicorn   │   │                               │    │
│  │   thread)   │   │  ┌─────────────────────────┐ │    │
│  └─────────────┘   │  │  1. Check strategy exits │ │    │
│                    │  │  2. Check stop-losses     │ │    │
│  ┌─────────────┐   │  │  3. Scan + execute        │ │    │
│  │  Alert      │   │  │  4. Print status          │ │    │
│  │  ThreadPool │   │  └─────────────────────────┘ │    │
│  └─────────────┘   └──────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

The main thread owns the event loop: it launches the dashboard thread, waits for a start command from the WebUI (or starts immediately with `--auto-start`), then blocks on the trading thread via signals. All shared state (positions, balance, PnL) is guarded by `threading.Lock` inside the portfolio components.

Each trading loop iteration:
1. Reads `SCAN_INTERVAL_MS` fresh (supports hot-reload)
2. Calculates the next tick deadline monotonically (avoids drift from slow scans)
3. Runs the four phases above
4. Sleeps only the remaining time in the interval

---

## 2. Market Data Pipeline

### Components

```
Gamma API
    │
    ▼
market_scanner.scan_categories()   ← parallel per-category Gamma fetches
    │  raw List[dict]
    ▼
MarketProvider.get_markets(criteria)
    │
    ├── 1. Convert → List[PolymarketMarket]   (cached, TTL)
    ├── 2. Apply MarketCriteria filters
    │       - min_volume_usd
    │       - require_binary (exactly 2 outcomes)
    │       - max_time_to_close_s
    │       - categories
    └── 3. Resolve prices
            - GAMMA_EMBEDDED  (no extra API call)
            - CLOB_REST        (get_price() per market)
            - ORDER_BOOK_MID   (full book midpoint)
    │
    ▼
List[PolymarketMarket] with resolved_price set
    │
    ▼
Strategy.scan_for_opportunities()
```

### MarketCriteria

Each strategy declares what it needs via `get_market_criteria()`:

```python
@dataclass
class MarketCriteria:
    categories: List[str] = field(default_factory=list)
    min_volume_usd: float = 0.0
    require_binary: bool = False
    max_time_to_close_s: Optional[float] = None
    price_source_preference: List[MarketDataSource] = field(
        default_factory=lambda: [MarketDataSource.GAMMA_EMBEDDED, MarketDataSource.CLOB_REST]
    )
```

The pre-filter runs inside `MarketProvider` before the strategy ever sees a market object. This means strategies do not need to implement their own volume or binary checks — they receive only markets that already pass the gates.

### Price Resolution

`MarketProvider` resolves prices using the strategy's preference list:

1. **GAMMA_EMBEDDED** — the Gamma API `/events` response includes `outcomePrices` for most markets. Zero extra API calls. Slightly stale (Gamma cache ~30 s).
2. **CLOB_REST** — calls `ClobClient.get_price(token_id)`. One HTTP request per market. Always fresh.
3. **ORDER_BOOK_MID** — fetches the full order book and computes `(best_bid + best_ask) / 2`. Most expensive; gives a true mid-market price when precision matters.

If the preferred source returns 0 or fails, the provider falls back down the list.

---

## 3. Settlement Arbitrage Strategy

### Premise

Prediction markets settle at exactly $1.00 (YES wins) or $0.00 (NO wins) when the outcome is resolved. If a market's YES token is trading at $0.985 — and you are highly confident YES will win — you can buy at $0.985 and collect $1.00 at settlement, netting a $0.015 gross profit per dollar of YES tokens held.

Polymarket charges a 2% taker fee on order execution, applied as a percentage of the trade value. With a 2% fee on a $0.985 entry:

```
Gross edge = (1.00 - 0.985) × 100  = 1.5%
Fee cost   = 2.0%
Net edge   = 1.5% - 2.0%           = -0.5%   ← negative, do not trade
```

At this fee level the strategy requires a price threshold of approximately **≤ 0.98** for positive net edge. The default `MIN_PRICE_THRESHOLD=0.985` produces opportunities where the fee occasionally consumes all edge — the `edge_filter_mode` setting controls how strictly this is enforced (see [Edge Filtering Modes](#5-edge-filtering-modes)).

### Scan Logic

For each market in the pre-filtered list:

```
1. Read resolved_price (set by MarketProvider)
2. Skip if price == 0 or outside [min_price_threshold, max_price_threshold]
3. Compute:
       gross_edge = (1.00 - price) × 100
       net_edge   = gross_edge - TAKER_FEE_PERCENT
4. Apply edge filter (net_edge mode or slippage-adjusted mode)
5. Compute time_to_close = market.end_time - now
6. Compute confidence score (see §4)
7. If confidence >= MIN_CONFIDENCE → create TradeOpportunity
```

### Ranking

`get_best_opportunities()` sorts by **risk-adjusted score**: `edge_percent × confidence`. This rewards opportunities with both large edge and high certainty over ones that have edge but low confidence (or vice versa).

### Exit Logic

`should_exit()` returns `True` when `datetime.now(utc) >= position.expires_at` — i.e., when the market's scheduled close time has passed. The exit price is always `$1.00` (the expected YES settlement price).

---

## 4. Confidence Scoring

The confidence score is a number in `[0, 1]` that summarises how attractive an opportunity is. Three factors contribute:

### Factor 1: Price Proximity (40% weight)

```
price_factor = (yes_price - min_price_threshold) / (max_price_threshold - min_price_threshold)
```

A price of `0.999` is near the top of the window → `price_factor ≈ 1.0`.
A price of `0.985` (the floor) → `price_factor = 0.0`.

Rationale: a higher price signals the market has already priced in a high YES probability. The closer to $1.00, the less residual uncertainty about the outcome.

### Factor 2: Time to Close (40% weight)

| Time to close | `time_factor` | Reasoning |
|---------------|--------------|-----------|
| ≤ 0 s (expired) | 0.0 | Cannot fill |
| < `execute_before_close_seconds` | 0.2 | Inside execution window but may not fill in time |
| ≤ 300 s (5 min) | 1.0 | Sweet spot: close is imminent, still time to fill |
| ≤ 3600 s (1 hr) | 0.6 | Approaching close, outcome reasonably certain |
| > 3600 s | 0.3 | Far from close, outcome uncertainty is higher |

### Factor 3: Edge Size (20% weight)

```
edge_factor = min(net_edge / 5.0, 1.0)
```

Normalised against a 5% maximum expected edge. Larger edge provides more buffer against actual slippage and fee variation; minor contribution compared to price and time.

### Final Score

```
confidence = 0.4 × price_factor + 0.4 × time_factor + 0.2 × edge_factor
```

A trade that scores below `MIN_CONFIDENCE` (default `0.5`) is silently skipped. This gate prevents entries on markets that are technically in the price window but have very low certainty (e.g., a market at `0.985` with 4 hours to close scores `≈ 0.4` and is filtered out by default).

---

## 5. Edge Filtering Modes

Controlled by `edge_filter_mode` in `strategies/configs/settlement_arbitrage.yaml` (or the `_DEFAULTS` dict if no YAML is present).

### `net_edge` (default)

Allow entry whenever `net_edge = gross_edge - taker_fee > 0`.

Any positive net edge after fee deduction is sufficient. This is the least conservative mode — it allows entering markets where edge is positive but may be fully consumed by real slippage.

### `slippage_adjusted`

Allow entry only when `net_edge > expected_slippage_buffer_pct` (default 1.0%).

The slippage buffer is a static estimate of typical market-impact cost, added on top of the taker fee. With a 2% fee and 1% slippage buffer:

```
Required gross edge  = 2.0% (fee) + 1.0% (buffer) = 3.0%
Minimum price        = 1.00 - 0.03 = 0.97
```

At this level the strategy only enters markets within the last 3 cents of YES resolution — a much tighter window. Combine with the actual pre-trade slippage gate (`SLIPPAGE_TOLERANCE_PERCENT`) for full protection.

---

## 6. Order Execution Flow

```
execute_buy(opportunity, position_id)
│
├── 1. PRE-TRADE SLIPPAGE CHECK
│       if client available:
│           order_book = client.get_order_book(token_id, levels=10)
│           slip = estimate_slippage(order_book, capital, side="BUY")
│           if slip["slippage_pct"] > SLIPPAGE_TOLERANCE_PERCENT:
│               log warning → return False          ← order aborted
│           if slip["insufficient_liquidity"]:
│               log warning (but continue if within tolerance)
│
├── 2. POSITION SIZE
│       capital = currency_tracker.get_available() × CAPITAL_SPLIT_PERCENT
│       shares  = capital / price
│
├── 3. ALLOCATE BALANCE
│       currency_tracker.allocate_to_position(position_id, capital)
│       if allocation fails → return False
│
├── 4. EXECUTE ORDER
│       Paper mode:
│           position_tracker.open_position(position_id, ...)  ← internal record
│       Live mode:
│           order = build_limit_order(token_id, price, shares, side="BUY")
│           if RELAYER_ENABLED:  submit via relayer endpoint
│           else:                submit via CLOB client
│           if submit fails:     currency_tracker.return_allocation(position_id)
│                                return False
│
├── 5. RECORD HISTORY
│       executor.order_history.append({
│           action, position_id, price, shares, capital,
│           slippage_pct, timestamp, ...
│       })
│
└── return True
```

`execute_sell()` mirrors this flow in reverse: retrieves the position, calculates realised P&L, settles it in `PositionTracker` and `PnLTracker`, and returns the capital to `FakeCurrencyTracker`.

---

## 7. Pre-Trade Slippage Estimation

`utils/slippage.py` implements a pure-function VWAP walker that requires no API dependencies.

### Algorithm

Input: an order book dict `{"asks": [...], "bids": [...]}`, capital in USD, and side (`"BUY"` or `"SELL"`).

```
Select levels:
    BUY  → asks (sorted low → high)
    SELL → bids (sorted high → low)

Find best_price:
    Scan forward for the first level with price > 0
    (guards against malformed zero-price entries)

Walk levels until capital is exhausted or book is drained:
    for each level:
        level_value = price × available_size
        if remaining_usd <= level_value:
            shares_filled = remaining_usd / price
            remaining_usd = 0
            break
        else:
            consume entire level, move to next

vwap = total_cost / total_shares_filled

slippage_pct:
    BUY:  (vwap - best_price) / best_price × 100
    SELL: (best_price - vwap) / best_price × 100
    (negative = favourable fill; reported as 0.0)
```

### Return value

```python
{
    "vwap":                   float,   # weighted average fill price
    "best_price":             float,   # top-of-book price
    "slippage_pct":           float,   # adverse deviation from best (%)
    "fill_ratio":             float,   # fraction of order filled (1.0 = full)
    "unfilled_usd":           float,   # USD not filled (thin book)
    "insufficient_liquidity": bool,    # True if book cannot fully absorb order
    "levels_consumed":        int,     # number of price levels touched
}
```

### Failure handling

If `get_order_book()` raises (network timeout, API error), the pre-trade gate is skipped and the order proceeds normally. A `WARNING` is logged. This ensures a transient API failure never silently blocks all trading.

### Paper mode usage

In paper mode the slippage estimate *is* the recorded fill slippage. The `slippage_pct` value is stored on the order history entry so you can review expected fill quality on simulated trades.

---

## 8. Position Lifecycle

```
DETECTED → EXECUTED → SETTLED / CLOSED
                    ↑
               FAILED (buy failed; position never opened)
```

### PositionTracker

Maintains a dict of `TradePosition` objects keyed by `position_id`. Each position stores:
- `entry_price`, `shares`, `capital_allocated`
- `winning_token_id`, `market_id`, `market_slug`
- `expires_at` (for time-based strategy exits)
- `status` (OPEN → SETTLED / CLOSED)
- `exit_price`, `realized_pnl` (set on close)

**Position ID format**: `{market_id}_{YYYYMMDDHHMMSS_microseconds}` — unique per execution.

### Opening a position

`position_tracker.open_position(position_id, opportunity, entry_price, shares, capital)` — thread-safe, enforces `MAX_POSITIONS`. Returns `False` if the cap is reached.

### Settling a position

`executor.settle_position(position_id, settlement_price)`:
1. Looks up the position
2. Calculates `realized_pnl = (settlement_price - entry_price) × shares - fee_cost`
3. Calls `position_tracker.close_position()`
4. Records the trade in `PnLTracker`
5. Returns capital to `FakeCurrencyTracker`

---

## 9. Capital Sizing

### Dynamic allocation

Each position consumes `CAPITAL_SPLIT_PERCENT` of the **current available balance** (not the starting balance):

```
Iteration 1: available = $10,000  → allocate $2,000  (20%)
Iteration 2: available = $8,000   → allocate $1,600   (20%)
Iteration 3: available = $6,400   → allocate $1,280   (20%)
```

This creates a natural scaling effect: as more capital is deployed, each new position is proportionally smaller. The maximum theoretical exposure after `N` positions (with no exits) is:

```
deployed = starting_balance × (1 - (1 - CAPITAL_SPLIT_PERCENT)^N)
```

With default settings (20%, 5 positions): `$10,000 × (1 - 0.8^5) ≈ $6,723` maximum deployed.

### FakeCurrencyTracker

`FakeCurrencyTracker` maintains:
- `starting_balance` — fixed at init from `FAKE_CURRENCY_BALANCE`
- `_allocations` — dict of `{position_id: capital}`
- `get_available()` = `starting_balance - sum(_allocations.values())`
- `get_deployed()` = `sum(_allocations.values())`

`allocate_to_position(position_id, amount)` — returns `False` if available < amount, ensuring the bot never over-commits.

---

## 10. Stop-Loss Mechanism

The stop-loss is a **generic infrastructure mechanism**, not strategy-specific logic.

On each scan tick, `_check_stop_losses()` runs over all open positions:

```python
drop_pct = (entry_price - current_price) / entry_price × 100
if drop_pct >= STOP_LOSS_PERCENT:
    executor.execute_sell(position_id, current_price, reason="stop_loss")
```

A shared `price_cache` dict is used across `_check_strategy_exits()` and `_check_stop_losses()` in the same tick, so each token's price is fetched at most once per iteration regardless of how many positions hold it.

`STOP_LOSS_PERCENT=0` (default) disables the stop-loss entirely — no extra API calls are made.

---

## 11. P&L Tracking

`PnLTracker` accumulates statistics across all closed trades:

| Metric | Calculation |
|--------|-------------|
| `total_pnl` | Sum of all `realized_pnl` values |
| `win_rate` | `wins / total_trades × 100` |
| `profit_factor` | `gross_profit / gross_loss` (∞ if no losses) |
| `max_drawdown` | Largest peak-to-trough decline in running P&L |
| `avg_win` / `avg_loss` | Average P&L for winning / losing trades |

`get_summary()` returns a `PnLSummary` dataclass. `get_report()` formats it as a human-readable string printed at shutdown.

### Trade records

Each `PnLTrade` stores:
- `position_id`, `market_id`
- `entry_price`, `exit_price`, `shares`
- `capital_allocated`, `realized_pnl`
- `entry_time`, `exit_time`
- `slippage_pct` — pre-trade estimate recorded at buy time

---

## 12. Hot-Reload Configuration

`config.reload()` re-reads the `.env` file in place and updates all live-configurable fields on the existing singleton instance — no restart required.

### What can be hot-reloaded

All trading and strategy parameters:
- `TRADING_MODE`, `PAPER_TRADING_ONLY`, `STRATEGY`
- `MAX_POSITIONS`, `CAPITAL_SPLIT_PERCENT`, `STOP_LOSS_PERCENT`, `MIN_CONFIDENCE`
- `SCAN_INTERVAL_MS`, `SCAN_CATEGORIES`, `MIN_VOLUME_USD`
- `SLIPPAGE_TOLERANCE_PERCENT`, `TAKER_FEE_PERCENT`
- `MAX_RETRIES`, `RETRY_DELAY_MS`
- Alert settings (email, Discord)
- Dashboard settings
- Logging level, log-to-file

### What requires a restart

Fields consumed only during component `__init__()` and cannot be applied to a running instance:
- `POLYMARKET_PRIVATE_KEY` — used to sign orders at client init
- All `RELAYER_*` and `BUILDER_*` fields — wired into the ClobClient at startup
- `DB_ENABLED`, `DB_PATH` — database connection established at init
- `SCYLLA_*` — ScyllaDB session established at init

### How scan interval hot-reload works

`config.SCAN_INTERVAL_MS` is read at the top of every loop iteration:
```python
scan_interval = config.SCAN_INTERVAL_MS / 1000
```
Changing it in `.env` and calling `/api/reload` takes effect on the next tick with no restart.

---

## 13. Authentication Modes

Priority order: **Relayer → Builder → Standard**

### Standard (default)

The `PolymarketClient` builds a `ClobClient` from your `POLYMARKET_PRIVATE_KEY` and `POLYMARKET_FUNDER_ADDRESS`. All orders are L2 CLOB signed (EIP-712 typed-data signature on Polygon). Subject to the 100 relay tx/day limit.

### Builder

When `BUILDER_ENABLED=True`, `py_builder_signing_sdk` attaches additional builder attribution headers to each order payload. This signals to Polymarket which builder built the order, unlocking tiered rate limits:
- **Unverified**: 100/day (default, no approval)
- **Verified**: 3,000/day (apply at `builder@polymarket.com`)
- **Partner**: unlimited (strategic arrangement)

### Relayer

When `RELAYER_ENABLED=True`, orders are submitted to the Relayer endpoint `https://relayer-v2.polymarket.com/` rather than directly to the CLOB. Relayer keys provide unlimited relay transactions for a single wallet — no tier approval process. Auth headers:
- `POLY_ADDRESS`: your `RELAYER_API_KEY_ADDRESS`
- `POLY_API_KEY`: your `RELAYER_API_KEY`
- Plus the standard L2 CLOB signature headers

Relayer mode takes priority over Builder mode if both are configured.

---

## 14. Alert System

`AlertManager` in `utils/alerts.py` wraps both email (SMTP) and Discord (webhook) delivery.

### Architecture

- A `ThreadPoolExecutor` with a small worker pool handles sends asynchronously — the main trading loop is never blocked waiting for an alert to deliver
- `atexit.register()` ensures the thread pool shuts down cleanly when the process exits
- Rate limiting prevents alert floods: there is a minimum interval between repeated sends of the same alert type

### Alert types

| Method | When fired |
|--------|-----------|
| `send_system_start_alert()` | Bot process starts |
| `send_system_stop_alert()` | Bot process stops (final report) |
| `send_opportunity_detected_alert()` | New position opened |
| `send_error_alert()` | Unhandled exception in trading loop |

---

## 15. SQLite Persistence

When `DB_ENABLED=True`, `TradeDatabase` (in `data/database.py`) persists trading data to SQLite at `DB_PATH`.

### Tables

- `trade_opportunities` — every `TradeOpportunity` detected (whether executed or not)
- `trade_positions` — open and settled `TradePosition` records
- `pnl_snapshots` — time-series of `(timestamp, balance, pnl)` for charting

### Upsert pattern

All writes use `upsert_position()` / `upsert_trade()` — insert-or-update semantics so records remain consistent across restarts without duplicate rows.

### SQLite vs ScyllaDB

SQLite stores the trading state (positions, P&L, trade history) and is suitable for all use cases. ScyllaDB (`data/order_book_store.py`) is an optional time-series store for order book snapshots — only needed if you want to analyse historical book depth. Leave `SCYLLA_ENABLED=False` unless you have a Docker environment running.

---

---

## 16. Strategy Session Tracking

Every bot run creates exactly one session per strategy. The session captures every settled trade from that run so you can review and analyse strategy performance historically.

### Data flow

```
TradingBot.__init__()
    └─ SessionStore.connect()          ← opens SQLite, creates tables if needed

TradingBot.start_trading_loop()
    └─ SessionStore.create_session()   ← inserts session row, returns UUID

Each settled trade (_check_strategy_exits / _check_stop_losses):
    └─ SessionStore.record_settled_trade()   ← inserts one session_trades row

TradingBot.stop()
    ├─ SessionStore.close_session()    ← computes stats, writes JSON export, returns dict
    ├─ SessionReviewer.generate_review()   ← optional: sends prompt to Ollama
    ├─ SessionStore.save_review()      ← patches SQLite row + JSON file
    └─ SessionStore.close()            ← closes SQLite connection
```

### SessionStore (`data/session_store.py`)

Shares the same SQLite file (`DB_PATH`) as `TradeDatabase` but uses two separate tables (`strategy_sessions`, `session_trades`). All public methods are non-fatal — they log a warning on failure and return a safe default, so storage errors never interrupt the trading loop.

**Key design choices:**
- `create_session()` always returns a valid UUID even when the DB is unavailable, so callers never need to branch on `None`
- `close_session()` computes all aggregate stats in Python after fetching rows, rather than using SQL aggregates, to keep the code readable and testable
- The JSON export is written atomically in `_write_json()` — the file is only created once all stats are finalised
- `profit_factor` is `None` (not infinity) when there are no losing trades — this is the correct mathematical sentinel and avoids division-by-zero in downstream code

### JSON export format

Written to `SESSIONS_DIR/<YYYYMMDD>_<strategy>_<session_id_8chars>.json`:

```
{
  "session": { session metadata },
  "stats":   { aggregate performance metrics },
  "equity_curve": [
    { "time": "<iso>", "balance": <float>, "trade_count": <int> },
    ...
  ],
  "trades": [ { one dict per settled trade, all fields } ],
  "ollama_review": "<string> | null"
}
```

The equity curve has one point before any trades (the opening balance) and one point per settled trade. This is sufficient for charting a P&L curve without requiring any joins.

### Fields excluded from the Ollama prompt

`SessionReviewer._REVIEW_SAFE_TRADE_FIELDS` is a whitelist. Fields stripped before the prompt is built include: `winning_token_id`, `position_id`, `trade_id`, `session_id`, `market_id`, `shares`, `allocated_capital`, `entry_fee`, `exit_fee`, `balance_after`. See `utils/session_reviewer.py` for the full list and rationale.

---

## 17. Ollama Strategy Review

When `OLLAMA_ENABLED=True`, `SessionReviewer` (`utils/session_reviewer.py`) generates a natural language performance review on bot shutdown. The call is **synchronous and blocking** — the process does not exit until the review is complete (or times out at 3 minutes).

### Ollama API calls

| Step | Method | Endpoint | Purpose |
|------|--------|----------|---------|
| 1 | `GET` | `/api/tags` | Check if model is already downloaded |
| 2 | `POST` | `/api/pull` | Pull model if not present (up to 10 min timeout) |
| 3 | `POST` | `/api/generate` | Generate review text (`stream=false`, 3 min timeout) |

### Prompt structure

```
STRATEGY: <name>
DATE: <YYYY-MM-DD>
DURATION: <Xh YYm>
MODE: paper | live | simulation
BALANCE: $<start> → $<end> (<pct>%)

PERFORMANCE
Trades: N | Won: W | Lost: L | Win rate: X%
Net PnL: $X | Fees paid: $X | Profit factor: X
Avg hold time: Xh YYm | Avg edge at entry: X%
Best trade: $X | Worst trade: $X

TRADE LOG
# Market                  Entry   Exit    Hold      Edge%   Net PnL  Outcome
...

Write a concise strategy review covering: [4 points]
Limit: 250 words.
```

### Failure modes

Every Ollama failure is non-fatal:
- Network unreachable → `generate_review()` returns `None`; bot shuts down normally; JSON export is complete without `ollama_review`
- Model pull timeout → same
- Generation timeout (3 min) → same
- `_ensure_model()` HTTP error → returns `False`; `generate_review()` returns `None`

### Docker Compose

The `ollama` service in `docker-compose.yml` uses `ollama list` as its healthcheck. The `trading-bot` service declares `depends_on: ollama: condition: service_healthy`, so the bot never starts until Ollama is accepting requests. The model itself is pulled lazily on first review generation, not at container startup.

---

*End of architecture reference.*
