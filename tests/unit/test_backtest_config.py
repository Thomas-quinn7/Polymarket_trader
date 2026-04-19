"""
Unit tests for BacktestConfig (backtesting/config.py).

Covers:
- Default field values
- validate() raises on bad date order
- validate() raises on bad balance / pct / fee values
- validate() raises on unknown price_interval
- validate() passes on a well-formed config
- to_json() / from_json() round-trip preserves every field
"""

import json
import pytest

from backtesting.config import BacktestConfig

# ── Helpers ───────────────────────────────────────────────────────────────────


def _valid() -> BacktestConfig:
    """Return a minimal valid config."""
    return BacktestConfig(
        strategy_name="example_strategy",
        start_date="2025-01-01",
        end_date="2025-04-01",
    )


# ── Defaults ──────────────────────────────────────────────────────────────────


class TestDefaults:
    def test_default_balance(self):
        c = _valid()
        assert c.initial_balance == 1000.0

    def test_default_max_positions(self):
        c = _valid()
        assert c.max_positions == 5

    def test_default_capital_pct(self):
        c = _valid()
        assert c.capital_per_trade_pct == 20.0

    def test_default_taker_fee(self):
        c = _valid()
        assert c.taker_fee_pct == 2.0

    def test_default_category(self):
        c = _valid()
        assert c.category == "crypto"

    def test_default_price_interval(self):
        c = _valid()
        assert c.price_interval == "5m"

    def test_default_rate_limit(self):
        c = _valid()
        assert c.rate_limit_rps == 3.0


# ── validate() date checks ────────────────────────────────────────────────────


class TestValidateDates:
    def test_end_before_start_raises(self):
        c = BacktestConfig("s", start_date="2025-04-01", end_date="2025-01-01")
        with pytest.raises(ValueError, match="end_date"):
            c.validate()

    def test_end_equal_start_raises(self):
        c = BacktestConfig("s", start_date="2025-01-01", end_date="2025-01-01")
        with pytest.raises(ValueError, match="end_date"):
            c.validate()

    def test_valid_dates_pass(self):
        _valid().validate()  # should not raise


# ── validate() capital checks ─────────────────────────────────────────────────


class TestValidateCapital:
    def test_zero_balance_raises(self):
        c = _valid()
        c.initial_balance = 0.0
        with pytest.raises(ValueError, match="initial_balance"):
            c.validate()

    def test_negative_balance_raises(self):
        c = _valid()
        c.initial_balance = -100.0
        with pytest.raises(ValueError, match="initial_balance"):
            c.validate()

    def test_zero_capital_pct_raises(self):
        c = _valid()
        c.capital_per_trade_pct = 0.0
        with pytest.raises(ValueError, match="capital_per_trade_pct"):
            c.validate()

    def test_over_100_capital_pct_raises(self):
        c = _valid()
        c.capital_per_trade_pct = 101.0
        with pytest.raises(ValueError, match="capital_per_trade_pct"):
            c.validate()

    def test_100_capital_pct_valid(self):
        c = _valid()
        c.capital_per_trade_pct = 100.0
        c.validate()  # should not raise

    def test_zero_max_positions_raises(self):
        c = _valid()
        c.max_positions = 0
        with pytest.raises(ValueError, match="max_positions"):
            c.validate()

    def test_negative_fee_raises(self):
        c = _valid()
        c.taker_fee_pct = -1.0
        with pytest.raises(ValueError, match="taker_fee_pct"):
            c.validate()

    def test_zero_fee_valid(self):
        c = _valid()
        c.taker_fee_pct = 0.0
        c.validate()  # should not raise


# ── validate() price_interval ─────────────────────────────────────────────────


class TestValidateInterval:
    @pytest.mark.parametrize("iv", ["1m", "5m", "15m", "1h", "4h", "1d"])
    def test_valid_intervals(self, iv):
        c = _valid()
        c.price_interval = iv
        c.validate()  # should not raise

    def test_unknown_interval_raises(self):
        c = _valid()
        c.price_interval = "99x"
        with pytest.raises(ValueError, match="price_interval"):
            c.validate()


# ── JSON round-trip ───────────────────────────────────────────────────────────


class TestJsonRoundTrip:
    def test_to_json_is_valid_json(self):
        data = json.loads(_valid().to_json())
        assert isinstance(data, dict)

    def test_roundtrip_preserves_strategy_name(self):
        c = _valid()
        c2 = BacktestConfig.from_json(c.to_json())
        assert c2.strategy_name == c.strategy_name

    def test_roundtrip_preserves_dates(self):
        c = _valid()
        c2 = BacktestConfig.from_json(c.to_json())
        assert c2.start_date == c.start_date
        assert c2.end_date == c.end_date

    def test_roundtrip_preserves_all_numeric_fields(self):
        c = BacktestConfig(
            strategy_name="demo",
            initial_balance=500.0,
            max_positions=3,
            capital_per_trade_pct=10.0,
            taker_fee_pct=1.5,
            min_volume_usd=250.0,
            max_duration_seconds=900,
            rate_limit_rps=2.0,
        )
        c2 = BacktestConfig.from_json(c.to_json())
        assert c2.initial_balance == 500.0
        assert c2.max_positions == 3
        assert c2.capital_per_trade_pct == 10.0
        assert c2.taker_fee_pct == 1.5
        assert c2.min_volume_usd == 250.0
        assert c2.max_duration_seconds == 900
        assert c2.rate_limit_rps == 2.0
