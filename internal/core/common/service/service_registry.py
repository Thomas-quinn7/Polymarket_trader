"""
Service Registry - Dependency injection container.
Wires up all services and provides them to the application.
"""

from dataclasses import dataclass
from typing import Optional

from pkg.config import get_settings
from pkg.logger import get_logger

from internal.core.execution.domain import OrderExecutorProtocol
from internal.core.execution.service import PaperTradingExecutor, ExecutorService
from internal.core.notifications.domain import NotificationChannel
from internal.core.notifications.service import DiscordChannel, EmailChannel, NotificationService
from internal.core.portfolio.domain import PortfolioRepositoryProtocol
from internal.core.portfolio.service import InMemoryRepository, PortfolioService
from internal.core.scanner.domain import MarketClientProtocol
from internal.core.scanner.infrastructure import PolymarketClient, ScannerService


@dataclass
class Services:
    """
    Container for all application services.
    Provides clean dependency injection throughout the application.
    """

    scanner: ScannerService
    executor: ExecutorService
    portfolio: PortfolioService
    notifications: NotificationService
    market_client: MarketClientProtocol


def create_services(settings: Optional[object] = None) -> Services:
    """
    Create and wire up all application services.

    Args:
        settings: Settings object (optional, loads from config if not provided)

    Returns:
        Services container with all configured services

    Example:
        ```python
        services = create_services()
        opportunities = await services.scanner.scan()
        await services.executor.execute_order(...)
        positions = await services.portfolio.get_all_positions()
        ```
    """
    # Load settings if not provided
    if settings is None:
        settings = get_settings()

    logger = get_logger(__name__)

    # Create market client (real or mock based on settings)
    try:
        market_client = PolymarketClient(settings)
        logger.info("market_client_created", type="polymarket_client")
    except Exception as e:
        logger.warning("market_client_fallback", error=str(e), message="Using mock client")
        market_client = MockMarketClient()  # Fallback to mock

    # Create scanner service
    scanner = ScannerService(
        market_client=market_client,
        settings=settings,
    )
    logger.info("scanner_service_created")

    # Create notification channels
    notification_channels: list[NotificationChannel] = []

    # Discord notification (if configured)
    if settings.enable_discord_alerts and settings.discord_webhook_url:
        try:
            discord_channel = DiscordChannel(
                webhook_url=settings.discord_webhook_url,
                mention_user_id=settings.discord_mention_user_id,
            )
            notification_channels.append(discord_channel)
            logger.info("discord_channel_created")
        except Exception as e:
            logger.error("discord_channel_creation_failed", error=str(e))

    # Email notification (if configured)
    if settings.enable_email_alerts and settings.smtp_server:
        try:
            email_channel = EmailChannel(
                smtp_server=settings.smtp_server,
                smtp_port=settings.smtp_port,
                username=settings.smtp_username,
                password=settings.smtp_password,
                from_email=settings.alert_email_from,
                to_email=settings.alert_email_to,
            )
            notification_channels.append(email_channel)
            logger.info("email_channel_created")
        except Exception as e:
            logger.error("email_channel_creation_failed", error=str(e))

    # Create notification service
    notifications = NotificationService(channels=notification_channels, cooldown_seconds=300)
    logger.info("notification_service_created", channels_count=len(notification_channels))

    # Create portfolio repository
    portfolio_repository = InMemoryRepository(
        initial_balance=settings.fake_currency_balance,
    )
    logger.info("portfolio_repository_created", initial_balance=settings.fake_currency_balance)

    # Create portfolio service
    portfolio = PortfolioService(
        repository=portfolio_repository,
        settings=settings,
        notifications=notifications,
    )
    logger.info("portfolio_service_created")

    # Create executor service
    executor = ExecutorService(
        executor=PaperTradingExecutor(),
        settings=settings,
        notifications=notifications,
    )
    logger.info("executor_service_created")

    # Return all services
    services = Services(
        scanner=scanner,
        executor=executor,
        portfolio=portfolio,
        notifications=notifications,
        market_client=market_client,
    )

    logger.info("all_services_created")

    return services


# Mock market client for fallback
class MockMarketClient(MarketClientProtocol):
    """Mock market client for testing or when API is unavailable."""

    def __init__(self):
        """Initialize mock client."""
        self._markets = []

    def set_markets(self, markets: list) -> None:
        """Set mock markets."""
        self._markets = markets

    async def get_markets(
        self,
        category: Optional[str] = None,
        keywords: Optional[list] = None,
        exclude_keywords: Optional[list] = None,
        exclude_slugs: Optional[list] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        min_time_to_close: Optional[int] = None,
        max_time_to_close: Optional[int] = None,
    ) -> list:
        """Return mock markets."""
        logger = get_logger(__name__)
        logger.info("mock_markets_fetched", count=len(self._markets))
        return self._markets

    async def get_market_by_id(self, market_id: str) -> Optional[dict]:
        """Return mock market."""
        return next((m for m in self._markets if m.get("id") == market_id), None)

    async def get_current_prices(self, market_ids: list) -> dict:
        """Return mock prices."""
        return {}


# Import for Protocol type hint
from typing import Protocol
