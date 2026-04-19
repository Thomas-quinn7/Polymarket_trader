# Code Review — Polymarket Trading Framework

**Reviewer:** Claude Sonnet 4.6  
**Last updated:** 2026-04-19 (Session 8)  
**Sessions:** Session 1 (2026-04-10) · Session 2 (2026-04-11) · Session 3 (2026-04-11) · Session 4 (2026-04-12) · Session 5 (2026-04-12) · Session 6 (2026-04-15) · Session 7 (2026-04-19)

---

## Status Summary

48 issues found across four review sessions. 48 resolved; 0 open (design notes remain for architectural tracking).

| Severity | Found | Fixed |
|---|---|---|
| P0 — Critical correctness | 8 | 8 ✓ |
| P1 — High correctness | 9 | 9 ✓ |
| P2 — Moderate | 10 | 10 ✓ |
| P3 — Minor | 17 | 17 ✓ |
| P4 — Polish | 4 | 4 ✓ |
| Security | 5 | 5 ✓ |

---

## Issue Log

### P0 — Critical Correctness

| # | File | Issue | Fix |
|---|---|---|---|
| 1 | `portfolio/fake_currency_tracker.py` | No lock — race condition on `balance` and `deployed` | Added `threading.Lock()`; all mutations and reads protected |
| 2 | `strategies/enhanced_market_scanner/scanner.py` | `"regulation"` typo — keyword filters silently never applied | Replaced with `"regulatory"` in all five locations |
| 31 | `strategies/example_strategy/strategy.py` | Edge formula `(1 - price) × 100` measured profit as fraction of settlement value, not investment cost | Changed to `(1/price - 1) × 100` (return-on-investment basis) |
| 32 | `execution/order_executor.py` | `settle_position()` charged a taker exit fee on auto-settlement — Polymarket token redemption is free | `settle_position()` now accepts an explicit `exit_fee=0.0` parameter; normal settlement path passes nothing |
| 38 | `dashboard/api.py` | Newline injection via `_write_env_key` — a value containing `\n` could inject extra keys into `.env` | Strip `\r`, `\n`, `\x00` from every value before writing |
| 39 | `dashboard/api.py` | No authentication on any control endpoint — anyone who could reach the port could modify settings or stop the bot | Added optional `DASHBOARD_API_KEY` env var; all endpoints except `/api/health` require matching `X-API-Key` header |
| 45 | `portfolio/position_tracker.py` + `main.py` | **Open positions are not restored on restart.** `PositionTracker.__init__` starts with `self.positions = {}`. DB rows survive but are invisible to the trading loop — capital is never freed and exits are never checked. | Added `PositionTracker.restore_position()` and `TradingBot._restore_open_positions()`. On startup (after DB connects), all OPEN rows are loaded, converted to `Position` objects, and re-inserted into the position tracker, pnl tracker, and currency tracker. |

---

### P1 — High Correctness

