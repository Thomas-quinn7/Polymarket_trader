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


@dataclass(slots=True)
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
    entry_fee: float = 0.0  # fee paid at entry (simulated or actual)
    # Whether this market uses neg-risk (inverse) settlement.
    # Must be passed to create_market_order on the SELL side to produce the
    # correct order hash.  Defaults False (standard markets).
    neg_risk: bool = False
    status: str = "OPEN"  # OPEN, SETTLED, FAILED
    opened_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None  # absolute time this position should settle
    settled_at: Optional[datetime] = None
    settlement_price: Optional[float] = None
    exit_fee: float = 0.0  # fee paid at exit/settlement
    realized_pnl: Optional[float] = None  # net PnL after fees
    gross_pnl: Optional[float] = None  # PnL before fees

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
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "settled_at": self.settled_at.isoformat() if self.settled_at else None,
            "entry_fee": self.entry_fee,
            "exit_fee": self.exit_fee,
            "settlement_price": self.settlement_price,
            "gross_pnl": self.gross_pnl,
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
        entry_fee: float = 0.0,
        slippage_pct: float = 0.0,
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
            position_id = f"{opportunity.market_id}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

        expires_at = getattr(opportunity, "expires_at", None)
        neg_risk = getattr(opportunity, "neg_risk", False)

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
            expires_at=expires_at,
            entry_fee=entry_fee,
            neg_risk=neg_risk,
        )

        with self._lock:
            self.positions[position_id] = position

        # Track in PnL tracker
        self.pnl_tracker.open_position(
            position_id=position_id,
            market_id=opportunity.market_id,
            quantity=shares,
            entry_price=opportunity.current_price,
            entry_fee=entry_fee,
            slippage_pct=slippage_pct,
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
        exit_fee: float = 0.0,
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

            # Guard against double-settle races: mark the position as in-flight
            # immediately so any concurrent call that also holds the lock after us
            # will see a non-OPEN status and bail out before touching the PnL tracker.
            if position.status != "OPEN":
                logger.debug(
                    f"Position {position_id} already {position.status} — skipping settle"
                )
                return None
            position.status = "SETTLING"

            # Snapshot the fields we need for calculation while under the lock.
            shares = position.shares
            allocated_capital = position.allocated_capital
            entry_fee = position.entry_fee

        # PnL computation happens outside the lock — close_position acquires its own
        # internal lock and is safe to call concurrently.  Only the one thread that
        # transitioned status to "SETTLING" above reaches this point.
        net_pnl = self.pnl_tracker.close_position(
            position_id=position_id,
            exit_price=settlement_price,
            final_price=settlement_price,
            exit_fee=exit_fee,
        )

        gross_return = shares * settlement_price
        gross_pnl = gross_return - allocated_capital

        # Write the final settled state atomically.
        with self._lock:
            position.settlement_price = settlement_price
            position.settled_at = datetime.now()
            position.exit_fee = exit_fee
            position.gross_pnl = gross_pnl
            position.realized_pnl = net_pnl
            position.status = "SETTLED"

        return net_pnl

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
        """Get number of open positions."""
        with self._lock:
            return sum(1 for p in self.positions.values() if p.status == "OPEN")

    def can_open_position(self) -> bool:
        """Check if we can open a new position (single lock, single pass).

        Reads config.MAX_POSITIONS live so hot-reloads (via /api/settings or
        config.reload()) take effect immediately without a restart.
        """
        with self._lock:
            open_count = sum(1 for p in self.positions.values() if p.status == "OPEN")
        return open_count < config.MAX_POSITIONS

    def get_summary(self) -> Dict:
        """Get position summary"""
        # Single lock acquisition + single pass over positions
        with self._lock:
            open_count = settled_count = total_count = wins = losses = 0
            total_allocated = total_realized_pnl = 0.0
            for p in self.positions.values():
                total_count += 1
                if p.status == "OPEN":
                    open_count += 1
                    total_allocated += p.allocated_capital
                elif p.status == "SETTLED":
                    settled_count += 1
                    if p.realized_pnl is not None:
                        total_realized_pnl += p.realized_pnl
                        if p.realized_pnl > 0:
                            wins += 1
                        else:
                            losses += 1

        return {
            "open_positions": open_count,
            "settled_positions": settled_count,
            "total_positions": total_count,
            "allocated_capital": total_allocated,
            "realized_pnl": total_realized_pnl,
            "wins": wins,
            "losses": losses,
        }

    def reset(self):
        """Reset tracker"""
        with self._lock:
            self.positions = {}
        logger.info("Position tracker reset")
