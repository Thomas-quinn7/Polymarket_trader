"""
Polymarket Data Models
Database models for arbitrage bot
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Enum, Index
from sqlalchemy.ext.declarative import declarative_base
import enum

Base = declarative_base()


class ArbitrageStatus(str, enum.Enum):
    """Status of arbitrage opportunity"""

    DETECTED = "detected"
    EXECUTED = "executed"
    FAILED = "failed"
    SETTLED = "settled"


class PositionStatus(str, enum.Enum):
    """Status of position"""

    OPEN = "open"
    SETTLED = "settled"
    CLOSED = "closed"


class ArbitrageOpportunity(Base):
    """Arbitrage opportunity model"""

    __tablename__ = "arbitrage_opportunities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market_id = Column(String(100), nullable=False, index=True)
    market_slug = Column(String(200), nullable=False)
    question = Column(String(500), nullable=False)
    category = Column(String(50), nullable=False)
    token_id_yes = Column(String(100), nullable=False)
    token_id_no = Column(String(100), nullable=False)
    winning_token_id = Column(String(100), nullable=False)
    current_price = Column(Float, nullable=False)
    edge_percent = Column(Float, nullable=False)
    confidence = Column(Float, nullable=True)
    time_to_close_seconds = Column(Float, nullable=False)
    detected_at = Column(DateTime, nullable=False, index=True)
    status = Column(
        Enum(ArbitrageStatus), default=ArbitrageStatus.DETECTED, nullable=False
    )
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
            "edge_percent": self.edge_percent,
            "confidence": self.confidence,
            "time_to_close_seconds": self.time_to_close_seconds,
            "detected_at": self.detected_at.isoformat() if self.detected_at else None,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "status": self.status.value if self.status else None,
        }


class ArbitragePosition(Base):
    """Arbitrage position model"""

    __tablename__ = "arbitrage_positions"

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
    opened_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
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
    """Fake currency model for paper trading"""

    __tablename__ = "fake_currency"

    id = Column(Integer, primary_key=True, autoincrement=True)
    balance = Column(Float, nullable=False, default=10000.00)
    deployed = Column(Float, nullable=False, default=0.0)
    pending_returns = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "balance": self.balance,
            "deployed": self.deployed,
            "pending_returns": self.pending_returns,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TradeRecord(Base):
    """Paper trading record for analysis"""

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
    status = Column(Enum(ArbitrageStatus), nullable=False)
    opened_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
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
    """Cache for market data to reduce API calls"""

    __tablename__ = "market_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market_id = Column(String(100), nullable=False, unique=True, index=True)
    token_id_yes = Column(String(100), nullable=False)
    token_id_no = Column(String(100), nullable=False)
    yes_price = Column(Float, nullable=True)
    no_price = Column(Float, nullable=True)
    mid_price = Column(Float, nullable=True)
    cached_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
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