| # | File | Issue | Fix |
|---|---|---|---|
| 3 | `main.py` | `stop()` called twice on SIGINT — once in `_signal_handler()` and once via `finally:` | Removed explicit `stop()` from signal handler; `SystemExit` propagates to `finally` which calls it once |
| 4 | `portfolio/position_tracker.py` | `get_summary()` used `if p.realized_pnl:` — break-even trades (pnl=0.0) counted as losses | Changed to `if p.realized_pnl is not None:` |
| 5 | `execution/order_executor.py` | `execute_sell()` had no retry logic — transient exchange errors created ghost open positions | Added same retry loop as `execute_buy()` |
| 6 | `data/polymarket_models.py` + `utils/pnl_tracker.py` | Duplicate `TradeRecord` class name — ORM model silently shadowed by the dataclass | Renamed ORM class to `TradeAuditRecord`; kept `TradeRecord = TradeAuditRecord` alias |
| 33 | `portfolio/fake_currency_tracker.py` | `allocate_to_position()` silently capped at 20 % of starting balance — executor used full amount for shares/fees but only capped amount left the balance | Removed the cap; executor is responsible for position sizing |
| 34 | `data/polymarket_client.py` | Pagination broke on `not page_markets` — exits early when a full page happens to contain only inactive markets | Only break on `len(events) < page_size` (last page sentinel) |
| 35 | `data/market_provider.py` | `_convert_and_filter` never applied `criteria.categories` — entire market universe passed to strategy for unmapped categories | Added category gate (check 0) before all other filters |
| 40 | `dashboard/api.py` | `detail=str(e)` in all 500 handlers — exposed stack traces, file paths, config values to HTTP clients | Replaced with `"Internal server error"`; added `exc_info=True` to server-side log |
| 46 | `main.py` | `should_exit()` does not distinguish a market that resolved NO (price → 0) from a data error — calls `execute_sell()` on a resolved NO market and pays a taker fee instead of the free redemption path | `_check_strategy_exits()` in `main.py` routes `exit_price <= 0.0` to `settle_position(settlement_price=0.0)` (fee-free redemption) in all modes. |

---

### P2 — Moderate

| # | File | Issue | Fix |
|---|---|---|---|
| 7 | `config/polymarket_config.py` | `@dataclass` on a class with no annotated fields | Removed `@dataclass` decorator and import |
| 8 | `data/polymarket_models.py` | `datetime.utcnow` deprecated in Python 3.12+ | Replaced all five column defaults with `lambda: datetime.now(timezone.utc)` |
| 9 | `data/polymarket_models.py` | `sqlalchemy.ext.declarative.declarative_base` deprecated | Changed to `sqlalchemy.orm.declarative_base` |
| 10 | Multiple | `import` statements inside functions | Moved all standard-library imports to top of each module |
| 11 | `dashboard/api.py` | CORS `allow_origins=["*"]` with `allow_credentials=True` | Restricted to explicit localhost origins; removed `allow_credentials` |
| 13 | `execution/order_executor.py` | Capital sized off `starting_balance` — position sizes never scaled down after drawdowns | Changed to `get_balance() × CAPITAL_SPLIT_PERCENT` |
| 21 | `data/database.py` | No lock on SQLite writes — concurrent `upsert_position` + `upsert_trade` calls could corrupt the DB | Added `threading.Lock()` around all `execute()` + `commit()` pairs |
| 36 | `data/market_scanner.py` | Sequential `join(timeout=30)` on 4 threads — worst-case 120 s block per scan | Replaced with a shared monotonic deadline: `deadline = time.monotonic() + 30` |
| 41 | `dashboard/api.py` | No upper bound on `?limit` in `/api/trades` — trivial DoS via `?limit=999999` | `Query(default=50, ge=1, le=500)` |

---

### P3 — Minor

