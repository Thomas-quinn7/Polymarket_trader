# Code Review — Polymarket Trading Framework

**Reviewer:** Claude Sonnet 4.6  
**Date:** 2026-04-11  
**Scope:** Full codebase review covering bugs, design issues, security concerns, and improvement suggestions.  
**Sessions:** Session 1 (2026-04-10) — 30 issues found, 28 fixed. Session 2 (2026-04-11) — strategy math, market data pipeline, and dashboard security deep-dive; 12 additional issues found and fixed; 2 open areas identified.

---

## Summary

The codebase is well-structured with clear separation of concerns, good use of threading primitives in the core trackers, and solid defensive programming (clamping, NaN checks, rollback on failure). The main trading loop, position tracker, PnL tracker, and order executor are the strongest parts. The issues below range from a critical thread-safety gap to naming collisions, deprecated APIs, and dead code.

---

## Critical Issues (Bugs / Correctness)

### 1. `FakeCurrencyTracker` is not thread-safe
**File:** `portfolio/fake_currency_tracker.py`  
**Status: FIXED** ✓

Added `threading.Lock()` (`self._lock`) in `__init__`. All mutations in `allocate_to_position()`, `return_to_balance()`, and `reset()` are now protected by the lock. Read-only accessors (`get_balance()`, `get_deployed()`, `get_available()`) also acquire the lock for consistency.

---

### 2. `EnhancedMarketScanner` uses `"regulation"` instead of `"regulatory"` throughout
**File:** `strategies/enhanced_market_scanner/scanner.py`  
**Status: FIXED** ✓

Replaced `"regulation"` with `"regulatory"` in all five affected locations: `_get_category_keywords_lower()`, `_get_category_keywords()`, `get_category_priority()`, `scan_markets_by_category()`, and the `scan_all_markets()` category map key. Keyword filters, the enabled flag, and priority for the regulatory category now apply correctly.

---

### 3. `TradingBot.stop()` is called twice on SIGINT
**File:** `main.py`  
**Status: FIXED** ✓

Removed the explicit `self.stop()` call from `_signal_handler()`. `sys.exit(0)` raises `SystemExit` which propagates to the `finally:` block in `start()`, calling `stop()` exactly once. `KeyboardInterrupt` (Ctrl+C) falls through the `except` branch to the same `finally` block.

---

### 4. `PositionTracker.get_summary()` treats break-even trades as losses
**File:** `portfolio/position_tracker.py`  
**Status: FIXED** ✓

Changed `if p.realized_pnl:` to `if p.realized_pnl is not None:`. Break-even trades (pnl == 0.0) are now correctly counted rather than silently ignored. The inner `> 0` / `else` split for wins vs losses is unchanged.

---

### 5. `execute_sell()` has no retry logic for live orders
**File:** `execution/order_executor.py`  
**Status: FIXED** ✓

Added the same retry loop pattern as `execute_buy()`: up to `config.MAX_RETRIES` attempts with `config.RETRY_DELAY_MS` back-off between each attempt. Transient exchange errors on SELL orders no longer create ghost positions.

---

### 6. `TradeRecord` name collision
**Files:** `data/polymarket_models.py`, `data/__init__.py`, `tests/unit/test_polymarket_models.py`  
**Status: FIXED** ✓

Renamed the SQLAlchemy ORM class in `data/polymarket_models.py` from `TradeRecord` to `TradeAuditRecord`. A backward-compatibility alias `TradeRecord = TradeAuditRecord` is retained so existing imports continue to work. `data/__init__.py` now exports `TradeAuditRecord` explicitly. The model test was updated to use `TradeAuditRecord` directly.

---

## Moderate Issues

### 7. `PolymarketConfig` uses `@dataclass` incorrectly
**File:** `config/polymarket_config.py`  
**Status: FIXED** ✓

Removed the `@dataclass` decorator and the `from dataclasses import dataclass` import. `PolymarketConfig` is now a plain class, which accurately reflects that none of its attributes are dataclass fields.

---

### 8. `datetime.utcnow()` deprecated in Python 3.12+
**File:** `data/polymarket_models.py`  
**Status: FIXED** ✓

Added `timezone` to the `datetime` import. Replaced all five `default=datetime.utcnow` column defaults with `default=lambda: datetime.now(timezone.utc)`.

---

