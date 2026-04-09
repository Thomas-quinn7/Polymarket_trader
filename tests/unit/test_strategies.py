"""
Unit tests for strategy infrastructure:
  - strategies/base.py                          (BaseStrategy ABC, default hooks)
  - strategies/registry.py                      (auto-discovery, load_strategy)
  - strategies/config_loader.py                 (YAML loading, env-var overrides)
  - strategies/demo_buy/strategy.py
  - strategies/settlement_arbitrage/strategy.py (including edge filter modes)
"""

import os
import pytest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from strategies.base import BaseStrategy, TradingStrategy
from strategies.registry import load_strategy, available_strategies
from strategies.config_loader import load_strategy_config
from strategies.demo_buy import DemoBuy
from strategies.settlement_arbitrage import SettlementArbitrage

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


def _make_settlement_arb(**yaml_overrides):
    """
    Create a SettlementArbitrage with config_loader patched to return specific values.
    """
    defaults = dict(
        min_price_threshold=0.985,
        max_price_threshold=1.00,
        execute_before_close_seconds=30,
        edge_filter_mode="net_edge",
        expected_slippage_buffer_pct=1.0,
    )
    defaults.update(yaml_overrides)
    with patch(
        "strategies.settlement_arbitrage.strategy.load_strategy_config",
        return_value=defaults,
    ):
        return SettlementArbitrage(_make_client())


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

        assert isinstance(Minimal(), BaseStrategy)

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

    def test_should_exit_returns_false_by_default(self):
        class Minimal(BaseStrategy):
            def scan_for_opportunities(self, m):
                return []

            def get_best_opportunities(self, o, limit=5):
                return o[:limit]

        assert Minimal().should_exit(_make_position(), 0.99) is False

    def test_get_exit_price_returns_current_price(self):
        class Minimal(BaseStrategy):
            def scan_for_opportunities(self, m):
                return []

            def get_best_opportunities(self, o, limit=5):
                return o[:limit]

        assert Minimal().get_exit_price(_make_position(), 0.97) == 0.97

    def test_get_scan_categories_returns_all_four(self):
        class Minimal(BaseStrategy):
            def scan_for_opportunities(self, m):
                return []

            def get_best_opportunities(self, o, limit=5):
                return o[:limit]

        assert set(Minimal().get_scan_categories()) == {"crypto", "fed", "regulatory", "other"}


# ---------------------------------------------------------------------------
# Strategy YAML config loader
# ---------------------------------------------------------------------------


class TestStrategyConfigLoader:

    def test_missing_yaml_returns_empty_dict(self):
        with patch("strategies.config_loader._STRATEGIES_DIR", "/nonexistent/path"):
            result = load_strategy_config("no_such_strategy")
        assert result == {}

    def test_loads_yaml_values(self):
        result = load_strategy_config("settlement_arbitrage")
        assert result["min_price_threshold"] == pytest.approx(0.985)
        assert result["edge_filter_mode"] in {"net_edge", "slippage_adjusted"}

    def test_strategy_metadata_key_removed(self):
        assert "strategy" not in load_strategy_config("settlement_arbitrage")

    def test_env_var_overrides_yaml(self):
        with patch.dict(os.environ, {"MIN_PRICE_THRESHOLD": "0.970"}):
            result = load_strategy_config("settlement_arbitrage")
        assert result["min_price_threshold"] == pytest.approx(0.970)

    def test_env_var_int_cast(self):
        with patch.dict(os.environ, {"EXECUTE_BEFORE_CLOSE_SECONDS": "60"}):
            result = load_strategy_config("settlement_arbitrage")
        assert result["execute_before_close_seconds"] == 60
        assert isinstance(result["execute_before_close_seconds"], int)

    def test_invalid_edge_filter_mode_falls_back_to_net_edge(self):
        with patch.dict(os.environ, {"EDGE_FILTER_MODE": "totally_wrong"}):
            result = load_strategy_config("settlement_arbitrage")
        assert result["edge_filter_mode"] == "net_edge"

    def test_invalid_env_var_type_uses_yaml_value(self):
        with patch.dict(os.environ, {"MIN_PRICE_THRESHOLD": "not_a_float"}):
            result = load_strategy_config("settlement_arbitrage")
        assert result["min_price_threshold"] == pytest.approx(0.985)


# ---------------------------------------------------------------------------
# Strategy Registry — auto-discovery
# ---------------------------------------------------------------------------


