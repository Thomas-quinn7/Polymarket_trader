"""
Unit tests for strategy infrastructure:
  - strategies/base.py                          (BaseStrategy ABC, default hooks)
  - strategies/registry.py                      (auto-discovery, load_strategy)
  - strategies/config_loader.py                 (YAML loading, env-var overrides)
  - strategies/demo_buy/strategy.py
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
from data.market_schema import PolymarketMarket

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


def _make_market(
    slug="test-market",
    yes_price=0.60,
    volume=10_000.0,
    seconds_to_close=3600,
    category="crypto",
    resolved_price=None,
) -> PolymarketMarket:
    """
    Build a PolymarketMarket with resolved_price set — matches what MarketProvider
    delivers to strategies after pre-filtering and price resolution.
    """
    now = datetime.now(timezone.utc)
    end_date = (now + timedelta(seconds=seconds_to_close)).strftime("%Y-%m-%dT%H:%M:%SZ")
    raw = {
        "id": f"id-{slug}",
        "slug": slug,
        "question": f"Will {slug} happen?",
        "clobTokenIds": [f"{slug}_yes", f"{slug}_no"],
        "outcomePrices": [str(yes_price), str(round(1.0 - yes_price, 4))],
        "tags": [{"label": category}],
        "volume": volume,
        "endDate": end_date,
    }
    market = PolymarketMarket.from_api(raw)
    market.resolved_price = resolved_price if resolved_price is not None else yes_price
    return market


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
        result = load_strategy_config("example_strategy")
        assert "min_price" in result
        assert result["edge_filter_mode"] in {"net_edge", "slippage_adjusted"}

    def test_strategy_metadata_key_removed(self):
        assert "strategy" not in load_strategy_config("example_strategy")

    def test_env_var_overrides_yaml(self):
        with patch.dict(os.environ, {"EXPECTED_SLIPPAGE_BUFFER_PCT": "1.5"}):
            result = load_strategy_config("example_strategy")
        assert result["expected_slippage_buffer_pct"] == pytest.approx(1.5)

    def test_env_var_int_cast(self):
        with patch.dict(os.environ, {"EXECUTE_BEFORE_CLOSE_SECONDS": "60"}):
            result = load_strategy_config("example_strategy")
        assert result["execute_before_close_seconds"] == 60
        assert isinstance(result["execute_before_close_seconds"], int)

    def test_invalid_edge_filter_mode_falls_back_to_net_edge(self):
        with patch.dict(os.environ, {"EDGE_FILTER_MODE": "totally_wrong"}):
            result = load_strategy_config("example_strategy")
        assert result["edge_filter_mode"] == "net_edge"

    def test_invalid_env_var_type_uses_yaml_value(self):
        with patch.dict(os.environ, {"EXECUTE_BEFORE_CLOSE_SECONDS": "not_an_int"}):
            result = load_strategy_config("example_strategy")
        assert isinstance(result["execute_before_close_seconds"], int)


# ---------------------------------------------------------------------------
# Strategy Registry — auto-discovery
# ---------------------------------------------------------------------------


class TestStrategyRegistry:
    def test_available_strategies_lists_known(self):
        strategies = available_strategies()
        assert "demo_buy" in strategies
        assert "example_strategy" in strategies

    def test_load_demo_buy(self):
        assert isinstance(load_strategy("demo_buy", _make_client()), DemoBuy)

    def test_load_unknown_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown strategy"):
            load_strategy("nonexistent_strategy", _make_client())

    def test_error_message_lists_available(self):
        with pytest.raises(ValueError) as exc_info:
            load_strategy("bad", _make_client())
        msg = str(exc_info.value)
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
        # Folders that intentionally don't export a BaseStrategy subclass.
        non_strategy_folders = {"enhanced_market_scanner"}
        for folder in found_folders:
            if folder not in non_strategy_folders:
                assert folder in registered, (
                    f"Strategy folder '{folder}' has an __init__.py but is not in the registry. "
                    f"Either add a BaseStrategy subclass or add it to non_strategy_folders."
                )


# ---------------------------------------------------------------------------
# DemoBuy strategy
# ---------------------------------------------------------------------------


class TestDemoBuy:
    def test_get_scan_categories(self):
        s = DemoBuy(_make_client())
        assert s.get_scan_categories() == ["crypto"]

    def test_scan_empty_markets_returns_empty(self):
        assert DemoBuy(_make_client()).scan_for_opportunities([]) == []

    def test_scan_returns_opportunity_per_market(self):
        markets = [_make_market(f"mkt-{i}") for i in range(3)]
        assert len(DemoBuy(_make_client()).scan_for_opportunities(markets)) == 3

    def test_opportunity_side_is_yes(self):
        opps = DemoBuy(_make_client()).scan_for_opportunities([_make_market()])
        assert opps[0].side == "YES"

    def test_opportunity_uses_resolved_price(self):
        opps = DemoBuy(_make_client()).scan_for_opportunities([_make_market(resolved_price=0.65)])
        assert opps[0].current_price == pytest.approx(0.65, abs=0.001)

    def test_zero_resolved_price_falls_back_to_0_5(self):
        opps = DemoBuy(_make_client()).scan_for_opportunities([_make_market(resolved_price=0.0)])
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

    def test_scan_produces_valid_opportunity_fields(self):
        market = _make_market(slug="sol-100k", resolved_price=0.72)
        opps = DemoBuy(_make_client()).scan_for_opportunities([market])
        assert len(opps) == 1
        opp = opps[0]
        assert opp.market_slug == "sol-100k"
        assert opp.current_price == pytest.approx(0.72)

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