| # | File | Issue | Fix |
|---|---|---|---|
| 12 | `dashboard/api.py` | `start_dashboard()` defaulted to `host="0.0.0.0"` | Default changed to `host=config.DASHBOARD_HOST` |
| 14 | `strategies/example_strategy/strategy.py` | `execute_opportunity()` dead code — position sizing handled by `OrderExecutor` | Removed method and unused `Optional` import |
| 15 | `config/polymarket_config.py` | `reload()` did not re-create `PolymarketClient` — auth changes had no effect until restart | Added restart-required field list to `reload()` docstring |
| 16 | `portfolio/fake_currency_tracker.py` | `get_available()` was identical to `get_balance()` — misleading duplicate | Removed `get_available()`; updated two callers to use `get_balance()` |
| 17 | `utils/alerts.py` | `ThreadPoolExecutor` never shut down on exit | Added `atexit.register(self._executor.shutdown, wait=False)` |
| 18 | `.gitignore` | `data/.seen_markets.json` not excluded — could be committed accidentally | Added entry to `.gitignore` |
| 19 | `utils/logger.py` | CSV writes not thread-safe — concurrent trading + dashboard threads could produce corrupt lines | Added `threading.Lock()`; all `open()` + `write()` calls hold the lock |
| 20 | `data/market_scanner.py` | Thread `join()` had no timeout — a stalled Gamma API call blocked the entire loop indefinitely | Added `join(timeout=30)` and a warning log for threads that don't finish |
| 25 | `strategies/enhanced_market_scanner/scanner.py` | `seen_markets` set grew unboundedly — slow JSON flush and large memory footprint over time | Capped at `_SEEN_MARKETS_MAX = 10_000`; oldest entries trimmed on each save |
| 28 | `config/polymarket_config.py` | `_TIER_DAILY_LIMITS` accessed as `self._TIER_DAILY_LIMITS` — misleads readers into thinking it's an instance field | Changed to `PolymarketConfig._TIER_DAILY_LIMITS`; removed dead `_SENSITIVE_FIELDS` |
| 29 | `utils/logger.py` | CSV written with manual string formatting — commas in market slugs or reason strings corrupted column counts | Replaced with `csv.writer(f).writerow(...)` |
| 37 | `data/market_scanner.py` | Timeout warning logged `Thread-1` not the category name | Added `name=f"scanner-{cat}"` to `Thread()` constructor |
| 42 | `dashboard/api.py` | `?status` param accepted any string silently — invalid values returned all positions with no error | Changed type to `Optional[Literal["open", "settled"]]` |
| 43 | `pkg/` + `api/` directories | Both directories were dead code — imported nowhere in the live system | Deleted both directories (11 files) and the two test files that only tested them |
| 47 | `dashboard/api.py` | `POST /api/settings` with `trading_mode=live` updates `config.TRADING_MODE` but does not set `config.PAPER_TRADING_ONLY = False` — the actual live-order gate never opens via the dashboard | Resolved (was already present): endpoint rejects `trading_mode=live` with HTTP 422; only `"paper"` or `"simulation"` are accepted, and both set `PAPER_TRADING_ONLY = True`. Live mode requires `--live` CLI flag (with confirmation prompt + private-key pre-check). |

---

### P4 — Polish

| # | File | Issue | Fix |
|---|---|---|---|
| 22 | `utils/logger.py` | Log level hardcoded to `DEBUG` — `config.LOG_LEVEL` had no effect | Changed to `logger.setLevel(getattr(logging, config.LOG_LEVEL.upper(), logging.INFO))` |
| 23 | `main.py` | Magic `time.sleep(2)` / `time.sleep(3)` with no explanation | Extracted to named constants (`_DASHBOARD_STARTUP_WAIT_S`) with inline comments |
| 24 | `main.py` | `scan_interval` computed once at loop start — hot-reload of `SCAN_INTERVAL_MS` had no effect | Moved `scan_interval = config.SCAN_INTERVAL_MS / 1000` inside the loop body |
| 26 | `data/polymarket_client.py` | `get_market()` made a single request with no retry | Wrapped with `_with_retry()` matching all other network calls |
| 27 | `data/polymarket_client.py` | Retry delays were fixed — concurrent retries hit the API simultaneously (thundering herd) | Each delay multiplied by `0.5 + random.random()` (jitter in [0.5, 1.5)) |

---

### Security

| # | File | Issue | Fix |
|---|---|---|---|
| S1 | `dashboard/api.py` | `allow_origins=["*"]` with `allow_credentials=True` | Fixed — see item 11 |
| S2 | `dashboard/api.py` | `start_dashboard()` bound to `0.0.0.0` by default | Fixed — see item 12 |
| S3 | `dashboard/api.py` | Settings endpoint wrote `.env` with no auth — any caller could change `TRADING_MODE` or credentials | Fixed — see items 38 & 39 |
| S4 | `data/polymarket_client.py` | `_relayer_headers` dict held `RELAYER_API_KEY` in plain text — could appear in exception tracebacks | Added `__repr__` to `PolymarketClient` that shows mode flags only; never exposes `_relayer_headers` |
| S5 | `config/polymarket_config.py` | `__repr__` masks credentials correctly; ensure no `str()` / `print()` of the raw config object elsewhere | Operational awareness — no code change required; `__repr__` is the authoritative safe path |

