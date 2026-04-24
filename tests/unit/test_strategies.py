"""
Unit tests for strategy infrastructure:
  - strategies/base.py          (BaseStrategy ABC, default hooks)
  - strategies/registry.py      (auto-discovery, load_strategy)
  - strategies/config_loader.py (YAML loading, env-var overrides)
  - strategies/example_strategy (template strategy)
"""

import os
import pytest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from strategies.base import BaseStrategy, TradingStrategy
from strategies.registry import load_strategy, available_strategies
from strategies.config_loader import load_strategy_config
from strategies.example_strategy import ExampleStrategy
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
    def test_available_strategies_includes_example(self):
        assert "example_strategy" in available_strategies()

    def test_load_example_strategy(self):
        assert isinstance(load_strategy("example_strategy", _make_client()), ExampleStrategy)

    def test_load_unknown_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown strategy"):
            load_strategy("nonexistent_strategy", _make_client())

    def test_error_message_lists_available(self):
        with pytest.raises(ValueError) as exc_info:
            load_strategy("bad_strategy", _make_client())
        assert "example_strategy" in str(exc_info.value)

    def test_non_strategy_folders_not_registered(self):
        """examples/ and configs/ must not appear in the registry."""
        strategies = available_strategies()
        assert "examples" not in strategies
        assert "configs" not in strategies

    def test_public_strategies_are_registered(self):
        """All committed (public) strategy folders must appear in the registry."""
        # Only check strategies that are tracked by git — private/local-only
        # folders (gitignored) are intentionally absent from the registry on CI.
        import subprocess

        result = subprocess.run(
            ["git", "ls-files", "strategies/"],
            capture_output=True,
            text=True,
        )
        tracked = {
            p.split("/")[1]
            for p in result.stdout.splitlines()
            if p.startswith("strategies/") and "/" in p[len("strategies/") :]
        }
        # Remove non-strategy entries (base files, not subfolders with strategies)
        # enhanced_market_scanner lives under strategies/ but exports a scanner
        # utility class, not a BaseStrategy subclass — the registry deliberately
        # skips it, so the test must too.
        skip = {"__pycache__", "examples", "configs", "enhanced_market_scanner"}
        registered = available_strategies()
        for folder in tracked - skip:
            if folder and not folder.startswith("_"):
                assert (
                    folder in registered
                ), f"Tracked strategy folder '{folder}' is not in the registry."


# ---------------------------------------------------------------------------
# ExampleStrategy — template strategy
# ---------------------------------------------------------------------------


class TestExampleStrategy:
    def test_initialises_without_error(self):
        ExampleStrategy(_make_client())

    def test_scan_empty_markets_returns_empty(self):
        assert ExampleStrategy(_make_client()).scan_for_opportunities([]) == []

    def test_scan_returns_no_opportunities_with_zero_gross_edge(self):
        # The template has gross_edge = 0.0 (stub). With a 2% taker fee,
        # net_edge = -2.0, which fails the edge filter — no entries fired.
        markets = [_make_market(f"mkt-{i}") for i in range(3)]
        opps = ExampleStrategy(_make_client()).scan_for_opportunities(markets)
        assert opps == []

    def test_get_best_opportunities_limits(self):
        from data.polymarket_models import TradeOpportunity, TradeStatus

        opps = [
            TradeOpportunity(
                market_id=f"mkt-{i}",
                market_slug=f"slug-{i}",
                question="Q?",
                category="crypto",
                token_id_yes="yes",
                token_id_no="no",
                winning_token_id="yes",
                current_price=0.60,
                edge_percent=float(i),
                confidence=0.8,
                detected_at=datetime.now(timezone.utc),
                status=TradeStatus.DETECTED,
            )
            for i in range(10)
        ]
        result = ExampleStrategy(_make_client()).get_best_opportunities(opps, limit=3)
        assert len(result) == 3

    def test_should_exit_false_before_expiry(self):
        s = ExampleStrategy(_make_client())
        pos = _make_position(expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
        assert s.should_exit(pos, 0.99) is False

    def test_should_exit_true_after_expiry(self):
        s = ExampleStrategy(_make_client())
        pos = _make_position(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        assert s.should_exit(pos, 0.99) is True

    def test_should_exit_false_when_no_expiry(self):
        s = ExampleStrategy(_make_client())
        assert s.should_exit(_make_position(expires_at=None), 0.99) is False

    def test_get_exit_price_returns_current(self):
        s = ExampleStrategy(_make_client())
        assert s.get_exit_price(_make_position(), 0.97) == pytest.approx(0.97)

    def test_get_scan_categories_from_config(self):
        s = ExampleStrategy(_make_client())
        cats = s.get_scan_categories()
        assert isinstance(cats, list)
        assert len(cats) > 0
