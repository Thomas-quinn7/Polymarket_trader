# Copyright (C) 2026  Thomas Quinn (github.com/Thomas-quinn7)
#                     Ciaran McDonnell (github.com/CiaranMcDonnell)
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

import argparse
import os
import signal
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from data.polymarket_client import PolymarketClient
from data.database import TradeDatabase
from data.market_provider import MarketProvider
from data.order_book_store import OrderBookStore, OrderBookSnapshot, OrderBookLevel
from data.session_store import SessionStore
from strategies.registry import load_strategy
from strategies.base import BaseStrategy
from portfolio.fake_currency_tracker import FakeCurrencyTracker
from portfolio.position_tracker import PositionTracker
from execution.order_executor import OrderExecutor
from utils.logger import logger
from utils.pnl_tracker import PnLTracker
from utils.alerts import alert_manager
from utils.session_reviewer import SessionReviewer
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

        self.market_provider = MarketProvider(self.client)

        # Session store — records settled trades per strategy run for later review
        self.session_store: Optional[SessionStore] = None
        self._session_id: Optional[str] = None
        _session_db_path = config.DB_PATH  # share the same SQLite file
        self.session_store = SessionStore(
            db_path=_session_db_path,
            sessions_dir=config.SESSIONS_DIR,
        )
        if not self.session_store.connect():
            logger.warning("SessionStore unavailable — session data will not be persisted")
            self.session_store = None

        # Ollama reviewer — generates natural language review at end of each session
        self.session_reviewer: Optional[SessionReviewer] = None
        if config.OLLAMA_ENABLED:
            self.session_reviewer = SessionReviewer(
                host=config.OLLAMA_HOST,
                model=config.OLLAMA_MODEL,
            )

        self.running = False
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
        # Raise SystemExit so the finally block in start() calls stop() exactly once.
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
            port = config.DASHBOARD_PORT
            original_port = port
            while True:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
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
                threading.Thread(target=self._start_dashboard, args=(port,), daemon=True).start()
                # Brief pause to let uvicorn finish binding before the process
                # proceeds; empirically 2 s is enough on all tested platforms.
                _DASHBOARD_STARTUP_WAIT_S = 2
                time.sleep(_DASHBOARD_STARTUP_WAIT_S)

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

        # Close the session, export JSON, then generate the Ollama review (blocking).
        if self.session_store is not None and self._session_id is not None:
            session_data = self.session_store.close_session(
                self._session_id,
                ending_balance=self.currency_tracker.get_balance(),
            )
            if self.session_reviewer is not None and session_data:
                review = self.session_reviewer.generate_review(session_data)
                if review:
                    self.session_store.save_review(
                        self._session_id, review, config.OLLAMA_MODEL
                    )

        if self.session_store is not None:
            self.session_store.close()

        alert_manager.send_system_stop_alert()
        _release_power_policy()
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
        self.market_provider = MarketProvider(self.client)

        # Open a new session record for this run
        if self.session_store is not None:
            self._session_id = self.session_store.create_session(
                strategy_name=config.STRATEGY,
                trading_mode=config.TRADING_MODE,
                starting_balance=self.currency_tracker.get_balance(),
            )

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

        while self.running:
            iteration += 1
            # Re-read scan interval each iteration so hot-reloading config.SCAN_INTERVAL_MS
            # takes effect without a restart.
            scan_interval = config.SCAN_INTERVAL_MS / 1000
            logger.debug(
                f"Loop #{iteration} — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
                f"| strategy={config.STRATEGY} mode={config.TRADING_MODE}"
            )

            # Monotonic deadline: next iteration fires scan_interval seconds after
            # this one *started*, not after it finished — eliminates drift from work time.
            next_tick = time.monotonic() + scan_interval

            try:
                # Fetch open positions once per iteration — shared by exits, stops, and scan.
                open_positions = self.position_tracker.get_open_positions()
                price_cache: dict = {}

                self._check_strategy_exits(open_positions, price_cache)
                self._check_stop_losses(open_positions, price_cache)
                self._scan_and_execute(open_positions)
                self._print_status()

            except Exception as e:
                logger.error(f"Error in trading loop: {e}", exc_info=True)
                alert_manager.send_error_alert(
                    str(e), f"Error in trading loop iteration #{iteration}"
                )

            # Sleep only the remaining time in this interval; never negative.
            remaining = next_tick - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)

    # ── Strategy-driven exit ───────────────────────────────────────────

    def _check_strategy_exits(self, open_positions: list, price_cache: dict):
        """
        Ask the strategy whether any open position should be closed.
        The strategy owns all exit logic — the infrastructure just calls it.

        In live mode, exits go through execute_sell() so a real SELL order is
        submitted to the exchange before the internal books are updated.
        In paper/simulation mode, settle_position() is called directly (no order).

        open_positions: pre-fetched snapshot from run() — avoids a redundant lock acquisition.
        price_cache: dict shared with _check_stop_losses so each token is fetched at most once.
        """
        for pos in open_positions:
            try:
                if pos.winning_token_id not in price_cache:
                    price_cache[pos.winning_token_id] = self.client.get_price(pos.winning_token_id)
                current_price = price_cache[pos.winning_token_id]

                if not self.strategy.should_exit(pos, current_price):
                    continue

                exit_price = self.strategy.get_exit_price(pos, current_price)
                logger.info(f"Strategy exit signal: {pos.position_id} @ ${exit_price:.4f}")

                if not config.PAPER_TRADING_ONLY:
                    # Live mode: submit a real SELL to the exchange first.
                    # execute_sell() falls through to settle_position() internally
                    # once the exchange order is confirmed.
                    self.executor.execute_sell(pos.position_id, exit_price, reason="strategy_exit")
                else:
                    # Paper / simulation: settle directly against the strategy price.
                    self.executor.settle_position(pos.position_id, settlement_price=exit_price)

                settled = self.position_tracker.get_position(pos.position_id)
                if self.db and settled:
                    self.db.upsert_position(settled)
                    for trade in self.pnl_tracker.trades:
                        if trade.position_id == pos.position_id and trade.exit_time:
                            self.db.upsert_trade(trade)
                            break
                if (
                    self.session_store is not None
                    and self._session_id is not None
                    and settled
                    and settled.status == "SETTLED"
                ):
                    # Paper: settled directly (no sell order) → "settlement"
                    # Live: went through execute_sell → "strategy_exit"
                    exit_reason = "settlement" if config.PAPER_TRADING_ONLY else "strategy_exit"
                    self.session_store.record_settled_trade(
                        self._session_id,
                        settled,
                        self.currency_tracker.get_balance(),
                        exit_reason,
                    )

            except Exception as e:
                logger.error(f"Error checking exit for {pos.position_id}: {e}")

    # ── Stop-loss ──────────────────────────────────────────────────────

    def _check_stop_losses(self, open_positions: list, price_cache: dict):
        """
        Generic stop-loss: close a position if its price has dropped
        STOP_LOSS_PERCENT below entry.  Skipped when the setting is 0.

        open_positions: pre-fetched snapshot from run().
        price_cache: prices already fetched by _check_strategy_exits are reused here.
        """
        if config.STOP_LOSS_PERCENT <= 0:
            return
        for pos in open_positions:
            try:
                if pos.winning_token_id not in price_cache:
                    price_cache[pos.winning_token_id] = self.client.get_price(pos.winning_token_id)
                current_price = price_cache[pos.winning_token_id]
                if current_price <= 0:
                    continue
                drop_pct = (pos.entry_price - current_price) / pos.entry_price * 100
                if drop_pct >= config.STOP_LOSS_PERCENT:
                    logger.warning(
                        f"Stop-loss triggered: {pos.position_id} — "
                        f"entry ${pos.entry_price:.4f}, now ${current_price:.4f} "
                        f"(dropped {drop_pct:.1f}%)"
                    )
                    self.executor.execute_sell(pos.position_id, current_price, reason="stop_loss")
                    settled = self.position_tracker.get_position(pos.position_id)
                    if self.db and settled:
                        self.db.upsert_position(settled)
                    if (
                        self.session_store is not None
                        and self._session_id is not None
                        and settled
                        and settled.status == "SETTLED"
                    ):
                        self.session_store.record_settled_trade(
                            self._session_id,
                            settled,
                            self.currency_tracker.get_balance(),
                            "stop_loss",
                        )
            except Exception as e:
                logger.error(f"Error checking stop-loss for {pos.position_id}: {e}")

    # ── Market scan + immediate execution ─────────────────────────────

    def _scan_and_execute(self, open_positions: list):
        """
        Refresh market cache via the multi-category scanner, run the strategy's
        opportunity scan, then immediately execute the best ones that are not
        already in the portfolio.

        open_positions: pre-fetched snapshot from run() — avoids a third lock acquisition.
        """
        try:
            criteria = self.strategy.get_market_criteria()
            markets = self.market_provider.get_markets(criteria)
            opportunities = self.strategy.scan_for_opportunities(markets)

            if not opportunities:
                logger.debug("No opportunities found in this scan")
                return

            logger.info(f"Found {len(opportunities)} opportunity(ies)")
            best = self.strategy.get_best_opportunities(opportunities, limit=5)

            if self.order_book_store is not None:
                self._capture_order_book_snapshots(best)

            # Build set from the already-fetched snapshot — no extra lock acquisition.
            open_market_ids = {p.market_id for p in open_positions}

            for opp in best:
                if opp.market_id in open_market_ids:
                    logger.debug(f"Already have open position for: {opp.market_id}")
                    continue

                if not self.position_tracker.can_open_position():
                    logger.info("Max positions reached — skipping remaining opportunities")
                    break

                position_id = f"{opp.market_id}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
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
        now = datetime.now(timezone.utc)
        for opp in opportunities:
            try:
                token_id = opp.winning_token_id
                book = self.client.get_order_book(token_id, levels=5)
                snapshot = OrderBookSnapshot(
                    token_id=token_id,
                    captured_at=now,
                    bids=[
                        OrderBookLevel(lvl["price"], lvl["size"]) for lvl in book.get("bids", [])
                    ],
                    asks=[
                        OrderBookLevel(lvl["price"], lvl["size"]) for lvl in book.get("asks", [])
                    ],
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


def _apply_power_policy() -> None:
    """
    Block Windows idle sleep while the bot runs (PREVENT_SLEEP=true in .env).

    Uses SetThreadExecutionState to hold ES_SYSTEM_REQUIRED and
    ES_AWAYMODE_REQUIRED so the system won't sleep due to inactivity.

    Note: this prevents *idle* sleep only. To keep the bot running when
    the laptop lid is closed you must also change Windows power settings:
        Settings → System → Power & sleep → Additional power settings
        → Choose what closing the lid does → "Do nothing" (on battery + plugged in)
    """
    if not config.PREVENT_SLEEP:
        return

    if sys.platform != "win32":
        logger.warning("PREVENT_SLEEP is only supported on Windows — ignoring")
        return

    import ctypes

    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001
    ES_AWAYMODE_REQUIRED = 0x00000040  # prevents deep sleep in away / lid-closed mode

    result = ctypes.windll.kernel32.SetThreadExecutionState(
        ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED
    )
    if result:
        logger.info(
            "Power policy: idle sleep blocked (PREVENT_SLEEP=True). "
            "For lid-close support set 'When I close the lid' → 'Do nothing' "
            "in Windows power settings."
        )
    else:
        logger.warning("Power policy: SetThreadExecutionState failed — sleep not blocked")


def _release_power_policy() -> None:
    """Restore normal Windows sleep behaviour on shutdown."""
    if sys.platform != "win32" or not config.PREVENT_SLEEP:
        return
    import ctypes

    ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)  # ES_CONTINUOUS only
    logger.info("Power policy: sleep restrictions released")