### 9. Deprecated SQLAlchemy import
**File:** `data/polymarket_models.py`  
**Status: FIXED** ✓

Changed `from sqlalchemy.ext.declarative import declarative_base` to `from sqlalchemy.orm import declarative_base`.

---

### 10. `import` statements inside functions/methods
**Files:** Multiple  
**Status: FIXED** ✓

Moved all standard library imports to the top of each module:

| File | Import | Action |
|---|---|---|
| `data/polymarket_client.py` | `import math` | Moved to top; removed from `get_price()` |
| `data/market_schema.py` | `import json as _json` | Moved to top; removed from `_parse_outcome_prices()` |
| `execution/order_executor.py` | `import math` | Moved to top; removed from `settle_position()` |
| `data/database.py` | `from datetime import datetime` | Moved to top; removed from `add_pnl_snapshot()` |
| `main.py` | `import argparse`, `import socket`, `from datetime import datetime, timezone` | Moved to top |
| `main.py` | `import threading as _threading` | Removed — redundant alias for already-imported `threading` |

Note: `import uvicorn` inside `_start_dashboard()` was intentionally left in place — it is a heavy optional dependency that should only be loaded if the dashboard is actually started.

---

### 11. CORS wildcard in dashboard API
**File:** `dashboard/api.py`  
**Status: FIXED** ✓

Replaced `allow_origins=["*"]` with explicit localhost origins derived from `config.DASHBOARD_PORT`. Removed `allow_credentials=True` (unused — the dashboard has no cookies or auth headers). Restricted `allow_methods` to `["GET", "POST"]` and `allow_headers` to `["Content-Type"]`.

---

### 12. `start_dashboard()` default binds to `0.0.0.0`
**File:** `dashboard/api.py`, line 651

The module-level `start_dashboard()` function defaults to `host="0.0.0.0"`, but the bot's `_start_dashboard()` method correctly uses `config.DASHBOARD_HOST` (which defaults to `127.0.0.1`). If `start_dashboard()` is ever called directly (e.g., from a test script), it silently exposes the dashboard on all interfaces.

**Fix:** Change the default to `host=config.DASHBOARD_HOST`.

---

### 13. Capital sizing uses `starting_balance`, not `current_balance`
**File:** `execution/order_executor.py`  
**Status: FIXED** ✓

Changed `self.currency_tracker.starting_balance * config.CAPITAL_SPLIT_PERCENT` to `self.currency_tracker.get_available() * config.CAPITAL_SPLIT_PERCENT`. Position sizes now scale with available cash, so after drawdowns the bot sizes down gracefully rather than failing to open positions at the original fixed dollar amount.

---

### 14. `execute_opportunity()` is dead code
**File:** `strategies/settlement_arbitrage/strategy.py`  
**Status: FIXED** ✓

Removed `execute_opportunity()` entirely. The unused `Optional` import it required was also removed. Position sizing is handled exclusively by `OrderExecutor.execute_buy()`.

---

### 15. `config.reload()` does not re-create `PolymarketClient`
**File:** `config/polymarket_config.py`, `dashboard/api.py`

`reload()` updates `RELAYER_ENABLED`, `BUILDER_ENABLED`, auth keys, etc. in memory, but the existing `PolymarketClient` instance (which chose auth mode at construction time) is not recreated. Changing auth settings via the dashboard API has no effect on live order submission until a full restart. There is no user-facing warning about this.

**Fix:** Either document this limitation clearly in the API response (add a `"restart_required"` flag for auth fields), or trigger `bot.start_trading_loop()` to recreate the client (as it already does on `start_trading_loop()` calls).

Also, `PREVENT_SLEEP` is missing from `reload()` entirely. Since it triggers a Windows API call it cannot truly be hot-reloaded, but its absence means any reload silently reverts it to the class default.

---

### 16. `get_available()` is identical to `get_balance()`
**File:** `portfolio/fake_currency_tracker.py`
**Status: FIXED** ✓

Removed `get_available()` entirely. Updated the two callers (`order_executor.py` and `dashboard/api.py`) to call `get_balance()` directly. Removed the test that encoded the duplicate.

---

### 17. `AlertManager` thread pool is never shut down
**File:** `utils/alerts.py`, line 70

The `ThreadPoolExecutor` is created at module import time but `executor.shutdown()` is never called on process exit. On CPython this is harmless because the interpreter will clean up threads on exit, but it suppresses any `RuntimeError` from tasks that were still running during shutdown, and will log warnings in Python 3.9+.

