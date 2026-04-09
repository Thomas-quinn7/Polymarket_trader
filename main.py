# Copyright (C) 2026  Thomas Quinn (github.com/Thomas-quinn7)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public
# License along with this program. If not, see
# <https://www.gnu.org/licenses/>.

"""
Main Trading Bot
Orchestrates all components and runs the strategy loop.
"""

import os
import time
import signal
import sys
import threading
from datetime import datetime
from typing import Optional

from data.polymarket_client import PolymarketClient
from data.polymarket_models import TradeOpportunity
from data.database import TradeDatabase
from data.market_scanner import scan_categories
from data.order_book_store import OrderBookStore, OrderBookSnapshot, OrderBookLevel
from strategies.registry import load_strategy
from strategies.base import BaseStrategy
from portfolio.fake_currency_tracker import FakeCurrencyTracker
from portfolio.position_tracker import PositionTracker
from execution.order_executor import OrderExecutor
from utils.logger import logger
from utils.pnl_tracker import PnLTracker
from utils.alerts import alert_manager
from config.polymarket_config import config

import dashboard.api


class TradingBot:
    """Main trading bot orchestrator."""

    def __init__(self):
        logger.info("=" * 70)
        logger.info("Initializing Polymarket Trading Bot")
        logger.info("=" * 70)

        self.start_time = datetime.now()

        self.client: PolymarketClient = PolymarketClient()
        self.strategy: BaseStrategy = load_strategy(config.STRATEGY, self.client)

        self.currency_tracker = FakeCurrencyTracker()
        self.pnl_tracker = PnLTracker(initial_balance=self.currency_tracker.starting_balance)
        self.position_tracker = PositionTracker(self.pnl_tracker)

        self.executor = OrderExecutor(
            pnl_tracker=self.pnl_tracker,
            position_tracker=self.position_tracker,
            currency_tracker=self.currency_tracker,
            polymarket_client=self.client,
        )

        self.db: Optional[TradeDatabase] = None
        if config.DB_ENABLED:
            self.db = TradeDatabase(config.DB_PATH)
            if not self.db.connect():
                logger.warning("SQLite DB unavailable — data will not be persisted")
                self.db = None

        self.order_book_store: Optional[OrderBookStore] = None
        if config.SCYLLA_ENABLED:
            self.order_book_store = OrderBookStore(
                hosts=[config.SCYLLA_HOST],
                port=config.SCYLLA_PORT,
                keyspace=config.SCYLLA_KEYSPACE,
            )
            if not self.order_book_store.connect():
                logger.warning("ScyllaDB unavailable — order book snapshots disabled")
                self.order_book_store = None

        self.running = False
        self.markets_cache: list = []
        self.last_scan_time: float = 0
        self._trading_thread: Optional[threading.Thread] = None

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info(f"Strategy: {config.STRATEGY}")
        logger.info(f"Initial Balance: ${self.currency_tracker.starting_balance:.2f}")
        logger.info("=" * 70)
        logger.info("Ready — use the WebUI to configure mode and start trading")
        logger.info("=" * 70)

    def _signal_handler(self, signum, frame):
        logger.info("\nShutdown signal received")
        self.stop()
        sys.exit(0)

    def _start_dashboard(self, port: int):
        import uvicorn
        try:
            uvicorn_config = uvicorn.Config(
                app="dashboard.api:app",
                host=config.DASHBOARD_HOST,
                port=port,
                log_level="warning",
            )
            uvicorn.Server(uvicorn_config).run()
        except Exception as e:
            logger.error(f"Dashboard server crashed: {e}")

    # ── Process lifecycle ──────────────────────────────────────────────

    def start(self):
        """Start the process: launch dashboard and wait for WebUI commands."""
        logger.info("Starting Trading Bot...")

        if config.DASHBOARD_ENABLED:
            import socket as _socket
            port = config.DASHBOARD_PORT
            original_port = port
            while True:
                with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
                    if s.connect_ex(("127.0.0.1", port)) != 0:
                        break
                port += 1
                if port > original_port + 10:
                    logger.error(
                        f"No free port in range {original_port}–{original_port + 10}, "
                        "dashboard disabled."
                    )
                    port = None
                    break

            if port:
                if port != original_port:
                    logger.warning(f"Port {original_port} in use, using port {port}")
                logger.info(f"Dashboard: http://localhost:{port}")
                dashboard.api.set_bot_instance(self)
                threading.Thread(
                    target=self._start_dashboard, args=(port,), daemon=True
                ).start()
                time.sleep(2)

        alert_manager.send_system_start_alert()

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("\nShutdown requested")
        finally:
            self.stop()

    def stop(self):
        """Stop everything cleanly."""
        if self.running:
            self.stop_trading_loop()
            if self._trading_thread and self._trading_thread.is_alive():
                self._trading_thread.join(timeout=5)

        self._print_final_report()
        alert_manager.send_system_stop_alert()
        logger.info("Trading Bot stopped")

    # ── Trading loop control ───────────────────────────────────────────

    def start_trading_loop(self) -> bool:
        if self.running:
            logger.warning("Trading loop already running")
            return False

        logger.info(
            f"Starting trading loop (mode={config.TRADING_MODE}, strategy={config.STRATEGY})"
        )
        self.client = PolymarketClient()
        self.strategy = load_strategy(config.STRATEGY, self.client)
        self.executor.polymarket_client = self.client

        self.markets_cache = []
        self.last_scan_time = 0

        self.running = True
        self._trading_thread = threading.Thread(
            target=self._run_loop_thread, daemon=True
        )
        self._trading_thread.start()

        mode_label = (
            "SIMULATION (offline, synthetic data)"
            if config.TRADING_MODE == "simulation"
            else "PAPER (real prices, simulated execution)"
        )
        logger.info(f"Trading loop started — {mode_label}")
        return True

    def stop_trading_loop(self) -> bool:
        if not self.running:
            logger.warning("Trading loop is not running")
            return False
        logger.info("Stopping trading loop...")
        self.running = False
        return True

    def _run_loop_thread(self):
        try:
            self.run()
        except Exception as e:
            logger.critical(f"Fatal error in trading loop: {e}", exc_info=True)
            alert_manager.send_error_alert(str(e), "Fatal error in trading loop")
        finally:
            self.running = False
            logger.info("Trading loop exited")

    # ── Main trading loop ──────────────────────────────────────────────

    def run(self):
        """Main trading loop (runs in _trading_thread)."""
        iteration = 0
        scan_interval = config.SCAN_INTERVAL_MS / 1000

        while self.running:
            iteration += 1
            logger.info(f"\n{'=' * 70}")
            logger.info(
                f"Loop #{iteration} — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
                f"| strategy={config.STRATEGY} mode={config.TRADING_MODE}"
            )
            logger.info(f"{'=' * 70}")

            try:
                self._check_strategy_exits()
                self._check_stop_losses()
                self._scan_and_execute()
                self._print_status()

                logger.info(f"Sleeping {scan_interval:.1f}s...")
                time.sleep(scan_interval)

            except Exception as e:
                logger.error(f"Error in trading loop: {e}", exc_info=True)
                alert_manager.send_error_alert(
                    str(e), f"Error in trading loop iteration #{iteration}"
                )
                time.sleep(scan_interval)

    # ── Strategy-driven exit ───────────────────────────────────────────

    def _check_strategy_exits(self):
        """
        Ask the strategy whether any open position should be closed.
        The strategy owns all exit logic — the infrastructure just calls it.
        """
        for pos in self.position_tracker.get_open_positions():
            try:
                current_price = self.client.get_price(pos.winning_token_id)
                if not self.strategy.should_exit(pos, current_price):
                    continue

                exit_price = self.strategy.get_exit_price(pos, current_price)
                logger.info(
                    f"Strategy exit signal: {pos.position_id} @ ${exit_price:.4f}"
                )
                pnl = self.executor.settle_position(
                    pos.position_id, settlement_price=exit_price
                )

                if self.db:
                    settled = self.position_tracker.get_position(pos.position_id)
                    if settled:
                        self.db.upsert_position(settled)
                    for trade in self.pnl_tracker.trades:
                        if trade.position_id == pos.position_id and trade.exit_time:
                            self.db.upsert_trade(trade)
                            break

            except Exception as e:
                logger.error(f"Error checking exit for {pos.position_id}: {e}")

    # ── Stop-loss ──────────────────────────────────────────────────────

    def _check_stop_losses(self):
        """
        Generic stop-loss: close a position if its price has dropped
        STOP_LOSS_PERCENT below entry.  Skipped when the setting is 0.
        """
        if config.STOP_LOSS_PERCENT <= 0:
            return
        for pos in self.position_tracker.get_open_positions():
            try:
                current_price = self.client.get_price(pos.winning_token_id)
                if current_price <= 0:
                    continue
                drop_pct = (pos.entry_price - current_price) / pos.entry_price * 100
                if drop_pct >= config.STOP_LOSS_PERCENT:
                    logger.warning(
                        f"Stop-loss triggered: {pos.position_id} — "
                        f"entry ${pos.entry_price:.4f}, now ${current_price:.4f} "
                        f"(dropped {drop_pct:.1f}%)"
                    )
                    self.executor.execute_sell(
                        pos.position_id, current_price, reason="stop_loss"
                    )
                    if self.db:
                        settled = self.position_tracker.get_position(pos.position_id)
                        if settled:
                            self.db.upsert_position(settled)
            except Exception as e:
                logger.error(f"Error checking stop-loss for {pos.position_id}: {e}")

    # ── Market scan + immediate execution ─────────────────────────────

    def _scan_and_execute(self):
        """
        Refresh market cache via the multi-category scanner, run the strategy's
        opportunity scan, then immediately execute the best ones that are not
        already in the portfolio.
        """
        try:
            cache_ttl = 5 if config.TRADING_MODE == "simulation" else 60
            if not self.markets_cache or time.time() - self.last_scan_time > cache_ttl:
                categories = (
                    self.strategy.get_scan_categories()
                    if hasattr(self.strategy, "get_scan_categories")
                    else config.SCAN_CATEGORIES
                )
                self.markets_cache = scan_categories(self.client, categories)
                self.last_scan_time = time.time()

            opportunities = self.strategy.scan_for_opportunities(self.markets_cache)

            if not opportunities:
                logger.debug("No opportunities found in this scan")
                return

            logger.info(f"Found {len(opportunities)} opportunity(ies)")
            best = self.strategy.get_best_opportunities(opportunities, limit=5)

            if self.order_book_store is not None:
                self._capture_order_book_snapshots(best)

            open_market_ids = {
                p.market_id for p in self.position_tracker.get_open_positions()
            }

            for opp in best:
                if opp.market_id in open_market_ids:
                    logger.debug(f"Already have open position for: {opp.market_id}")
                    continue

                if not self.position_tracker.can_open_position():
                    logger.info("Max positions reached — skipping remaining opportunities")
                    break

                position_id = (
                    f"{opp.market_id}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
                )
                success = self.executor.execute_buy(opp, position_id)

                if success:
                    open_market_ids.add(opp.market_id)
                    logger.info(f"Position opened: {position_id}")
                    if self.db:
                        pos = self.position_tracker.get_position(position_id)
                        if pos:
                            self.db.upsert_position(pos)
                        trade = self.pnl_tracker.open_positions.get(position_id)
                        if trade:
                            self.db.upsert_trade(trade)

                    alert_manager.send_opportunity_detected_alert(
                        market_id=opp.market_slug,
                        price=opp.current_price,
                        edge=opp.edge_percent,
                    )

        except Exception as e:
            logger.error(f"Error in scan/execute: {e}", exc_info=True)

    def _capture_order_book_snapshots(self, opportunities: list):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        for opp in opportunities:
            try:
                token_id = opp.winning_token_id
                book = self.client.get_order_book(token_id, levels=5)
                snapshot = OrderBookSnapshot(
                    token_id=token_id,
                    captured_at=now,
                    bids=[OrderBookLevel(lvl["price"], lvl["size"]) for lvl in book.get("bids", [])],
                    asks=[OrderBookLevel(lvl["price"], lvl["size"]) for lvl in book.get("asks", [])],
                )
                self.order_book_store.write_snapshot(snapshot)
            except Exception as e:
                logger.debug("Snapshot capture failed for %s: %s", opp.market_slug, e)

    # ── Reporting ──────────────────────────────────────────────────────

    def _print_status(self):
        balance = self.currency_tracker.get_balance()
        deployed = self.currency_tracker.get_deployed()
        position_count = self.position_tracker.get_position_count()
        pnl_summary = self.pnl_tracker.get_summary()

        logger.info(f"\nBalance: ${balance:.2f} | Deployed: ${deployed:.2f}")
        logger.info(f"Open Positions: {position_count}/{config.MAX_POSITIONS}")
        logger.info(f"Total P&L: ${pnl_summary.total_pnl:.2f}")
        logger.info(f"Win Rate: {pnl_summary.win_rate:.1f}%")

        if self.db:
            self.db.add_pnl_snapshot(balance=balance, pnl=pnl_summary.total_pnl)

    def _print_final_report(self):
        logger.info("\n" + "=" * 70)
        logger.info("FINAL REPORT")
        logger.info("=" * 70)
        print(self.pnl_tracker.get_report())
        pos_summary = self.position_tracker.get_summary()
        logger.info(
            f"\nPositions Summary:\n"
            f"  Open: {pos_summary['open_positions']}\n"
            f"  Settled: {pos_summary['settled_positions']}\n"
            f"  Wins: {pos_summary['wins']}\n"
            f"  Losses: {pos_summary['losses']}\n"
            f"  Realized P&L: ${pos_summary['realized_pnl']:.2f}"
        )