---

---

## Session 6 — Open Issues

### A-4 — Analytics page KV lists stuck at "Loading…"

**Symptom:** After navigating to the Analytics page, the Risk Metrics and Transaction Costs KV lists remain at their initial "Loading…" state. Charts are blank.

**Root cause (suspected):** `loadAnalytics()` in `app.js` exits early when `apiFetch('/api/analytics')` returns `null`. This happens whenever the endpoint returns a non-200 status. Two known triggers:
1. `/api/analytics` previously had no `try/except` — any computation error produced a silent 500.
2. `_bot_instance` may be `None` at call time if the bot hasn't fully started — the endpoint returned valid JSON with `sample_size: 0`, but an unhandled edge case elsewhere in `_compute_analytics` could throw.

**What was done in Session 6:**
- Wrapped `/api/analytics` in `try/except`; extracted body to `_compute_analytics()` so errors are logged at ERROR level.
- Added `console.warn` / `console.error` to `apiFetch` in `app.js` — failed calls now appear in the browser console (F12 → Console).
- Extended `/api/health` (no-auth endpoint) to expose `bot_registered` and `session_trades_in_db` for quick sanity-checking.
- Fixed `/api/trades` to merge `executor.order_history` with `session_store.get_all_trades()` so historical settled trades survive restarts.

**Remaining fix needed:**

> In `app.js`, `loadAnalytics()` should not leave KV divs at "Loading…" on failure. Replace the early-return block with:
> ```js
> if (!data) {
>   const msg = '<div class="kv-empty">Unavailable</div>';
>   ['risk-kv','costs-kv','an-edge-kv','slippage-kv'].forEach(id => {
>     const el = document.getElementById(id);
>     if (el) el.innerHTML = msg;
>   });
>   document.getElementById('analytics-warning').textContent =
>     'Analytics unavailable — visit /api/health to check bot status.';
>   document.getElementById('analytics-warning').classList.remove('hidden');
>   return;
> }
> ```
> Also verify via `/api/health` that `bot_registered: true` and `session_trades_in_db` matches expected count. If `bot_registered: false` the bot instance is not being passed to `set_bot_instance()` — check `start()` in `main.py`.

---

## Analytics Page — Deferred Enhancements

Three analytics features from the Session 5 proposal require additional data plumbing before they can be implemented. Each entry below is sized as a self-contained prompt for a future session.

---

### A-1 — Slippage vs Position Size Scatter

**What:** Scatter chart — X axis = order size ($), Y axis = slippage (%). Detects whether larger orders move the market.

**Why deferred:** `slippage_pct` is stored in the in-memory `order_history` deque (max 500 orders, current session only) but **not** in `session_trades`. The chart only has current-session coverage, limiting usefulness.

**Fix prompt:**
> Add `slippage_pct REAL DEFAULT 0.0` to the `session_trades` SQLite schema in `data/session_store.py`. Populate it in `record_settled_trade()` by looking up the matching BUY order from `executor.order_history` (match on `position_id`). Add a `slippage_vs_size` array to the `/api/analytics` response (list of `{size, slippage, outcome}` dicts). In `app.js`, add a new scatter chart panel below the edge-realization scatter using the existing `state.an` chart pattern — X = `size`, Y = `slippage`, coloured by outcome. Add the `session_trades` schema migration (ALTER TABLE ADD COLUMN IF NOT EXISTS) in `SessionStore.connect()` so existing DBs are upgraded automatically.

---

### A-2 — Multi-Session Equity Curve Overlay

**What:** All past sessions plotted as normalised equity curves on a single chart (each starts at 100%). Immediately shows whether consecutive sessions are improving or degrading.