_BANNER = (
    "\033[96m"
    "╔══════════════════════════════════════════════════════════════════════╗\n"
    "║      Polymarket Trading Framework  ·  pmf-7e3f-tq343                 ║\n"
    "║                                                                      ║\n"
    "║  Authors : Thomas Quinn  (github.com/Thomas-quinn7)                  ║\n"
    "║            Ciaran McDonnell  (github.com/CiaranMcDonnell)           ║\n"
    "║                                                                      ║\n"
    "║  Repo    : github.com/Thomas-quinn7/Polymarket_trader                ║\n"
    "║  License : GNU Affero General Public License v3  (AGPL-3.0-only)     ║\n"
    "╚══════════════════════════════════════════════════════════════════════╝"
    "\033[0m"
)


def _confirm_live_trading(parser: argparse.ArgumentParser) -> None:
    """
    Apply live-trading config and prompt the user for explicit confirmation.

    Exits via parser.error() (non-zero) if:
      - POLYMARKET_PRIVATE_KEY is not set
      - The user does not type the confirmation phrase

    On success, mutates config in-place so the rest of main() proceeds in live mode.
    """
    # Guard: private key must be present before we commit to live mode
    if not config.POLYMARKET_PRIVATE_KEY:
        parser.error(
            "--live requires POLYMARKET_PRIVATE_KEY to be set in .env "
            "(or via --config). Refusing to start live trading without credentials."
        )

    funder = config.POLYMARKET_FUNDER_ADDRESS or "(not set)"
    auth_mode = config.builder_tier_label

    print("\n" + "=" * 70)
    print("  ⚠️   LIVE TRADING MODE — REAL MONEY AT RISK   ⚠️")
    print("=" * 70)
    print(f"  Funder address : {funder}")
    print(f"  Auth mode      : {auth_mode}")
    print(f"  Strategy       : {config.STRATEGY}")
    print(f"  Max positions  : {config.MAX_POSITIONS}")
    print(f"  Capital / pos  : {config.CAPITAL_SPLIT_PERCENT * 100:.0f}%")
    print(f"  Taker fee      : {config.TAKER_FEE_PERCENT:.1f}%")
    print(f"  Slippage limit : {config.SLIPPAGE_TOLERANCE_PERCENT:.1f}%")
    print("=" * 70)
    print("  Real orders WILL be submitted to Polymarket.")
    print("  Losses are possible. Only proceed if you understand the risks.")
    print("=" * 70)

    try:
        answer = input("\n  Type  CONFIRM  to proceed, or press Enter to abort: ").strip()
    except (EOFError, KeyboardInterrupt):
        answer = ""

    if answer != "CONFIRM":
        print("Aborted — live trading not started.")
        raise SystemExit(0)

    # Apply live-mode config after confirmation
    config.TRADING_MODE = "live"
    config.PAPER_TRADING_ONLY = False
    print()


