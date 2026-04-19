# Copyright (C) 2026  Thomas Quinn (github.com/Thomas-quinn7)
#                     Ciaran McDonnell (github.com/CiaranMcDonnell)
# SPDX-License-Identifier: AGPL-3.0-only

import uuid
from typing import Callable, Optional

from backtesting.config import BacktestConfig
from backtesting.db import BacktestDB
from backtesting.engine import ReplayEngine, _NullClient
from backtesting.fetcher import HistoricalDataFetcher
from backtesting.metrics import BacktestMetrics, MetricsCalculator
from strategies.registry import load_strategy
from utils.logger import logger


class BacktestRunner:
    """
    Orchestrates: fetch → price history prefetch → replay → metrics → persist.
    Can be called from the CLI (synchronous) or from the API (in a background thread).
    """

    def __init__(self, db_path: str = "storage/backtest.db"):
        self._db = BacktestDB(db_path)

    def execute(
        self,
        config: BacktestConfig,
        run_id: Optional[str] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> BacktestMetrics:
        """
        Run a complete backtest. Thread-safe — the DB uses a lock internally.

        Args:
            config:            Run parameters.
            run_id:            Optional pre-created run_id.
                               If None, a new UUID is generated.
            progress_callback: Optional fn(message: str) for status updates.

        Returns:
            BacktestMetrics with all computed values.
        """
        config.validate()

        if run_id is None:
            run_id = str(uuid.uuid4())

        def _progress(msg: str):
            if progress_callback:
                progress_callback(msg)
            logger.info(f"[Runner:{run_id[:8]}] {msg}")

        # ── 1. Create run record ──────────────────────────────────────────────
        self._db.create_run(run_id, config.strategy_name, config.to_json())
        self._db.update_run_status(run_id, "running")

        try:
            # ── 2. Fetch/load market list ─────────────────────────────────────
            _progress("Fetching market list...")
            fetcher = HistoricalDataFetcher(self._db, config.rate_limit_rps)
            condition_ids = fetcher.fetch_markets_for_range(
                config,
                progress_callback=lambda n, msg: _progress(msg),
            )

            if not condition_ids:
                raise ValueError(
                    f"No resolved markets found for category={config.category} "
                    f"in {config.start_date}–{config.end_date} "
                    f"with max_duration_seconds={config.max_duration_seconds}"
                )

            _progress(f"Found {len(condition_ids)} markets. Fetching price histories...")

            # ── 3. Prefetch price histories ───────────────────────────────────
            fetcher.prefetch_all_price_histories(
                condition_ids,
                interval=config.price_interval,
                progress_callback=lambda done, total: (
                    _progress(f"Price history: {done}/{total}") if done % 100 == 0 else None
                ),
            )

            price_histories = {cid: self._db.get_price_history(cid) for cid in condition_ids}

            # ── 4. Load strategy ──────────────────────────────────────────────
            _progress(f"Loading strategy: {config.strategy_name}")
            strategy = load_strategy(config.strategy_name, _NullClient())

            # ── 5. Run replay engine ──────────────────────────────────────────
            _progress("Running replay engine...")
            engine = ReplayEngine(strategy, config, self._db)
            trades, equity_curve = engine.run(condition_ids, price_histories)

            _progress(f"Replay complete. {len(trades)} trades simulated.")

            # ── 6. Compute metrics ────────────────────────────────────────────
            metrics = MetricsCalculator().compute(trades, equity_curve, config)

            # ── 7. Persist results ────────────────────────────────────────────
            trade_dicts = [vars(t) for t in trades]
            self._db.insert_run_trades(run_id, trade_dicts)
            self._db.save_run_results(
                run_id,
                market_count=len(condition_ids),
                trade_count=len(trades),
                metrics=metrics.to_dict(),
                equity_curve=[(ts, bal) for ts, bal in equity_curve],
            )

            _progress("Done.")
            return metrics

        except Exception as exc:
            logger.error(f"[Runner] Backtest {run_id} failed: {exc}", exc_info=True)
            self._db.update_run_status(run_id, "error", error_message=str(exc))
            raise