**Fix:** Add `atexit.register(self._executor.shutdown, wait=True)` in `__init__`, or shut it down in `TradingBot.stop()`.

---

### 18. `data/.seen_markets.json` is not in `.gitignore`
**File:** `.gitignore`, `strategies/enhanced_market_scanner/scanner.py`

The scanner writes a persistent seen-market cache to `data/.seen_markets.json`. This file could grow large and should not be committed. The `.gitignore` covers `*.db` and `*.log` but not this JSON file.

**Fix:** Add `data/.seen_markets.json` to `.gitignore`.

---

### 19. `TradeLogger` CSV writes are not thread-safe
**File:** `utils/logger.py`, line 140

`log_trade()` opens the CSV file in append mode on every call without any lock. The trading thread and dashboard thread (which could call alerts) may call this concurrently, resulting in interleaved or truncated CSV lines.

**Fix:** Add a `threading.Lock()` to `TradeLogger` and hold it around the `open()` → `write()` block, or use `logging.FileHandler` which already has internal locking.

---

### 20. `scan_categories()` threads have no join timeout
**File:** `data/market_scanner.py`, line 55

```python
for t in threads:
    t.join()  # no timeout
```

If the Gamma API hangs on one category (e.g., a slow DNS or stalled TLS), `join()` blocks indefinitely, stalling the entire trading loop iteration.

**Fix:** Add a timeout: `t.join(timeout=30)`. After the joins, check which threads are still alive and log a warning for any that did not complete.

---

### 21. `TradeDatabase` has no application-level lock
**File:** `data/database.py`  
**Status: FIXED** ✓

Added `import threading` and `self._lock = threading.Lock()` to `TradeDatabase.__init__()`. All three write methods (`upsert_position`, `upsert_trade`, `add_pnl_snapshot`) now acquire the lock around their `execute()` + `commit()` pairs. `datetime` was also moved from the inline import inside `add_pnl_snapshot()` to the top of the file (item 10).

---

## Minor Issues

### 22. Logger level hardcoded to `DEBUG`
**File:** `utils/logger.py`, line 68

```python
logger.setLevel(logging.DEBUG)
```

The logger and both handlers are set to `DEBUG` regardless of `config.LOG_LEVEL`. The env-var setting has no effect on what the root logger passes to its handlers.

**Fix:** `logger.setLevel(getattr(logging, config.LOG_LEVEL.upper(), logging.INFO))`

Also, `config.LOG_LEVEL` is loaded at import time (before the user has a chance to set it via `.env`), so if the logger module is imported before `load_dotenv()` runs, `LOG_LEVEL` will always be its default. This is a module import order concern.

---

### 23. Magic numbers `time.sleep(2)` and `time.sleep(3)` in `main.py`
**File:** `main.py`, lines 153, 534

Both sleeps are arbitrary waits with no documented rationale. The `sleep(2)` after starting the dashboard is waiting for uvicorn to bind the port; the `sleep(3)` in `_deferred_start` is waiting for the bot to fully initialise.

**Fix:** Extract these into named constants or config values, and add a brief comment explaining what is being awaited. A more robust approach would use an event object (`threading.Event`) set by the dashboard once it's ready.

---

### 24. `scan_interval_ms` not refreshed mid-loop
**File:** `main.py`, line 227

```python
scan_interval = config.SCAN_INTERVAL_MS / 1000  # computed once at loop start
```

`scan_interval` is read once when `run()` is called. Hot-reloading `SCAN_INTERVAL_MS` via the dashboard has no effect until the trading loop is stopped and restarted.

**Fix:** Read `config.SCAN_INTERVAL_MS` at the top of each loop iteration.

---

### 25. `seen_markets` has no expiry or size cap
**File:** `strategies/enhanced_market_scanner/scanner.py`

`seen_markets` grows unboundedly and is flushed to disk after every full scan. Over months of operation this set could become very large and slow down the JSON serialisation / deserialisation.

**Fix:** Add an LRU-style cap (e.g., keep only the last 10,000 market IDs) or store a timestamp alongside each entry and prune entries older than N days.

---

### 26. `get_market()` has no retry logic
**File:** `data/polymarket_client.py`, line 305

All other network calls use `_with_retry()`, but `get_market()` makes a single request with no retry on transient failures.

