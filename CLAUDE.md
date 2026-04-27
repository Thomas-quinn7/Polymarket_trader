# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Do not make any changes until you have 95% confidence in what you need to build. Ask me follow-up question until you reach that confidence.

## Commands

```bash
# Install (first time)
uv venv && source .venv/bin/activate && uv pip install -e ".[dev]"

# Run all unit tests
python -m pytest tests/unit/

# Run a single test file
python -m pytest tests/unit/test_order_executor.py -v

# Run a single test by name
python -m pytest tests/unit/test_order_executor.py::TestOrderExecutor::test_execute_buy_success -v

# Lint
flake8 .

# Format
black .

# Type-check (not in CI yet — run manually)
mypy .

# Validate setup (checks credentials, deps, config)
python tests/scripts/validate_setup.py

# Run the bot
python main.py                          # waits for dashboard Start button
python main.py --auto-start             # starts trading loop immediately
python main.py --paper --auto-start     # force paper mode
python main.py --live                   # live mode (requires confirmation prompt)
```

Line length is 100. Black and flake8 are configured in `pyproject.toml` / `.flake8`. `isort` uses the `black` profile.

## Repo structure and public/private split

This is a **public framework repo** (`origin` → `github.com/Thomas-quinn7/Polymarket_trader`). A separate private repo (`private`/`dev` → `github.com/Thomas-quinn7/Polymarket_private`) receives everything via `./push_private.sh`, which force-adds gitignored paths (strategies, tools, storage, logs, PDFs) and force-pushes to `private/main`.

Files intentionally gitignored on `origin`:
- `strategies/crypto_5min_mm/`, `strategies/paper_demo/`, `strategies/demo_buy/`, `strategies/enhanced_market_scanner/` — live strategies
- `tools/` — research tooling (tick_recorder, price_target_tracker)
- `storage/` — SQLite DB + CSV exports
- `logs/` — app logs, session JSON exports
- `build_guide_pdf.py`, `build_run_guide_pdf.py`, `*.pdf` — internal collaborator docs

Never commit `.env`. Never push to `origin` anything from the above list.

## Architecture

The framework separates infrastructure from alpha. Strategies implement a small interface; everything else (data, execution, sizing, persistence, alerts) is handled by the framework.

**Request flow for each trading loop tick:**

```
main.py TradingBot._scan_and_execute()
  → MarketProvider.get_markets()          # Gamma API fetch → 60s TTL cache → filter → price-resolve
  → Strategy.scan_for_opportunities()     # strategy sees []PolymarketMarket, emits TradeOpportunity
  → Strategy.get_best_opportunities()     # rank and cap
  → OrderExecutor.execute_buy()           # slippage gate → Kelly sizing → PolymarketClient → positions
```

**Exit flow (checked every tick after entries):**
```
Strategy.should_exit() / Strategy.get_exit_price()
  → OrderExecutor.execute_sell() or settle_position()
  → PnLTracker.close_position() → PaperPortfolio.return_to_balance()
  → DB upsert, session record, alert
```

### Key modules

| Module | Responsibility |
|---|---|
| `config/polymarket_config.py` | All env-var loading; `config` singleton; `reload()` for hot-reload |
| `data/polymarket_client.py` | Gamma API + CLOB SDK wrapper; `_with_retry()` backoff; Relayer/Builder/Standard auth |
| `data/market_schema.py` | `PolymarketMarket` dataclass; `_orient_yes_no()` normalises YES/NO token order at parse time |
| `data/market_provider.py` | Fetch → filter (`MarketCriteria`) → price-resolve pipeline; `PRICE_SOURCE` enum |
| `execution/order_executor.py` | Pre-trade slippage gate; `_kelly_position_size()`; allocation/rollback; post-fill reconciliation |
| `portfolio/paper_portfolio.py` | Capital allocation (`allocate_to_position` / `return_to_balance`); `PaperPortfolio` also exported as `FakeCurrencyTracker` alias |
| `portfolio/position_tracker.py` | `Position` lifecycle (OPEN → SETTLING → SETTLED); double-settle prevention via atomic status transition |
| `utils/pnl_tracker.py` | Per-position P&L, drawdown, win rate, profit factor |
| `strategies/base.py` | `BaseStrategy` ABC; `MarketCriteria`; `TradeOpportunity` |
| `strategies/registry.py` | Loads strategy class by folder name; `load_strategy()` |
| `strategies/config_loader.py` | Merges `config.yaml` with env-var overrides (scalars only; lists are YAML-only) |
| `backtesting/engine.py` | Wall-clock timeline replay; side-aware YES/NO settlement; half-spread model |
| `dashboard/api.py` | FastAPI app; mounts at `127.0.0.1:8080`; shares in-process state with the bot |
| `main.py` | `TradingBot` orchestrator; position restore on restart; signal handlers |

### YES/NO orientation

`market_schema.py:_orient_yes_no()` normalises every market so `token_ids[0]` is always the YES token. All downstream code relies on this — `token_ids[0]` = YES, `token_ids[1]` = NO — and `resolved_price` always refers to the YES-side probability. Do not access `outcome_prices` directly from the API; use `market.resolved_price`.

### Position restore on restart

`TradingBot._restore_open_positions()` (`main.py`) reloads OPEN rows from SQLite. Restore order matters:
1. `position_tracker.restore_position()` — in-memory only
2. `pnl_tracker.open_position(..., entry_fee=position.entry_fee)` — must pass `entry_fee`
3. `currency_tracker.allocate_to_position()` — must succeed; if it returns `False`, mark DB row FAILED

### Execution auth modes

`PolymarketClient.__init__` selects auth in priority order: Relayer (if `RELAYER_ENABLED`) → Builder (if `BUILDER_ENABLED`) → Standard. Order signing is two-phase: local sign → exchange submit. Retries reuse the same signed order (idempotent via salt). Builder daily limits are computed at startup and logged as `safe_scan_interval_ms`.

## Writing a strategy

Copy `strategies/example_strategy/` to a new folder. Implement:
- `scan_for_opportunities(markets)` → yields `TradeOpportunity`
- `get_best_opportunities(opportunities, limit)` → ranked list
- `should_exit(position, current_price)` → bool (optional)
- `get_exit_price(position, market)` → float (optional)

Use `market.resolved_price` (never raw `outcome_prices`). `override_capital` on `TradeOpportunity` bypasses Kelly sizing. Register in `strategies/registry.py` and set `STRATEGY=folder_name` in `.env`.

## Known constraints

- `PREVENT_SLEEP` env var is Windows-only and a no-op on macOS — use `caffeinate -ims polymarket ...` on Mac for overnight runs.
- `MAX_POSITIONS_PER_CATEGORY` must be ≥ 2× the number of simultaneous markets when running `crypto_5min_mm`, because each market opens both a YES and a NO position.
- `tools/tick_recorder.py` and `tools/price_target_tracker.py` bootstrap `sys.path` manually (not installed as a package) — run them from the repo root.
- mypy is configured with strict settings in `pyproject.toml` but is not yet gated in CI.
