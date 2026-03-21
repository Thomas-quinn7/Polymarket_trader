"""
Main Polymarket Arbitrage Bot
Orchestrates all components and runs the trading loop
"""

import time
import signal
import sys
import threading
from datetime import datetime, timedelta
from typing import Optional

from data.polymarket_client import PolymarketClient
from data.polymarket_models import ArbitrageOpportunity
from strategies.settlement_arbitrage import SettlementArbitrage
from portfolio.fake_currency_tracker import FakeCurrencyTracker
from portfolio.position_tracker import PositionTracker
from execution.order_executor import OrderExecutor
from utils.execution_timer import ExecutionTimer
from utils.logger import logger
from utils.pnl_tracker import PnLTracker
from utils.alerts import alert_manager
from config.polymarket_config import config

# Import dashboard module (conditionally loaded when DASHBOARD_ENABLED is True)
import dashboard.api


class TradingBot:
    """Main trading bot orchestrator"""

    def __init__(self):
        """Initialize the trading bot"""
        logger.info("=" * 70)
        logger.info("Initializing Polymarket Arbitrage Bot")
        logger.info("=" * 70)

        # Initialize Polymarket client
        self.client = PolymarketClient()

        # Initialize strategy
        self.strategy = SettlementArbitrage(self.client)

        # Initialize trackers
        self.currency_tracker = FakeCurrencyTracker()
        self.pnl_tracker = PnLTracker(initial_balance=self.currency_tracker.starting_balance)
        self.position_tracker = PositionTracker(self.pnl_tracker)

        # Initialize executor
        self.executor = OrderExecutor(
            pnl_tracker=self.pnl_tracker,
            position_tracker=self.position_tracker,
            currency_tracker=self.currency_tracker,
        )

        # Initialize execution timer
        self.execution_timer = ExecutionTimer()

        # Trading state
        self.running = False
        self.markets_cache = []
        self.last_scan_time = 0
        self.active_timers = {}

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info(f"Trading Mode: Paper Trading")
        logger.info(f"Strategy: 98.5 Cent Settlement Arbitrage")
        logger.info(f"Execution Timing: {config.EXECUTE_BEFORE_CLOSE_SECONDS} seconds before close")
        logger.info(f"Max Positions: {config.MAX_POSITIONS}")
        logger.info(f"Initial Balance: ${self.currency_tracker.starting_balance:.2f}")
        logger.info("=" * 70)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        logger.info("\nShutdown signal received")
        self.stop()

    def _start_dashboard(self):
        """Start the dashboard in a separate thread"""
        import uvicorn
        
        logger.info(f"Starting dashboard server on {config.DASHBOARD_HOST}:{config.DASHBOARD_PORT}")
        
        # Set bot instance for dashboard API
        if config.DASHBOARD_ENABLED:
            global dashboard_bot_instance
            dashboard_bot_instance = self
        
        # Create uvicorn config
        uvicorn_config = uvicorn.Config(
            app="dashboard.api:app",
            host=config.DASHBOARD_HOST,
            port=config.DASHBOARD_PORT,
            log_level="warning",
        )
        
        # Create and run server
        server = uvicorn.Server(uvicorn_config)
        server.run()

    def start(self):
        """Start the trading bot"""
        logger.info("Starting Trading Bot...")
        self.running = True
        logger.info("Trading Bot started successfully")

        # Start dashboard in background thread if enabled
        if config.DASHBOARD_ENABLED:
            logger.info(f"Dashboard will be available at http://localhost:{config.DASHBOARD_PORT}")
            # Set bot instance for dashboard API before starting dashboard
            dashboard.api.bot_instance = self
            dashboard_thread = threading.Thread(target=self._start_dashboard, daemon=True)
            dashboard_thread.start()
            # Give dashboard time to start
            time.sleep(2)

        # Send system start alert
        alert_manager.send_system_start_alert()

        # Run the main trading loop
        try:
            self.run()
        except KeyboardInterrupt:
            logger.info("\nBot stopped by user")
        except Exception as e:
            logger.critical(f"Fatal error in trading bot: {e}", exc_info=True)
            alert_manager.send_error_alert(str(e), "Fatal error in trading bot")
        finally:
            self.stop()

    def stop(self):
        """Stop the trading bot"""
        if not self.running:
            return

        logger.info("Stopping Trading Bot...")
        self.running = False

        # Print final report
        self._print_final_report()

        # Send system stop alert
        alert_manager.send_system_stop_alert()

        logger.info("Trading Bot stopped")

    def run(self):
        """Main trading loop"""
        iteration = 0
        scan_interval = config.SCAN_INTERVAL_MS / 1000  # Convert to seconds

        while self.running:
            iteration += 1
            logger.info(f"\n{'=' * 70}")
            logger.info(
                f"Trading Loop Iteration #{iteration} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            logger.info(f"{'=' * 70}")

            try:
                # Check for executions that should happen now
                self._check_executions()

                # Scan for opportunities
                self._scan_for_opportunities()

                # Print status
                self._print_status()

                # Sleep between scans
                logger.info(f"Sleeping for {scan_interval:.1f} seconds...")
                time.sleep(scan_interval)

            except Exception as e:
                logger.error(f"Error in trading loop: {e}", exc_info=True)
                # Alert and continue
                alert_manager.send_error_alert(str(e), f"Error in trading loop iteration #{iteration}")
                time.sleep(scan_interval)

    def _check_executions(self):
        """Check and execute timed positions"""
        try:
            ready_to_execute = self.execution_timer.check_executions()

            for market_id in ready_to_execute:
                logger.info(f"🎯 Executing position for market: {market_id}")

                # Find opportunity for this market
                opportunity = self._find_opportunity_by_market(market_id)
                if not opportunity:
                    logger.warning(f"Opportunity not found for market {market_id}")
                    self.execution_timer.remove_timer(market_id)
                    continue

                # Check if we can open a new position
                if not self.position_tracker.can_open_position():
                    logger.warning("Max positions reached, skipping execution")
                    self.execution_timer.remove_timer(market_id)
                    continue

                # Generate position ID
                position_id = f"{market_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

                # Execute buy
                success = self.executor.execute_buy(opportunity, position_id)

                if success:
                    logger.info(f"✅ Position executed successfully: {position_id}")
                else:
                    logger.error(f"❌ Position execution failed: {position_id}")

                # Remove timer
                self.execution_timer.remove_timer(market_id)

        except Exception as e:
            logger.error(f"Error checking executions: {e}", exc_info=True)

    def _scan_for_opportunities(self):
        """Scan for arbitrage opportunities"""
        try:
            # Get markets (cache for performance)
            if not self.markets_cache or time.time() - self.last_scan_time > 60:  # Refresh every minute
                self.markets_cache = self.client.get_all_markets(category="crypto")
                self.last_scan_time = time.time()
                logger.debug(f"Refreshed market cache: {len(self.markets_cache)} markets")

            # Scan for opportunities
            opportunities = self.strategy.scan_for_opportunities(self.markets_cache)

            if not opportunities:
                logger.debug("No opportunities found in this scan")
                return

            logger.info(f"🎯 Found {len(opportunities)} opportunity(ies)")

            # Get best opportunities (max 5)
            best_opportunities = self.strategy.get_best_opportunities(opportunities, limit=5)

            # Set up timers for best opportunities
            for opportunity in best_opportunities:
                # Check if already tracking this market
                if opportunity.market_id in self.execution_timer.active_timers:
                    logger.debug(f"Already tracking market: {opportunity.market_id}")
                    continue

                # Start timer
                timer_started = self.execution_timer.start_timer(
                    market_id=opportunity.market_id,
                    opportunity=opportunity.to_dict(),
                )

                if timer_started:
                    logger.info(
                        f"⏱️ Timer started for {opportunity.market_slug} - "
                        f"Executing in {opportunity.time_to_close_seconds - config.EXECUTE_BEFORE_CLOSE_SECONDS:.0f}s"
                    )

                    # Send alert
                    alert_manager.send_opportunity_detected_alert(
                        market_id=opportunity.market_slug,
                        price=opportunity.current_price,
                        edge=opportunity.edge_percent,
                        time_to_close=opportunity.time_to_close_seconds - config.EXECUTE_BEFORE_CLOSE_SECONDS,
                    )

        except Exception as e:
            logger.error(f"Error scanning for opportunities: {e}", exc_info=True)

    def _find_opportunity_by_market(self, market_id: str) -> Optional[ArbitrageOpportunity]:
        """Find cached opportunity by market ID"""
        opportunities = self.strategy.scan_for_opportunities(self.markets_cache)

        for opp in opportunities:
            if opp.market_id == market_id:
                return opp

        return None

    def _print_status(self):
        """Print current status"""
        # Portfolio status
        balance = self.currency_tracker.get_balance()
        deployed = self.currency_tracker.get_deployed()
        position_count = self.position_tracker.get_position_count()

        # PnL status
        pnl_summary = self.pnl_tracker.get_summary()

        logger.info(f"\nBalance: ${balance:.2f} | Deployed: ${deployed:.2f}")
        logger.info(f"Open Positions: {position_count}/{config.MAX_POSITIONS}")
        logger.info(f"Total P&L: ${pnl_summary.total_pnl:.2f}")
        logger.info(f"Win Rate: {pnl_summary.win_rate:.1f}%")

    def _print_final_report(self):
        """Print final report"""
        logger.info("\n" + "=" * 70)
        logger.info("FINAL REPORT")
        logger.info("=" * 70)

        # Print PnL report
        print(self.pnl_tracker.get_report())

        # Print position summary
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
    """Main entry point"""
    bot = TradingBot()
    bot.start()


if __name__ == "__main__":
    main()
