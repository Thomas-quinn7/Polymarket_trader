"""
Bot Orchestration - Main entry point with service injection.
Wires up all services and runs the trading bot loop.
"""

import asyncio
import signal
from datetime import datetime
from typing import Optional

from pkg.config import get_settings
from pkg.logger import configure_logger, get_logger

from internal.core.common.service.service_registry import create_services
from internal.core.notifications.domain import Alert, AlertSeverity, AlertType
from internal.core.scanner.domain import MarketOpportunity


class TradingBot:
    """
    Main trading bot orchestrator with service injection.
    """

    def __init__(self, services: dict):
        """
        Initialize trading bot.

        Args:
            services: Services container from create_services()
        """
        self.services = services
        self.settings = get_settings()

        self._running = False
        self._shutdown_event = asyncio.Event()

        logger = get_logger(__name__)
        logger.info("trading_bot_initialized", features={
            "scanner": "enabled",
            "executor": "enabled",
            "portfolio": "enabled",
            "notifications": "enabled",
            "paper_trading_only": self.settings.paper_trading_only,
        })

        # Safety mode alert
        if self.settings.paper_trading_only:
            self._send_safety_mode_alert()

    async def start(self) -> None:
        """
        Start the trading bot loop.
        """
        logger = get_logger(__name__)
        logger.info("starting_trading_bot", settings=self.settings.dict())

        # Create signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._shutdown_event.set)

        self._running = True

        try:
            logger.info("bot_started", message="Trading bot running in main loop")
            await self._main_loop()

        except Exception as e:
            logger = get_logger(__name__)
            logger.error("bot_crashed", error=str(e), exc_info=True)

            # Send error notification
            await self._send_error_alert(str(e))

        finally:
            await self.stop()
            logger.info("bot_stopped")

    async def stop(self) -> None:
        """
        Stop the trading bot gracefully.
        """
        if not self._running:
            return

        logger = get_logger(__name__)
        logger.info("shutting_down")

        self._running = False
        self._shutdown_event.set()

        # Send shutdown notification
        await self._send_shutdown_notification()

    async def _main_loop(self) -> None:
        """
        Main trading bot loop.
        Continuously scans for opportunities and executes trades.
        """
        logger = get_logger(__name__)

        while self._running:
            try:
                await self._scan_and_execute()

            except Exception as e:
                logger.error("error_in_main_loop", error=str(e), exc_info=True)

                # Send error notification and continue
                await self._send_error_alert(f"Main loop error: {str(e)}")

            # Wait for next scan interval
            try:
                await asyncio.sleep(self.settings.scan_interval_ms / 1000)
            except asyncio.CancelledError:
                break

    async def _scan_and_execute(self) -> None:
        """
        Scan for opportunities and execute trades.
        """
        logger = get_logger(__name__)

        # Get current time
        scan_time = datetime.utcnow()

        # Scan for opportunities
        logger.info("starting_market_scan")
        opportunities = await self.services["scanner"].scan(
            min_price_threshold=self.settings.min_price_threshold,
            max_price_threshold=self.settings.max_price_threshold,
            execute_before_close_seconds=self.settings.execute_before_close_seconds,
        )

        logger.info("scan_complete", opportunities_found=opportunities.total_opportunities)

        # Execute trades for each opportunity
        for opportunity in opportunities.opportunities:
            try:
                await self._execute_opportunity(opportunity)

            except Exception as e:
                logger.error("opportunity_execution_failed", market_id=opportunity.market_id, error=str(e))
                # Continue with next opportunity instead of stopping

    async def _execute_opportunity(self, opportunity: object) -> None:
        """
        Execute a single opportunity.
        """
        logger = get_logger(__name__)

        logger.info(
            "opportunity_found",
            market_id=opportunity.market_id,
            price=opportunity.price,
            time_to_close=opportunity.time_to_close,
        )

        # Calculate position size based on capital allocation
        capital_per_position = self.settings.fake_currency_balance * self.settings.capital_split_percent

        # Determine quantity (simplified - assumes position size equals price for simplicity)
            quantity = capital_per_position / opportunity.price

        # Execute order (buy YES token)
        try:
            result = await self.services["executor"].execute_order(
                market_id=opportunity.market_id,
                outcome="YES",
                side="BUY",
                quantity=quantity,
                price=opportunity.price,
                order_type="FOK",
                metadata={
                    "scan_time": opportunity.timestamp.isoformat(),
                    "entry_price": opportunity.price,
                },
            )

            if result.is_success:
                logger.info(
                    "order_filled",
                    order_id=result.order_id,
                    market_id=opportunity.market_id,
                    quantity=result.filled_amount,
                    price=result.price,
                )

                 # Open position in portfolio
                 position_id = f"{result.order_id}_position"
                 await self.services["portfolio"].open_position(
                     position_id=position_id,
                     market_id=opportunity.market_id,
                     outcome="YES",
                     side="BUY",
                     quantity=quantity,
                     entry_price=opportunity.price,
                     current_price=opportunity.price,
                 )

                 logger.info(
                     "position_opened",
                     position_id=position_id,
                     market_id=opportunity.market_id,
                     quantity=quantity,
                 )

            else:
                logger.warning("order_failed", order_id=result.order_id, reason="Execution failed")

        except Exception as e:
            logger.error("order_execution_exception", market_id=opportunity.market_id, error=str(e))
            raise

    def _send_safety_mode_alert(self) -> None:
        """Send safety mode notification."""
        logger = get_logger(__name__)
        logger.warning("safety_mode_active", message="⚠️ PAPER TRADING ONLY - NO REAL MONEY TRADES ⚠️")
        logger.warning("safety_mode_active", message="Ensure PAPER_TRADING_ONLY=True in configuration")

    async def _send_shutdown_notification(self) -> None:
        """Send shutdown notification."""
        if not self.services["notifications"]:
            return

        alert = Alert(
            type=AlertType.SYSTEM_STOP,
            severity=AlertSeverity.INFO,
            title="Bot Stopped",
            message="Trading bot has been stopped",
        )

        await self.services["notifications"].notify(alert)

    async def _send_error_alert(self, error_message: str) -> None:
        """Send error notification."""
        if not self.services["notifications"]:
            return

        alert = Alert(
            type=AlertType.SYSTEM_ERROR,
            severity=AlertSeverity.ERROR,
            title="Bot Error",
            message=f"Error occurred: {error_message}",
        )

        await self.services["notifications"].notify(alert)

    async def get_status(self) -> dict:
        """
        Get bot status.

        Returns:
            Dictionary with current status
        """
        scanner_stats = self.services["scanner"].get_scan_statistics()
        portfolio_stats = self.services["portfolio"].get_trading_statistics()
        executor_stats = self.services["executor"].get_execution_statistics()

        return {
            "running": self._running,
            "paper_trading_only": self.settings.paper_trading_only,
            "scan_statistics": scanner_stats,
            "portfolio_statistics": portfolio_stats,
            "executor_statistics": executor_stats,
            "active_positions": len(await self.services["portfolio"].get_all_positions()),
            "balance": await self.services["portfolio"].get_balance(),
        }


async def main() -> None:
    """
    Main entry point for the trading bot.
    """
    # Configure logging
    configure_logger(
        level="INFO",
        log_to_file=True,
        log_file="logs/app.log",
    )

    # Create services container
    services = create_services()

    # Create and start bot
    bot = TradingBot(services=services)

    # Start bot in background
    bot_task = asyncio.create_task(bot.start())

    # Run until signal received
    try:
        await bot_task
    except KeyboardInterrupt:
        await bot.stop()


if __name__ == "__main__":
    import sys

    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()

    # Run main
    asyncio.run(main())
