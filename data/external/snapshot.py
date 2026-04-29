# Copyright (C) 2026  Thomas Quinn (github.com/Thomas-quinn7)
# SPDX-License-Identifier: AGPL-3.0-only
"""
Immutable snapshot of all external market signals at a single point in time.

Passed as the optional `ext` parameter to Strategy.scan_for_opportunities().
All fields are Optional — a missing value means the provider was unavailable
or outside its TTL. Strategies must guard with `is not None`.

Convenience methods (is_fear_regime, is_overbought, etc.) always return
False when the underlying data is unavailable, making them safe to call
unconditionally inside strategy logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional


@dataclass
class ExternalSnapshot:
    """Snapshot of all external market signals at a single moment."""

    # ── Crypto spot prices (USD) ─────────────────────────────────────────────
    # Keyed by UPPERCASE symbol: {"BTC": 94500.0, "ETH": 1820.0, "SOL": 145.0}
    crypto_prices: Dict[str, float] = field(default_factory=dict)

    # 14-period RSI on 1-hour candles (0–100).
    # >70 = overbought (bearish signal), <30 = oversold (bullish signal).
    crypto_rsi_1h: Dict[str, float] = field(default_factory=dict)

    # 24-hour price change as a percentage. Negative = price fell.
    crypto_change_24h: Dict[str, float] = field(default_factory=dict)

    # 24-hour trading volume in USD (quote volume, i.e. USDT).
    crypto_volume_24h: Dict[str, float] = field(default_factory=dict)

    # ── Sentiment ────────────────────────────────────────────────────────────
    # Alternative.me Crypto Fear & Greed Index (0–100).
    # 0–24 = Extreme Fear | 25–49 = Fear | 50 = Neutral |
    # 51–74 = Greed | 75–100 = Extreme Greed
    fear_greed_index: Optional[int] = None
    fear_greed_label: Optional[str] = None  # "Extreme Fear", "Fear", "Greed", etc.

    # ── Macro (FRED) ─────────────────────────────────────────────────────────
    # Federal Funds Effective Rate (%)
    fed_funds_rate: Optional[float] = None
    # CPI All Urban Consumers (index level — FRED series CPIAUCSL)
    cpi_level: Optional[float] = None
    # Core PCE Price Index (index level — Fed's preferred inflation measure)
    core_pce_level: Optional[float] = None
    # US Unemployment Rate (%)
    unemployment_rate: Optional[float] = None

    # ── Metadata ─────────────────────────────────────────────────────────────
    # UTC timestamp when this snapshot was assembled by ExternalDataBus.
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # ─────────────────────────────────────────────────────────────────────────
    # Convenience accessors — all return a safe default when data unavailable
    # ─────────────────────────────────────────────────────────────────────────

    def price(self, symbol: str) -> Optional[float]:
        """Spot price for symbol (e.g. 'BTC'). None if unavailable."""
        return self.crypto_prices.get(symbol.upper())

    def rsi(self, symbol: str) -> Optional[float]:
        """1-hour RSI for symbol. None if unavailable."""
        return self.crypto_rsi_1h.get(symbol.upper())

    def change_24h(self, symbol: str) -> Optional[float]:
        """24h % price change for symbol. None if unavailable."""
        return self.crypto_change_24h.get(symbol.upper())

    def is_fear_regime(self, threshold: int = 30) -> bool:
        """True when Fear & Greed is below threshold (bearish/fearful market).
        Returns False (safe) when F&G data is unavailable."""
        return self.fear_greed_index is not None and self.fear_greed_index < threshold

    def is_greed_regime(self, threshold: int = 70) -> bool:
        """True when Fear & Greed is above threshold (greedy/risky market).
        Returns False (safe) when F&G data is unavailable."""
        return self.fear_greed_index is not None and self.fear_greed_index > threshold

    def is_overbought(self, symbol: str, threshold: float = 70.0) -> bool:
        """True when 1h RSI for symbol exceeds threshold. False if RSI unavailable."""
        r = self.rsi(symbol)
        return r is not None and r > threshold

    def is_oversold(self, symbol: str, threshold: float = 30.0) -> bool:
        """True when 1h RSI for symbol is below threshold. False if RSI unavailable."""
        r = self.rsi(symbol)
        return r is not None and r < threshold

    def age_seconds(self) -> float:
        """Seconds elapsed since this snapshot was captured."""
        return (datetime.now(timezone.utc) - self.captured_at).total_seconds()

    def has_crypto_data(self) -> bool:
        """True if at least one crypto price is populated."""
        return bool(self.crypto_prices)

    def __repr__(self) -> str:
        syms = list(self.crypto_prices.keys())
        return (
            f"ExternalSnapshot("
            f"symbols={syms}, "
            f"fear_greed={self.fear_greed_index}, "
            f"fed_funds={self.fed_funds_rate}, "
            f"age={self.age_seconds():.0f}s)"
        )
