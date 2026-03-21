"""
Integration tests for scanner module.
"""

import pytest
from datetime import datetime

from internal.core.scanner.domain import MarketOpportunity, ScanResult
from internal.core.scanner.infrastructure import MockMarketClient


class TestScannerInfrastructure:
    """Test cases for scanner infrastructure."""

    def test_mock_market_client_initialization(self):
        """Test mock market client can be initialized."""
        client = MockMarketClient()
        assert client is not None

    def test_mock_market_client_set_markets(self):
        """Test mock market client can set markets."""
        client = MockMarketClient()
        markets = [{"id": "market_1", "title": "Test Market"}]

        client.set_markets(markets)

        # Verify markets are set
        assert len(client._markets) == 1

    def test_mock_market_client_get_markets(self):
        """Test mock market client returns configured markets."""
        client = MockMarketClient()
        markets = [{"id": "market_1", "title": "Test Market"}]

        client.set_markets(markets)

        # Get markets
        result = asyncio.run(client.get_markets())
        assert len(result) == 1
        assert result[0]["id"] == "market_1"

    def test_mock_market_client_get_current_prices(self):
        """Test mock market client returns prices."""
        client = MockMarketClient()
        prices = {"market_1": 0.95, "market_2": 0.87}

        client._prices = prices

        result = asyncio.run(client.get_current_prices(["market_1", "market_2"]))
        assert result == prices


# Mock asyncio for testing
import asyncio

# Re-define the async tests properly
class TestScannerMockClient:
    """Test cases for scanner mock client functionality."""

    def setup_method(self):
        """Setup test fixture."""
        self.client = MockMarketClient()

    def test_set_and_get_markets(self):
        """Test setting and getting markets."""
        markets = [{"id": "market_1", "title": "Test Market"}]
        self.client.set_markets(markets)

        result = asyncio.run(self.client.get_markets())
        assert len(result) == 1
        assert result[0]["id"] == "market_1"

    def test_set_and_get_prices(self):
        """Test setting and getting prices."""
        prices = {"market_1": 0.95}
        self.client._prices = prices

        result = asyncio.run(self.client.get_current_prices(["market_1"]))
        assert result["market_1"] == 0.95

    def test_get_markets_empty(self):
        """Test getting markets when none are set."""
        result = asyncio.run(self.client.get_markets())
        assert len(result) == 0

    def test_get_market_by_id(self):
        """Test getting a specific market by ID."""
        markets = [{"id": "market_1", "title": "Test Market"}]
        self.client.set_markets(markets)

        result = asyncio.run(self.client.get_market_by_id("market_1"))
        assert result is not None
        assert result["id"] == "market_1"

    def test_get_market_by_id_not_found(self):
        """Test getting a market that doesn't exist."""
        result = asyncio.run(self.client.get_market_by_id("nonexistent"))
        assert result is None
