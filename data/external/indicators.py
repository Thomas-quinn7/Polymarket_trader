"""
Pure-function technical indicators.

No external dependencies — operates on plain Python lists of floats.
All functions are stateless and suitable for both live and backtest use.
Returns None whenever insufficient data is provided rather than raising.
"""

from __future__ import annotations

import math
from typing import List, Optional


def rsi(closes: List[float], period: int = 14) -> Optional[float]:
    """
    Compute Wilder's RSI for the last bar of a close-price series.

    Uses Wilder's smoothed moving average (SMMA), not a simple MA — this
    matches the standard definition used by TradingView and most platforms.

    Args:
        closes: List of close prices, oldest first. Minimum length: period + 1.
        period: RSI lookback period (default 14).

    Returns:
        RSI value in range [0.0, 100.0], or None if insufficient data.
    """
    if len(closes) < period + 1:
        return None

    # Use a 3x-period tail to allow the SMMA to converge before the final bar
    tail = closes[-(period * 3) :]

    gains: List[float] = []
    losses: List[float] = []
    for i in range(1, len(tail)):
        delta = tail[i] - tail[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    if len(gains) < period:
        return None

    # Seed: simple average of first `period` bars
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # Wilder smoothing for all subsequent bars
    for g, loss_val in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + loss_val) / period

    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def ema(values: List[float], period: int) -> Optional[float]:
    """
    Exponential Moving Average of the last element in values.

    Uses standard smoothing factor: 2 / (period + 1).
    Seeds with a simple average of the first `period` values.

    Returns None if fewer than `period` values are provided.
    """
    if len(values) < period:
        return None
    k = 2.0 / (period + 1)
    result = sum(values[:period]) / period
    for v in values[period:]:
        result = v * k + result * (1.0 - k)
    return round(result, 6)


def sma(values: List[float], period: int) -> Optional[float]:
    """Simple Moving Average of the last `period` values."""
    if len(values) < period:
        return None
    return round(sum(values[-period:]) / period, 6)


def z_score(values: List[float], period: int = 20) -> Optional[float]:
    """
    Z-score of the last value relative to its rolling mean and stddev.

    Z = (last_value - mean_of_window) / stddev_of_window

    Useful for detecting when a price has deviated unusually far from its norm.
    Typical thresholds: |Z| > 2.0 = notable, |Z| > 3.0 = extreme.

    Returns None if stddev is zero (flat series) or fewer than `period` values.
    """
    if len(values) < period:
        return None
    window = values[-period:]
    mean = sum(window) / period
    variance = sum((x - mean) ** 2 for x in window) / period
    if variance == 0.0:
        return None
    return round((values[-1] - mean) / math.sqrt(variance), 4)
