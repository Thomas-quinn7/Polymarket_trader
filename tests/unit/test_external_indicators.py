"""Unit tests for data/external/indicators.py — no network calls."""

import pytest
from data.external.indicators import rsi, ema, sma, z_score


class TestRSI:
    def test_returns_none_for_insufficient_data(self):
        assert rsi([1.0, 2.0], period=14) is None

    def test_returns_none_at_exact_period_boundary(self):
        # Need period + 1 values minimum
        assert rsi([1.0] * 14, period=14) is None

    def test_all_gains_returns_100(self):
        closes = [float(i) for i in range(1, 20)]
        assert rsi(closes, period=14) == pytest.approx(100.0)

    def test_all_losses_returns_0(self):
        closes = [float(20 - i) for i in range(20)]
        assert rsi(closes, period=14) == pytest.approx(0.0)

    def test_result_in_valid_range(self):
        import random

        random.seed(42)
        closes = [50.0 + random.gauss(0, 2) for _ in range(50)]
        result = rsi(closes, period=14)
        assert result is not None
        assert 0.0 <= result <= 100.0

    def test_flat_series_returns_100_for_avg_loss_zero(self):
        # Flat closes → avg_loss = 0 → RSI should be 100
        closes = [50.0] * 20
        assert rsi(closes, period=14) == pytest.approx(100.0)

    def test_rsi_returns_float(self):
        closes = [
            40.0,
            41.0,
            42.0,
            41.5,
            43.0,
            42.0,
            44.0,
            43.5,
            45.0,
            44.0,
            46.0,
            45.5,
            47.0,
            46.0,
            48.0,
        ]
        result = rsi(closes, period=14)
        assert isinstance(result, float)


class TestEMA:
    def test_returns_none_for_insufficient_data(self):
        assert ema([1.0, 2.0], period=5) is None

    def test_single_period_equals_value(self):
        assert ema([5.0], period=1) == pytest.approx(5.0)

    def test_ema_weights_recent_more_than_sma(self):
        # With period=5, need at least one value beyond the seed window for EMA
        # to differ from SMA. Seed avg = 1.0; next value 10 → EMA ~ 4.0.
        # SMA of last 5 = [1,1,1,1,10] = 2.8 → EMA (4.0) > SMA (2.8).
        values = [1.0, 1.0, 1.0, 1.0, 1.0, 10.0]
        assert ema(values, period=5) > sma(values, period=5)


class TestSMA:
    def test_basic_average(self):
        assert sma([1.0, 2.0, 3.0, 4.0, 5.0], period=3) == pytest.approx(4.0)

    def test_uses_last_n_values(self):
        assert sma([100.0, 1.0, 2.0, 3.0], period=3) == pytest.approx(2.0)

    def test_returns_none_for_insufficient(self):
        assert sma([1.0, 2.0], period=5) is None


class TestZScore:
    def test_outlier_high_zscore(self):
        values = [10.0] * 19 + [20.0]
        result = z_score(values, period=20)
        assert result is not None
        assert result > 2.0

    def test_flat_series_returns_none(self):
        assert z_score([5.0] * 20) is None  # stddev = 0

    def test_returns_none_for_insufficient_data(self):
        assert z_score([1.0, 2.0], period=10) is None