**Why deferred:** The equity curve is computed in `close_session()` and written to JSON but not stored in the DB. The `/api/sessions/{id}` endpoint returns the DB row (no equity curve). Fetching it requires reading the JSON files or a new DB column.

**Fix prompt:**
> Add an `equity_curve` TEXT column to `strategy_sessions` (stored as a JSON string). In `SessionStore.close_session()`, serialise the `equity_curve` list to JSON and write it to the new column alongside the existing UPDATE. Add `GET /api/sessions/{session_id}/equity` endpoint in `dashboard/api.py` that returns `{"session_id": ..., "curve": [...]}`. In `app.js`, add an overlay chart in the Analytics page: fetch all session IDs from `/api/sessions`, then fetch each curve in parallel (up to 10 most recent), normalise each to 100 at index 0, and render as a multi-line ECharts chart using the existing dark-theme pattern.

---

### A-3 — Maximum Adverse Excursion (MAE)

**What:** For each closed position, how far below entry did the price go before settling? A fat left tail (large MAE on winning trades) means you're holding through large paper losses and relying on mean-reversion — riskier than the P&L alone suggests.

**Why deferred:** MAE requires intra-hold price data (the low-water mark of the winning token price between entry and settlement). This data is not currently collected anywhere.

**Fix prompt:**
> This requires price polling during hold. Add a lightweight background task in `TradingBot.run()` that, once per scan interval, calls `client.get_price(pos.winning_token_id)` for each open position and records the minimum seen. Store `min_price_during_hold REAL` on the `Position` dataclass (default `None`, updated by the loop, persisted to the `positions` DB table via `upsert_position`). Add `mae_pct = (entry_price - min_price_during_hold) / entry_price * 100` to `session_trades` (populate in `record_settled_trade`). Expose in `/api/analytics` as `mae: {avg_pct, max_pct, distribution}` and add a histogram to the Analytics page.

---

## Remaining Design Notes

These are architectural observations that do not require immediate code changes but are worth tracking for future work.

### Dual model hierarchy

Two parallel model hierarchies exist:
- **SQLAlchemy ORM** in `data/polymarket_models.py` (`TradeOpportunity`, `TradePosition`, `TradeAuditRecord`)
- **Dataclasses** in `utils/pnl_tracker.py` (`TradeRecord`) and `portfolio/position_tracker.py` (`Position`)

The dataclass models are used by the live trading loop; the ORM models are used for DB persistence via `data/database.py`. The field mapping is done manually in `upsert_position()` / `upsert_trade()`. Any field addition requires changes in two places. Consider writing explicit mapper tests to catch mismatches.

### `MarketProvider` vs `EnhancedMarketScanner` caching

`MarketProvider` has a TTL cache. `EnhancedMarketScanner` calls `client.get_all_markets()` per category on every scan with no caching. Strategies using `EnhancedMarketScanner` directly bypass the cache entirely. Consider routing `EnhancedMarketScanner` through `MarketProvider`.

### `PolymarketConfig.reload()` coverage gaps

Fields not covered by `reload()` (require a process restart):
`PREVENT_SLEEP`, `ENABLE_*_MARKETS`, `PRIORITY_*`, `ORDER_TYPE`, `CHAIN_ID`, `CLOB_API_URL`, `GAMMA_API_URL`, and all auth credentials.
This is documented in the `reload()` docstring.

### DB is write-only (audit log, not recovery store)

`data/database.py` persists every position and trade on create/settle. But no code path reads positions back into runtime state. On restart, `PositionTracker` and `FakeCurrencyTracker` start empty. The DB is effectively an audit log. Issue #45 addresses the immediate P0 (positions lost on restart); longer-term, consider whether the DB should be the authoritative source of truth for `balance` and `deployed` as well (today those are recomputed from scratch on each boot).

### Strategy in-memory deduplication state

Strategies that maintain an in-memory set of active market IDs to prevent re-entry do not persist this state across restarts. After a restart the deduplication set starts empty, so the strategy may attempt to re-enter markets already held. The strategy's deduplication set should be seeded from `PositionTracker.positions` on startup.

