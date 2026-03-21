"""
Executor Service - Main business logic for order execution.
Implements paper trading and settlement logic.
"""

import asyncio
from datetime import datetime
from typing import Dict, List, Optional

from pkg.config import get_settings
from pkg.logger import get_logger

from internal.core.notifications.domain import Alert, AlertSeverity, AlertType
from internal.core.execution.domain import (
    OrderExecutorProtocol,
    OrderSide,
    OrderStatus,
    OrderType,
    ExecutionResult,
    SettlementResult,
    ExecutionError,
    OrderValidationError,
)


class ExecutorService:
    """
    Service for executing orders with paper trading logic.
    """

    def __init__(
        self,
        executor: OrderExecutorProtocol,
        settings: Optional[object] = None,
        notifications: Optional[object] = None,
    ):
        """
        Initialize executor service.

        Args:
            executor: Order executor implementation
            settings: Settings object (optional)
            notifications: Notification service (optional)
        """
        self.executor = executor
        self.notifications = notifications

        # Load settings if not provided
        if settings is None:
            settings = get_settings()

        self.settings = settings

        # Check safety mode
        if self.settings.paper_trading_only:
            self._is_safety_mode = True
        else:
            self._is_safety_mode = False

        self._pending_orders: Dict[str, datetime] = {}
        self._successful_orders: int = 0
        self._failed_orders: int = 0

    async def execute_order(
        self,
        market_id: str,
        outcome: str,
        side: OrderSide,
        quantity: float,
        price: float,
        order_type: OrderType = OrderType.FOK,
        metadata: Dict[str, any] = None,
    ) -> ExecutionResult:
        """
        Execute an order with safety checks.

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

        Raises:
            OrderValidationError: If order is invalid
            ExecutionError: If execution fails
        """
        logger = get_logger(__name__)

        # Safety check
        if self._is_safety_mode:
            logger.info("paper_trading_only_mode", message="Paper trading only, blocking real trades")
            raise ExecutionError("Paper trading only mode - real trades disabled")

        # Validate order
        self._validate_order(market_id, outcome, side, quantity, price)

        # Check if position limit reached
        if await self._check_position_limit():
            raise ExecutionError("Maximum positions reached, cannot open new position")

        # Execute order
        try:
            result = await self.executor.execute_order(
                market_id=market_id,
                outcome=outcome,
                side=side,
                quantity=quantity,
                price=price,
                order_type=order_type,
                metadata=metadata,
            )

            # Record execution statistics
            if result.is_success:
                self._successful_orders += 1
                await self._notify_order_executed(result)
            else:
                self._failed_orders += 1
                await self._notify_execution_failed(result)

            return result

        except Exception as e:
            logger.error("order_execution_failed", market_id=market_id, error=str(e))
            raise ExecutionError(f"Order execution failed: {str(e)}")

    def _validate_order(
        self,
        market_id: str,
        outcome: str,
        side: OrderSide,
        quantity: float,
        price: float,
    ) -> None:
        """
        Validate order parameters.

        Args:
            market_id: Market identifier
            outcome: Outcome type
            side: Order side
            quantity: Order quantity
            price: Order price

        Raises:
            OrderValidationError: If order is invalid
        """
        if not market_id:
            raise OrderValidationError("Market ID is required")

        if outcome not in ("YES", "NO"):
            raise OrderValidationError(f"Invalid outcome: {outcome}. Must be YES or NO")

        if side not in (OrderSide.BUY, OrderSide.SELL):
            raise OrderValidationError(f"Invalid side: {side}. Must be BUY or SELL")

        if quantity <= 0:
            raise OrderValidationError(f"Invalid quantity: {quantity}. Must be positive")

        if price <= 0 or price > 100:
            raise OrderValidationError(f"Invalid price: {price}. Must be between 0 and 100")

        if order_type not in (OrderType.FOK, OrderType.IOC):
            raise OrderValidationError(f"Invalid order type: {order_type}. Must be FOK or IOC")

    async def _check_position_limit(self) -> bool:
        """
        Check if position limit is reached.

        Returns:
            True if position limit reached
        """
        if self.settings.max_positions <= 0:
            return False

        # Get current positions (simplified check)
        try:
            positions = await self.executor.get_current_positions()
            current_positions = len(positions)
            return current_positions >= self.settings.max_positions
        except Exception:
            # If we can't check, be conservative and allow execution
            return False

    async def _notify_order_executed(self, result: ExecutionResult) -> None:
        """Notify that an order was executed."""
        if not self.notifications:
            return

        alert = Alert(
            type=AlertType.TRADE_EXECUTED,
            severity=AlertSeverity.INFO,
            title="Order Executed",
            message=f"Order {result.order_id} filled successfully",
            metadata={
                "order_id": result.order_id,
                "market_id": result.market_id,
                "side": result.side.value,
                "price": result.price,
                "quantity": result.amount,
                "filled_amount": result.filled_amount,
            },
        )

        await self.notifications.notify(alert)

    async def _notify_execution_failed(self, result: ExecutionResult) -> None:
        """Notify that an order execution failed."""
        if not self.notifications:
            return

        alert = Alert(
            type=AlertType.EXECUTION_ERROR,
            severity=AlertSeverity.ERROR,
            title="Order Execution Failed",
            message=f"Order {result.order_id} failed to execute",
            metadata={
                "order_id": result.order_id,
                "market_id": result.market_id,
                "status": result.status.value,
                "error": "Execution failed",
            },
        )

        await self.notifications.notify(alert)

    async def settle_position(self, market_id: str) -> SettlementResult:
        """
        Settle an open position.

        Args:
            market_id: Market identifier

        Returns:
            SettlementResult with outcome details

        Raises:
            ExecutionError: If settlement fails
        """
        logger = get_logger(__name__)

        try:
            result = await self.executor.settle_position(market_id)

            # Send notification based on outcome
            if result.winning_outcome == "YES":
                await self._notify_position_won(result)
            else:
                await self._notify_position_lost(result)

            return result

        except Exception as e:
            logger.error("settlement_failed", market_id=market_id, error=str(e))
            raise ExecutionError(f"Settlement failed: {str(e)}")

    async def _notify_position_won(self, result: SettlementResult) -> None:
        """Notify that a position was won."""
        if not self.notifications:
            return

        alert = Alert(
            type=AlertType.WIN,
            severity=AlertSeverity.INFO,
            title="Position Won",
            message=f"Market {result.market_id} resolved in favor of YES",
            metadata={
                "market_id": result.market_id,
                "winning_outcome": result.winning_outcome,
                "close_price": result.close_price,
            },
        )

        await self.notifications.notify(alert)

    async def _notify_position_lost(self, result: SettlementResult) -> None:
        """Notify that a position was lost."""
        if not self.notifications:
            return

        alert = Alert(
            type=AlertType.LOSS,
            severity=AlertSeverity.WARNING,
            title="Position Lost",
            message=f"Market {result.market_id} resolved in favor of NO",
            metadata={
                "market_id": result.market_id,
                "winning_outcome": result.winning_outcome,
                "close_price": result.close_price,
            },
        )

        await self.notifications.notify(alert)

    def get_execution_statistics(self) -> dict:
        """
        Get execution statistics.

        Returns:
            Dictionary with execution statistics
        """
        return {
            "successful_orders": self._successful_orders,
            "failed_orders": self._failed_orders,
            "position_limit": self.settings.max_positions,
            "paper_trading_only": self._is_safety_mode,
        }