**Fix:** Wrap the `_http_session.get()` call with `_with_retry()` as is done in `get_all_markets()`.

---

### 27. `_with_retry` has no jitter
**File:** `data/polymarket_client.py`, line 25

The retry delays are fixed: `(0.1, 0.5, 2.0)`. Under load, multiple concurrent clients retrying simultaneously will hit the API at the same instant after each delay, creating a thundering herd pattern.

**Fix:** Add random jitter: `delay *= (0.5 + random.random())`.

---

### 28. `PolymarketConfig` `_TIER_DAILY_LIMITS` and `_SENSITIVE_FIELDS` accessed as instance attributes
**File:** `config/polymarket_config.py`
**Status: FIXED** ✓

Changed `self._TIER_DAILY_LIMITS` to `PolymarketConfig._TIER_DAILY_LIMITS` in `daily_request_limit`. Removed `_SENSITIVE_FIELDS` entirely — it was defined but never referenced anywhere in the codebase.

---

### 29. `TradeLogger.log_trade()` CSV format has no quoting
**File:** `utils/logger.py`, line 142

The CSV is written manually without using Python's `csv` module. If any field contains a comma (e.g., a market slug or reason string), the output will have incorrect column counts.

**Fix:** Use `csv.writer` with `quoting=csv.QUOTE_MINIMAL`.

---

### 30. `has_sufficient_liquidity()` double-condition on zero volume
**File:** `data/market_schema.py`, line 124

```python
return self.volume > 0 and self.volume >= min_volume
```

When `min_volume=0.0`, markets with `volume=0.0` are still rejected (first condition fails). This means `MinVolumeUSD=0` does not mean "no filter" — it still silently excludes markets with unknown/zero volume. This is intentional per the comment but is surprising behavior for a zero-value filter.

**Fix:** Document this explicitly, or rename the parameter to `min_volume_usd_exclusive` and note that 0.0 means "must have at least some volume".

---

## Session 2 Findings — Strategy Math Review

### 31. Settlement edge formula measured on the wrong basis
**File:** `strategies/settlement_arbitrage/strategy.py`  
**Status: FIXED** ✓

The old formula `gross_edge = (1.00 - yes_price) * 100` computed profit as a fraction of the settlement *value* ($1.00), not the investment *cost* (the price paid). For example, buying at 0.985 gives a 1.52% ROI but the old formula reported 1.50%, understating the edge for lower-priced tokens and potentially rejecting borderline opportunities.

Correct formula:
```python
# Return on investment: spend yes_price per share, receive $1.00 at settlement
gross_edge = (1.0 / yes_price - 1.0) * 100
net_edge = gross_edge - taker_fee
```

---

### 32. Auto-settlement incorrectly charged an exit fee
**Files:** `execution/order_executor.py`, `portfolio/position_tracker.py`  
**Status: FIXED** ✓

`settle_position()` previously computed `exit_fee = shares × settlement_price × (TAKER_FEE_PERCENT / 100)` and subtracted it from the net return. Polymarket token redemption at expiry is automatic — no SELL order is placed, so no taker fee applies. Only the entry taker fee is a real cost.

Fix: Changed `settle_position()` to accept an explicit `exit_fee: float = 0.0` parameter (defaulting to zero). `execute_sell()` (early manual exits) passes a computed fee; the normal settlement path passes nothing, correctly recording `exit_fee=0.0` on the position.

---

### 33. `FakeCurrencyTracker.allocate_to_position()` silently capped allocation at 20 %
**File:** `portfolio/fake_currency_tracker.py`  
**Status: FIXED** ✓

```python
# old — silent cap
position_amount = min(amount, self.starting_balance * 0.2)
```

`OrderExecutor.execute_buy()` computed `capital_to_allocate = available_balance × CAPITAL_SPLIT_PERCENT` and used the full value for shares and fee calculations, but `allocate_to_position()` only deducted the capped amount from the balance. With a $10,000 balance and a 20 % split the discrepancy was $0, but at any non-default CAPITAL_SPLIT_PERCENT the balance and position-cost diverged, making PnL invariant tests fail.

Fix: Removed the cap; the caller (executor) is responsible for sizing.

---

## Session 2 Findings — Market Data Pipeline

### 34. Pagination loop breaks on empty page instead of undersized page
**File:** `data/polymarket_client.py`  
**Status: FIXED** ✓