class TestStrategyRegistry:
    def test_available_strategies_lists_known(self):
        strategies = available_strategies()
        assert "settlement_arbitrage" in strategies
        assert "demo_buy" in strategies

    def test_load_settlement_arbitrage(self):
        assert isinstance(
            load_strategy("settlement_arbitrage", _make_client()), SettlementArbitrage
        )

    def test_load_demo_buy(self):
        assert isinstance(load_strategy("demo_buy", _make_client()), DemoBuy)

    def test_load_unknown_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown strategy"):
            load_strategy("nonexistent_strategy", _make_client())

    def test_error_message_lists_available(self):
        with pytest.raises(ValueError) as exc_info:
            load_strategy("bad", _make_client())
        msg = str(exc_info.value)
        assert "settlement_arbitrage" in msg
        assert "demo_buy" in msg

    def test_non_strategy_folders_not_registered(self):
        """examples/ and configs/ must not appear in the registry."""
        strategies = available_strategies()
        assert "examples" not in strategies
        assert "configs" not in strategies

    def test_auto_discovery_finds_all_strategy_folders(self):
        """Every subfolder with an __init__.py and a BaseStrategy class is registered."""
        import os

        strategies_dir = os.path.join(os.path.dirname(__file__), "..", "..", "strategies")
        skip = {"__pycache__", "examples", "configs"}
        found_folders = [
            e.name
            for e in os.scandir(strategies_dir)
            if e.is_dir()
            and e.name not in skip
            and not e.name.startswith("_")
            and os.path.exists(os.path.join(e.path, "__init__.py"))
        ]
        registered = available_strategies()
        # Every discovered folder that exports a strategy must be in the registry.
        # (Non-strategy folders like enhanced_market_scanner may legitimately be absent.)
        for folder in found_folders:
            if folder in registered:
                assert folder in registered


# ---------------------------------------------------------------------------
# DemoBuy strategy
# ---------------------------------------------------------------------------


