"""
Domain models for the execution module.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from datetime import datetime

from pkg.errors import AppError


class OrderStatus(Enum):
    """Status of an order."""
    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class OrderSide(Enum):
    """Side of the order (BUY/SELL)."""
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    """Type of order."""
    FOK = "FOK"  # Fill or Kill
    IOC = "IOC"  # Immediate or Cancel


class ExecutionResult:
    """
    Represents the result of an order execution.
    """

    def __init__(
        self,
        order_id: str,
        status: OrderStatus,
        side: OrderSide,
        price: float,
        amount: float,
        market_id: str,
        filled_amount: float,
        timestamp: datetime,
        metadata: Dict[str, Any] = None,
    ):
        """
        Initialize execution result.

        Args:
            order_id: Order identifier
            status: Execution status
            side: Order side (BUY/SELL)
            price: Execution price
            amount: Total amount
            market_id: Market identifier
            filled_amount: Amount filled
            timestamp: Execution timestamp
            metadata: Additional metadata
        """
        self.order_id = order_id
        self.status = status
        self.side = side
        self.price = price
        self.amount = amount
        self.market_id = market_id
        self.filled_amount = filled_amount
        self.timestamp = timestamp
        self.metadata = metadata or {}

    @property
    def is_success(self) -> bool:
        """Check if execution was successful."""
        return self.status == OrderStatus.FILLED

    @property
    def is_pending(self) -> bool:
        """Check if order is pending."""
        return self.status in (OrderStatus.PENDING, OrderStatus.FILLED)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "order_id": self.order_id,
            "status": self.status.value,
            "side": self.side.value,
            "price": self.price,
            "amount": self.amount,
            "market_id": self.market_id,
            "filled_amount": self.filled_amount,
            "timestamp": self.timestamp.isoformat(),
            "is_success": self.is_success,
            **self.metadata,
        }


class Position:
    """
    Represents a trading position.
    """

    def __init__(
        self,
        market_id: str,
        outcome: str,
        side: OrderSide,
        quantity: float,
        entry_price: float,
        timestamp: datetime,
        metadata: Dict[str, Any] = None,
    ):
        """
        Initialize position.

        Args:
            market_id: Market identifier
            outcome: Outcome type (YES/NO)
            side: Order side (BUY/SELL)
            quantity: Position quantity
            entry_price: Entry price
            timestamp: Position timestamp
            metadata: Additional metadata
        """
        self.market_id = market_id
        self.outcome = outcome
        self.side = side
        self.quantity = quantity
        self.entry_price = entry_price
        self.timestamp = timestamp
        self.metadata = metadata or {}

    @property
    def is_long(self) -> bool:
        """Check if position is long (BUY)."""
        return self.side == OrderSide.BUY

    @property
    def value(self) -> float:
        """Calculate position value."""
        return self.quantity * self.entry_price

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "market_id": self.market_id,
            "outcome": self.outcome,
            "side": self.side.value,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "value": self.value,
            "timestamp": self.timestamp.isoformat(),
            **self.metadata,
        }


class SettlementResult:
    """
    Represents the result of market settlement.
    """

    def __init__(
        self,
        market_id: str,
        winning_outcome: str,
        close_price: float,
        timestamp: datetime,
        metadata: Dict[str, Any] = None,
    ):
        """
        Initialize settlement result.

        Args:
            market_id: Market identifier
            winning_outcome: Winning outcome (YES/NO)
            close_price: Final price
            timestamp: Settlement timestamp
            metadata: Additional metadata
        """
        self.market_id = market_id
        self.winning_outcome = winning_outcome
        self.close_price = close_price
        self.timestamp = timestamp
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "market_id": self.market_id,
            "winning_outcome": self.winning_outcome,
            "close_price": self.close_price,
            "timestamp": self.timestamp.isoformat(),
            **self.metadata,
        }


class ExecutionError(AppError):
    """Error when order execution fails."""
    pass


class OrderValidationError(AppError):
    """Error when order validation fails."""
    pass


class BalanceError(AppError):
    """Error when balance management fails."""
    pass


class OrderExecutorProtocol(Protocol):
    """
    Protocol for order executor.
    Interface contract for order execution.
    """

    async def execute_order(
        self,
        market_id: str,
        outcome: str,
        side: OrderSide,
        quantity: float,
        price: float,
        order_type: OrderType = OrderType.FOK,
        metadata: Dict[str, Any] = None,
    ) -> ExecutionResult:
        """
        Execute an order.

        Args:
            market_id: Market identifier
            outcome: Outcome type (YES/NO)
            side: Order side (BUY/SELL)
            quantity: Order quantity
            price: Order price
            order_type: Order type (FOK/IOC)
            metadata: Additional metadata

        Returns:
            ExecutionResult with execution details
        """
        ...

    async def get_current_positions(self) -> List[Dict[str, Any]]:
        """
        Get current open positions.

        Returns:
            List of position data dictionaries
        """
        ...

    async def settle_position(self, market_id: str) -> SettlementResult:
        """
        Settle an open position.

        Args:
            market_id: Market identifier

        Returns:
            SettlementResult with outcome details
        """
        ...
