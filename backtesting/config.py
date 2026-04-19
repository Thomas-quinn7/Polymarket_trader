# Copyright (C) 2026  Thomas Quinn (github.com/Thomas-quinn7)
#                     Ciaran McDonnell (github.com/CiaranMcDonnell)
# SPDX-License-Identifier: AGPL-3.0-only

from dataclasses import dataclass, asdict
import json


@dataclass
class BacktestConfig:
    # ── Required ──────────────────────────────────────────────────────────────
    strategy_name: str

    # ── Date range ────────────────────────────────────────────────────────────
    start_date: str = "2025-01-01"  # ISO date; inclusive
    end_date: str = "2025-04-01"  # ISO date; inclusive

    # ── Capital model ─────────────────────────────────────────────────────────
    initial_balance: float = 1000.0  # starting USDC
    max_positions: int = 5  # max simultaneous open positions
    capital_per_trade_pct: float = 20.0  # % of current balance per trade entry
    taker_fee_pct: float = 2.0  # entry and exit fee (%)
    # Half the bid/ask spread, applied symmetrically: effective entry price rises
    # by this %, effective exit price falls by this %.  Set to 0 to model fees only.
    # Polymarket prediction markets can have 1–5% spreads on illiquid markets.
    half_spread_pct: float = 0.0

    # ── Market filter ─────────────────────────────────────────────────────────
    category: str = "crypto"  # "crypto" | "fed" | "regulatory" | "other"
    min_volume_usd: float = 500.0  # minimum USDC volume to include market
    max_duration_seconds: int = 1800  # 30-min cap → catches 5m and 15m markets
    # set to 86400 for daily, 0 for no filter

    # ── Price data ────────────────────────────────────────────────────────────
    price_interval: str = "5m"  # "1m" | "5m" | "15m" | "1h"

    # ── Risk-free rate ────────────────────────────────────────────────────────
    # Annual risk-free rate used to compute excess returns for Sharpe/Sortino.
    # Default 0.0 is appropriate for prediction markets: capital locked in a
    # position earns no interest.  Set to e.g. 0.05 to compare against T-bills.
    risk_free_rate_annual: float = 0.0

    # ── API behaviour ─────────────────────────────────────────────────────────
    rate_limit_rps: float = 3.0  # Gamma API requests per second

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, s: str) -> "BacktestConfig":
        return cls(**json.loads(s))

    def validate(self):
        """Raise ValueError on obviously bad config."""
        from datetime import date

        start = date.fromisoformat(self.start_date)
        end = date.fromisoformat(self.end_date)
        if end <= start:
            raise ValueError(
                f"end_date ({self.end_date}) must be after start_date ({self.start_date})"
            )
        if self.initial_balance <= 0:
            raise ValueError("initial_balance must be positive")
        if not (0 < self.capital_per_trade_pct <= 100):
            raise ValueError("capital_per_trade_pct must be in (0, 100]")
        if self.max_positions < 1:
            raise ValueError("max_positions must be >= 1")
        if self.taker_fee_pct < 0:
            raise ValueError("taker_fee_pct cannot be negative")
        if self.half_spread_pct < 0:
            raise ValueError("half_spread_pct cannot be negative")
        if self.price_interval not in ("1m", "5m", "15m", "1h", "4h", "1d"):
            raise ValueError(f"Unknown price_interval: {self.price_interval}")
