"""
PnL Tracker Module
Tracks wins, losses, and PnL evolution for paper trading
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime

from utils.logger import logger


@dataclass
class TradeRecord:
    """Single trade record"""

    trade_id: str
    position_id: str
    market_id: str
    action: str
    quantity: float
    entry_price: float
    exit_price: Optional[float] = None
    entry_time: datetime = field(default_factory=datetime.now)
    exit_time: Optional[datetime] = None
    pnl: Optional[float] = None
    pnl_percent: Optional[float] = None

    def to_dict(self):
        return {
            "trade_id": self.trade_id,
            "position_id": self.position_id,
            "market_id": self.market_id,
            "action": self.action,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "entry_time": self.entry_time.isoformat() if self.entry_time else None,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "pnl": self.pnl,
            "pnl_percent": self.pnl_percent,
        }


@dataclass
class PnLSummary:
    """PnL summary statistics"""

    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    average_win: float = 0.0
    average_loss: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    current_drawdown: float = 0.0
    peak_balance: float = 0.0
    initial_balance: float = 10000.0

    def to_dict(self):
        return {
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "total_pnl": self.total_pnl,
            "win_rate": self.win_rate,
            "average_win": self.average_win,
            "average_loss": self.average_loss,
            "profit_factor": self.profit_factor,
            "max_drawdown": self.max_drawdown,
            "current_drawdown": self.current_drawdown,
            "peak_balance": self.peak_balance,
            "initial_balance": self.initial_balance,
        }


class PnLTracker:
    """
    Tracks wins, losses, and PnL evolution

    Features:
    - Track all trades with entry/exit
    - Calculate win/loss statistics
    - Track PnL over time
    - Calculate drawdown
    - Export trade history
    """

    def __init__(self, initial_balance: float = 10000.0):
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.peak_balance = initial_balance
        self.trades: List[TradeRecord] = []
        self.open_positions: Dict[str, TradeRecord] = {}
        self.max_drawdown = 0.0
        self.current_drawdown = 0.0

        logger.info(f"PnL tracker initialized with ${initial_balance:.2f}")

    def open_position(
        self,
        position_id: str,
        market_id: str,
        quantity: float,
        entry_price: float,
    ) -> str:
        """
        Open a new position

        Args:
            position_id: Position ID
            market_id: Market ID
            quantity: Number of shares
            entry_price: Entry price

        Returns:
            Trade ID
        """
        trade_id = f"{position_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

        trade = TradeRecord(
            trade_id=trade_id,
            position_id=position_id,
            market_id=market_id,
            action="BUY",
            quantity=quantity,
            entry_price=entry_price,
            entry_time=datetime.now(),
        )

        self.open_positions[position_id] = trade
        self.trades.append(trade)

        logger.debug(f"Position opened: {trade_id} - {quantity:.4f} @ ${entry_price:.4f}")

        return trade_id

    def close_position(
        self,
        position_id: str,
        exit_price: float,
        final_price: float = 1.0,  # Settlement price (usually $1.00 or $0.00)
    ) -> Optional[float]:
        """
        Close a position and calculate PnL

        Args:
            position_id: Position ID
            exit_price: Exit price (if sold early)
            final_price: Final settlement price

        Returns:
            Realized PnL
        """
        if position_id not in self.open_positions:
            logger.warning(f"Position {position_id} not found")
            return None

        trade = self.open_positions[position_id]

        # Use exit_price if provided, otherwise use final settlement price
        settlement_price = exit_price if exit_price > 0 else final_price

        # Calculate PnL
        # If YES token settles at $1.00, we get $1.00 per share
        # If NO token settles at $0.00, we get $0.00 per share
        pnl = (settlement_price - trade.entry_price) * trade.quantity
        pnl_percent = (pnl / (trade.entry_price * trade.quantity)) * 100

        trade.exit_price = settlement_price
        trade.exit_time = datetime.now()
        trade.pnl = pnl
        trade.pnl_percent = pnl_percent

        # Update balance
        self.current_balance += pnl

        # Update peak balance and drawdown
        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance
            self.current_drawdown = 0.0
        else:
            self.current_drawdown = (
                (self.peak_balance - self.current_balance) / self.peak_balance * 100
            )
            if abs(self.current_drawdown) > self.max_drawdown:
                self.max_drawdown = abs(self.current_drawdown)

        # Remove from open positions
        del self.open_positions[position_id]

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

    def get_summary(self) -> PnLSummary:
        """
        Calculate PnL summary statistics

        Returns:
            PnLSummary object
        """
        closed_trades = [t for t in self.trades if t.exit_price is not None]

        if not closed_trades:
            return PnLSummary(
                initial_balance=self.initial_balance,
                current_balance=self.current_balance,
                peak_balance=self.peak_balance,
            )

        wins = [t for t in closed_trades if t.pnl > 0]
        losses = [t for t in closed_trades if t.pnl <= 0]

        total_pnl = sum(t.pnl for t in closed_trades)
        win_rate = (len(wins) / len(closed_trades) * 100) if closed_trades else 0.0
        average_win = sum(t.pnl for t in wins) / len(wins) if wins else 0.0
        average_loss = sum(t.pnl for t in losses) / len(losses) if losses else 0.0

        # Profit factor: total profit / total loss (absolute)
        total_profit = sum(t.pnl for t in wins)
        total_loss = abs(sum(t.pnl for t in losses))
        profit_factor = total_profit / total_loss if total_loss > 0 else 0.0

        return PnLSummary(
            total_trades=len(closed_trades),
            wins=len(wins),
            losses=len(losses),
            total_pnl=total_pnl,
            win_rate=win_rate,
            average_win=average_win,
            average_loss=average_loss,
            profit_factor=profit_factor,
            max_drawdown=self.max_drawdown,
            current_drawdown=self.current_drawdown,
            peak_balance=self.peak_balance,
            initial_balance=self.initial_balance,
        )

    def get_open_positions(self) -> List[TradeRecord]:
        """Get list of open positions"""
        return list(self.open_positions.values())

    def get_trade_history(self, limit: Optional[int] = None) -> List[TradeRecord]:
        """Get trade history"""
        trades = [t for t in self.trades if t.exit_price is not None]
        trades.sort(key=lambda x: x.exit_time or x.entry_time, reverse=True)

        if limit:
            return trades[:limit]

        return trades

    def get_recent_trades(self, limit: int = 10) -> List[TradeRecord]:
        """Get recent closed trades"""
        return self.get_trade_history(limit)

    def get_pnl_history(self) -> List[Dict]:
        """Get PnL history over time"""
        history = []
        running_balance = self.initial_balance

        for trade in sorted(
            self.trades, key=lambda x: x.exit_time or x.entry_time
        ):
            if trade.exit_price is not None:
                running_balance += trade.pnl
                history.append(
                    {
                        "timestamp": (trade.exit_time or trade.entry_time).isoformat(),
                        "balance": running_balance,
                        "pnl": trade.pnl,
                        "trade_id": trade.trade_id,
                    }
                )

        return history

    def reset(self, new_balance: Optional[float] = None):
        """Reset tracker"""
        self.initial_balance = new_balance or self.initial_balance
        self.current_balance = self.initial_balance
        self.peak_balance = self.initial_balance
        self.trades = []
        self.open_positions = {}
        self.max_drawdown = 0.0
        self.current_drawdown = 0.0

        logger.info(f"PnL tracker reset with ${self.initial_balance:.2f}")

    def get_report(self) -> str:
        """Generate formatted PnL report"""
        summary = self.get_summary()

        report = f"""
