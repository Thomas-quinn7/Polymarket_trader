"""
Domain models for the scanner module.
"""

from internal.core.scanner.domain.models import (
    MarketOpportunity,
    ScanResult,
    MarketClientProtocol,
    MarketDataError,
    NoOpportunityError,
    MarketFilterError,
)

__all__ = [
    "MarketOpportunity",
    "ScanResult",
    "MarketClientProtocol",
    "MarketDataError",
    "NoOpportunityError",
    "MarketFilterError",
]
