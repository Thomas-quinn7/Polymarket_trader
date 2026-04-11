"""
Polymarket Data Models
Strategy-agnostic database models for the trading bot.
"""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import Column, Integer, String, Float, DateTime, Enum, Index
from sqlalchemy.orm import declarative_base
import enum

Base = declarative_base()


class TradeStatus(str, enum.Enum):
    """Lifecycle status of a trade opportunity or position."""

    DETECTED = "detected"
    EXECUTED = "executed"
    FAILED = "failed"
    CLOSED = "closed"


class PositionStatus(str, enum.Enum):
    """Status of a live position."""

    OPEN = "open"
    SETTLED = "settled"
    CLOSED = "closed"


class TradeOpportunity(Base):
    """
    A single trade opportunity produced by any strategy.

    Fields are deliberately generic — strategy-specific metadata should be
    stored in the strategy layer, not here.
    """

    __tablename__ = "trade_opportunities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market_id = Column(String(100), nullable=False, index=True)
    market_slug = Column(String(200), nullable=False)
    question = Column(String(500), nullable=False)
    category = Column(String(50), nullable=False)
    token_id_yes = Column(String(100), nullable=False)
    token_id_no = Column(String(100), nullable=False)
    winning_token_id = Column(String(100), nullable=False)
    # "YES" or "NO" — which side this trade is on
    side = Column(String(10), nullable=False, default="YES")
    # "single" | "paired" | "basket" — for stat-arb multi-leg trades
    opportunity_type = Column(String(20), nullable=False, default="single")
    current_price = Column(Float, nullable=False)
    edge_percent = Column(Float, nullable=False)
    confidence = Column(Float, nullable=True)
    detected_at = Column(DateTime, nullable=False, index=True)
    status = Column(Enum(TradeStatus), default=TradeStatus.DETECTED, nullable=False)
    executed_at = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "market_id": self.market_id,
            "market_slug": self.market_slug,
            "question": self.question,
            "category": self.category,
            "winning_token_id": self.winning_token_id,
            "winning_price": self.current_price,
            "side": self.side,
            "opportunity_type": self.opportunity_type,
            "edge_percent": self.edge_percent,
            "confidence": self.confidence,
            "detected_at": self.detected_at.isoformat() if self.detected_at else None,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "status": self.status.value if self.status else None,
        }


class TradePosition(Base):
    """Persisted record of an open or closed position."""

    __tablename__ = "trade_positions"

    id = Column(String(100), primary_key=True)
    market_id = Column(String(100), nullable=False, index=True)
    market_slug = Column(String(200), nullable=False)
    question = Column(String(500), nullable=False)
    token_id = Column(String(100), nullable=False)
    shares = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    current_price = Column(Float, nullable=True)
    expected_pnl = Column(Float, nullable=False)
    edge_percent = Column(Float, nullable=False)
    status = Column(Enum(PositionStatus), default=PositionStatus.OPEN, nullable=False)
    opened_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    settled_at = Column(DateTime, nullable=True)
    settlement_price = Column(Float, nullable=True)
    realized_pnl = Column(Float, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "market_id": self.market_id,
            "market_slug": self.market_slug,
            "question": self.question,
            "token_id": self.token_id,
            "shares": self.shares,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "expected_pnl": self.expected_pnl,
            "edge_percent": self.edge_percent,
            "status": self.status.value if self.status else None,
            "opened_at": self.opened_at.isoformat() if self.opened_at else None,
            "settled_at": self.settled_at.isoformat() if self.settled_at else None,
            "settlement_price": self.settlement_price,
            "realized_pnl": self.realized_pnl,
        }


class FakeCurrency(Base):
    """Paper trading balance."""

    __tablename__ = "fake_currency"

    id = Column(Integer, primary_key=True, autoincrement=True)
    balance = Column(Float, nullable=False, default=10000.00)
    deployed = Column(Float, nullable=False, default=0.0)
    pending_returns = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "balance": self.balance,
            "deployed": self.deployed,
            "pending_returns": self.pending_returns,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TradeAuditRecord(Base):
    """Immutable audit record for every completed trade."""

    __tablename__ = "trade_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market_id = Column(String(100), nullable=False, index=True)
    market_slug = Column(String(200), nullable=False)
    token_id = Column(String(100), nullable=False)
    shares = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=False)
    pnl = Column(Float, nullable=False)
    pnl_percent = Column(Float, nullable=False)
    edge_percent = Column(Float, nullable=False)
    status = Column(Enum(TradeStatus), nullable=False)
    opened_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    settled_at = Column(DateTime, nullable=True)
    settlement_price = Column(Float, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "market_id": self.market_id,
            "market_slug": self.market_slug,
            "token_id": self.token_id,
            "shares": self.shares,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "pnl": self.pnl,
            "pnl_percent": self.pnl_percent,
            "edge_percent": self.edge_percent,
            "status": self.status.value if self.status else None,
            "opened_at": self.opened_at.isoformat() if self.opened_at else None,
            "settled_at": self.settled_at.isoformat() if self.settled_at else None,
            "settlement_price": self.settlement_price,
        }


class MarketCache(Base):
    """Short-lived cache for market price snapshots."""

    __tablename__ = "market_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market_id = Column(String(100), nullable=False, unique=True, index=True)
    token_id_yes = Column(String(100), nullable=False)
    token_id_no = Column(String(100), nullable=False)
    yes_price = Column(Float, nullable=True)
    no_price = Column(Float, nullable=True)
    mid_price = Column(Float, nullable=True)
    cached_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    expires_at = Column(DateTime, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "market_id": self.market_id,
            "yes_price": self.yes_price,
            "no_price": self.no_price,
            "mid_price": self.mid_price,
            "cached_at": self.cached_at.isoformat() if self.cached_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


# ---------------------------------------------------------------------------
# Backward-compatibility aliases — remove once all call sites are updated
# ---------------------------------------------------------------------------
ArbitrageStatus = TradeStatus
ArbitrageOpportunity = TradeOpportunity
ArbitragePosition = TradePosition
# TradeRecord was renamed to TradeAuditRecord to avoid collision with the
# utils.pnl_tracker.TradeRecord dataclass.  This alias keeps old imports working.
TradeRecord = TradeAuditRecord