class PaperTradingExecutor(OrderExecutorProtocol):
    """
    Mock executor for paper trading simulation.
    """

    def __init__(self):
        """Initialize mock executor."""
        self.orders: List[dict] = []
        self.pending_settlements: List[str] = []

    async def execute_order(
        self,
        market_id: str,
        outcome: str,
        side: OrderSide,
        quantity: float,
        price: float,
        order_type: OrderType = OrderType.FOK,
        metadata: Dict[str, any] = None,
    ) -> ExecutionResult:
        """Execute a paper trading order."""
        order_id = f"paper_{market_id}_{len(self.orders)}"

        # Simulate order execution
        order = {
            "id": order_id,
            "market_id": market_id,
            "outcome": outcome,
            "side": side.value,
            "quantity": quantity,
            "price": price,
            "status": OrderStatus.FILLED.value,
            "timestamp": datetime.utcnow().isoformat(),
        }

        self.orders.append(order)

        return ExecutionResult(
            order_id=order_id,
            status=OrderStatus.FILLED,
            side=side,
            price=price,
            amount=quantity,
            market_id=market_id,
            filled_amount=quantity,
            timestamp=datetime.utcnow(),
            metadata=metadata or {},
        )

    async def get_current_positions(self) -> List[dict]:
        """Get current positions (simplified)."""
        return self.orders

    async def settle_position(self, market_id: str) -> SettlementResult:
        """Settle a paper trading position."""
        if market_id in self.pending_settlements:
            # Simulate winning outcome
            return SettlementResult(
                market_id=market_id,
                winning_outcome="YES",
                close_price=0.99,
                timestamp=datetime.utcnow(),
            )
        else:
            # Simulate losing outcome
            return SettlementResult(
                market_id=market_id,
                winning_outcome="NO",
                close_price=0.01,
                timestamp=datetime.utcnow(),
            )


# Import for Protocol type hint
from typing import Protocol