╔════════════════════════════════════════════════════════════════╗
║                    P&L REPORT                                    ║
╠════════════════════════════════════════════════════════════════╣
║ Balance                                                        ║
║   Initial:     ${summary.initial_balance:>12,.2f}                ║
║   Current:     ${self.current_balance:>12,.2f}                ║
║   Peak:        ${summary.peak_balance:>12,.2f}                 ║
║   Change:      ${summary.total_pnl:>12,.2f} ({summary.total_pnl/summary.initial_balance*100:>6.2f}%) ║
║                                                                 ║
║ Trade Statistics                                               ║
║   Total Trades: {summary.total_trades:>8}                             ║
║   Wins:        {summary.wins:>8} ({summary.win_rate:>5.1f}%)             ║
║   Losses:      {summary.losses:>8} ({100-summary.win_rate:>5.1f}%)           ║
║                                                                 ║
║ Performance                                                     ║
║   Avg Win:     ${summary.average_win:>12,.2f}                ║
║   Avg Loss:    ${summary.average_loss:>12,.2f}                ║
║   Profit Factor: {summary.profit_factor:>9.2f}                          ║
║                                                                 ║
║ Drawdown                                                       ║
║   Max DD:      {summary.max_drawdown:>9.2f}%                          ║
║   Current DD:  {summary.current_drawdown:>9.2f}%                          ║
╚════════════════════════════════════════════════════════════════╝
"""

        return report
