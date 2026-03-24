"""
Domain models for the portfolio module.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable
from datetime import datetime

from pkg.errors import AppError


class Balance:
    """
    Represents account balance information.
    """

    def __init__(
        self,
        balance: float,
        currency: str = "USD",
        timestamp: datetime = None,
        metadata: Dict[str, Any] = None,
    ):
        """
        Initialize balance.

        Args:
            balance: Current balance amount
            currency: Currency code
            timestamp: Balance timestamp
            metadata: Additional metadata
        """
        self.balance = balance
        self.currency = currency
        self.timestamp = timestamp or datetime.utcnow()
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "balance": self.balance,
            "currency": self.currency,
            "timestamp": self.timestamp.isoformat(),
            **self.metadata,
        }


class PnLReport:
    """
    Represents profit/loss report for a trading session.
    """

    def __init__(
        self,
        total_trades: int,
        winning_trades: int,
        losing_trades: int,
        total_profit: float,
        total_loss: float,
        net_profit: float,
        win_rate: float,
        timestamp: datetime,
        metadata: Dict[str, Any] = None,
    ):
        """
        Initialize P&L report.

        Args:
            total_trades: Total number of trades
            winning_trades: Number of winning trades
            losing_trades: Number of losing trades
            total_profit: Total profit amount
            total_loss: Total loss amount
            net_profit: Net profit (total_profit - total_loss)
            win_rate: Win rate percentage
            timestamp: Report timestamp
            metadata: Additional metadata
        """
        self.total_trades = total_trades
        self.winning_trades = winning_trades
        self.losing_trades = losing_trades
        self.total_profit = total_profit
        self.total_loss = total_loss
        self.net_profit = net_profit
        self.win_rate = win_rate
        self.timestamp = timestamp
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "total_profit": self.total_profit,
            "total_loss": self.total_loss,
            "net_profit": self.net_profit,
            "win_rate": self.win_rate,
            "timestamp": self.timestamp.isoformat(),
            **self.metadata,
        }


class Position:
    """
    Represents a trading position.
    """

    def __init__(
        self,
        position_id: str,
        market_id: str,
        outcome: str,
        side: str,
        quantity: float,
        entry_price: float,
        current_price: float,
        timestamp: datetime,
        metadata: Dict[str, Any] = None,
    ):
        """
        Initialize position.

        Args:
            position_id: Position identifier
            market_id: Market identifier
            outcome: Outcome type (YES/NO)
            side: Position side (BUY/SELL)
            quantity: Position quantity
            entry_price: Entry price
            current_price: Current price
            timestamp: Position timestamp
            metadata: Additional metadata
        """
        self.position_id = position_id
        self.market_id = market_id
        self.outcome = outcome
        self.side = side
        self.quantity = quantity
        self.entry_price = entry_price
        self.current_price = current_price
        self.timestamp = timestamp
        self.metadata = metadata or {}

    @property
    def unrealized_pnl(self) -> float:
        """Calculate unrealized P&L."""
        if self.side == "BUY":
            # Long position: P&L = (current_price - entry_price) * quantity
            return (self.current_price - self.entry_price) * self.quantity
        else:
            # Short position: P&L = (entry_price - current_price) * quantity
            return (self.entry_price - self.current_price) * self.quantity

    @property
    def position_value(self) -> float:
        """Calculate position value."""
        return self.quantity * self.current_price

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "position_id": self.position_id,
            "market_id": self.market_id,
            "outcome": self.outcome,
            "side": self.side,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "unrealized_pnl": self.unrealized_pnl,
            "position_value": self.position_value,
            "timestamp": self.timestamp.isoformat(),
            **self.metadata,
        }


class PortfolioError(AppError):
    """Error when portfolio management fails."""
    pass


class PortfolioRepositoryProtocol(Protocol):
    """
    Protocol for portfolio repository.
    Interface contract for portfolio data persistence.
    """

    async def save_position(self, position: Position) -> None:
        """Save a position."""
        ...

    async def get_positions(self) -> List[Position]:
        """Get all positions."""
        ...

    async def get_position_by_id(self, position_id: str) -> Optional[Position]:
        """Get a position by ID."""
        ...

    async def delete_position(self, position_id: str) -> None:
        """Delete a position."""
        ...

    async def save_balance(self, balance: Balance) -> None:
        """Save balance information."""
        ...

    async def get_balance(self) -> Balance:
        """Get current balance."""
        ...
