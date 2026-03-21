"""
Scanner module - Market scanning and opportunity detection.
"""

from internal.core.scanner.domain import (
    MarketClientProtocol,
    MarketDataError,
    MarketOpportunity,
    NoOpportunityError,
    ScanResult,
)
from internal.core.scanner.infrastructure.market_client import (
    MockMarketClient,
    PolymarketClient,
)
from internal.core.scanner.service.scanner_service import ScannerService

__all__ = [
    # Domain
    "MarketOpportunity",
    "ScanResult",
    "MarketClientProtocol",
    "MarketDataError",
    "NoOpportunityError",
    # Service
    "ScannerService",
    # Infrastructure
    "PolymarketClient",
    "MockMarketClient",
]