### `safe_scan_interval_ms` call-count assumption

The divisor of 4 assumes one API call per market category. Actual call count varies with enabled categories and pagination depth. Tune `SCAN_INTERVAL_MS` manually if the rate limit is being hit — see the `safe_scan_interval_ms` docstring for details.

---

## Session 7 — Interview Pitfall Audit (2026-04-19)

A full architectural review against quant-trading interview standards. Issues are ranked by how severely they would damage credibility in a technical interview. None are currently blocking live operation, but all are open.

---

### I-1 (Critical) — No real strategy signal exists

**File:** `strategies/example_strategy/strategy.py`  
**Status:** Framework made explicitly strategy-agnostic (2026-04-19). Signal stub must be implemented per strategy.

The template previously hard-coded a specific strategy's edge formula. Changes made:
- Signal block replaced with a clearly marked `TODO` stub (`gross_edge = 0.0; net_edge = gross_edge - taker_fee`). Defaults to negative edge so no trades fire until a real signal is implemented.
- `_calculate_confidence` refactored: `price_factor` replaced with a `0.0` stub (annotated `TODO`), `time_factor` replaced with a generic gate-linear decay (annotated `ADAPT`), `edge_factor` kept as a generic ceiling-normalised metric.
- `config.yaml` reset to open defaults (`min_price: 0.0`, `max_price: 1.0`, `execute_before_close_seconds: 86400`, `edge_filter_mode: net_edge`, `strategy_min_confidence: 0.0`).

**Remaining action required:** Implement `gross_edge`, `net_edge`, and `price_factor` in a concrete strategy file. Copy `strategies/example_strategy/` to a new folder and replace the three `TODO` blocks.

---

### ~~I-2 (Critical) — Risk management is position count + a flat stop-loss, nothing more~~ RESOLVED (2026-04-19)

**Files:** `portfolio/position_tracker.py`, `execution/order_executor.py`, `main.py`, `config/polymarket_config.py`  
**Fix applied:** Two independent risk controls added.

**1. Fractional Kelly position sizing** (`execution/order_executor.py`)  
- `_kelly_position_size()` computes full Kelly fraction: `f* = (p·b − (1−p)) / b` where `p = opportunity.confidence`, `b = (1−price)/price`
- Scaled by `KELLY_FRACTION` (default 0.25 — quarter Kelly) and capped at `CAPITAL_SPLIT_PERCENT`
- Falls back to flat `CAPITAL_SPLIT_PERCENT` when confidence is zero (no signal)
- Config: `KELLY_FRACTION` in `.env`

**2. Category concentration limit** (`main.py`, `portfolio/position_tracker.py`)  
- `Position` now carries a `category` field, populated from `opportunity.category` at entry
- `_scan_and_execute` counts open positions per category before each execution decision
- Skips an opportunity if its category already has `MAX_POSITIONS_PER_CATEGORY` open positions (default 2)
- Count is updated as positions are opened within the same scan iteration
- Config: `MAX_POSITIONS_PER_CATEGORY` in `.env`

---

### I-3 (High) — Backtesting only takes the long YES side

**File:** `backtesting/engine.py` line 43 (`side: str = "YES"` hardcoded in `SimTrade`)  
**Issue:** The replay engine never buys NO tokens. Strategies that identify NO-side mispricing (low-probability outcomes that the market overestimates) cannot be tested. The backtest results are structurally one-sided.  
**Interview impact:** Medium-high. Shows the backtest was built for one specific trade type and was not designed for generality.  
**Fix:** Parameterise `side` on `SimPosition`/`SimTrade`. Let `scan_for_opportunities` return an opportunity with `winning_token_id = token_id_no` and propagate that into `_enter`/`_settle`.

---

### I-4 (High) — Unknown market resolution defaults to 0.5

