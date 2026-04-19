# Copyright (C) 2026  Thomas Quinn (github.com/Thomas-quinn7)
#                     Ciaran McDonnell (github.com/CiaranMcDonnell)
# SPDX-License-Identifier: AGPL-3.0-only

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from data.market_schema import PolymarketMarket
from strategies.base import BaseStrategy
from backtesting.config import BacktestConfig
from backtesting.db import BacktestDB

logger = logging.getLogger(__name__)

_MIN_TICKS = 3


@dataclass
class SimPosition:
    """A simulated open position during replay."""

    condition_id: str
    question: str
    entry_ts: int
    entry_price: float
    shares: float
    allocated_capital: float
    entry_fee: float
    side: str = "YES"  # "YES" or "NO"


@dataclass
class SimTrade:
    """A fully closed simulated trade."""

    strategy_name: str
    condition_id: str
    question: str
    entry_ts: int
    exit_ts: int
    entry_price: float
    exit_price: float
    shares: float
    allocated_capital: float
    side: str
    gross_pnl: float
    net_pnl: float
    entry_fee: float
    exit_fee: float
    outcome: str  # WIN|LOSS|BREAK_EVEN|TIMEOUT
    exit_reason: str  # settlement|strategy_exit|timeout


class _NullClient:
    """
    Stub that satisfies the client constructor requirement but raises on any API call.
    Any strategy that calls client methods directly (instead of reading resolved_price)
    will fail loudly here, signalling it needs to be updated.
    """

    def __getattr__(self, name):
        raise NotImplementedError(
            f"Strategy called client.{name}() during backtest. "
            f"Strategies must read market.resolved_price instead of calling the client directly."
        )