```python
# old — breaks when a full page is all-inactive events
if len(events) < page_size or not page_markets:
    break
```

`not page_markets` was `True` whenever all events on a full page had inactive markets. This caused the loop to stop mid-dataset, missing all markets on subsequent pages. The correct sentinel is receiving *fewer events than requested*, which unambiguously signals the last page.

Fix:
```python
if len(events) < page_size:
    break
```

---

### 35. `_convert_and_filter` never applied the category filter
**File:** `data/market_provider.py`  
**Status: FIXED** ✓

`MarketProvider._convert_and_filter()` iterated `skip_volume`, `skip_binary`, and `skip_time` reasons, but had no gate for `criteria.categories`. For categories without a Gamma API `tag_id` mapping (`regulatory`, `other`), the entire market universe was fetched and then passed wholesale to the strategy — ignoring the caller's category restriction entirely.

Fix: Added check 0 (cheapest after parse — no I/O):
```python
if criteria.categories and market.category not in criteria.categories:
    skipped_category += 1
    continue
```

---

### 36. Sequential `join(timeout=30)` compounded to 4 × 30 = 120 s worst case
**File:** `data/market_scanner.py`  
**Status: FIXED** ✓

```python
# old — sequential timeouts, total worst-case = N × 30 s
for t in threads:
    t.join(timeout=30)
```

With four category threads, a single stalled thread caused the loop to wait 30 s; with all four stalled the trading loop was blocked for 120 s — far exceeding any reasonable scan interval.

Fix: Replaced with a shared monotonic deadline:
```python
deadline = time.monotonic() + 30
for t in threads:
    remaining = max(0.0, deadline - time.monotonic())
    t.join(timeout=remaining)
    if t.is_alive():
        logger.warning("market_scanner: thread '%s' did not finish …", t.name)
```

---

### 37. Timeout warning logged `Thread-N` instead of the category name
**File:** `data/market_scanner.py`  
**Status: FIXED** ✓

Threads were created with `threading.Thread(target=_fetch, args=(cat,))` (no `name=` argument), so the warning message was `"thread 'Thread-1' did not finish"` — useless for diagnosing which category API call was slow.

Fix: Added `name=f"scanner-{cat}"` to the `Thread()` constructor. The warning now logs, e.g., `"thread 'scanner-crypto' did not finish"`.

---

## Session 2 Findings — Dashboard Security

### 38. `.env` newline injection in `_write_env_key`
**File:** `dashboard/api.py`  
**Status: FIXED** ✓

A caller supplying a value containing `\n` (e.g., `smtp_server = "host\nPAPER_TRADING_ONLY=false"`) would inject an extra key into the `.env` file. Since `config.reload()` reads `.env` on every hot-reload, this could silently override safety-critical settings.

Fix:
```python
value = value.replace("\r", "").replace("\n", "").replace("\x00", "")
```
Applied before any `.env` write.

---

### 39. No authentication on any dashboard control endpoint
**File:** `dashboard/api.py`  
**Status: FIXED** ✓

All routes — including `POST /api/settings` (writes `.env`), `POST /api/start`, `POST /api/stop` — were unauthenticated. Anyone who could reach the dashboard port could modify trading settings or start/stop the bot.

Fix: Added an optional `DASHBOARD_API_KEY` env var. When set, all endpoints except `GET /api/health` require an `X-API-Key` header matching the configured key. When not set the middleware is a no-op, preserving backward compatibility.

```python
async def verify_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    configured_key = config.DASHBOARD_API_KEY
    if not configured_key:
        return          # auth disabled
    if x_api_key != configured_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
```

`DASHBOARD_API_KEY` was added to `PolymarketConfig` and `.env.example`.

---

### 40. Internal error details leaked via `detail=str(e)`
**File:** `dashboard/api.py`  
**Status: FIXED** ✓

Every `except Exception as e` catch-all handler returned `HTTPException(status_code=500, detail=str(e))`. This exposed stack-trace fragments, internal file paths, and configuration values to any HTTP client. OWASP A05:2021 (Security Misconfiguration) — information disclosure.

Fix: Replaced all `detail=str(e)` with `detail="Internal server error"` and added `logger.error(…, exc_info=True)` so the real error still appears in server logs.

---

### 41. Unbounded `limit` on `/api/trades`
**File:** `dashboard/api.py`  
**Status: FIXED** ✓

