"""
Main Polymarket Arbitrage Bot
Orchestrates all components and runs the trading loop
"""

import os
import time
import signal
import sys
import threading
from datetime import datetime, timedelta
from typing import Optional

from data.polymarket_client import PolymarketClient
from data.polymarket_models import ArbitrageOpportunity
from data.database import TradeDatabase
from data.order_book_store import OrderBookStore, OrderBookSnapshot, OrderBookLevel
from strategies.registry import load_strategy
from strategies.base import TradingStrategy
from portfolio.fake_currency_tracker import FakeCurrencyTracker
from portfolio.position_tracker import PositionTracker
from execution.order_executor import OrderExecutor
from utils.execution_timer import ExecutionTimer
from utils.logger import logger
from utils.pnl_tracker import PnLTracker
from utils.alerts import alert_manager
from config.polymarket_config import config

# Import dashboard module
import dashboard.api


class TradingBot:
    """Main trading bot orchestrator"""

    def __init__(self):
        logger.info("=" * 70)
        logger.info("Initializing Polymarket Arbitrage Bot")
        logger.info("=" * 70)

        self.start_time = datetime.now()

        # Initialize client & strategy (may be re-created on each trading start)
        self.client = PolymarketClient()
        self.strategy: TradingStrategy = load_strategy(config.STRATEGY, self.client)

        # Initialize trackers (persist across start/stop cycles)
        self.currency_tracker = FakeCurrencyTracker()
        self.pnl_tracker = PnLTracker(initial_balance=self.currency_tracker.starting_balance)
        self.position_tracker = PositionTracker(self.pnl_tracker)

        # Initialize executor
        self.executor = OrderExecutor(
            pnl_tracker=self.pnl_tracker,
            position_tracker=self.position_tracker,
            currency_tracker=self.currency_tracker,
            polymarket_client=self.client,
        )

        # Initialize execution timer
        self.execution_timer = ExecutionTimer()

        # SQLite persistence (positions, trades, PnL history)
        self.db: Optional[TradeDatabase] = None
        if config.DB_ENABLED:
            self.db = TradeDatabase(config.DB_PATH)
            if not self.db.connect():
                logger.warning("SQLite DB unavailable — data will not be persisted")
                self.db = None

        # Optional ScyllaDB order book store
        self.order_book_store: Optional[OrderBookStore] = None
        if config.SCYLLA_ENABLED:
            self.order_book_store = OrderBookStore(
                hosts=[config.SCYLLA_HOST],
                port=config.SCYLLA_PORT,
                keyspace=config.SCYLLA_KEYSPACE,
            )
            connected = self.order_book_store.connect()
            if not connected:
                logger.warning("ScyllaDB unavailable — order book snapshots disabled")
                self.order_book_store = None

        # Trading state
        self.running = False
        self.markets_cache = []
        self.last_scan_time = 0
        self._last_opportunities: dict = {}  # market_id → ArbitrageOpportunity (from last scan)
        self._trading_thread: Optional[threading.Thread] = None

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

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
                    if s.connect_ex(('127.0.0.1', port)) != 0:
                        break
                port += 1
                if port > original_port + 10:
                    logger.error(
                        f"No free port in range {original_port}–{original_port + 10}, dashboard disabled."
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

        # Keep main thread alive — trading is started via WebUI
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
            # Wait briefly for the loop thread to exit
            if self._trading_thread and self._trading_thread.is_alive():
                self._trading_thread.join(timeout=5)

        self._print_final_report()
        alert_manager.send_system_stop_alert()
        logger.info("Trading Bot stopped")

    # ── Trading loop control (called via WebUI API) ────────────────────

    def start_trading_loop(self) -> bool:
        """Reinitialize client for current mode and start the trading loop."""
        if self.running:
            logger.warning("Trading loop already running")
            return False

        # Reinitialize client so new TRADING_MODE takes effect
        logger.info(f"Starting trading loop (mode={config.TRADING_MODE}, strategy={config.STRATEGY})")
        self.client = PolymarketClient()
        self.strategy = load_strategy(config.STRATEGY, self.client)
        self.executor.polymarket_client = self.client

        # Reset scan cache and timers for a clean run
        self.markets_cache = []
        self.last_scan_time = 0
        self._last_opportunities = {}
        self.execution_timer = ExecutionTimer()

        self.running = True
        self._trading_thread = threading.Thread(target=self._run_loop_thread, daemon=True)
        self._trading_thread.start()

        mode_label = (
            "SIMULATION (offline, synthetic data)"
            if config.TRADING_MODE == "simulation"
            else "PAPER (real prices, simulated execution)"
        )
        logger.info(f"Trading loop started — {mode_label}")
        return True

    def stop_trading_loop(self) -> bool:
        """Signal the trading loop to stop after its current iteration."""
        if not self.running:
            logger.warning("Trading loop is not running")
            return False
        logger.info("Stopping trading loop...")
        self.running = False
        return True

    def _run_loop_thread(self):
        """Run trading loop inside a daemon thread."""
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
                f"Trading Loop Iteration #{iteration} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            logger.info(f"{'=' * 70}")

            try:
                self._settle_expired_positions()
                self._check_stop_losses()
                self._check_executions()
                self._scan_for_opportunities()
                self._print_status()

                logger.info(f"Sleeping for {scan_interval:.1f} seconds...")
                time.sleep(scan_interval)

            except Exception as e:
                logger.error(f"Error in trading loop: {e}", exc_info=True)
                alert_manager.send_error_alert(str(e), f"Error in trading loop iteration #{iteration}")
                time.sleep(scan_interval)

    def _check_executions(self):
        try:
            ready_to_execute = self.execution_timer.check_executions()

            for market_id in ready_to_execute:
                logger.info(f"Executing position for market: {market_id}")

                opportunity = self._find_opportunity_by_market(market_id)
                if not opportunity:
                    logger.warning(f"Opportunity not found for market {market_id}")
                    self.execution_timer.remove_timer(market_id)
                    continue

                if not self.position_tracker.can_open_position():
                    logger.warning("Max positions reached, skipping execution")
                    self.execution_timer.remove_timer(market_id)
                    continue

                position_id = f"{market_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                success = self.executor.execute_buy(opportunity, position_id)

                if success:
                    logger.info(f"Position executed successfully: {position_id}")
                    if self.db:
                        pos = self.position_tracker.get_position(position_id)
                        if pos:
                            self.db.upsert_position(pos)
                        trade = self.pnl_tracker.open_positions.get(position_id)
                        if trade:
                            self.db.upsert_trade(trade)
                else:
                    logger.error(f"Position execution failed: {position_id}")

                self.execution_timer.remove_timer(market_id)

        except Exception as e:
            logger.error(f"Error checking executions: {e}", exc_info=True)

    def _scan_for_opportunities(self):
        try:
            # Simulation refreshes every 5s (new random prices each cycle)
            # Paper mode refreshes every 60s (real API data changes slowly)
            cache_ttl = 5 if config.TRADING_MODE == "simulation" else 60
            if not self.markets_cache or time.time() - self.last_scan_time > cache_ttl:
                self.markets_cache = self.client.get_all_markets(category="crypto")
                self.last_scan_time = time.time()
                logger.debug(f"Refreshed market cache: {len(self.markets_cache)} markets")

            opportunities = self.strategy.scan_for_opportunities(self.markets_cache)

            # Cache by market_id so timer callbacks can look up without rescanning
            self._last_opportunities = {opp.market_id: opp for opp in opportunities}

            if not opportunities:
                logger.debug("No opportunities found in this scan")
                return

            logger.info(f"Found {len(opportunities)} opportunity(ies)")
            best_opportunities = self.strategy.get_best_opportunities(opportunities, limit=5)

            # Capture order book snapshots for each opportunity
            if self.order_book_store is not None:
                self._capture_order_book_snapshots(best_opportunities)

            open_market_ids = {p.market_id for p in self.position_tracker.get_open_positions()}

            for opportunity in best_opportunities:
                if opportunity.market_id in self.execution_timer.active_timers:
                    logger.debug(f"Already tracking market: {opportunity.market_id}")
                    continue

                if opportunity.market_id in open_market_ids:
                    logger.debug(f"Already have open position for: {opportunity.market_id}")
                    continue

                timer_started = self.execution_timer.start_timer(
                    market_id=opportunity.market_id,
                    opportunity=opportunity.to_dict(),
                )

                if timer_started:
                    logger.info(
                        f"Timer started for {opportunity.market_slug} - "
                        f"Executing in {opportunity.time_to_close_seconds - config.EXECUTE_BEFORE_CLOSE_SECONDS:.0f}s"
                    )
                    alert_manager.send_opportunity_detected_alert(
                        market_id=opportunity.market_slug,
                        price=opportunity.current_price,
                        edge=opportunity.edge_percent,
                        time_to_close=opportunity.time_to_close_seconds - config.EXECUTE_BEFORE_CLOSE_SECONDS,
                    )

        except Exception as e:
            logger.error(f"Error scanning for opportunities: {e}", exc_info=True)

    def _capture_order_book_snapshots(self, opportunities: list):
        """Capture top-5 order book snapshots for each opportunity token."""
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
                logger.debug(
                    "Order book snapshot saved: %s (%d bids, %d asks)",
                    token_id[:16],
                    len(snapshot.bids),
                    len(snapshot.asks),
                )
            except Exception as e:
                logger.debug("Snapshot capture failed for %s: %s", opp.market_slug, e)

    def _find_opportunity_by_market(self, market_id: str) -> Optional[ArbitrageOpportunity]:
        return self._last_opportunities.get(market_id)

    def _settle_expired_positions(self):
        """
        Auto-settle positions whose markets have passed their close time.
        Called each loop iteration so positions don't stay open indefinitely.
        """
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)

        # Build a single lookup dict from the cache (O(n) once vs O(n×m) per position)
        market_end_dates: dict = {}
        for m in self.markets_cache:
            end = m.get("endDate")
            if end:
                mid = m.get("id", "")
                slug = m.get("slug", "")
                if mid:
                    market_end_dates[mid] = end
                if slug:
                    market_end_dates[slug] = end

        for pos in self.position_tracker.get_open_positions():
            try:
                # Look up the market's end date from our pre-built dict
                end_date_str = market_end_dates.get(pos.market_id) or market_end_dates.get(pos.market_slug)

                # Fall back to the expiry time stored on the position itself
                # (important for simulation where the market cache regenerates with new end dates)
                if not end_date_str:
                    if pos.expires_at and now >= pos.expires_at:
                        end_date = pos.expires_at
                    else:
                        continue
                else:
                    end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                    if now < end_date:
                        # Also check position-level expiry in case cache end date was refreshed
                        if not (pos.expires_at and now >= pos.expires_at):
                            continue

                # Market has closed — settle YES at $1.00 (strategy only bets near-certain YES)
                logger.info(f"Market closed, settling position: {pos.position_id}")
                pnl = self.executor.settle_position(pos.position_id, settlement_price=1.0)

                if self.db:
                    settled_pos = self.position_tracker.get_position(pos.position_id)
                    if settled_pos:
                        self.db.upsert_position(settled_pos)
                    # Find the closed trade record
                    for trade in self.pnl_tracker.trades:
                        if trade.position_id == pos.position_id and trade.exit_time:
                            self.db.upsert_trade(trade)
                            break

            except Exception as e:
                logger.error(f"Error settling position {pos.position_id}: {e}")

    def _check_stop_losses(self):
        """
        Scan open positions and trigger an early sell if the price has dropped
        more than STOP_LOSS_PERCENT below the entry price.
        Skipped entirely when STOP_LOSS_PERCENT == 0 (disabled).
        """
        if config.STOP_LOSS_PERCENT <= 0:
            return
        for pos in self.position_tracker.get_open_positions():
            try:
                current_price = self.client.get_price(pos.winning_token_id)
                if current_price <= 0:
                    continue
                price_drop_pct = (pos.entry_price - current_price) / pos.entry_price * 100
                if price_drop_pct >= config.STOP_LOSS_PERCENT:
                    logger.warning(
                        f"Stop-loss triggered: {pos.position_id} — "
                        f"entry ${pos.entry_price:.4f}, now ${current_price:.4f} "
                        f"(dropped {price_drop_pct:.1f}% ≥ {config.STOP_LOSS_PERCENT:.1f}% threshold)"
                    )
                    self.executor.execute_sell(pos.position_id, current_price, reason="stop_loss")
                    if self.db:
                        settled = self.position_tracker.get_position(pos.position_id)
                        if settled:
                            self.db.upsert_position(settled)
            except Exception as e:
                logger.error(f"Error checking stop-loss for {pos.position_id}: {e}")

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
        position_summary = self.position_tracker.get_summary()
        logger.info(
            f"\nPositions Summary:\n"
            f"  Open: {position_summary['open_positions']}\n"
            f"  Settled: {position_summary['settled_positions']}\n"
            f"  Wins: {position_summary['wins']}\n"
            f"  Losses: {position_summary['losses']}\n"
            f"  Realized P&L: ${position_summary['realized_pnl']:.2f}"
        )


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Polymarket Trading Bot")
    parser.add_argument(
        "--simulation", action="store_true",
        help="Run in simulation mode (synthetic data, no real API calls)",
    )
    parser.add_argument(
        "--auto-start", action="store_true",
        help="Automatically start the trading loop on launch (skips WebUI trigger)",
    )
    args = parser.parse_args()

    if args.simulation:
        os.environ["TRADING_MODE"] = "simulation"
        # Reload config so the override is picked up
        config.TRADING_MODE = "simulation"

    bot = TradingBot()

    if args.simulation or args.auto_start:
        # Start trading loop in a background thread right after the dashboard
        # comes up, without waiting for a WebUI command.
        import threading as _threading
        def _deferred_start():
            time.sleep(3)   # let dashboard finish initialising
            bot.start_trading_loop()
        _threading.Thread(target=_deferred_start, daemon=True).start()

    bot.start()


if __name__ == "__main__":
    main()
