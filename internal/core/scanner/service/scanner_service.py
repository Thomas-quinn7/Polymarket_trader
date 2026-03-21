"""
Scanner Service - Main business logic for market scanning.
Implements the 98.5 cent settlement arbitrage strategy.
"""

import asyncio
from datetime import datetime
from typing import List, Optional

from pkg.config import get_settings
from pkg.logger import get_logger

from internal.core.notifications.domain import Alert, AlertSeverity, AlertType
from internal.core.scanner.domain import (
    MarketClientProtocol,
    MarketOpportunity,
    NoOpportunityError,
    ScanResult,
)


class ScannerService:
    """
    Service for scanning markets and finding settlement arbitrage opportunities.
    """

    def __init__(self, market_client: MarketClientProtocol, settings: Optional[object] = None):
        """
        Initialize scanner service.

        Args:
            market_client: Market data client implementation
            settings: Settings object (optional, will load from config if not provided)
        """
        self.market_client = market_client

        # Load settings if not provided
        if settings is None:
            settings = get_settings()

        self.settings = settings

        self._last_scan_time: datetime = None
        self._scan_count: int = 0
        self._total_opportunities_found: int = 0

    async def scan(
        self,
        category: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        exclude_keywords: Optional[List[str]] = None,
        exclude_slugs: Optional[List[str]] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        min_time_to_close: Optional[int] = None,
        max_time_to_close: Optional[int] = None,
        min_edge: Optional[float] = None,
    ) -> ScanResult:
        """
        Scan markets for arbitrage opportunities.

        Args:
            category: Market category filter
            keywords: Keyword filters to include
            exclude_keywords: Keywords to exclude
            exclude_slugs: Market slugs to exclude
            min_price: Minimum price filter
            max_price: Maximum price filter
            min_time_to_close: Minimum time to close (seconds)
            max_time_to_close: Maximum time to close (seconds)
            min_edge: Minimum edge percentage

        Returns:
            ScanResult with found opportunities

        Raises:
            NoOpportunityError: If no opportunities found
            MarketDataError: If market data fetch fails
        """
        scan_start = datetime.utcnow()

        # Fetch markets from API
        markets = await self._fetch_markets(
            category=category,
            keywords=keywords,
            exclude_keywords=exclude_keywords,
            exclude_slugs=exclude_slugs,
            min_price=min_price,
            max_price=max_price,
            min_time_to_close=min_time_to_close,
            max_time_to_close=max_time_to_close,
        )

        # Filter and process opportunities
        opportunities = []
        for market in markets:
            opportunity = await self._process_market(market)
            if opportunity:
                opportunities.append(opportunity)

        # Update statistics
        self._last_scan_time = scan_start
        self._scan_count += 1
        self._total_opportunities_found += len(opportunities)

        # Create result
        scan_end = datetime.utcnow()
        scan_duration = (scan_end - scan_start).total_seconds()

        result = ScanResult(
            opportunities=opportunities,
            timestamp=scan_start,
            scan_duration=scan_duration,
        )

        # Log if no opportunities found
        if not result.has_opportunities:
            logger = get_logger(__name__)
            logger.info("no_opportunities_found", scan_duration=scan_duration)

        return result

    async def _fetch_markets(
        self,
        category: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        exclude_keywords: Optional[List[str]] = None,
        exclude_slugs: Optional[List[str]] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        min_time_to_close: Optional[int] = None,
        max_time_to_close: Optional[int] = None,
    ) -> List[dict]:
        """
        Fetch markets from API with filtering.

        Args:
            category: Market category filter
            keywords: Keyword filters to include
            exclude_keywords: Keywords to exclude
            exclude_slugs: Market slugs to exclude
            min_price: Minimum price filter
            max_price: Maximum price filter
            min_time_to_close: Minimum time to close
            max_time_to_close: Maximum time to close

        Returns:
            List of market data dictionaries
        """
        logger = get_logger(__name__)
        logger.info("fetching_markets", category=category, keywords=keywords)

        try:
            markets = await self.market_client.get_markets(
                category=category,
                keywords=keywords,
                exclude_keywords=exclude_keywords,
                exclude_slugs=exclude_slugs,
                min_price=min_price,
                max_price=max_price,
                min_time_to_close=min_time_to_close,
                max_time_to_close=max_time_to_close,
            )

            logger.info("markets_fetched", count=len(markets))
            return markets

        except Exception as e:
            logger.error("market_fetch_failed", error=str(e))
            raise MarketDataError(f"Failed to fetch markets: {str(e)}")

    async def _process_market(self, market: dict) -> Optional[MarketOpportunity]:
        """
        Process a single market and extract opportunities.

        Args:
            market: Market data dictionary

        Returns:
            MarketOpportunity if found, None otherwise
        """
        logger = get_logger(__name__)

        # Extract market information
        market_id = market.get("id")
        if not market_id:
            logger.warning("market_missing_id", market=market)
            return None

        title = market.get("title", "Unknown Market")
        close_time_str = market.get("closeTime")
        if not close_time_str:
            logger.warning("market_missing_close_time", market_id=market_id)
            return None

        try:
            close_time = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
        except ValueError as e:
            logger.error("invalid_close_time", market_id=market_id, error=str(e))
            return None

        # Get current prices
        try:
            prices = await self.market_client.get_current_prices([market_id])
            current_price = prices.get(market_id)

            if not current_price:
                logger.warning("market_missing_price", market_id=market_id)
                return None

        except Exception as e:
            logger.error("failed_to_get_price", market_id=market_id, error=str(e))
            return None

        # Check price thresholds for settlement arbitrage
        if not self._is_valid_opportunity(current_price, close_time):
            return None

        # Create opportunity
        opportunity = MarketOpportunity(
            market_id=market_id,
            outcome="YES",
            price=current_price,
            close_time=close_time,
            title=title,
            metadata={
                "market": market,
                "close_time_seconds": int((close_time - datetime.utcnow()).total_seconds()),
            },
        )

        return opportunity

    def _is_valid_opportunity(self, price: float, close_time: datetime) -> bool:
        """
        Check if a market represents a valid arbitrage opportunity.

        Args:
            price: Current market price
            close_time: Market close time

        Returns:
            True if opportunity is valid
        """
        # Check time to close
        time_to_close = int((close_time - datetime.utcnow()).total_seconds())
        if time_to_close < self.settings.execute_before_close_seconds:
            return False

        # Check price thresholds
        if price < self.settings.min_price_threshold or price > self.settings.max_price_threshold:
            return False

        # Check if it's a YES token in valid range
        if price > 0 and price < 1.0:
            return True

        return False

    def get_scan_statistics(self) -> dict:
        """
        Get scan statistics.

        Returns:
            Dictionary with scan statistics
        """
        return {
            "last_scan_time": self._last_scan_time.isoformat() if self._last_scan_time else None,
            "scan_count": self._scan_count,
            "total_opportunities_found": self._total_opportunities_found,
        }

    async def find_opportunities(
        self,
        min_price_threshold: Optional[float] = None,
        max_price_threshold: Optional[float] = None,
        execute_before_close_seconds: Optional[int] = None,
    ) -> List[MarketOpportunity]:
        """
        Convenience method to find opportunities with default filters.

        Args:
            min_price_threshold: Override minimum price threshold
            max_price_threshold: Override maximum price threshold
            execute_before_close_seconds: Override execution timing

        Returns:
            List of market opportunities
        """
        # Use provided filters or settings
        min_price = min_price_threshold or self.settings.min_price_threshold
        max_price = max_price_threshold or self.settings.max_price_threshold
        time_to_close = execute_before_close_seconds or self.settings.execute_before_close_seconds

        # Fetch markets
        markets = await self._fetch_markets(
            min_price=min_price,
            max_price=max_price,
            min_time_to_close=time_to_close,
            max_time_to_close=time_to_close + 60,  # Allow some flexibility
        )

        # Process and filter
        opportunities = []
        for market in markets:
            opportunity = await self._process_market(market)
            if opportunity:
                opportunities.append(opportunity)

        return opportunities


# Import for Protocol type hint
from typing import Protocol


# Update the logger import
from pkg.logger import logger

# Update imports
from internal.core.scanner.domain.models import MarketDataError, NoOpportunityError

# Import Protocol
from typing import Protocol