def main():
    print(_BANNER)
    _apply_power_policy()

    parser = argparse.ArgumentParser(
        description="Polymarket Trading Bot",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # ── Environment / config file ──────────────────────────────────────
    parser.add_argument(
        "--config",
        metavar="PATH",
        help=(
            "Path to a .env file to load instead of the default .env "
            "(useful for running multiple accounts or environments). "
            "CLI args still take priority over values in this file."
        ),
    )

    # ── Trading mode ───────────────────────────────────────────────────
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--paper",
        action="store_true",
        help="Paper trading: real prices, simulated execution (no real money)",
    )
    mode_group.add_argument(
        "--simulation",
        action="store_true",
        help="Simulation mode: fully offline, synthetic data, no API calls",
    )
    mode_group.add_argument(
        "--live",
        action="store_true",
        help=(
            "LIVE trading: real prices, REAL orders submitted to Polymarket. "
            "Requires POLYMARKET_PRIVATE_KEY to be set. "
            "An interactive confirmation prompt is shown before the bot starts."
        ),
    )

    # ── Loop control ───────────────────────────────────────────────────
    parser.add_argument(
        "--auto-start",
        action="store_true",
        help="Automatically start the trading loop on launch without waiting for the WebUI",
    )
    parser.add_argument(
        "--strategy",
        metavar="NAME",
        help="Strategy to load (e.g. settlement_arbitrage). Overrides STRATEGY in .env",
    )
    parser.add_argument(
        "--scan-interval",
        type=int,
        metavar="MS",
        help="Scan interval in milliseconds. Overrides SCAN_INTERVAL_MS in .env",
    )
    parser.add_argument(
        "--categories",
        metavar="LIST",
        help=(
            "Comma-separated list of market categories to scan "
            "(e.g. crypto,fed). Overrides SCAN_CATEGORIES in .env"
        ),
    )

    # ── Risk / execution ───────────────────────────────────────────────
    parser.add_argument(
        "--max-positions",
        type=int,
        metavar="N",
        help="Maximum number of concurrent open positions. Overrides MAX_POSITIONS in .env",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        metavar="0.0-1.0",
        help=(
            "Minimum confidence score for a trade opportunity to be acted on (0.0–1.0). "
            "Overrides MIN_CONFIDENCE in .env"
        ),
    )
    parser.add_argument(
        "--stop-loss",
        type=float,
        metavar="PCT",
        help=(
            "Stop-loss threshold as a percentage drop from entry price (e.g. 5.0 = 5%%). "
            "Set 0 to disable. Overrides STOP_LOSS_PERCENT in .env"
        ),
    )

    # ── Capital ────────────────────────────────────────────────────────
    parser.add_argument(
        "--balance",
        type=float,
        metavar="USD",
        help="Starting paper-trading balance in USD. Overrides FAKE_CURRENCY_BALANCE in .env",
    )

    # ── Dashboard ──────────────────────────────────────────────────────
    parser.add_argument(
        "--no-dashboard",
        action="store_true",
        help="Disable the web dashboard (useful for headless / server runs)",
    )
    parser.add_argument(
        "--port",
        type=int,
        metavar="PORT",
        help="Dashboard port. Overrides DASHBOARD_PORT in .env",
    )

    # ── Logging ────────────────────────────────────────────────────────
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        metavar="LEVEL",
        help="Log verbosity (DEBUG|INFO|WARNING|ERROR|CRITICAL). Overrides LOG_LEVEL in .env",
    )

    args = parser.parse_args()

    # ── 1. Load alternative .env if --config was given ─────────────────
    # This runs before all other overrides so CLI args still win.
    if args.config:
        if not os.path.isfile(args.config):
            parser.error(f"--config: file not found: {args.config}")
        from dotenv import load_dotenv as _load_dotenv

        _load_dotenv(dotenv_path=args.config, override=True)
        config.reload()
        logger.info("Loaded config from: %s", args.config)

    # ── 2. Apply CLI overrides on top (highest priority) ───────────────
    if args.simulation:
        config.TRADING_MODE = "simulation"
        config.PAPER_TRADING_ONLY = True
    elif args.paper:
        config.TRADING_MODE = "paper"
        config.PAPER_TRADING_ONLY = True
    elif args.live:
        _confirm_live_trading(parser)

    if args.strategy:
        config.STRATEGY = args.strategy

    if args.scan_interval is not None:
        config.SCAN_INTERVAL_MS = args.scan_interval

    if args.categories:
        config.SCAN_CATEGORIES = [c.strip() for c in args.categories.split(",") if c.strip()]

    if args.max_positions is not None:
        config.MAX_POSITIONS = args.max_positions

    if args.min_confidence is not None:
        if not 0.0 <= args.min_confidence <= 1.0:
            parser.error("--min-confidence must be between 0.0 and 1.0")
        config.MIN_CONFIDENCE = args.min_confidence

    if args.stop_loss is not None:
        if args.stop_loss < 0:
            parser.error("--stop-loss must be 0 or greater")
        config.STOP_LOSS_PERCENT = args.stop_loss

    if args.balance is not None:
        config.FAKE_CURRENCY_BALANCE = args.balance

    if args.no_dashboard:
        config.DASHBOARD_ENABLED = False

    if args.port is not None:
        config.DASHBOARD_PORT = args.port

    if args.log_level:
        config.LOG_LEVEL = args.log_level
        # Re-configure already-created loggers so the override takes effect
        import logging as _logging

        for name in ("polymarket_trading", "trades"):
            _logging.getLogger(name).setLevel(getattr(_logging, args.log_level, _logging.INFO))

    bot = TradingBot()

    if args.simulation or args.paper or args.live or args.auto_start:

        def _deferred_start():
            # Wait for the dashboard to become ready before kicking off the loop
            # so the first status push lands on an already-listening server.
            _AUTO_START_DELAY_S = 3
            time.sleep(_AUTO_START_DELAY_S)
            bot.start_trading_loop()

        threading.Thread(target=_deferred_start, daemon=True).start()

    bot.start()


if __name__ == "__main__":
    main()