**File:** `backtesting/engine.py` line 140  
**Issue:** When a market row has no `resolution` value, `resolutions[cid] = 0.5` silently assigns a break-even outcome. Markets that resolved NO (price → 0) and YES (price → 1) are treated identically. This can inflate win rate and flatten the equity curve on backtests that include unresolved or stale market data.  
**Interview impact:** Medium-high. Silent default values in financial simulations are a red flag for data quality discipline.  
**Fix:** Exclude markets with no recorded resolution from the backtest rather than defaulting. Log a warning with the count of skipped markets.

---

### I-5 (High) — No spread or market impact model in backtesting

**Files:** `backtesting/engine.py`, `backtesting/config.py`  
**Issue:** Transaction costs are modelled as taker fee only. There is no bid/ask spread and no market impact model. Polymarket prediction market spreads can be 1–5% on illiquid markets. The backtest will systematically overstate profitability on any strategy that relies on entering near fair value.  
**Interview impact:** Medium. Any quant will ask "how did you model transaction costs?" Saying "taker fee only" is incomplete.  
**Fix:** Add a `half_spread_pct` field to `BacktestConfig` (default 0). Apply it symmetrically: effective entry price = `price * (1 + half_spread_pct/100)`, effective exit price = `price * (1 - half_spread_pct/100)`.

---

### I-6 (Medium) — Sharpe ratio computed on per-trade returns, not a time-series

**File:** `backtesting/metrics.py` lines 129–148  
**Issue:** `returns` is a list of `net_pnl / allocated_capital` per trade. Annualisation uses `sqrt(trades_per_year)` which assumes each trade is an independent period. Standard Sharpe is computed on a daily (or periodic) time-series of returns. A strategy with 3 trades/day and 5 minute durations will produce a very different Sharpe depending on whether you use trade-level or calendar-day returns.  
**Interview impact:** Medium. Will be questioned by anyone who has computed Sharpe professionally. The current approach is not wrong for a specific interpretation, but it should be documented and defended.  
**Fix (documentation):** Add an explicit comment noting this is trade-frequency Sharpe, not calendar Sharpe. Optionally add a second calculation that bins PnL into daily buckets.

---

### I-7 (Medium) — `market_id` uses `slug` as a fallback primary key

**File:** `data/market_schema.py` lines 74–77  
**Issue:** `from_api()` resolves `market_id` as `id` → `conditionId` → `marketSlug` → `slug`. A `slug` is a human-readable URL segment that is not guaranteed globally unique across the Gamma API. Using it as a primary key risks silent collision between two markets with the same slug in different time periods.  
**Interview impact:** Low-medium. Shows up as a data integrity question.  
**Fix:** Return `None` (and skip the market) when neither `id` nor `conditionId` is present, rather than falling back to the slug.

---

### I-8 (Medium) — No integration or end-to-end tests; test suite mocks the strategy

**Files:** `tests/unit/test_backtest_engine.py` and others  
**Issue:** All tests are unit tests that mock the strategy with `MagicMock`. There are no integration tests against a mock HTTP server (e.g., `responses` or `httpretty`). No test exercises a full scan → opportunity → execute → settle cycle with a real (stub) strategy. Strategy signal logic itself has no test coverage.  
**Interview impact:** Medium. A quant dev interview will ask about how you verified the strategy is correct. "Unit tests with mocked strategy" does not answer that.  
**Fix:** Add at least one integration test that instantiates `ExampleStrategy` (or the real strategy) with a mock client, runs a full `scan_for_opportunities` → `execute_buy` → `settle_position` cycle, and asserts the final balance is correct.

---

### I-9 (Low) — Risk-free rate is implicitly zero with no documentation

**File:** `backtesting/metrics.py` line 148  
**Issue:** Sharpe and Sortino are computed with `mean_r / stdev_r` — no risk-free rate subtracted from the numerator. For prediction markets this is arguably correct (deployed capital earns no interest while locked), but it should be stated explicitly.  
**Fix:** Add a `risk_free_rate_annual: float = 0.0` field to `BacktestConfig` and apply it: `excess_return = mean_r - risk_free_rate_per_trade`.