`GET /api/trades?limit=999999` returned the entire trade history in one response with no cap, enabling a denial-of-service by exhausting memory or I/O.

Fix:
```python
async def get_trades(limit: int = Query(default=50, ge=1, le=500)):
```

---

### 42. `status` query parameter accepted any string silently
**File:** `dashboard/api.py`  
**Status: FIXED** ✓

`GET /api/positions?status=garbage` previously fell through to returning all positions (the `else` branch), giving no error to the caller. This made the API misleading: invalid status values silently returned wrong data.

Fix: Changed type annotation to `Optional[Literal["open", "settled"]]`, which causes FastAPI to return a `422 Unprocessable Entity` for invalid values automatically.

---

## Remaining Open Areas

### 43. `pkg/config.py` (Pydantic Settings class) is unreachable dead code
**File:** `pkg/` directory
**Status: FIXED** ✓

Deleted the entire `pkg/` directory (`config.py`, `errors.py`, `logger.py`, `__init__.py`) and the sibling `api/` directory which depended on it (`router.py`, `routes/`). Neither was imported by the live trading system. Removed the two unit test files (`test_config.py`, `test_errors.py`) that only tested this dead code.

---

### 44. Rate-limiting accounting in `safe_scan_interval_ms` may be inaccurate
**File:** `config/polymarket_config.py`

`safe_scan_interval_ms` estimates API call frequency to stay within rate limits, but its denominator assumes a fixed number of calls per scan cycle (~4). The actual number depends on which categories are enabled, how many pages are required per category, and whether `get_market()` calls are made for individual markets. If the real call count diverges from the estimate, the calculated interval either over-throttles (missing opportunities) or under-throttles (hitting the rate limit).

**Recommended action:** Instrument `PolymarketClient` with a call counter, log the actual call count per scan at `DEBUG` level, and use that to calibrate `safe_scan_interval_ms`. Alternatively, add an explicit `MAX_API_CALLS_PER_SCAN` config knob so operators can tune it directly.

---

## Security Notes

| # | Location | Issue | Status |
|---|---|---|---|
| S1 | `dashboard/api.py` | `allow_origins=["*"]` with `allow_credentials=True` | **FIXED** — see item 11 |
| S2 | `dashboard/api.py` | `host="0.0.0.0"` default in `start_dashboard()` | **FIXED** — see item 12 |
| S3 | `dashboard/api.py` | Settings endpoint writes `.env`; no auth meant any caller could change `TRADING_MODE`, email credentials, etc. | **FIXED** — see items 38 & 39 |
| S4 | `data/polymarket_client.py` | Relayer headers (`RELAYER_API_KEY`) stored in plain dict on instance | **FIXED** — added `__repr__` that never exposes `_relayer_headers`; shows only mode flags |
| S5 | `config/polymarket_config.py:204` | `__repr__` correctly masks credentials; ensure no other `str()` / `print()` paths expose the raw config | **OPEN** — no code change needed; operational awareness required |

| # | Location | Issue |
|---|---|---|
| S1 | `dashboard/api.py:78` | `allow_origins=["*"]` with `allow_credentials=True` — see item 11 above |
| S2 | `dashboard/api.py:651` | `host="0.0.0.0"` default in `start_dashboard()` — see item 12 above |
| S3 | `dashboard/api.py:559` | `.env` file is written by the settings endpoint; if the dashboard is exposed externally, any user can change `DISCORD_WEBHOOK_URL`, email credentials, or `TRADING_MODE` |
| S4 | `data/polymarket_client.py:165` | Relayer headers (`RELAYER_API_KEY`) are stored in a plain dict `self._relayer_headers` on the instance; care should be taken that this object is not serialised or logged anywhere |
| S5 | `config/polymarket_config.py:204` | `__repr__` correctly masks credentials; ensure no other `str()` / `print()` paths accidentally expose the raw config object |

---

## Deprecated API Summary

| File | Deprecated Usage | Replacement |
|---|---|---|
| `data/polymarket_models.py` | `sqlalchemy.ext.declarative.declarative_base` | `sqlalchemy.orm.declarative_base` |
| `data/polymarket_models.py` | `datetime.utcnow` as column default | `lambda: datetime.now(timezone.utc)` |
| `config/polymarket_config.py` | `@dataclass` on a class with no annotated fields | Remove decorator |

---

