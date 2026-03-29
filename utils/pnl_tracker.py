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

        settlement_price = exit_price

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
                peak_balance=self.peak_balance,
                initial_balance=self.initial_balance,
            )

        # Single pass over closed trades
        wins_count = losses_count = 0
        total_pnl = total_win_pnl = total_loss_pnl = 0.0
        for t in closed_trades:
            total_pnl += t.pnl
            if t.pnl > 0:
                wins_count += 1
                total_win_pnl += t.pnl
            else:
                losses_count += 1
                total_loss_pnl += t.pnl

        total_trades = len(closed_trades)
        win_rate = wins_count / total_trades * 100
        average_win = total_win_pnl / wins_count if wins_count else 0.0
        average_loss = total_loss_pnl / losses_count if losses_count else 0.0
        abs_loss = abs(total_loss_pnl)
        profit_factor = total_win_pnl / abs_loss if abs_loss > 0 else 0.0

        return PnLSummary(
            total_trades=total_trades,
            wins=wins_count,
            losses=losses_count,
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

        pnl_pct = summary.total_pnl / summary.initial_balance * 100 if summary.initial_balance else 0
        W = 50  # inner width between the two ║ chars

        def row(label: str, value: str) -> str:
            content = f"  {label:<16}{value}"
            return f"║ {content:<{W}} ║"

        def section(title: str) -> str:
            return f"║ {title:<{W}} ║"

        def blank() -> str:
            return f"║ {'':<{W}} ║"

        border = "═" * (W + 2)
        lines = [
            f"╔{border}╗",
            f"║{'P&L REPORT':^{W+2}}║",
            f"╠{border}╣",
            section("Balance"),
            row("Initial:",  f"${summary.initial_balance:>13,.2f}"),
            row("Current:",  f"${self.current_balance:>13,.2f}"),
            row("Peak:",     f"${summary.peak_balance:>13,.2f}"),
            row("Change:",   f"${summary.total_pnl:>13,.2f}  ({pnl_pct:+.2f}%)"),
            blank(),
            section("Trade Statistics"),
            row("Total Trades:", f"{summary.total_trades:>8}"),
            row("Wins:",         f"{summary.wins:>8}  ({summary.win_rate:>5.1f}%)"),
            row("Losses:",       f"{summary.losses:>8}  ({100 - summary.win_rate:>5.1f}%)"),
            blank(),
            section("Performance"),
            row("Avg Win:",       f"${summary.average_win:>13,.2f}"),
            row("Avg Loss:",      f"${summary.average_loss:>13,.2f}"),
            row("Profit Factor:", f"{summary.profit_factor:>13.2f}"),
            blank(),
            section("Drawdown"),
            row("Max DD:",     f"{summary.max_drawdown:>12.2f}%"),
            row("Current DD:", f"{summary.current_drawdown:>12.2f}%"),
            f"╚{border}╝",
        ]
        report = "\n" + "\n".join(lines) + "\n"

        return report
