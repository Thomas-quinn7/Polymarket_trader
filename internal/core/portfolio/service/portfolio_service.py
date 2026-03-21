"""
Portfolio Service - Main business logic for portfolio management.
Implements P&L tracking, balance management, and position tracking.
"""

from datetime import datetime
from typing import Dict, List, Optional

from pkg.config import get_settings
from pkg.logger import get_logger

from internal.core.notifications.domain import Alert, AlertSeverity, AlertType
from internal.core.portfolio.domain import (
    Balance,
    PnLReport,
    Position,
    PortfolioError,
    PortfolioRepositoryProtocol,
)


class PortfolioService:
    """
    Service for managing portfolio, positions, and P&L tracking.
    """

    def __init__(
        self,
        repository: PortfolioRepositoryProtocol,
        settings: Optional[object] = None,
        notifications: Optional[object] = None,
    ):
        """
        Initialize portfolio service.

        Args:
            repository: Portfolio repository implementation
            settings: Settings object (optional)
            notifications: Notification service (optional)
        """
        self.repository = repository
        self.notifications = notifications

        # Load settings if not provided
        if settings is None:
            settings = get_settings()

        self.settings = settings

        self._total_profit: float = 0.0
        self._total_loss: float = 0.0
        self._total_trades: int = 0
        self._winning_trades: int = 0
        self._losing_trades: int = 0

    async def open_position(
        self,
        position_id: str,
        market_id: str,
        outcome: str,
        side: str,
        quantity: float,
        entry_price: float,
        current_price: float,
        metadata: Dict[str, any] = None,
    ) -> Position:
        """
        Open a new position.

        Args:
            position_id: Position identifier
            market_id: Market identifier
            outcome: Outcome type (YES/NO)
            side: Position side (BUY/SELL)
            quantity: Position quantity
            entry_price: Entry price
            current_price: Current price
            metadata: Additional metadata

        Returns:
            Created position

        Raises:
            BalanceError: If insufficient balance for paper trading
        """
        logger = get_logger(__name__)

        # Check balance for paper trading
        if self._is_paper_trading() and await self._check_balance(quantity):
            raise BalanceError(f"Insufficient balance for paper trading. Required: {quantity}, Available: {await self._get_balance()}")
        else:
            # In real trading, check actual balance here
            pass

        position = Position(
            position_id=position_id,
            market_id=market_id,
            outcome=outcome,
            side=side,
            quantity=quantity,
            entry_price=entry_price,
            current_price=current_price,
            timestamp=datetime.utcnow(),
            metadata=metadata or {},
        )

        # Save to repository
        await self.repository.save_position(position)

        logger.info("position_opened", position_id=position_id, market_id=market_id, quantity=quantity)

        return position

    async def close_position(self, position_id: str, final_price: float) -> Dict[str, any]:
        """
        Close a position and calculate P&L.

        Args:
            position_id: Position identifier
            final_price: Final price at close

        Returns:
            Dictionary with close details and P&L
        """
        logger = get_logger(__name__)

        # Get position
        position = await self.repository.get_position_by_id(position_id)
        if not position:
            raise PortfolioError(f"Position {position_id} not found")

        # Calculate P&L
        if position.side == "BUY":
            pnl = (final_price - position.entry_price) * position.quantity
        else:
            pnl = (position.entry_price - final_price) * position.quantity

        # Update statistics
        self._total_trades += 1
        if pnl > 0:
            self._total_profit += pnl
            self._winning_trades += 1
            await self._notify_profit(pnl)
        else:
            self._total_loss += abs(pnl)
            self._losing_trades += 1
            await self._notify_loss(abs(pnl))

        # Delete position from repository
        await self.repository.delete_position(position_id)

        logger.info("position_closed", position_id=position_id, pnl=pnl, final_price=final_price)

        return {
            "position_id": position_id,
            "market_id": position.market_id,
            "pnl": pnl,
            "is_profitable": pnl > 0,
            "final_price": final_price,
        }

    async def get_all_positions(self) -> List[Position]:
        """Get all open positions."""
        return await self.repository.get_positions()

    async def get_position_by_id(self, position_id: str) -> Optional[Position]:
        """Get a position by ID."""
        return await self.repository.get_position_by_id(position_id)

    async def get_balance(self) -> float:
        """Get current balance."""
        balance = await self.repository.get_balance()
        return balance.balance

    async def get_pnl_report(self) -> PnLReport:
        """
        Generate P&L report for current session.

        Returns:
            PnLReport with trading statistics
        """
        win_rate = 0.0
        if self._total_trades > 0:
            win_rate = (self._winning_trades / self._total_trades) * 100

        return PnLReport(
            total_trades=self._total_trades,
            winning_trades=self._winning_trades,
            losing_trades=self._losing_trades,
            total_profit=self._total_profit,
            total_loss=self._total_loss,
            net_profit=self._total_profit - self._total_loss,
            win_rate=win_rate,
            timestamp=datetime.utcnow(),
        )

    def get_trading_statistics(self) -> Dict[str, any]:
        """Get trading statistics."""
        win_rate = 0.0
        if self._total_trades > 0:
            win_rate = (self._winning_trades / self._total_trades) * 100

        return {
            "total_trades": self._total_trades,
            "winning_trades": self._winning_trades,
            "losing_trades": self._losing_trades,
            "total_profit": self._total_profit,
            "total_loss": self._total_loss,
            "net_profit": self._total_profit - self._total_loss,
            "win_rate": win_rate,
            "paper_trading_only": self._is_paper_trading(),
        }

    def reset_statistics(self) -> None:
        """Reset trading statistics (useful for new trading sessions)."""
        self._total_profit = 0.0
        self._total_loss = 0.0
        self._total_trades = 0
        self._winning_trades = 0
        self._losing_trades = 0

    async def _check_balance(self, required_amount: float) -> bool:
        """
        Check if balance is sufficient for paper trading.

        Args:
            required_amount: Required balance amount

        Returns:
            True if balance is sufficient
        """
        balance = await self.repository.get_balance()
        return balance.balance >= required_amount

    async def _get_balance(self) -> float:
        """Get current balance."""
        balance = await self.repository.get_balance()
        return balance.balance

    def _is_paper_trading(self) -> bool:
        """Check if running in paper trading mode."""
        return self.settings.paper_trading_only

    async def _notify_profit(self, profit: float) -> None:
        """Notify about profitable trade."""
        if not self.notifications:
            return

        alert = Alert(
            type=AlertType.WIN,
            severity=AlertSeverity.INFO,
            title="Profitable Trade",
            message=f"Closed position with profit: ${profit:.2f}",
            metadata={
                "profit": profit,
                "total_profit": self._total_profit,
                "win_rate": (self._winning_trades / self._total_trades * 100) if self._total_trades > 0 else 0,
            },
        )

        await self.notifications.notify(alert)

    async def _notify_loss(self, loss: float) -> None:
        """Notify about losing trade."""
        if not self.notifications:
            return

        alert = Alert(
            type=AlertType.LOSS,
            severity=AlertSeverity.WARNING,
            title="Unprofitable Trade",
            message=f"Closed position with loss: ${loss:.2f}",
            metadata={
                "loss": loss,
                "total_loss": self._total_loss,
                "net_profit": self._total_profit - self._total_loss,
            },
        )

        await self.notifications.notify(alert)


class InMemoryRepository(PortfolioRepositoryProtocol):
    """
    In-memory repository for portfolio data (for testing).
    """

    def __init__(self, initial_balance: float = 10000.0):
        """Initialize in-memory repository."""
        self._positions: Dict[str, Position] = {}
        self._balance = Balance(balance=initial_balance, currency="USD")

    async def save_position(self, position: Position) -> None:
        """Save a position."""
        self._positions[position.position_id] = position

    async def get_positions(self) -> List[Position]:
        """Get all positions."""
        return list(self._positions.values())

    async def get_position_by_id(self, position_id: str) -> Optional[Position]:
        """Get a position by ID."""
        return self._positions.get(position_id)

    async def delete_position(self, position_id: str) -> None:
        """Delete a position."""
        if position_id in self._positions:
            del self._positions[position_id]

    async def save_balance(self, balance: Balance) -> None:
        """Save balance information."""
        self._balance = balance

    async def get_balance(self) -> Balance:
        """Get current balance."""
        return self._balance


# Import for Protocol type hint
from typing import Protocol