class ReplayEngine:
    """
    Replays historical YES-token price series through a strategy's interface.

    The engine synthesises PolymarketMarket objects with resolved_price set to
    the historical price at each tick, then calls the strategy's scan / exit
    methods exactly as the live bot does. No strategy modifications needed.
    """

    def __init__(self, strategy: BaseStrategy, config: BacktestConfig, db: BacktestDB):
        self._strategy = strategy
        self._config = config
        self._db = db

    def run(
        self,
        condition_ids: List[str],
        price_histories: Dict[str, List[Tuple[int, float]]],
    ) -> Tuple[List[SimTrade], List[Tuple[int, float]]]:
        """
        Run the full backtest replay using a wall-clock-driven timeline.

        All markets advance together in chronological order. At each timestamp
        the strategy receives the full list of currently visible markets,
        matching the call pattern of the live bot.

        Args:
            condition_ids: Markets to replay (from BacktestDB).
            price_histories: Dict of condition_id → sorted [(ts, price)] list.

        Returns:
            (trades, equity_curve) where equity_curve is [(ts, balance)].
        """
        balance = self._config.initial_balance
        open_positions: Dict[str, SimPosition] = {}
        trades: List[SimTrade] = []
        equity_curve: List[Tuple[int, float]] = [(0, balance)]

        market_rows = {
            r["condition_id"]: r
            for r in self._db.get_markets_in_range(
                self._config.start_date + "T00:00:00+00:00",
                self._config.end_date + "T23:59:59+00:00",
                category=self._config.category,
            )
        }

        # Filter to markets with sufficient price history.
        valid_ids = [
            cid
            for cid in condition_ids
            if price_histories.get(cid) and len(price_histories[cid]) >= _MIN_TICKS
        ]
        if not valid_ids:
            return trades, equity_curve

        # Per-market tick lookup and terminal timestamp.
        tick_index: Dict[str, Dict[int, float]] = {
            cid: {ts: price for ts, price in price_histories[cid]} for cid in valid_ids
        }
        last_tick_ts: Dict[str, int] = {cid: price_histories[cid][-1][0] for cid in valid_ids}

        # Pre-compute per-market metadata used in every tick.
        end_dts: Dict[str, Optional[datetime]] = {}
        resolutions: Dict[str, float] = {}
        questions: Dict[str, str] = {}
        no_resolution: List[str] = []
        for cid in valid_ids:
            mrow = market_rows.get(cid)
            questions[cid] = mrow["question"] if mrow else ""
            if mrow and mrow["resolution"] is not None:
                resolutions[cid] = float(mrow["resolution"])
            else:
                no_resolution.append(cid)
            end_dts[cid] = None
            if mrow:
                try:
                    end_dts[cid] = datetime.fromisoformat(mrow["end_time"].replace("Z", "+00:00"))
                except (KeyError, ValueError, TypeError):
                    pass

        if no_resolution:
            logger.warning(
                "Skipping %d market(s) with no recorded resolution: %s",
                len(no_resolution),
                no_resolution[:5],
            )
            skip_set = set(no_resolution)
            valid_ids = [cid for cid in valid_ids if cid not in skip_set]
            if not valid_ids:
                return trades, equity_curve

        # Global wall-clock timeline — union of all market tick timestamps.
        all_timestamps = sorted({ts for cid in valid_ids for ts in tick_index[cid]})

        # last_known_price tracks the most recent price per market as time advances.
        # A market only becomes visible to the strategy once it has at least one tick.
        last_known_price: Dict[str, float] = {}

        for ts in all_timestamps:
            # ── Step 1: advance prices for every market with a tick at this ts ──
            for cid in valid_ids:
                if ts in tick_index[cid]:
                    last_known_price[cid] = tick_index[cid][ts]

            # ── Step 2: process exits before any new entries ──────────────────
            for cid in list(open_positions.keys()):
                yes_price = last_known_price.get(cid)
                if yes_price is None:
                    continue

                pos = open_positions[cid]
                # Deliver the price from the perspective of the held token side.
                side_price = yes_price if pos.side == "YES" else max(1.0 - yes_price, 0.001)

                if ts >= last_tick_ts[cid]:
                    # Settle at the resolution price for this side.
                    settle_price = resolutions[cid] if pos.side == "YES" else 1.0 - resolutions[cid]
                    trade, balance = self._settle(
                        pos,
                        settle_price,
                        ts,
                        balance,
                        "settlement",
                        cid,
                        questions[cid],
                    )
                    trades.append(trade)
                    equity_curve.append((ts, balance))
                    del open_positions[cid]

                elif self._strategy.should_exit(pos, side_price):
                    exit_price = self._strategy.get_exit_price(pos, side_price)
                    trade, balance = self._settle(
                        pos,
                        exit_price,
                        ts,
                        balance,
                        "strategy_exit",
                        cid,
                        questions[cid],
                    )
                    trades.append(trade)
                    equity_curve.append((ts, balance))
                    del open_positions[cid]

            # ── Step 3: scan for new entries if capacity allows ───────────────
            if len(open_positions) < self._config.max_positions:
                # Build the full list of markets visible at this tick.
                # Excludes markets already held and those at or past their final tick.
                visible = [
                    self._build_market(
                        cid,
                        market_rows.get(cid),
                        last_known_price[cid],
                        ts,
                        end_dts[cid],
                    )
                    for cid in valid_ids
                    if cid in last_known_price
                    and cid not in open_positions
                    and ts < last_tick_ts[cid]
                ]

                if visible:
                    opportunities = self._strategy.scan_for_opportunities(visible)
                    if opportunities:
                        slots = self._config.max_positions - len(open_positions)
                        best = self._strategy.get_best_opportunities(opportunities, limit=slots)
                        for opp in best:
                            if len(open_positions) >= self._config.max_positions:
                                break
                            cid = opp.market_id
                            if cid in open_positions:
                                continue
                            pos, balance = self._enter(
                                opp,
                                cid,
                                questions.get(cid, ""),
                                ts,
                                last_known_price[cid],
                                balance,
                            )
                            if pos:
                                open_positions[cid] = pos

        # Safety net: settle anything still open after the full timeline.
        # Normally empty — markets are settled at their last tick above.
        for cid, pos in list(open_positions.items()):
            last_ts = last_tick_ts.get(cid, pos.entry_ts)
            trade, balance = self._settle(
                pos,
                0.5,
                last_ts,
                balance,
                "timeout",
                cid,
                "Timeout — market still open at end of backtest range",
            )
            trades.append(trade)

        return trades, equity_curve

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_market(self, condition_id, mrow, price, ts, end_dt) -> PolymarketMarket:
        """Build a synthetic PolymarketMarket for the strategy to evaluate."""
        market = PolymarketMarket(
            market_id=condition_id,
            slug=mrow["slug"] if mrow else condition_id,
            question=mrow["question"] if mrow else "",
            token_ids=(
                [
                    mrow["token_id_yes"] or "",
                    mrow["token_id_no"] or "",
                ]
                if mrow
                else []
            ),
            category=mrow["category"] if mrow else "crypto",
            volume=float(mrow["volume"]) if mrow else 0.0,
            end_time=end_dt,
            outcome_prices=[price, 1.0 - price],
        )
        market.resolved_price = price
        return market

    def _enter(
        self, opportunity, condition_id, question, ts, yes_price, balance
    ) -> Tuple[Optional[SimPosition], float]:
        """Open a new simulated position. Returns (SimPosition, updated_balance)."""
        # Determine which side of the market this opportunity trades.
        # Prefer the explicit `side` attribute; fall back to token ID comparison.
        side = "YES"
        opp_side = getattr(opportunity, "side", None)
        if isinstance(opp_side, str) and opp_side.upper() == "NO":
            side = "NO"
        else:
            winning = getattr(opportunity, "winning_token_id", None)
            yes_token = getattr(opportunity, "token_id_yes", None)
            if (
                isinstance(winning, str)
                and isinstance(yes_token, str)
                and winning
                and yes_token
                and winning != yes_token
            ):
                side = "NO"

        # Price from the perspective of the held token, adjusted for half-spread.
        raw_price = yes_price if side == "YES" else max(1.0 - yes_price, 0.001)
        spread_adj = raw_price * (getattr(self._config, "half_spread_pct", 0.0) / 100.0)
        price = raw_price + spread_adj  # pay spread on entry

        capital = balance * (self._config.capital_per_trade_pct / 100.0)
        if capital <= 0 or balance < capital:
            return None, balance

        shares = capital / price if price > 0 else 0
        if shares <= 0:
            return None, balance

        entry_fee = capital * (self._config.taker_fee_pct / 100.0)
        balance -= capital + entry_fee

        pos = SimPosition(
            condition_id=condition_id,
            question=question,
            entry_ts=ts,
            entry_price=price,
            shares=shares,
            allocated_capital=capital,
            entry_fee=entry_fee,
            side=side,
        )
        return pos, balance

    def _settle(
        self,
        pos: SimPosition,
        exit_price: float,
        exit_ts: int,
        balance: float,
        reason: str,
        condition_id: str,
        question: str,
    ) -> Tuple[SimTrade, float]:
        """Close a position and return (SimTrade, updated_balance)."""
        # Settlement is token redemption — free. Strategy exits cross the spread.
        if reason == "settlement":
            effective_exit = exit_price
            exit_fee = 0.0
        else:
            spread_adj = exit_price * (getattr(self._config, "half_spread_pct", 0.0) / 100.0)
            effective_exit = exit_price - spread_adj  # receive less on exit
            exit_fee = effective_exit * pos.shares * (self._config.taker_fee_pct / 100.0)

        gross_pnl = (effective_exit - pos.entry_price) * pos.shares
        net_pnl = gross_pnl - exit_fee
        balance += pos.allocated_capital + gross_pnl - exit_fee

        if reason == "timeout":
            outcome = "TIMEOUT"
        elif net_pnl > 0.001:
            outcome = "WIN"
        elif net_pnl < -0.001:
            outcome = "LOSS"
        else:
            outcome = "BREAK_EVEN"

        trade = SimTrade(
            strategy_name=self._config.strategy_name,
            condition_id=condition_id,
            question=question,
            entry_ts=pos.entry_ts,
            exit_ts=exit_ts,
            entry_price=pos.entry_price,
            exit_price=effective_exit,
            shares=pos.shares,
            allocated_capital=pos.allocated_capital,
            side=pos.side,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            entry_fee=pos.entry_fee,
            exit_fee=exit_fee,
            outcome=outcome,
            exit_reason=reason,
        )
        return trade, balance
