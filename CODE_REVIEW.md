# Code Review — Polymarket Trading Framework

**Reviewer:** Claude Sonnet 4.6  
**Last updated:** 2026-04-11  
**Sessions:** Session 1 (2026-04-10) · Session 2 (2026-04-11) · Session 3 (2026-04-11)

---

## Status Summary

48 issues found across three review sessions. 44 resolved; 4 open (#45, #46, #47, and the design note on `settlement_arbitrage.active_positions`).

| Severity | Found | Fixed |
|---|---|---|
| P0 — Critical correctness | 8 | 7 |
| P1 — High correctness | 9 | 8 |
| P2 — Moderate | 10 | 9 |
| P3 — Minor | 17 | 16 |
| P4 — Polish | 4 | 4 ✓ |
| Security | 5 | 5 ✓ |

---

## Issue Log

### P0 — Critical Correctness

| # | File | Issue | Fix |
|---|---|---|---|
| 1 | `portfolio/fake_currency_tracker.py` | No lock — race condition on `balance` and `deployed` | Added `threading.Lock()`; all mutations and reads protected |
| 2 | `strategies/enhanced_market_scanner/scanner.py` | `"regulation"` typo — keyword filters silently never applied | Replaced with `"regulatory"` in all five locations |
| 31 | `strategies/settlement_arbitrage/strategy.py` | Edge formula `(1 - price) × 100` measured profit as fraction of settlement value, not investment cost | Changed to `(1/price - 1) × 100` (return-on-investment basis) |
| 32 | `execution/order_executor.py` | `settle_position()` charged a taker exit fee on auto-settlement — Polymarket token redemption is free | `settle_position()` now accepts an explicit `exit_fee=0.0` parameter; normal settlement path passes nothing |
| 38 | `dashboard/api.py` | Newline injection via `_write_env_key` — a value containing `\n` could inject extra keys into `.env` | Strip `\r`, `\n`, `\x00` from every value before writing |
| 39 | `dashboard/api.py` | No authentication on any control endpoint — anyone who could reach the port could modify settings or stop the bot | Added optional `DASHBOARD_API_KEY` env var; all endpoints except `/api/health` require matching `X-API-Key` header |
| 45 | `portfolio/position_tracker.py` + `main.py` | **Open positions are not restored on restart.** `PositionTracker.__init__` starts with `self.positions = {}`. DB rows survive but are invisible to the trading loop — capital is never freed and exits are never checked. | On startup, load open positions from `database.get_positions(status="open")` and re-populate `position_tracker.positions` and `currency_tracker`. |

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
| 46 | `strategies/settlement_arbitrage/strategy.py` | `should_exit()` does not distinguish a market that resolved NO (price → 0) from a data error — calls `execute_sell()` on a resolved NO market and pays a taker fee instead of the free redemption path | Add a resolved-NO branch: if `current_price < RESOLUTION_THRESHOLD` and market is past `end_time`, call `settle_position()` with `settlement_price=0` rather than `execute_sell()` |

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
| 14 | `strategies/settlement_arbitrage/strategy.py` | `execute_opportunity()` dead code — position sizing handled by `OrderExecutor` | Removed method and unused `Optional` import |
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
| 47 | `dashboard/api.py` | `POST /api/settings` with `trading_mode=live` updates `config.TRADING_MODE` but does not set `config.PAPER_TRADING_ONLY = False` — the actual live-order gate never opens via the dashboard | Decide: either wire the dashboard toggle to flip `PAPER_TRADING_ONLY` (requires private-key pre-check), or document that live mode requires a restart with `PAPER_TRADING_ONLY=False` in `.env` |

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

### `settlement_arbitrage` active_positions in-memory list

`strategy.active_positions: List = []` (line 52 of `settlement_arbitrage/strategy.py`) is a parallel position register maintained entirely in memory. It is not persisted and is reset on every bot restart. This is separate from `PositionTracker` and means the strategy's internal view of open positions diverges from the DB after a restart, even if issue #45 is fixed. The strategy list and `PositionTracker` must both be restored consistently.

### `safe_scan_interval_ms` call-count assumption

The divisor of 4 assumes one API call per market category. Actual call count varies with enabled categories and pagination depth. Tune `SCAN_INTERVAL_MS` manually if the rate limit is being hit — see the `safe_scan_interval_ms` docstring for details.