## Architecture / Design Observations

### Dual `TradeRecord` / `TradePosition` models

There are two parallel model hierarchies:
- **SQLAlchemy ORM** models in `data/polymarket_models.py` (`TradeOpportunity`, `TradePosition`, `TradeRecord`)
- **Dataclass** models in `utils/pnl_tracker.py` (`TradeRecord`) and `portfolio/position_tracker.py` (`Position`)

The dataclass models are the ones actually used by the trading loop, while the SQLAlchemy models are used for DB persistence via `data/database.py`. The mapping between them is done manually in `upsert_position()` / `upsert_trade()`. This duplication means any field addition requires changes in two places. Consider either consolidating to one model layer or writing explicit mapper tests to catch mismatches.

### `MarketProvider` caching vs `EnhancedMarketScanner`

`MarketProvider` has a well-designed TTL cache. `EnhancedMarketScanner` independently calls `client.get_all_markets()` per category on every `scan_all_markets()` call with no caching. These two code paths can coexist but they represent diverging approaches. Strategies using `EnhancedMarketScanner` directly bypass `MarketProvider`'s cache entirely. Consider routing `EnhancedMarketScanner` through `MarketProvider` or deprecating one path.

### `PolymarketConfig.reload()` coverage gaps

Fields not covered by `reload()` (i.e., cannot be hot-reloaded):
- `PREVENT_SLEEP`
- `ENABLE_CRYPTO_MARKETS`, `ENABLE_FED_MARKETS`, `ENABLE_REGULATORY_MARKETS`, `ENABLE_OTHER_MARKETS`
- `PRIORITY_CRYPTO`, `PRIORITY_FED`, `PRIORITY_REGULATORY`, `PRIORITY_OTHER`
- `ORDER_TYPE`
- `CHAIN_ID`, `CLOB_API_URL`, `GAMMA_API_URL`

This is partially intentional but is undocumented. Adding a comment listing reload-capable vs restart-required settings would help operators.

---

## Issue Priority Matrix

