"""
Domain models for the scanner module.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from datetime import datetime

from pkg.errors import AppError


class MarketOpportunity:
    """
    Represents a potential trading opportunity.
    """

    def __init__(
        self,
        market_id: str,
        outcome: str,
        price: float,
        close_time: datetime,
        title: str,
        **metadata: Any,
    ):
        """
        Initialize market opportunity.

        Args:
            market_id: Market identifier
            outcome: Outcome type (YES/NO)
            price: Current price of the outcome
            close_time: Time when market closes
            title: Market title
            **metadata: Additional metadata
        """
        self.market_id = market_id
        self.outcome = outcome
        self.price = price
        self.close_time = close_time
        self.title = title
        self.metadata = metadata or {}

    @property
    def time_to_close(self) -> int:
        """Get seconds until market close."""
        delta = self.close_time - datetime.utcnow()
        return int(delta.total_seconds())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "market_id": self.market_id,
            "outcome": self.outcome,
            "price": self.price,
            "close_time": self.close_time.isoformat(),
            "time_to_close": self.time_to_close,
            "title": self.title,
            **self.metadata,
        }


class ScanResult:
    """
    Represents the result of a market scan.
    """

    def __init__(
        self,
        opportunities: List[MarketOpportunity],
        timestamp: datetime,
        scan_duration: float,
    ):
        """
        Initialize scan result.

        Args:
            opportunities: List of market opportunities found
            timestamp: Time when scan was performed
            scan_duration: Duration of scan in seconds
        """
        self.opportunities = opportunities
        self.timestamp = timestamp
        self.scan_duration = scan_duration

    @property
    def total_opportunities(self) -> int:
        """Get total number of opportunities."""
        return len(self.opportunities)

    @property
    def has_opportunities(self) -> bool:
        """Check if any opportunities were found."""
        return len(self.opportunities) > 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "opportunities": [opp.to_dict() for opp in self.opportunities],
            "timestamp": self.timestamp.isoformat(),
            "scan_duration": self.scan_duration,
            "total_opportunities": self.total_opportunities,
            "has_opportunities": self.has_opportunities,
        }


class MarketFilterError(AppError):
    """Error when market filtering fails."""
    pass


class MarketDataError(AppError):
    """Error when market data is invalid."""
    pass


class NoOpportunityError(AppError):
    """Error when no opportunities are found."""
    pass


class MarketClientProtocol(Protocol):
    """
    Protocol for market data client.
    Interface contract for fetching market data.
    """

    async def get_markets(
        self,
        category: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        exclude_keywords: Optional[List[str]] = None,
        exclude_slugs: Optional[List[str]] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        min_time_to_close: Optional[int] = None,
        max_time_to_close: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get markets based on filters.

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
        ...

    async def get_market_by_id(self, market_id: str) -> Optional[Dict[str, Any]]:
        """
        Get market by ID.

        Args:
            market_id: Market identifier

        Returns:
            Market data or None if not found
        """
        ...

    async def get_current_prices(self, market_ids: List[str]) -> Dict[str, float]:
        """
        Get current prices for multiple markets.

        Args:
            market_ids: List of market IDs

        Returns:
            Dictionary mapping market IDs to prices
        """
        ...
