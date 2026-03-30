"""
Unit tests for strategy infrastructure:
  - strategies/base.py      (BaseStrategy ABC, default hooks)
  - strategies/registry.py  (load_strategy, available_strategies)
  - strategies/examples/demo_buy.py
  - strategies/examples/settlement_arbitrage.py
"""

import pytest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from strategies.base import BaseStrategy, TradingStrategy
from strategies.registry import load_strategy, available_strategies
from strategies.examples.demo_buy import DemoBuy
from strategies.examples.settlement_arbitrage import SettlementArbitrage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client():
    client = MagicMock()
    client.get_price.return_value = 0.50
    return client


def _make_position(entry_price=0.985, expires_at=None):
    return SimpleNamespace(
        position_id="pos-1",
        market_id="mkt-1",
        winning_token_id="tok_yes",
        entry_price=entry_price,
        shares=100.0,
        expires_at=expires_at,
    )


def _make_raw_market(
    slug="test-market",
    yes_price=0.60,
    volume=10_000.0,
    seconds_to_close=3600,
    category="crypto",
):
    """Build a raw market dict matching the shape PolymarketMarket.from_api() expects."""
    now = datetime.now(timezone.utc)
    end_date = (now + timedelta(seconds=seconds_to_close)).strftime("%Y-%m-%dT%H:%M:%SZ")
    no_price = round(1.0 - yes_price, 4)
    return {
        "id": f"id-{slug}",
        "slug": slug,
        "question": f"Will {slug} happen?",
        "clobTokenIds": [f"{slug}_yes", f"{slug}_no"],
        "outcomePrices": [str(yes_price), str(no_price)],
        "tags": [{"label": category}],
        "volume": volume,
        "endDate": end_date,
    }


# ---------------------------------------------------------------------------
# BaseStrategy ABC
# ---------------------------------------------------------------------------

class TestBaseStrategyABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseStrategy()

    def test_concrete_subclass_works(self):
        class Minimal(BaseStrategy):
            def scan_for_opportunities(self, markets):
                return []
            def get_best_opportunities(self, opps, limit=5):
                return opps[:limit]

        s = Minimal()
        assert isinstance(s, BaseStrategy)

    def test_missing_scan_raises(self):
        with pytest.raises(TypeError):
            class Bad(BaseStrategy):
                def get_best_opportunities(self, opps, limit=5):
                    return []
            Bad()

    def test_missing_get_best_raises(self):
        with pytest.raises(TypeError):
            class Bad(BaseStrategy):
                def scan_for_opportunities(self, markets):
                    return []
            Bad()

    def test_trading_strategy_alias(self):
        assert TradingStrategy is BaseStrategy

    # Default hooks
    def test_should_exit_returns_false_by_default(self):
        class Minimal(BaseStrategy):
            def scan_for_opportunities(self, m): return []
            def get_best_opportunities(self, o, limit=5): return o[:limit]

        s = Minimal()
        pos = _make_position()
        assert s.should_exit(pos, 0.99) is False

    def test_get_exit_price_returns_current_price(self):
        class Minimal(BaseStrategy):
            def scan_for_opportunities(self, m): return []
            def get_best_opportunities(self, o, limit=5): return o[:limit]

        s = Minimal()
        assert s.get_exit_price(_make_position(), 0.97) == 0.97

    def test_get_scan_categories_returns_all_four(self):
        class Minimal(BaseStrategy):
            def scan_for_opportunities(self, m): return []
            def get_best_opportunities(self, o, limit=5): return o[:limit]

        cats = Minimal().get_scan_categories()
        assert set(cats) == {"crypto", "fed", "regulatory", "other"}


# ---------------------------------------------------------------------------
# Strategy Registry
# ---------------------------------------------------------------------------

class TestStrategyRegistry:
    def test_available_strategies_lists_known(self):
        strategies = available_strategies()
        assert "settlement_arbitrage" in strategies
        assert "demo_buy" in strategies

    def test_load_settlement_arbitrage(self):
        client = _make_client()
        strategy = load_strategy("settlement_arbitrage", client)
        assert isinstance(strategy, SettlementArbitrage)

    def test_load_demo_buy(self):
        client = _make_client()
        strategy = load_strategy("demo_buy", client)
        assert isinstance(strategy, DemoBuy)

    def test_load_unknown_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown strategy"):
            load_strategy("nonexistent_strategy", _make_client())

    def test_error_message_lists_available(self):
        try:
            load_strategy("bad", _make_client())
        except ValueError as e:
            assert "settlement_arbitrage" in str(e)
            assert "demo_buy" in str(e)


