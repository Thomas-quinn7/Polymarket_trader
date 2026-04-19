# Copyright (C) 2026  Thomas Quinn (github.com/Thomas-quinn7)
#                     Ciaran McDonnell (github.com/CiaranMcDonnell)
# SPDX-License-Identifier: AGPL-3.0-only

import math
import statistics
from dataclasses import dataclass, asdict
from typing import List, Optional, Tuple

from utils.pnl_tracker import PnLTracker


@dataclass
class BacktestMetrics:
    # ── From PnLTracker (reused) ──────────────────────────────────────────────
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    break_evens: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0  # percentage, e.g. 12.5 = 12.5%
    total_gross_pnl: float = 0.0
    total_net_pnl: float = 0.0
    total_fees: float = 0.0
    average_win: float = 0.0
    average_loss: float = 0.0

    # ── Extended metrics ──────────────────────────────────────────────────────
    total_return_pct: float = 0.0
    annualized_return: float = 0.0
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    calmar_ratio: Optional[float] = None
    consec_wins_max: int = 0
    consec_losses_max: int = 0
    avg_hold_seconds: float = 0.0
    avg_hold_win_seconds: float = 0.0
    avg_hold_loss_seconds: float = 0.0
    fee_drag_pct: float = 0.0
    final_balance: float = 0.0
    initial_balance: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class MetricsCalculator:
    """
    Computes BacktestMetrics from a list of SimTrade-like dicts and an equity curve.
    Reuses PnLTracker for base metrics to avoid duplication.
    Extends with Sharpe, Sortino, Calmar, annualized return, etc.
    """

    def compute(
        self,
        trades: list,
        equity_curve: List[Tuple[int, float]],
        config,
    ) -> BacktestMetrics:
        m = BacktestMetrics()
        m.initial_balance = config.initial_balance

        if not trades:
            m.final_balance = config.initial_balance
            return m

        # ── Feed trades into PnLTracker ───────────────────────────────────────
        # Use a unique position_id per trade (condition_id + entry_ts) so that
        # markets with multiple simulated trades don't collide in the tracker.
        tracker = PnLTracker(initial_balance=config.initial_balance)
        for t in trades:
            td = t if isinstance(t, dict) else vars(t)
            position_id = f"{td['condition_id']}_{td['entry_ts']}"
            tracker.open_position(
                position_id=position_id,
                market_id=td["condition_id"],
                quantity=td["shares"],
                entry_price=td["entry_price"],
                entry_fee=td.get("entry_fee", 0.0),
            )
            tracker.close_position(
                position_id=position_id,
                exit_price=td.get("exit_price", td["entry_price"]),
                exit_fee=td.get("exit_fee", 0.0),
            )

        summary = tracker.get_summary()
        m.total_trades = summary.total_trades
        m.wins = summary.wins
        m.losses = summary.losses
        m.win_rate = (
            summary.win_rate / 100.0
        )  # PnLTracker stores 0–100; BacktestMetrics uses 0.0–1.0
        m.profit_factor = summary.profit_factor
        m.max_drawdown = summary.max_drawdown
        m.total_gross_pnl = summary.gross_pnl
        m.total_net_pnl = summary.total_pnl
        m.total_fees = summary.total_fees_paid
        m.average_win = summary.average_win
        m.average_loss = summary.average_loss

        # ── Final balance ─────────────────────────────────────────────────────
        if equity_curve:
            m.final_balance = equity_curve[-1][1]
        else:
            m.final_balance = config.initial_balance + m.total_net_pnl

        m.total_return_pct = (
            (m.final_balance - config.initial_balance) / config.initial_balance * 100
            if config.initial_balance > 0
            else 0.0
        )

        # ── Annualized return ─────────────────────────────────────────────────
        from datetime import date

        years = 0.0
        try:
            start = date.fromisoformat(config.start_date)
            end = date.fromisoformat(config.end_date)
            years = (end - start).days / 365.25
            if years > 0 and m.total_return_pct > -100:
                m.annualized_return = ((1 + m.total_return_pct / 100) ** (1 / years) - 1) * 100
        except Exception:
            m.annualized_return = 0.0

        # ── Per-trade returns for Sharpe/Sortino ──────────────────────────────
        # NOTE: This is trade-frequency Sharpe, not calendar-day Sharpe.
        # Each trade is treated as one period; annualisation uses sqrt(trades/year).
        # This interpretation is valid but differs from institutional convention
        # (daily-return Sharpe).  The two will diverge when trade frequency is
        # irregular or hold times are long relative to the backtest window.
        returns = [
            (t if isinstance(t, dict) else vars(t)).get("net_pnl", 0.0)
            / max(
                (t if isinstance(t, dict) else vars(t)).get("allocated_capital", 1.0),
                0.001,
            )
            for t in trades
        ]

        if len(returns) >= 2:
            mean_r = statistics.mean(returns)
            stdev_r = statistics.stdev(returns)
            downside = [r for r in returns if r < 0]

            effective_years = max(years, 1 / 365)
            trades_per_year = m.total_trades / effective_years
            ann_factor = math.sqrt(trades_per_year)

            # Convert annual risk-free rate to per-trade equivalent so excess
            # returns are on the same frequency basis as the return series.
            rf_per_trade = getattr(config, "risk_free_rate_annual", 0.0) / max(trades_per_year, 1)
            excess_mean_r = mean_r - rf_per_trade

            if stdev_r > 0:
                m.sharpe_ratio = round(excess_mean_r / stdev_r * ann_factor, 4)

            if len(downside) >= 2:
                stdev_down = statistics.stdev(downside)
                if stdev_down > 0:
                    m.sortino_ratio = round(excess_mean_r / stdev_down * ann_factor, 4)

        if m.max_drawdown > 0 and m.annualized_return is not None:
            m.calmar_ratio = round(m.annualized_return / m.max_drawdown, 4)

        # ── Consecutive wins/losses ───────────────────────────────────────────
        max_consec_w = consec_w = 0
        max_consec_l = consec_l = 0
        for t in trades:
            td = t if isinstance(t, dict) else vars(t)
            if td.get("outcome") == "WIN":
                consec_w += 1
                consec_l = 0
                max_consec_w = max(max_consec_w, consec_w)
            elif td.get("outcome") == "LOSS":
                consec_l += 1
                consec_w = 0
                max_consec_l = max(max_consec_l, consec_l)
            else:
                consec_w = consec_l = 0
        m.consec_wins_max = max_consec_w
        m.consec_losses_max = max_consec_l

        # ── Hold times ────────────────────────────────────────────────────────
        hold_all: list = []
        hold_wins: list = []
        hold_losses: list = []
        for t in trades:
            td = t if isinstance(t, dict) else vars(t)
            if td.get("entry_ts") and td.get("exit_ts"):
                h = td["exit_ts"] - td["entry_ts"]
                hold_all.append(h)
                if td.get("outcome") == "WIN":
                    hold_wins.append(h)
                elif td.get("outcome") == "LOSS":
                    hold_losses.append(h)
        m.avg_hold_seconds = statistics.mean(hold_all) if hold_all else 0.0
        m.avg_hold_win_seconds = statistics.mean(hold_wins) if hold_wins else 0.0
        m.avg_hold_loss_seconds = statistics.mean(hold_losses) if hold_losses else 0.0

        # ── Fee drag ──────────────────────────────────────────────────────────
        if abs(m.total_gross_pnl) > 0.001:
            m.fee_drag_pct = round(m.total_fees / abs(m.total_gross_pnl) * 100, 2)

        m.break_evens = m.total_trades - m.wins - m.losses

        return m