class TestDemoBuy:
    def test_get_scan_categories(self):
        s = DemoBuy(_make_client())
        assert s.get_scan_categories() == ["crypto"]

    def test_scan_empty_markets_returns_empty(self):
        assert DemoBuy(_make_client()).scan_for_opportunities([]) == []

    def test_scan_skips_market_without_two_tokens(self):
        raw = _make_raw_market()
        raw["clobTokenIds"] = ["only_one"]
        assert DemoBuy(_make_client()).scan_for_opportunities([raw]) == []

    def test_scan_returns_opportunity_per_market(self):
        markets = [_make_raw_market(f"mkt-{i}") for i in range(3)]
        assert len(DemoBuy(_make_client()).scan_for_opportunities(markets)) == 3

    def test_opportunity_side_is_yes(self):
        opps = DemoBuy(_make_client()).scan_for_opportunities([_make_raw_market()])
        assert opps[0].side == "YES"

    def test_opportunity_uses_outcome_price(self):
        opps = DemoBuy(_make_client()).scan_for_opportunities([_make_raw_market(yes_price=0.65)])
        assert opps[0].current_price == pytest.approx(0.65, abs=0.001)

    def test_zero_price_falls_back_to_0_5(self):
        raw = _make_raw_market()
        raw["outcomePrices"] = ["0", "1"]
        client = _make_client()
        client.get_price.return_value = 0.0
        opps = DemoBuy(client).scan_for_opportunities([raw])
        assert opps[0].current_price == 0.50

    def test_get_best_opportunities_limits(self):
        opps = [MagicMock() for _ in range(10)]
        assert len(DemoBuy(_make_client()).get_best_opportunities(opps, limit=3)) == 3

    def test_should_exit_false_before_expiry(self):
        s = DemoBuy(_make_client())
        pos = _make_position(expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
        assert s.should_exit(pos, 0.99) is False

    def test_should_exit_true_after_expiry(self):
        s = DemoBuy(_make_client())
        pos = _make_position(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        assert s.should_exit(pos, 0.99) is True

    def test_should_exit_false_when_no_expiry(self):
        assert DemoBuy(_make_client()).should_exit(_make_position(expires_at=None), 0.99) is False

    def test_get_exit_price_returns_current(self):
        assert DemoBuy(_make_client()).get_exit_price(_make_position(), 0.97) == pytest.approx(0.97)

    def test_scan_handles_malformed_market_gracefully(self):
        markets = [{"bad": "data"}, _make_raw_market()]
        opps = DemoBuy(_make_client()).scan_for_opportunities(markets)
        assert len(opps) >= 1

    def test_hold_seconds_loaded_from_yaml(self):
        s = DemoBuy(_make_client())
        assert s._hold_seconds == 60

    def test_yaml_override_hold_seconds(self):
        with patch(
            "strategies.demo_buy.strategy.load_strategy_config",
            return_value={"hold_seconds": 120, "scan_categories": ["crypto"]},
        ):
            s = DemoBuy(_make_client())
        assert s._hold_seconds == 120


# ---------------------------------------------------------------------------
# SettlementArbitrage — core behaviour
# ---------------------------------------------------------------------------


class TestSettlementArbitrage:
    def test_get_scan_categories(self):
        s = _make_settlement_arb()
        assert set(s.get_scan_categories()) == {"crypto", "fed", "regulatory", "other"}

    def test_scan_empty_returns_empty(self):
        assert _make_settlement_arb().scan_for_opportunities([]) == []

    def test_scan_below_threshold_skipped(self):
        s = _make_settlement_arb()
        with patch("strategies.settlement_arbitrage.strategy.config") as cfg:
            cfg.MIN_VOLUME_USD = 100.0
            cfg.MIN_CONFIDENCE = 0.0
            cfg.TAKER_FEE_PERCENT = 2.0
            opps = s.scan_for_opportunities([_make_raw_market(yes_price=0.50)])
        assert opps == []

    def test_scan_illiquid_market_skipped(self):
        s = _make_settlement_arb()
        with patch("strategies.settlement_arbitrage.strategy.config") as cfg:
            cfg.MIN_VOLUME_USD = 1_000.0
            cfg.MIN_CONFIDENCE = 0.0
            cfg.TAKER_FEE_PERCENT = 2.0
            opps = s.scan_for_opportunities([_make_raw_market(yes_price=0.990, volume=50.0)])
        assert opps == []

    def test_should_exit_true_past_expiry(self):
        s = _make_settlement_arb()
        pos = _make_position(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        assert s.should_exit(pos, 0.99) is True

    def test_should_exit_false_before_expiry(self):
        s = _make_settlement_arb()
        pos = _make_position(expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
        assert s.should_exit(pos, 0.99) is False

    def test_should_exit_false_no_expiry(self):
        assert _make_settlement_arb().should_exit(_make_position(expires_at=None), 0.99) is False

    def test_get_exit_price_always_one(self):
        assert _make_settlement_arb().get_exit_price(_make_position(), 0.99) == 1.0

    def test_get_best_opportunities_ranked_by_edge_x_confidence(self):
        s = _make_settlement_arb()
        opps = [
            SimpleNamespace(edge_percent=1.0, confidence=0.5),
            SimpleNamespace(edge_percent=2.0, confidence=0.9),  # best
            SimpleNamespace(edge_percent=0.5, confidence=0.8),
        ]
        assert s.get_best_opportunities(opps, limit=3)[0].edge_percent == 2.0

    def test_get_best_opportunities_respects_limit(self):
        s = _make_settlement_arb()
        opps = [SimpleNamespace(edge_percent=i * 0.1, confidence=0.9) for i in range(10)]
        assert len(s.get_best_opportunities(opps, limit=3)) == 3

    def test_calculate_confidence_high_price_short_ttc(self):
        score = _make_settlement_arb()._calculate_confidence(0.999, 60.0, 1.5)
        assert score > 0.5

    def test_calculate_confidence_low_price_far_close(self):
        s = _make_settlement_arb()
        low = s._calculate_confidence(0.985, 86400, 0.5)
        high = s._calculate_confidence(0.999, 60, 1.5)
        assert low < high

    def test_calculate_confidence_clamped_0_to_1(self):
        s = _make_settlement_arb()
        for price in (0.985, 0.990, 0.999):
            for ttc in (0, 30, 300, 3600, 86400):
                score = s._calculate_confidence(price, float(ttc), 1.0)
                assert 0.0 <= score <= 1.0

    def test_scan_handles_malformed_market(self):
        s = _make_settlement_arb()
        with patch("strategies.settlement_arbitrage.strategy.config") as cfg:
            cfg.MIN_VOLUME_USD = 100.0
            cfg.MIN_CONFIDENCE = 0.0
            cfg.TAKER_FEE_PERCENT = 2.0
            opps = s.scan_for_opportunities([{"bad": "data"}, _make_raw_market(yes_price=0.50)])
        assert isinstance(opps, list)

    def test_yaml_config_applied_at_init(self):
        s = _make_settlement_arb(min_price_threshold=0.970, execute_before_close_seconds=60)
        assert s._min_price_threshold == pytest.approx(0.970)
        assert s._execute_before_close_seconds == 60

    def test_defaults_used_when_yaml_missing(self):
        with patch(
            "strategies.settlement_arbitrage.strategy.load_strategy_config",
            return_value={},
        ):
            s = SettlementArbitrage(_make_client())
        assert s._min_price_threshold == pytest.approx(0.985)
        assert s._edge_filter_mode == "net_edge"


# ---------------------------------------------------------------------------
# SettlementArbitrage — edge filter modes
# ---------------------------------------------------------------------------


class TestEdgeFilterMode:

    # ── _passes_edge_filter unit tests ──────────────────────────────────────

    def test_net_edge_mode_passes_positive_edge(self):
        s = _make_settlement_arb(edge_filter_mode="net_edge")
        assert s._passes_edge_filter(0.01, "mkt", 2.01) is True

    def test_net_edge_mode_rejects_zero_edge(self):
        s = _make_settlement_arb(edge_filter_mode="net_edge")
        assert s._passes_edge_filter(0.0, "mkt", 2.0) is False

    def test_net_edge_mode_rejects_negative_edge(self):
        s = _make_settlement_arb(edge_filter_mode="net_edge")
        assert s._passes_edge_filter(-0.5, "mkt", 1.5) is False

    def test_slippage_adjusted_passes_above_buffer(self):
        s = _make_settlement_arb(
            edge_filter_mode="slippage_adjusted", expected_slippage_buffer_pct=1.0
        )
        assert s._passes_edge_filter(1.5, "mkt", 3.5) is True

    def test_slippage_adjusted_rejects_at_buffer(self):
        s = _make_settlement_arb(
            edge_filter_mode="slippage_adjusted", expected_slippage_buffer_pct=1.0
        )
        assert s._passes_edge_filter(1.0, "mkt", 3.0) is False

    def test_slippage_adjusted_rejects_below_buffer(self):
        s = _make_settlement_arb(
            edge_filter_mode="slippage_adjusted", expected_slippage_buffer_pct=1.0
        )
        assert s._passes_edge_filter(0.5, "mkt", 2.5) is False

    def test_slippage_adjusted_zero_buffer_behaves_like_net_edge(self):
        s = _make_settlement_arb(
            edge_filter_mode="slippage_adjusted", expected_slippage_buffer_pct=0.0
        )
        assert s._passes_edge_filter(0.01, "mkt", 2.01) is True
        assert s._passes_edge_filter(0.0, "mkt", 2.0) is False

    def test_larger_buffer_rejects_more_trades(self):
        s_tight = _make_settlement_arb(
            edge_filter_mode="slippage_adjusted", expected_slippage_buffer_pct=0.5
        )
        s_loose = _make_settlement_arb(
            edge_filter_mode="slippage_adjusted", expected_slippage_buffer_pct=2.0
        )
        assert s_tight._passes_edge_filter(1.0, "mkt", 3.0) is True
        assert s_loose._passes_edge_filter(1.0, "mkt", 3.0) is False

    # ── Integration with scan_for_opportunities ──────────────────────────────

    def _scan(self, strategy, yes_price, fee_pct=2.0):
        market = _make_raw_market(yes_price=yes_price, seconds_to_close=60, volume=100_000)
        with patch("strategies.settlement_arbitrage.strategy.config") as cfg:
            cfg.MIN_VOLUME_USD = 100.0
            cfg.MIN_CONFIDENCE = 0.0
            cfg.TAKER_FEE_PERCENT = fee_pct
            return strategy.scan_for_opportunities([market])

    def test_net_edge_mode_accepts_marginal_trade(self):
        """price=0.985, fee=0% → net~1.5% > 0 → accepted."""
        assert len(self._scan(_make_settlement_arb(edge_filter_mode="net_edge"), 0.985, 0.0)) == 1

    def test_net_edge_mode_rejects_when_fee_wipes_edge(self):
        """price=0.990, fee=2% → net=-1.0% → rejected."""
        assert len(self._scan(_make_settlement_arb(edge_filter_mode="net_edge"), 0.990, 2.0)) == 0

    def test_slippage_adjusted_rejects_marginal_trade(self):
        """price=0.990, fee=0%, buffer=1.5% → net=1.0% < 1.5% → rejected."""
        s = _make_settlement_arb(
            edge_filter_mode="slippage_adjusted", expected_slippage_buffer_pct=1.5
        )
        assert len(self._scan(s, 0.990, 0.0)) == 0

    def test_slippage_adjusted_accepts_high_edge_trade(self):
        """price=0.985, fee=0%, buffer=1.0% → net~1.5% > 1.0% → accepted."""
        s = _make_settlement_arb(
            edge_filter_mode="slippage_adjusted", expected_slippage_buffer_pct=1.0
        )
        assert len(self._scan(s, 0.985, 0.0)) == 1

    def test_net_edge_opportunity_edge_percent_is_net(self):
        s = _make_settlement_arb(edge_filter_mode="net_edge")
        opps = self._scan(s, 0.985, 0.0)
        assert len(opps) == 1
        assert opps[0].edge_percent == pytest.approx((1.0 - 0.985) * 100 - 0.0, abs=0.01)

    def test_slippage_adjusted_opportunity_edge_percent_is_net(self):
        s = _make_settlement_arb(
            edge_filter_mode="slippage_adjusted", expected_slippage_buffer_pct=0.5
        )
        opps = self._scan(s, 0.985, 0.0)
        assert len(opps) == 1
        assert opps[0].edge_percent == pytest.approx((1.0 - 0.985) * 100 - 0.0, abs=0.01)
