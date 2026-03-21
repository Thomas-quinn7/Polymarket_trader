"""
Market Client Infrastructure - Polymarket API client.
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from requests.exceptions import RequestException

from pkg.config import get_settings
from pkg.errors import MarketClientError
from pkg.logger import get_logger

from internal.core.scanner.domain import MarketClientProtocol


class PolymarketClient(MarketClientProtocol):
    """
    Polymarket API client implementation.
    """

    def __init__(self, settings: Optional[object] = None):
        """
        Initialize Polymarket client.

        Args:
            settings: Settings object (optional)
        """
        if settings is None:
            settings = get_settings()

        self.settings = settings
        self.base_url = "https://clob.polymarket.com"

        # Initialize session
        self._session = None

    async def _get_session(self) -> requests.Session:
        """Get or create HTTP session."""
        if self._session is None:
            self._session = requests.Session()
        return self._session

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
        Get markets from Polymarket API.

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

        Raises:
            MarketClientError: If API call fails
        """
        session = await self._get_session()

        try:
            # Build query parameters
            params = {}

            if category:
                params["category"] = category

            if keywords:
                params["keywords"] = ",".join(keywords)

            if exclude_keywords:
                params["exclude_keywords"] = ",".join(exclude_keywords)

            if exclude_slugs:
                params["exclude_slugs"] = ",".join(exclude_slugs)

            if min_price is not None:
                params["min_price"] = str(min_price)

            if max_price is not None:
                params["max_price"] = str(max_price)

            if min_time_to_close is not None:
                params["min_time_to_close"] = str(min_time_to_close)

            if max_time_to_close is not None:
                params["max_time_to_close"] = str(max_time_to_close)

            logger = get_logger(__name__)
            logger.info("fetching_markets", params=params)

            # Make API request
            response = session.get(
                f"{self.base_url}/markets",
                params=params,
                timeout=30,
            )

            response.raise_for_status()

            markets = response.json()
            logger.info("markets_received", count=len(markets) if isinstance(markets, list) else 0)

            return markets if isinstance(markets, list) else [markets]

        except RequestException as e:
            logger.error("market_fetch_request_failed", error=str(e))
            raise MarketClientError(f"Failed to fetch markets: {str(e)}")

        except Exception as e:
            logger.error("market_fetch_parse_failed", error=str(e))
            raise MarketClientError(f"Failed to parse market data: {str(e)}")

    async def get_market_by_id(self, market_id: str) -> Optional[Dict[str, Any]]:
        """
        Get market by ID.

        Args:
            market_id: Market identifier

        Returns:
            Market data or None if not found
        """
        session = await self._get_session()

        try:
            response = session.get(
                f"{self.base_url}/markets/{market_id}",
                timeout=30,
            )

            response.raise_for_status()
            return response.json()

        except RequestException as e:
            logger = get_logger(__name__)
            logger.warning("market_not_found", market_id=market_id, error=str(e))
            return None

        except Exception as e:
            logger = get_logger(__name__)
            logger.error("market_parse_failed", market_id=market_id, error=str(e))
            return None

    async def get_current_prices(self, market_ids: List[str]) -> Dict[str, float]:
        """
        Get current prices for multiple markets.

        Args:
            market_ids: List of market IDs

        Returns:
            Dictionary mapping market IDs to prices
        """
        session = await self._get_session()

        try:
            # Build payload
            payload = {"ids": market_ids}

            response = session.post(
                f"{self.base_url}/markets/positions/prices",
                json=payload,
                timeout=30,
            )

            response.raise_for_status()

            # Parse response
            data = response.json()

            # Extract prices (format depends on API response)
            prices = {}
            if isinstance(data, list):
                for item in data:
                    market_id = item.get("marketId")
                    price = item.get("yesPrice", item.get("price", 0))
                    if market_id:
                        prices[market_id] = price

            return prices

        except RequestException as e:
            logger = get_logger(__name__)
            logger.error("price_fetch_failed", error=str(e))
            raise MarketClientError(f"Failed to fetch prices: {str(e)}")

        except Exception as e:
            logger = get_logger(__name__)
            logger.error("price_parse_failed", error=str(e))
            raise MarketClientError(f"Failed to parse price data: {str(e)}")


# For backward compatibility with existing code
from internal.core.scanner.domain import MarketClientProtocol


# Mock implementation for testing
class MockMarketClient(MarketClientProtocol):
    """Mock market client for testing."""

    def __init__(self):
        """Initialize mock client."""
        self._markets = []
        self._prices = {}

    def set_markets(self, markets: List[Dict[str, Any]]) -> None:
        """Set mock markets."""
        self._markets = markets

    def set_prices(self, prices: Dict[str, float]) -> None:
        """Set mock prices."""
        self._prices = prices

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
        """Return mock markets."""
        logger = get_logger(__name__)
        logger.info("mock_markets_fetched", count=len(self._markets))
        return self._markets

    async def get_market_by_id(self, market_id: str) -> Optional[Dict[str, Any]]:
        """Return mock market."""
        return next((m for m in self._markets if m.get("id") == market_id), None)

    async def get_current_prices(self, market_ids: List[str]) -> Dict[str, float]:
        """Return mock prices."""
        return self._prices


# Import logger
from pkg.logger import logger
