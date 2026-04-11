"""
PnL Tracker Module
Tracks wins, losses, and PnL evolution for paper trading
"""

import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime

from utils.logger import logger


@dataclass(slots=True)
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
    # Net PnL after fees (what hits the balance)
    pnl: Optional[float] = None
    pnl_percent: Optional[float] = None
    # Gross PnL before fees: (exit_price - entry_price) * quantity
    gross_pnl: Optional[float] = None
    # Fees
    entry_fee: float = 0.0
    exit_fee: float = 0.0
    # Slippage on entry: positive = filled worse than expected (cost more)
    slippage_pct: float = 0.0

    @property
    def total_fees(self) -> float:
        return self.entry_fee + self.exit_fee

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
            "gross_pnl": self.gross_pnl,
            "entry_fee": self.entry_fee,
            "exit_fee": self.exit_fee,
            "total_fees": self.total_fees,
            "slippage_pct": self.slippage_pct,
        }


@dataclass(slots=True)
class PnLSummary:
    """PnL summary statistics"""

    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0  # Net PnL after fees
    gross_pnl: float = 0.0  # PnL before fees
    total_fees_paid: float = 0.0  # All entry + exit fees
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
            "gross_pnl": self.gross_pnl,
            "total_fees_paid": self.total_fees_paid,
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
        # Closed trades kept separately so get_summary() avoids a full O(n) scan every call.
        self._closed_trades: List[TradeRecord] = []
        self.open_positions: Dict[str, TradeRecord] = {}
        self.max_drawdown = 0.0
        self.current_drawdown = 0.0
        self._lock = threading.Lock()

        logger.info(f"PnL tracker initialized with ${initial_balance:.2f}")

    def open_position(
        self,
        position_id: str,
        market_id: str,
        quantity: float,
        entry_price: float,
        entry_fee: float = 0.0,
        slippage_pct: float = 0.0,
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
        if quantity <= 0:
            raise ValueError(
                f"quantity must be positive, got {quantity!r} for position {position_id}"
            )

        trade_id = f"{position_id}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

        trade = TradeRecord(
            trade_id=trade_id,
            position_id=position_id,
            market_id=market_id,
            action="BUY",
            quantity=quantity,
            entry_price=entry_price,
            entry_time=datetime.now(),
            entry_fee=entry_fee,
            slippage_pct=slippage_pct,
        )

        with self._lock:
            self.open_positions[position_id] = trade
            self.trades.append(trade)

        logger.debug(f"Position opened: {trade_id} - {quantity:.4f} @ ${entry_price:.4f}")

        return trade_id

    def close_position(
        self,
        position_id: str,
        exit_price: float,
        final_price: float = 1.0,  # Settlement price (usually $1.00 or $0.00)
        exit_fee: float = 0.0,
    ) -> Optional[float]:
        """
        Close a position and calculate PnL (net of all fees).

        Args:
            position_id: Position ID
            exit_price: Exit/settlement price
            final_price: Unused legacy param (kept for call-site compatibility)
            exit_fee: Fee paid on exit/settlement

        Returns:
            Net realized PnL (after entry and exit fees)
        """
        with self._lock:
            if position_id not in self.open_positions:
                logger.warning(f"Position {position_id} not found")
                return None
            trade = self.open_positions[position_id]

        settlement_price = exit_price

        # Gross PnL: raw price change
        gross_pnl = (settlement_price - trade.entry_price) * trade.quantity
        # Net PnL: deduct both entry fee (paid at open) and exit fee (paid at close)
        total_fees = trade.entry_fee + exit_fee
        net_pnl = gross_pnl - total_fees
        cost_basis = trade.entry_price * trade.quantity
        pnl_percent = (net_pnl / cost_basis * 100) if cost_basis != 0 else 0.0

        trade.exit_price = settlement_price
        trade.exit_time = datetime.now()
        trade.gross_pnl = gross_pnl
        trade.exit_fee = exit_fee
        trade.pnl = net_pnl
        trade.pnl_percent = pnl_percent

        with self._lock:
            # Update balance with net PnL so it correctly reflects fees paid
            self.current_balance += net_pnl

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

            # Remove from open positions and add to the closed-trade index
            del self.open_positions[position_id]
            self._closed_trades.append(trade)

        # Log result
        fee_str = f" | fees ${total_fees:.2f}" if total_fees > 0 else ""
        if net_pnl >= 0:
            logger.info(
                f"✅ Position settled (WIN): {position_id} - "
                f"gross ${gross_pnl:.2f}, net ${net_pnl:.2f} ({pnl_percent:.2f}%){fee_str} 🎉"
            )
        else:
            logger.warning(
                f"❌ Position settled (LOSS): {position_id} - "
                f"gross ${gross_pnl:.2f}, net ${net_pnl:.2f} ({pnl_percent:.2f}%){fee_str}"
            )

        return net_pnl

    def get_summary(self) -> PnLSummary:
        """
        Calculate PnL summary statistics

        Returns:
            PnLSummary object
        """
        with self._lock:
            # _closed_trades is updated incrementally in close_position — O(1) per close,
            # so this snapshot is O(k) where k = closed trades, not O(all trades).
            closed_trades = list(self._closed_trades)
            peak_balance = self.peak_balance
            max_drawdown = self.max_drawdown
            current_drawdown = self.current_drawdown

        if not closed_trades:
            return PnLSummary(
                peak_balance=peak_balance,
                initial_balance=self.initial_balance,
            )

        # Single pass over closed trades
        wins_count = losses_count = 0
        total_pnl = total_win_pnl = total_loss_pnl = 0.0
        total_gross_pnl = total_fees = 0.0
        for t in closed_trades:
            total_pnl += t.pnl
            total_gross_pnl += t.gross_pnl or 0.0
            total_fees += t.total_fees
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
            gross_pnl=total_gross_pnl,
            total_fees_paid=total_fees,
            win_rate=win_rate,
            average_win=average_win,
            average_loss=average_loss,
            profit_factor=profit_factor,
            max_drawdown=max_drawdown,
            current_drawdown=current_drawdown,
            peak_balance=peak_balance,
            initial_balance=self.initial_balance,
        )

    def get_open_positions(self) -> List[TradeRecord]:
        """Get list of open positions"""
        with self._lock:
            return list(self.open_positions.values())

    def get_trade_history(self, limit: Optional[int] = None) -> List[TradeRecord]:
        """Get trade history"""
        with self._lock:
            trades = list(self._closed_trades)
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

        with self._lock:
            trades_snapshot = list(self.trades)

        for trade in sorted(trades_snapshot, key=lambda x: x.exit_time or x.entry_time):
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
        with self._lock:
            self.initial_balance = new_balance or self.initial_balance
            self.current_balance = self.initial_balance
            self.peak_balance = self.initial_balance
            self.trades = []
            self._closed_trades = []
            self.open_positions = {}
            self.max_drawdown = 0.0
            self.current_drawdown = 0.0

        logger.info(f"PnL tracker reset with ${self.initial_balance:.2f}")

    def get_report(self) -> str:
        """Generate formatted PnL report"""
        summary = self.get_summary()

        pnl_pct = (
            summary.total_pnl / summary.initial_balance * 100 if summary.initial_balance else 0
        )
        gross_pct = (
            summary.gross_pnl / summary.initial_balance * 100 if summary.initial_balance else 0
        )
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
            row("Initial:", f"${summary.initial_balance:>13,.2f}"),
            row("Current:", f"${self.current_balance:>13,.2f}"),
            row("Peak:", f"${summary.peak_balance:>13,.2f}"),
            row("Net Change:", f"${summary.total_pnl:>13,.2f}  ({pnl_pct:+.2f}%)"),
            blank(),
            section("Trade Statistics"),
            row("Total Trades:", f"{summary.total_trades:>8}"),
            row("Wins:", f"{summary.wins:>8}  ({summary.win_rate:>5.1f}%)"),
            row("Losses:", f"{summary.losses:>8}  ({100 - summary.win_rate:>5.1f}%)"),
            blank(),
            section("Performance"),
            row("Gross PnL:", f"${summary.gross_pnl:>13,.2f}  ({gross_pct:+.2f}%)"),
            row("Fees Paid:", f"${summary.total_fees_paid:>13,.2f}"),
            row("Net PnL:", f"${summary.total_pnl:>13,.2f}  ({pnl_pct:+.2f}%)"),
            row("Avg Win:", f"${summary.average_win:>13,.2f}"),
            row("Avg Loss:", f"${summary.average_loss:>13,.2f}"),
            row("Profit Factor:", f"{summary.profit_factor:>13.2f}"),
            blank(),
            section("Drawdown"),
            row("Max DD:", f"{summary.max_drawdown:>12.2f}%"),
            row("Current DD:", f"{summary.current_drawdown:>12.2f}%"),
            f"╚{border}╝",
        ]
        report = "\n" + "\n".join(lines) + "\n"

        return report