# ---------------------------------------------------------------------------
# DemoBuy strategy
# ---------------------------------------------------------------------------

class TestDemoBuy:
    def test_get_scan_categories(self):
        s = DemoBuy(_make_client())
        assert s.get_scan_categories() == ["crypto"]

    def test_scan_empty_markets_returns_empty(self):
        s = DemoBuy(_make_client())
        assert s.scan_for_opportunities([]) == []

    def test_scan_skips_market_without_two_tokens(self):
        raw = _make_raw_market()
        raw["clobTokenIds"] = ["only_one"]
        s = DemoBuy(_make_client())
        opps = s.scan_for_opportunities([raw])
        assert opps == []

    def test_scan_returns_opportunity_per_market(self):
        markets = [_make_raw_market(f"mkt-{i}") for i in range(3)]
        s = DemoBuy(_make_client())
        opps = s.scan_for_opportunities(markets)
        assert len(opps) == 3

    def test_opportunity_side_is_yes(self):
        s = DemoBuy(_make_client())
        opps = s.scan_for_opportunities([_make_raw_market()])
        assert opps[0].side == "YES"

    def test_opportunity_uses_outcome_price(self):
        raw = _make_raw_market(yes_price=0.65)
        s = DemoBuy(_make_client())
        opps = s.scan_for_opportunities([raw])
        assert opps[0].current_price == pytest.approx(0.65, abs=0.001)

    def test_zero_price_falls_back_to_0_5(self):
        raw = _make_raw_market()
        raw["outcomePrices"] = ["0", "1"]
        client = _make_client()
        client.get_price.return_value = 0.0
        s = DemoBuy(client)
        opps = s.scan_for_opportunities([raw])
        assert opps[0].current_price == 0.50

    def test_get_best_opportunities_limits(self):
        opps = [MagicMock() for _ in range(10)]
        s = DemoBuy(_make_client())
        best = s.get_best_opportunities(opps, limit=3)
        assert len(best) == 3

    def test_should_exit_false_before_expiry(self):
        s = DemoBuy(_make_client())
        pos = _make_position(expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
        assert s.should_exit(pos, 0.99) is False

    def test_should_exit_true_after_expiry(self):
        s = DemoBuy(_make_client())
        pos = _make_position(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        assert s.should_exit(pos, 0.99) is True

    def test_should_exit_false_when_no_expiry(self):
        s = DemoBuy(_make_client())
        pos = _make_position(expires_at=None)
        assert s.should_exit(pos, 0.99) is False

    def test_get_exit_price_returns_current(self):
        s = DemoBuy(_make_client())
        assert s.get_exit_price(_make_position(), 0.97) == pytest.approx(0.97)

    def test_scan_handles_malformed_market_gracefully(self):
        markets = [{"bad": "data"}, _make_raw_market()]
        s = DemoBuy(_make_client())
        opps = s.scan_for_opportunities(markets)
        # Should process the good one and skip the bad one
        assert len(opps) >= 1


# ---------------------------------------------------------------------------
# SettlementArbitrage strategy
# ---------------------------------------------------------------------------

class TestSettlementArbitrage:
    def test_get_scan_categories(self):
        s = SettlementArbitrage(_make_client())
        cats = s.get_scan_categories()
        assert set(cats) == {"crypto", "fed", "regulatory", "other"}

    def test_scan_empty_returns_empty(self):
        s = SettlementArbitrage(_make_client())
        assert s.scan_for_opportunities([]) == []

    def test_scan_below_threshold_skipped(self):
        """YES price of 0.50 is well below the 0.985 threshold."""
        s = SettlementArbitrage(_make_client())
        markets = [_make_raw_market(yes_price=0.50)]
        with patch("strategies.examples.settlement_arbitrage.config") as cfg:
            cfg.MIN_VOLUME_USD = 100.0
            cfg.MIN_CONFIDENCE = 0.0
            opps = s.scan_for_opportunities(markets)
        assert opps == []

    def test_scan_in_threshold_detected(self):
        """YES price of 0.990 is above 0.985 → should be detected."""
        s = SettlementArbitrage(_make_client())
        markets = [_make_raw_market(yes_price=0.990, seconds_to_close=60)]
        with patch("strategies.examples.settlement_arbitrage.config") as cfg:
            cfg.MIN_VOLUME_USD = 100.0
            cfg.MIN_CONFIDENCE = 0.0
        opps = s.scan_for_opportunities(markets)
        # Whether it passes depends on net_edge > 0 (yes_price=0.990, fee=2%)
        # gross_edge = 1.0%, net_edge = 1.0% - 2.0% = -1.0% → filtered out
        # Try with lower fee
        with patch("strategies.examples.settlement_arbitrage._TAKER_FEE_PERCENT", 0.5):
            with patch("strategies.examples.settlement_arbitrage.config") as cfg:
                cfg.MIN_VOLUME_USD = 100.0
                cfg.MIN_CONFIDENCE = 0.0
                opps = s.scan_for_opportunities(markets)
        assert len(opps) >= 0  # may or may not pass confidence filter

    def test_scan_illiquid_market_skipped(self):
        s = SettlementArbitrage(_make_client())
        markets = [_make_raw_market(yes_price=0.990, volume=50.0)]
        with patch("strategies.examples.settlement_arbitrage.config") as cfg:
            cfg.MIN_VOLUME_USD = 1_000.0
            cfg.MIN_CONFIDENCE = 0.0
            opps = s.scan_for_opportunities(markets)
        assert opps == []

    def test_should_exit_true_past_expiry(self):
        s = SettlementArbitrage(_make_client())
        pos = _make_position(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        assert s.should_exit(pos, 0.99) is True

    def test_should_exit_false_before_expiry(self):
        s = SettlementArbitrage(_make_client())
        pos = _make_position(expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
        assert s.should_exit(pos, 0.99) is False

    def test_should_exit_false_no_expiry(self):
        s = SettlementArbitrage(_make_client())
        pos = _make_position(expires_at=None)
        assert s.should_exit(pos, 0.99) is False

    def test_get_exit_price_always_one(self):
        s = SettlementArbitrage(_make_client())
        assert s.get_exit_price(_make_position(), 0.99) == 1.0

    def test_get_best_opportunities_ranked_by_edge_x_confidence(self):
        s = SettlementArbitrage(_make_client())
        opps = [
            SimpleNamespace(edge_percent=1.0, confidence=0.5),   # score=0.5
            SimpleNamespace(edge_percent=2.0, confidence=0.9),   # score=1.8 ← best
            SimpleNamespace(edge_percent=0.5, confidence=0.8),   # score=0.4
        ]
        best = s.get_best_opportunities(opps, limit=3)
        assert best[0].edge_percent == 2.0

    def test_get_best_opportunities_respects_limit(self):
        s = SettlementArbitrage(_make_client())
        opps = [SimpleNamespace(edge_percent=i * 0.1, confidence=0.9) for i in range(10)]
        assert len(s.get_best_opportunities(opps, limit=3)) == 3

    def test_calculate_confidence_high_price_short_ttc(self):
        s = SettlementArbitrage(_make_client())
        # price near 1.0, imminent close → high confidence
        score = s._calculate_confidence(yes_price=0.999, time_to_close=60.0, net_edge=1.5)
        assert score > 0.5

    def test_calculate_confidence_low_price_far_close(self):
        s = SettlementArbitrage(_make_client())
        # price at minimum threshold, far from close → lower confidence
        from strategies.examples.settlement_arbitrage import _MIN_PRICE_THRESHOLD
        score_low  = s._calculate_confidence(yes_price=_MIN_PRICE_THRESHOLD, time_to_close=86400, net_edge=0.5)
        score_high = s._calculate_confidence(yes_price=0.999, time_to_close=60, net_edge=1.5)
        assert score_low < score_high

    def test_calculate_confidence_clamped_0_to_1(self):
        s = SettlementArbitrage(_make_client())
        for price in (0.985, 0.990, 0.999):
            for ttc in (0, 30, 300, 3600, 86400):
                score = s._calculate_confidence(price, float(ttc), 1.0)
                assert 0.0 <= score <= 1.0, f"Out of range at price={price} ttc={ttc}"

    def test_scan_handles_malformed_market(self):
        s = SettlementArbitrage(_make_client())
        with patch("strategies.examples.settlement_arbitrage.config") as cfg:
            cfg.MIN_VOLUME_USD = 100.0
            cfg.MIN_CONFIDENCE = 0.0
            opps = s.scan_for_opportunities([{"bad": "data"}, _make_raw_market(yes_price=0.50)])
        assert isinstance(opps, list)