_BANNER = (
    "\033[96m"
    "╔══════════════════════════════════════════════════════════════════════╗\n"
    "║      Polymarket Trading Framework  ·  pmf-7e3f-tq343                 ║\n"
    "║                                                                      ║\n"
    "║  Author  : Thomas Quinn  (github.com/Thomas-quinn7)                  ║\n"
    "║  Repo    : github.com/Thomas-quinn7/Polymarket_trader                ║\n"
    "║  License : GNU Affero General Public License v3  (AGPL-3.0-only)     ║\n"
    "╚══════════════════════════════════════════════════════════════════════╝"
    "\033[0m"
)


def main():
    print(_BANNER)
    import argparse
    parser = argparse.ArgumentParser(description="Polymarket Trading Bot")
    parser.add_argument(
        "--simulation", action="store_true",
        help="Run in simulation mode (synthetic data, no real API calls)",
    )
    parser.add_argument(
        "--auto-start", action="store_true",
        help="Automatically start the trading loop on launch",
    )
    args = parser.parse_args()

    if args.simulation:
        os.environ["TRADING_MODE"] = "simulation"
        config.TRADING_MODE = "simulation"

    bot = TradingBot()

    if args.simulation or args.auto_start:
        import threading as _threading
        def _deferred_start():
            time.sleep(3)
            bot.start_trading_loop()
        _threading.Thread(target=_deferred_start, daemon=True).start()

    bot.start()


if __name__ == "__main__":
    main()