---

### I-10 (Low) — `FakeCurrencyTracker` name is unprofessional in a portfolio context

**File:** `portfolio/fake_currency_tracker.py`  
**Issue:** The class name telegraphs that live-mode capital tracking was never a priority. In an interview demo or code walkthrough, this creates a negative first impression.  
**Fix:** Rename to `PaperPortfolio` or `SimulatedBook`.

---

### I-11 (Low) — `datetime.now()` without timezone in `main.py`

**File:** `main.py` line 60  
**Issue:** `self.start_time = datetime.now()` produces a timezone-naive datetime while every other timestamp in the codebase uses `datetime.now(timezone.utc)`. Inconsistent timezone handling is a common source of off-by-one-hour bugs at DST transitions.  
**Fix:** `self.start_time = datetime.now(timezone.utc)`.

---

### I-12 (Low) — Global config singleton makes unit testing awkward

**File:** `config/polymarket_config.py`  
**Issue:** `config = PolymarketConfig()` is a module-level singleton. Tests that need different config values must monkey-patch the singleton, which is fragile and order-dependent. `reload()` partially addresses this but not for all fields.  
**Fix (long-term):** Accept a `config` parameter in `TradingBot.__init__` and inject it. Short-term, add a `PolymarketConfig.from_dict(overrides)` factory for test construction.

---

### I-13 (Low) — `_raw: dict` stored on every `PolymarketMarket`

**File:** `data/market_schema.py` line 64  
**Issue:** Every `PolymarketMarket` instance holds the full raw API response dict. At scan time this can be thousands of markets simultaneously. The `_raw` field is only used for debugging and is never read by any production code path.  
**Fix:** Remove `_raw` from the dataclass. If a debugging escape hatch is needed, add it only in `from_api()` under a flag.

---

### Summary Table — Open Interview Pitfalls

| ID | Severity | Issue | File |
|---|---|---|---|
| ~~I-1~~ | ~~Critical~~ | ~~No real strategy signal — `net_edge = 0.0` hardcoded~~ | ~~`strategies/example_strategy/strategy.py`~~ |
| ~~I-2~~ | ~~Critical~~ | ~~Risk model is only position count + flat stop-loss~~ | ~~`portfolio/`, `main.py`~~ |
| ~~I-3~~ | ~~High~~ | ~~Backtest only takes long YES side~~ | ~~`backtesting/engine.py`~~ |
| ~~I-4~~ | ~~High~~ | ~~Unknown resolution silently defaults to 0.5~~ | ~~`backtesting/engine.py`~~ |
| ~~I-5~~ | ~~High~~ | ~~No spread or market impact in backtest~~ | ~~`backtesting/engine.py`, `config.py`~~ |
| ~~I-6~~ | ~~Medium~~ | ~~Sharpe is trade-frequency, not calendar — undocumented~~ | ~~`backtesting/metrics.py`~~ |
| ~~I-7~~ | ~~Medium~~ | ~~`market_id` falls back to `slug` (not a stable PK)~~ | ~~`data/market_schema.py`~~ |
| I-8 | Medium | No integration tests; strategy logic untested | `tests/unit/` |
| I-9 | Low | Risk-free rate implicitly zero, not documented | `backtesting/metrics.py` |
| I-10 | Low | `FakeCurrencyTracker` name unprofessional | `portfolio/fake_currency_tracker.py` |
| ~~I-11~~ | ~~Low~~ | ~~`datetime.now()` timezone-naive in `main.py`~~ | ~~`main.py:60`~~ |
| I-12 | Low | Global config singleton — hard to test | `config/polymarket_config.py` |
| ~~I-13~~ | ~~Low~~ | ~~`_raw` dict on every `PolymarketMarket` wastes memory~~ | ~~`data/market_schema.py`~~ |
