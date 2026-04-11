"""Data package"""

from .polymarket_client import PolymarketClient
from .polymarket_models import (
    ArbitrageOpportunity,
    ArbitragePosition,
    FakeCurrency,
    TradeAuditRecord,
    TradeRecord,  # backward-compat alias for TradeAuditRecord
    MarketCache,
    ArbitrageStatus,
    PositionStatus,
    Base,
)

__all__ = [
    "PolymarketClient",
    "ArbitrageOpportunity",
    "ArbitragePosition",
    "FakeCurrency",
    "TradeAuditRecord",
    "TradeRecord",
    "MarketCache",
    "ArbitrageStatus",
    "PositionStatus",
    "Base",
]
