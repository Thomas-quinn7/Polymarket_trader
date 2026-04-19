"""
Paper trading balance tracker.
Manages simulated capital allocation and returns across open positions.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict

from config.polymarket_config import config
from utils.logger import logger


@dataclass
class CurrencyPosition:
    """Tracks capital allocation for a single open position."""

    market_id: str
    position_id: str = field(default_factory=lambda: str(int(datetime.now().timestamp())))
    allocated: float = field(default=0.0)
    returned: float = field(default=0.0)


class PaperPortfolio:
    """
    Simulated capital book for paper trading.

    Tracks available balance and deployed capital across all open positions.
    Allocation and return amounts are set by the caller (OrderExecutor) — this
    class enforces the MAX_POSITIONS limit and balance sufficiency only.
    """

    def __init__(self):
        self.positions: Dict[str, CurrencyPosition] = {}
        self.starting_balance = config.FAKE_CURRENCY_BALANCE
        self.balance = self.starting_balance
        self.deployed = 0.0
        self._lock = threading.Lock()

        logger.info(f"Paper portfolio initialised — starting balance ${self.starting_balance:.2f}")

    def allocate_to_position(self, position_id: str, market_id: str, amount: float) -> bool:
        """
        Deduct `amount` from available balance and record it as deployed capital.

        Returns False (without modifying state) when:
        - Available balance is below `amount`
        - MAX_POSITIONS open positions already exist
        """
        with self._lock:
            if self.balance < amount:
                logger.warning(f"Insufficient balance: ${self.balance:.2f}, need ${amount:.2f}")
                return False

            if len(self.positions) >= config.MAX_POSITIONS:
                logger.warning(f"Max {config.MAX_POSITIONS} positions reached")
                return False

            self.positions[position_id] = CurrencyPosition(
                position_id=position_id,
                market_id=market_id,
                allocated=amount,
            )
            self.balance -= amount
            self.deployed += amount

        logger.info(
            f"Allocated ${amount:.2f} to {position_id} "
            f"(balance=${self.balance:.2f}, deployed=${self.deployed:.2f})"
        )
        return True

    def return_to_balance(self, position_id: str, return_amount: float) -> bool:
        """
        Credit `return_amount` back to available balance on position close.

        The original allocated amount is subtracted from `deployed`; the
        actual return (which may differ due to P&L) is credited to `balance`.
        """
        with self._lock:
            if position_id not in self.positions:
                logger.warning(f"Position {position_id} not found in paper portfolio")
                return False

            original_allocated = self.positions[position_id].allocated
            self.balance += return_amount
            self.deployed -= original_allocated
            del self.positions[position_id]

        logger.info(
            f"Returned ${return_amount:.2f} from {position_id} " f"(balance=${self.balance:.2f})"
        )
        return True

    def get_balance(self) -> float:
        """Current available (undeployed) balance."""
        with self._lock:
            return self.balance

    def get_deployed(self) -> float:
        """Total capital currently deployed in open positions."""
        with self._lock:
            return self.deployed

    def reset(self):
        """Reset to starting state (used in tests)."""
        with self._lock:
            self.positions = {}
            self.balance = self.starting_balance
            self.deployed = 0.0
        logger.info("Paper portfolio reset")


# Backward-compatibility alias so existing code importing FakeCurrencyTracker
# continues to work without changes.
FakeCurrencyTracker = PaperPortfolio
