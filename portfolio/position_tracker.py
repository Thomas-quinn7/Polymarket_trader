"""
Position Tracker Module
Tracks individual positions and settlements
"""

import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime

from config.polymarket_config import config
from utils.logger import logger
from utils.pnl_tracker import PnLTracker, TradeRecord


@dataclass
class Position:
    """Tracks a single arbitrage position"""

    position_id: str
    market_id: str
    market_slug: str
    question: str
    token_id_yes: str
    token_id_no: str
    winning_token_id: str
    shares: float
    entry_price: float
    allocated_capital: float
    expected_profit: float
    edge_percent: float
    status: str = "OPEN"  # OPEN, SETTLED, FAILED
    opened_at: datetime = field(default_factory=datetime.now)
    settled_at: Optional[datetime] = None
    settlement_price: Optional[float] = None
    realized_pnl: Optional[float] = None

    def to_dict(self):
        return {
            "position_id": self.position_id,
            "market_id": self.market_id,
            "market_slug": self.market_slug,
            "question": self.question,
            "token_id_yes": self.token_id_yes,
            "token_id_no": self.token_id_no,
            "winning_token_id": self.winning_token_id,
            "shares": self.shares,
            "entry_price": self.entry_price,
            "allocated_capital": self.allocated_capital,
            "expected_profit": self.expected_profit,
            "edge_percent": self.edge_percent,
            "status": self.status,
            "opened_at": self.opened_at.isoformat() if self.opened_at else None,
            "settled_at": self.settled_at.isoformat() if self.settled_at else None,
            "settlement_price": self.settlement_price,
            "realized_pnl": self.realized_pnl,
        }


class PositionTracker:
    """
    Tracks all arbitrage positions

    Features:
    - Track all open positions
    - Track position settlements
    - Calculate position PnL
    - Integrate with PnLTracker
    """

    def __init__(self, pnl_tracker: PnLTracker):
        self.pnl_tracker = pnl_tracker
        self.positions: Dict[str, Position] = {}
        self.max_positions = config.MAX_POSITIONS
        self._lock = threading.Lock()

        logger.info("Position tracker initialized")

    def create_position(
        self,
        opportunity,
        shares: float,
        allocated_capital: float,
        expected_profit: float,
        position_id: Optional[str] = None,
    ) -> str:
        """
        Create a new position from an opportunity

        Args:
            opportunity: ArbitrageOpportunity object
            shares: Number of shares
            allocated_capital: Capital allocated
            expected_profit: Expected profit
            position_id: Optional caller-supplied ID; generated if not provided

        Returns:
            Position ID
        """
        if position_id is None:
            position_id = f"{opportunity.market_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

        position = Position(
            position_id=position_id,
            market_id=opportunity.market_id,
            market_slug=opportunity.market_slug,
            question=opportunity.question,
            token_id_yes=opportunity.token_id_yes,
            token_id_no=opportunity.token_id_no,
            winning_token_id=opportunity.winning_token_id,
            shares=shares,
            entry_price=opportunity.current_price,
            allocated_capital=allocated_capital,
            expected_profit=expected_profit,
            edge_percent=opportunity.edge_percent,
        )

        with self._lock:
            self.positions[position_id] = position

        # Track in PnL tracker
        self.pnl_tracker.open_position(
            position_id=position_id,
            market_id=opportunity.market_id,
            quantity=shares,
            entry_price=opportunity.current_price,
        )

        logger.info(
            f"Position created: {position_id} - "
            f"{shares:.4f} shares @ ${opportunity.current_price:.4f}, "
            f"Expected profit: ${expected_profit:.2f}"
        )

        return position_id

    def settle_position(
        self,
        position_id: str,
        settlement_price: float,
    ) -> Optional[float]:
        """
        Settle a position

        Args:
            position_id: Position ID
            settlement_price: Final settlement price (usually $1.00 or $0.00)

        Returns:
            Realized PnL
        """
        with self._lock:
            if position_id not in self.positions:
                logger.warning(f"Position {position_id} not found")
                return None
            position = self.positions[position_id]

        # Calculate PnL
        pnl = (settlement_price - position.entry_price) * position.shares
        pnl_percent = (pnl / (position.entry_price * position.shares)) * 100

        with self._lock:
            position.settlement_price = settlement_price
            position.settled_at = datetime.now()
            position.realized_pnl = pnl
            position.status = "SETTLED"

        # Update PnL tracker
        self.pnl_tracker.close_position(
            position_id=position_id,
            exit_price=settlement_price,
            final_price=settlement_price,
        )

        # Log result
        if pnl >= 0:
            logger.info(
                f"✅ Position settled (WIN): {position_id} - "
                f"PnL: ${pnl:.2f} ({pnl_percent:.2f}%) 🎉"
            )
        else:
            logger.warning(
                f"❌ Position settled (LOSS): {position_id} - "
                f"PnL: ${pnl:.2f} ({pnl_percent:.2f}%)"
            )

        return pnl

    def get_position(self, position_id: str) -> Optional[Position]:
        """Get a position by ID"""
        with self._lock:
            return self.positions.get(position_id)

    def get_open_positions(self) -> List[Position]:
        """Get a snapshot of all open positions (safe to iterate after return)."""
        with self._lock:
            return [p for p in self.positions.values() if p.status == "OPEN"]

    def get_settled_positions(self) -> List[Position]:
        """Get a snapshot of all settled positions."""
        with self._lock:
            return [p for p in self.positions.values() if p.status == "SETTLED"]

    def get_all_positions(self) -> List[Position]:
        """Get a snapshot of all positions."""
        with self._lock:
            return list(self.positions.values())

    def get_position_count(self) -> int:
        """Get number of open positions"""
        return len(self.get_open_positions())

    def can_open_position(self) -> bool:
        """Check if we can open a new position"""
        return self.get_position_count() < self.max_positions

    def get_summary(self) -> Dict:
        """Get position summary"""
        open_positions = self.get_open_positions()
        settled_positions = self.get_settled_positions()

        total_allocated = sum(p.allocated_capital for p in open_positions)
        total_realized_pnl = sum(p.realized_pnl for p in settled_positions if p.realized_pnl)

        wins = [p for p in settled_positions if p.realized_pnl and p.realized_pnl > 0]
        losses = [p for p in settled_positions if p.realized_pnl and p.realized_pnl <= 0]

        return {
            "open_positions": len(open_positions),
            "settled_positions": len(settled_positions),
            "total_positions": len(self.positions),
            "allocated_capital": total_allocated,
            "realized_pnl": total_realized_pnl,
            "wins": len(wins),
            "losses": len(losses),
        }

    def reset(self):
        """Reset tracker"""
        self.positions = {}
        logger.info("Position tracker reset")
