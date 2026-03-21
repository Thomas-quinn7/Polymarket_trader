"""
Fake Currency Tracker
Tracks fake currency for paper trading
"""

from dataclasses import dataclass, field
from typing import Dict
from datetime import datetime
from utils.logger import logger
from config.polymarket_config import config


@dataclass
class CurrencyPosition:
    """Tracks currency allocation per position"""

    market_id: str
    position_id: str = field(
        default_factory=lambda: str(int(datetime.now().timestamp()))
    )
    allocated: float = field(default=0.0)
    returned: float = field(default=0.0)


class FakeCurrencyTracker:
    """
    Tracks fake currency for paper trading

    Key Features:
    - Starting balance: $10,000
    - 20% allocated per position (equal split)
    - Tracks deployed capital
    - Tracks returns from settlements
    - Logs all transactions
    """

    def __init__(self):
        self.positions: Dict[str, CurrencyPosition] = {}
        self.starting_balance = config.FAKE_CURRENCY_BALANCE
        self.balance = self.starting_balance
        self.deployed = 0.0

        logger.info(
            f"Fake currency tracker initialized with ${self.starting_balance:.2f}"
        )

    def allocate_to_position(
        self, position_id: str, market_id: str, amount: float
    ) -> bool:
        """
        Allocate currency to a position (20% split)

        Args:
            position_id: Position ID
            market_id: Market ID
            amount: Amount to allocate

        Returns:
            True if successful
        """
        if self.balance < amount:
            logger.warning(
                f"Insufficient balance: ${self.balance:.2f}, need ${amount:.2f}"
            )
            return False

        if len(self.positions) >= 5:
            logger.warning("Max 5 positions reached")
            return False

        # 20% of starting balance per position
        position_amount = min(amount, self.starting_balance * 0.2)

        self.positions[position_id] = CurrencyPosition(
            position_id=position_id,
            market_id=market_id,
            allocated=position_amount,
            returned=0.0,
        )

        self.balance -= position_amount
        self.deployed += position_amount

        logger.info(
            f"💰 Allocated ${position_amount:.2f} to {position_id} "
            f"(Balance: ${self.balance:.2f}, "
            f"Deployed: ${self.deployed:.2f})"
        )

        return True

    def return_to_balance(self, position_id: str, return_amount: float) -> bool:
        """
        Return currency from settled position

        Args:
            position_id: Position ID
            return_amount: Amount to return

        Returns:
            True if successful
        """
        if position_id not in self.positions:
            logger.warning(f"Position {position_id} not found")
            return False

        self.positions[position_id].returned += return_amount
        self.balance += return_amount

        logger.info(
            f"💵 Returned ${return_amount:.2f} from {position_id} "
            f"(Balance: ${self.balance:.2f})"
        )

        return True

    def get_balance(self) -> float:
        """Get current fake currency balance"""
        return self.balance

    def get_deployed(self) -> float:
        """Get total deployed capital"""
        return self.deployed

    def get_available(self) -> float:
        """Get available balance for new positions"""
        return self.balance

    def reset(self):
        """Reset tracker for testing"""
        self.positions = {}
        self.balance = self.starting_balance
        self.deployed = 0.0
        logger.info("Fake currency tracker reset")