| Priority | # | File | One-line summary |
|---|---|---|---|
| **P0** ✓ | 1 | `fake_currency_tracker.py` | ~~No lock — balance race condition~~ FIXED |
| **P0** ✓ | 2 | `enhanced_market_scanner/scanner.py` | ~~`"regulation"` vs `"regulatory"` — filters silently never applied~~ FIXED |
| **P1** ✓ | 3 | `main.py` | ~~`stop()` called twice on SIGINT~~ FIXED |
| **P1** ✓ | 4 | `position_tracker.py` | ~~Break-even trades counted as losses~~ FIXED |
| **P1** ✓ | 5 | `order_executor.py` | ~~No retry on live SELL order~~ FIXED |
| **P1** ✓ | 6 | `polymarket_models.py` + `pnl_tracker.py` | ~~Duplicate `TradeRecord` name~~ FIXED → renamed to `TradeAuditRecord` |
| **P2** ✓ | 7 | `polymarket_config.py` | ~~`@dataclass` misuse~~ FIXED |
| **P2** ✓ | 8 | `polymarket_models.py` | ~~`datetime.utcnow` deprecated~~ FIXED |
| **P2** ✓ | 9 | `polymarket_models.py` | ~~`declarative_base` import deprecated~~ FIXED |
| **P2** ✓ | 10 | Multiple | ~~`import` statements inside functions~~ FIXED |
| **P2** ✓ | 11 | `dashboard/api.py` | ~~CORS wildcard + credentials~~ FIXED |
| **P2** ✓ | 13 | `order_executor.py` | ~~Capital sized off `starting_balance`~~ FIXED |
| **P2** ✓ | 14 | `settlement_arbitrage/strategy.py` | ~~`execute_opportunity()` dead code~~ FIXED — removed |
| **P2** ✓ | 21 | `database.py` | ~~No lock on SQLite writes~~ FIXED |
| **P3** ✓ | 12 | `dashboard/api.py` | ~~`start_dashboard()` exposes `0.0.0.0`~~ FIXED (resolved alongside #11) |
| **P3** ✓ | 15 | `polymarket_config.py` | ~~`reload()` doesn't re-create client~~ FIXED — added restart-required docstring listing auth/DB fields |
| **P3** ✓ | 17 | `alerts.py` | ~~Thread pool never shut down~~ FIXED — `atexit.register(executor.shutdown)` added |
| **P3** ✓ | 18 | `.gitignore` | ~~`data/.seen_markets.json` not excluded~~ FIXED |
| **P3** ✓ | 19 | `logger.py` | ~~CSV not thread-safe~~ FIXED — `threading.Lock()` wraps all CSV open/write |
| **P3** ✓ | 20 | `market_scanner.py` | ~~Thread join has no timeout~~ FIXED — `join(timeout=30)` + warning if still alive |
| **P3** ✓ | 22 | `logger.py` | ~~Log level hardcoded to DEBUG~~ FIXED — uses `config.LOG_LEVEL` |
| **P4** ✓ | 23 | `main.py` | ~~Magic sleep constants~~ FIXED — extracted to named constants with comments |
| **P4** ✓ | 24 | `main.py` | ~~`scan_interval` not re-read per iteration~~ FIXED — moved inside loop |
| **P4** ✓ | 25 | `scanner.py` | ~~`seen_markets` unbounded growth~~ FIXED — capped at 10,000; oldest trimmed on save |
| **P4** ✓ | 26 | `polymarket_client.py` | ~~`get_market()` no retry~~ FIXED — wrapped with `_with_retry()` |
| **P4** ✓ | 27 | `polymarket_client.py` | ~~Retry has no jitter~~ FIXED — delay multiplied by `random.random()` in [0.5, 1.5) |
| **P4** ✓ | 29 | `logger.py` | ~~CSV written without `csv.writer`~~ FIXED — uses `csv.writer` with `newline=""` |
| **P3** ✓ | 16 | `fake_currency_tracker.py` | ~~`get_available()` is identical to `get_balance()`~~ FIXED — removed `get_available()` |
| **P3** ✓ | 28 | `polymarket_config.py` | ~~Class vars accessed as `self.X`~~ FIXED — `PolymarketConfig._TIER_DAILY_LIMITS`; `_SENSITIVE_FIELDS` removed |
| **P3** | 30 | `market_schema.py` | `has_sufficient_liquidity(min_volume=0)` still rejects zero-volume markets — undocumented |
| **P0** ✓ | 31 | `settlement_arbitrage/strategy.py` | ~~Edge formula on wrong basis — ROI understated~~ FIXED → `(1/price - 1) × 100` |
| **P0** ✓ | 32 | `order_executor.py` | ~~Auto-settlement charged exit taker fee — Polymarket redemption is free~~ FIXED |
| **P1** ✓ | 33 | `fake_currency_tracker.py` | ~~`allocate_to_position()` silently capped at 20% — balance/PnL invariant broken~~ FIXED |
| **P1** ✓ | 34 | `polymarket_client.py` | ~~Pagination breaks on empty page — early exit misses markets~~ FIXED |
| **P1** ✓ | 35 | `market_provider.py` | ~~Category filter never applied — entire market universe passed to strategy~~ FIXED |
| **P2** ✓ | 36 | `market_scanner.py` | ~~Sequential join timeouts compound to 4×30 s worst case~~ FIXED — monotonic deadline |
| **P3** ✓ | 37 | `market_scanner.py` | ~~Timeout warning logs `Thread-N` not category name~~ FIXED — `name=f"scanner-{cat}"` |
| **P0** ✓ | 38 | `dashboard/api.py` | ~~`.env` newline injection in `_write_env_key`~~ FIXED — strip `\r\n\x00` |
| **P0** ✓ | 39 | `dashboard/api.py` | ~~No auth on control endpoints~~ FIXED — optional `DASHBOARD_API_KEY` + `X-API-Key` header |
| **P1** ✓ | 40 | `dashboard/api.py` | ~~`detail=str(e)` leaks internals in 500 responses~~ FIXED — generic message + `exc_info` |
| **P2** ✓ | 41 | `dashboard/api.py` | ~~Unbounded `limit` on `/api/trades`~~ FIXED — `Query(ge=1, le=500)` |
| **P3** ✓ | 42 | `dashboard/api.py` | ~~`status` param accepts any string silently~~ FIXED — `Literal["open", "settled"]` |
| **P3** ✓ | 43 | `pkg/` + `api/` directories | ~~Dead code — imported nowhere~~ FIXED — deleted both directories and their tests |
| **P4** | 44 | `polymarket_config.py` | `safe_scan_interval_ms` assumes fixed API call count per scan — may under/over-throttle |
