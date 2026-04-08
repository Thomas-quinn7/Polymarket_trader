"""
Data validation tests — field parsing, type correctness, and bounds.

Covers the boundary conditions and parsing logic across the data layer:
market schema normalisation, model serialisation, settlement bounds,
and executor input validation.

These tests are diagnostic / debugging aids; they are not run as part
of the live trading process.
"""

import math
import pytest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from data.market_schema import PolymarketMarket, _classify_category
from data.polymarket_models import (
    TradeOpportunity, TradeStatus, TradePosition, PositionStatus,
)
from portfolio.position_tracker import PositionTracker, Position
from utils.pnl_tracker import PnLTracker
from portfolio.fake_currency_tracker import FakeCurrencyTracker
from execution.order_executor import OrderExecutor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _raw_market(**overrides):
    """Return a minimal valid raw market dict, with optional overrides."""
    base = {
        "id": "mkt-001",
        "slug": "test-market",
        "question": "Will X happen?",
        "clobTokenIds": ["tok_yes", "tok_no"],
        "tags": [],
        "volume": 5_000.0,
    }
    base.update(overrides)
    return base


def _make_opportunity(**kwargs):
    defaults = dict(
        market_id="mkt-001",
        market_slug="test-market",
        question="Will X happen?",
        category="crypto",
        token_id_yes="tok_yes",
        token_id_no="tok_no",
        winning_token_id="tok_yes",
        side="YES",
        opportunity_type="single",
        current_price=0.985,
        edge_percent=1.5,
        confidence=0.8,
        detected_at=datetime(2026, 1, 1, 12, 0, 0),
        status=TradeStatus.DETECTED,
    )
    defaults.update(kwargs)
    return TradeOpportunity(**defaults)


def _make_executor(balance=10_000.0, max_pos=5, split=0.20):
    with patch("portfolio.fake_currency_tracker.config") as cfg:
        cfg.FAKE_CURRENCY_BALANCE = balance
        cfg.MAX_POSITIONS = max_pos
        currency = FakeCurrencyTracker()
    pnl = PnLTracker(initial_balance=balance)
    with patch("portfolio.position_tracker.config") as cfg:
        cfg.MAX_POSITIONS = max_pos
        positions = PositionTracker(pnl)
    with patch("execution.order_executor.config") as cfg:
        cfg.PAPER_TRADING_ONLY = True
        cfg.CAPITAL_SPLIT_PERCENT = split
        executor = OrderExecutor(
            pnl_tracker=pnl, position_tracker=positions, currency_tracker=currency
        )
    return executor, currency, pnl, positions


def _buy(executor, opp, pid, split=0.20):
    with patch("execution.order_executor.config") as cfg:
        cfg.PAPER_TRADING_ONLY = True
        cfg.CAPITAL_SPLIT_PERCENT = split
        return executor.execute_buy(opp, pid)


# ---------------------------------------------------------------------------
# Market schema — end_time field name variants
# ---------------------------------------------------------------------------

class TestEndTimeFieldVariants:
    """All known close-time field names must be recognised."""

    def _market_with_key(self, key: str, value: str) -> PolymarketMarket:
        raw = _raw_market()
        raw[key] = value
        return PolymarketMarket.from_api(raw)

    def _future_str(self, seconds=600) -> str:
        dt = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def test_endDate_key(self):
        m = self._market_with_key("endDate", self._future_str())
        assert m.end_time is not None

    def test_end_date_underscore_key(self):
        m = self._market_with_key("end_date", self._future_str())
        assert m.end_time is not None

    def test_end_time_key(self):
        m = self._market_with_key("end_time", self._future_str())
        assert m.end_time is not None

    def test_closeTime_key(self):
        m = self._market_with_key("closeTime", self._future_str())
        assert m.end_time is not None

    def test_close_time_underscore_key(self):
        m = self._market_with_key("close_time", self._future_str())
        assert m.end_time is not None

    def test_no_end_time_key_gives_none(self):
        m = PolymarketMarket.from_api(_raw_market())
        assert m.end_time is None

    def test_end_time_is_utc_aware(self):
        m = self._market_with_key("endDate", self._future_str())
        assert m.end_time.tzinfo is not None

    def test_malformed_date_string_gives_none(self):
        raw = _raw_market(endDate="not-a-date")
        m = PolymarketMarket.from_api(raw)
        assert m.end_time is None


# ---------------------------------------------------------------------------
# Market schema — outcomePrices field parsing
# ---------------------------------------------------------------------------

class TestOutcomePricesParsing:
    """outcomePrices may arrive as a JSON string or a Python list."""

    def test_json_string_parsed(self):
        raw = _raw_market(outcomePrices='["0.985","0.015"]')
        m = PolymarketMarket.from_api(raw)
        assert m.outcome_prices == pytest.approx([0.985, 0.015], abs=1e-6)

    def test_python_list_of_strings(self):
        raw = _raw_market(outcomePrices=["0.60", "0.40"])
        m = PolymarketMarket.from_api(raw)
        assert m.outcome_prices == pytest.approx([0.60, 0.40], abs=1e-6)

    def test_python_list_of_floats(self):
        raw = _raw_market(outcomePrices=[0.70, 0.30])
        m = PolymarketMarket.from_api(raw)
        assert m.outcome_prices == pytest.approx([0.70, 0.30], abs=1e-6)

    def test_malformed_json_string_returns_empty(self):
        raw = _raw_market(outcomePrices="[not valid json")
        m = PolymarketMarket.from_api(raw)
        assert m.outcome_prices == []

    def test_none_returns_empty(self):
        raw = _raw_market()
        # Explicitly set to None (overrides default)
        raw["outcomePrices"] = None
        m = PolymarketMarket.from_api(raw)
        assert m.outcome_prices == []

    def test_missing_field_returns_empty(self):
        m = PolymarketMarket.from_api(_raw_market())
        assert m.outcome_prices == []

    def test_outcome_prices_are_floats(self):
        raw = _raw_market(outcomePrices='["0.985","0.015"]')
        m = PolymarketMarket.from_api(raw)
        for p in m.outcome_prices:
            assert isinstance(p, float)

    def test_yes_price_at_index_zero(self):
        raw = _raw_market(outcomePrices=["0.99", "0.01"])
        m = PolymarketMarket.from_api(raw)
        assert m.outcome_prices[0] == pytest.approx(0.99, abs=1e-6)


# ---------------------------------------------------------------------------
# Market schema — volume field fallback chain
# ---------------------------------------------------------------------------

class TestVolumeFieldFallback:
    def test_volume_primary_field(self):
        m = PolymarketMarket.from_api(_raw_market(volume=12_345.0))
        assert m.volume == pytest.approx(12_345.0)

    def test_volume_num_fallback(self):
        raw = {"id": "x", "volumeNum": 9_999.0, "clobTokenIds": []}
        m = PolymarketMarket.from_api(raw)
        assert m.volume == pytest.approx(9_999.0)

    def test_volume_clob_fallback(self):
        raw = {"id": "x", "volumeClob": 4_321.0, "clobTokenIds": []}
        m = PolymarketMarket.from_api(raw)
        assert m.volume == pytest.approx(4_321.0)

    def test_all_missing_defaults_to_zero(self):
        raw = {"id": "x", "clobTokenIds": []}
        m = PolymarketMarket.from_api(raw)
        assert m.volume == 0.0

    def test_zero_volume_explicit(self):
        m = PolymarketMarket.from_api(_raw_market(volume=0.0))
        assert m.volume == 0.0

    def test_large_volume_preserved(self):
        m = PolymarketMarket.from_api(_raw_market(volume=1_000_000.0))
        assert m.volume == pytest.approx(1_000_000.0)


# ---------------------------------------------------------------------------
# Market schema — market_id fallback chain
# ---------------------------------------------------------------------------

class TestMarketIdFallback:
    def test_id_field_used_first(self):
        raw = {"id": "primary", "conditionId": "cond", "slug": "slg", "clobTokenIds": []}
        m = PolymarketMarket.from_api(raw)
        assert m.market_id == "primary"

    def test_conditionId_fallback(self):
        raw = {"conditionId": "cond-99", "clobTokenIds": []}
        m = PolymarketMarket.from_api(raw)
        assert m.market_id == "cond-99"

    def test_marketSlug_fallback(self):
        raw = {"marketSlug": "mslug", "clobTokenIds": []}
        m = PolymarketMarket.from_api(raw)
        assert m.market_id == "mslug"

    def test_slug_fallback(self):
        raw = {"slug": "fallback-slug", "clobTokenIds": []}
        m = PolymarketMarket.from_api(raw)
        assert m.market_id == "fallback-slug"

    def test_all_missing_returns_none(self):
        raw = {"clobTokenIds": ["t1"]}
        assert PolymarketMarket.from_api(raw) is None

    def test_market_id_always_string(self):
        raw = {"id": 12345, "clobTokenIds": []}
        m = PolymarketMarket.from_api(raw)
        assert isinstance(m.market_id, str)


# ---------------------------------------------------------------------------
# Market schema — question / title fallback
# ---------------------------------------------------------------------------

class TestQuestionFallback:
    def test_question_field_primary(self):
        raw = {"id": "x", "question": "Primary?", "title": "Title?", "slug": "slg", "clobTokenIds": []}
        m = PolymarketMarket.from_api(raw)
        assert m.question == "Primary?"

    def test_title_fallback(self):
        raw = {"id": "x", "title": "Title?", "slug": "slg", "clobTokenIds": []}
        m = PolymarketMarket.from_api(raw)
        assert m.question == "Title?"

    def test_slug_fallback(self):
        raw = {"id": "x", "slug": "the-slug", "clobTokenIds": []}
        m = PolymarketMarket.from_api(raw)
        assert m.question == "the-slug"


# ---------------------------------------------------------------------------
# Market schema — token_ids validation
# ---------------------------------------------------------------------------

class TestTokenIdParsing:
    def test_valid_list_preserved(self):
        m = PolymarketMarket.from_api(_raw_market())
        assert m.token_ids == ["tok_yes", "tok_no"]

    def test_non_list_becomes_empty(self):
        raw = _raw_market()
        raw["clobTokenIds"] = "not-a-list"
        m = PolymarketMarket.from_api(raw)
        assert m.token_ids == []

    def test_missing_field_becomes_empty(self):
        raw = {"id": "x", "slug": "s"}
        m = PolymarketMarket.from_api(raw)
        assert m.token_ids == []

    def test_single_element_list_preserved(self):
        raw = _raw_market()
        raw["clobTokenIds"] = ["only_one"]
        m = PolymarketMarket.from_api(raw)
        assert m.token_ids == ["only_one"]


# ---------------------------------------------------------------------------
# Category classification edge cases
# ---------------------------------------------------------------------------

class TestCategoryClassificationEdgeCases:
    def test_empty_list_returns_other(self):
        assert _classify_category([]) == "other"

    def test_none_values_in_list_skipped(self):
        assert _classify_category([None, None, {"label": "fed"}]) == "fed"

    def test_integer_tags_skipped(self):
        assert _classify_category([42, {"label": "crypto"}]) == "crypto"

    def test_case_insensitive_string_tag(self):
        assert _classify_category(["BITCOIN"]) == "crypto"
        assert _classify_category(["Bitcoin"]) == "crypto"

    def test_case_insensitive_dict_label(self):
        assert _classify_category([{"label": "CRYPTO"}]) == "crypto"

    def test_dict_with_name_key(self):
        assert _classify_category([{"name": "ethereum"}]) == "crypto"

    def test_unknown_tag_falls_through_to_other(self):
        assert _classify_category([{"label": "sports"}]) == "other"
        assert _classify_category(["randomtag"]) == "other"

    def test_first_matching_tag_wins(self):
        result = _classify_category([{"label": "fed"}, {"label": "crypto"}])
        assert result == "fed"

    def test_dict_missing_both_label_and_name(self):
        assert _classify_category([{"something": "crypto"}]) == "other"


# ---------------------------------------------------------------------------
# TradeOpportunity serialisation — to_dict types and shape
# ---------------------------------------------------------------------------

class TestTradeOpportunityToDict:
    def test_all_required_keys_present(self):
        opp = _make_opportunity()
        d = opp.to_dict()
        for key in ("id", "market_id", "market_slug", "question", "category",
                    "winning_token_id", "winning_price", "side",
                    "opportunity_type", "edge_percent", "confidence",
                    "detected_at", "executed_at", "status"):
            assert key in d, f"Missing key: {key}"

    def test_no_time_to_close_key(self):
        opp = _make_opportunity()
        d = opp.to_dict()
        assert "time_to_close_seconds" not in d
        assert "end_time" not in d

    def test_winning_price_is_float(self):
        opp = _make_opportunity(current_price=0.985)
        assert isinstance(opp.to_dict()["winning_price"], float)

    def test_edge_percent_is_float(self):
        opp = _make_opportunity(edge_percent=1.5)
        assert isinstance(opp.to_dict()["edge_percent"], float)

    def test_detected_at_is_isoformat_string(self):
        detected = datetime(2026, 6, 15, 10, 30, 0)
        opp = _make_opportunity(detected_at=detected)
        d = opp.to_dict()
        assert isinstance(d["detected_at"], str)
        # Should round-trip cleanly
        assert datetime.fromisoformat(d["detected_at"]) == detected

    def test_executed_at_none_by_default(self):
        opp = _make_opportunity()
        assert opp.to_dict()["executed_at"] is None

    def test_status_is_string_value(self):
        opp = _make_opportunity(status=TradeStatus.DETECTED)
        assert opp.to_dict()["status"] == "detected"

    def test_side_preserved(self):
        opp = _make_opportunity(side="YES")
        assert opp.to_dict()["side"] == "YES"

    def test_opportunity_type_preserved(self):
        opp = _make_opportunity(opportunity_type="paired")
        assert opp.to_dict()["opportunity_type"] == "paired"

    def test_confidence_none_allowed(self):
        opp = _make_opportunity(confidence=None)
        assert opp.to_dict()["confidence"] is None


# ---------------------------------------------------------------------------
# TradePosition serialisation
# ---------------------------------------------------------------------------

class TestTradePositionToDict:
    def _make_pos(self, **kwargs):
        defaults = dict(
            id="pos-001",
            market_id="mkt-001",
            market_slug="slug",
            question="Q?",
            token_id="tok_yes",
            shares=100.0,
            entry_price=0.985,
            current_price=0.990,
            expected_pnl=1.5,
            edge_percent=1.5,
            status=PositionStatus.OPEN,
            opened_at=datetime(2026, 1, 1, 12, 0, 0),
        )
        defaults.update(kwargs)
        return TradePosition(**defaults)

    def test_required_keys(self):
        pos = self._make_pos()
        d = pos.to_dict()
        for key in ("id", "market_id", "market_slug", "question", "token_id",
                    "shares", "entry_price", "current_price", "expected_pnl",
                    "edge_percent", "status", "opened_at", "settled_at",
                    "settlement_price", "realized_pnl"):
            assert key in d, f"Missing key: {key}"

    def test_status_string(self):
        assert self._make_pos().to_dict()["status"] == "open"

    def test_settled_status(self):
        pos = self._make_pos(
            status=PositionStatus.SETTLED,
            settled_at=datetime(2026, 1, 2),
            settlement_price=1.0,
            realized_pnl=1.5,
        )
        d = pos.to_dict()
        assert d["status"] == "settled"
        assert d["settlement_price"] == 1.0
        assert d["realized_pnl"] == 1.5

    def test_shares_is_float(self):
        assert isinstance(self._make_pos().to_dict()["shares"], float)

    def test_entry_price_is_float(self):
        assert isinstance(self._make_pos().to_dict()["entry_price"], float)


# ---------------------------------------------------------------------------
# Position dataclass — field types and defaults
# ---------------------------------------------------------------------------

class TestPositionDataclass:
    def _make(self, **kwargs):
        defaults = dict(
            position_id="p1",
            market_id="m1",
            market_slug="slug",
            question="Q?",
            token_id_yes="ty",
            token_id_no="tn",
            winning_token_id="ty",
            shares=10.0,
            entry_price=0.985,
            allocated_capital=985.0,
            expected_profit=15.0,
            edge_percent=1.5,
        )
        defaults.update(kwargs)
        return Position(**defaults)

    def test_default_status_open(self):
        assert self._make().status == "OPEN"

    def test_default_expires_at_none(self):
        assert self._make().expires_at is None

    def test_expires_at_set(self):
        expiry = datetime.now(timezone.utc) + timedelta(hours=1)
        pos = self._make(expires_at=expiry)
        assert pos.expires_at == expiry

    def test_to_dict_includes_expires_at(self):
        expiry = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        pos = self._make(expires_at=expiry)
        d = pos.to_dict()
        assert "expires_at" in d
        assert d["expires_at"] == expiry.isoformat()

    def test_to_dict_expires_at_none_serialised(self):
        pos = self._make(expires_at=None)
        assert pos.to_dict()["expires_at"] is None


# ---------------------------------------------------------------------------
# Order executor — rejects invalid prices
# ---------------------------------------------------------------------------

class TestExecutorInvalidPriceRejection:
    def _opp(self, price):
        return SimpleNamespace(
            market_id="m1", market_slug="s1",
            question="Q?",
            token_id_yes="ty", token_id_no="tn", winning_token_id="ty",
            current_price=price,
            edge_percent=1.5,
            expires_at=None,
        )

    def test_zero_price_rejected(self):
        executor, *_ = _make_executor()
        result = _buy(executor, self._opp(0.0), "p1")
        assert result is False

    def test_negative_price_rejected(self):
        executor, *_ = _make_executor()
        result = _buy(executor, self._opp(-0.5), "p1")
        assert result is False

    def test_none_price_rejected(self):
        executor, *_ = _make_executor()
        result = _buy(executor, self._opp(None), "p1")
        assert result is False

    def test_valid_low_price_accepted(self):
        executor, *_ = _make_executor()
        # Very low (but positive) price is valid — just means more shares
        result = _buy(executor, self._opp(0.01), "p1")
        assert result is True

    def test_valid_high_price_accepted(self):
        executor, *_ = _make_executor()
        result = _buy(executor, self._opp(0.999), "p1")
        assert result is True


# ---------------------------------------------------------------------------
# FakeCurrencyTracker — balance invariant at every step
# ---------------------------------------------------------------------------

class TestCurrencyTrackerInvariant:
    """balance + deployed must always equal starting_balance (ignoring realised PnL)."""

    def _tracker(self, balance=10_000.0):
        with patch("portfolio.fake_currency_tracker.config") as cfg:
            cfg.FAKE_CURRENCY_BALANCE = balance
            cfg.MAX_POSITIONS = 10
            return FakeCurrencyTracker()

    def test_invariant_on_init(self):
        t = self._tracker()
        assert t.balance + t.deployed == pytest.approx(t.starting_balance, abs=0.01)

    def test_invariant_after_allocate(self):
        t = self._tracker()
        t.allocate_to_position("p1", "m1", 2_000.0)
        assert t.balance + t.deployed == pytest.approx(t.starting_balance, abs=0.01)

    def test_invariant_after_return_at_cost(self):
        t = self._tracker()
        t.allocate_to_position("p1", "m1", 2_000.0)
        t.return_to_balance("p1", 2_000.0)
        # All capital returned at cost → back to starting balance
        assert t.balance == pytest.approx(t.starting_balance, abs=0.01)
        assert t.deployed == pytest.approx(0.0, abs=0.01)

    def test_return_at_profit_increases_balance(self):
        t = self._tracker()
        t.allocate_to_position("p1", "m1", 2_000.0)
        t.return_to_balance("p1", 2_100.0)  # $100 profit
        assert t.balance == pytest.approx(t.starting_balance + 100.0, abs=0.01)

    def test_return_at_loss_decreases_balance(self):
        t = self._tracker()
        t.allocate_to_position("p1", "m1", 2_000.0)
        t.return_to_balance("p1", 1_900.0)  # $100 loss
        assert t.balance == pytest.approx(t.starting_balance - 100.0, abs=0.01)

    def test_multiple_allocate_and_return_invariant(self):
        t = self._tracker()
        for i in range(4):
            t.allocate_to_position(f"p{i}", f"m{i}", 500.0)
        for i in range(4):
            t.return_to_balance(f"p{i}", 500.0)
        assert t.balance == pytest.approx(t.starting_balance, abs=0.01)
        assert t.deployed == pytest.approx(0.0, abs=0.01)

    def test_failed_allocate_does_not_change_state(self):
        t = self._tracker()
        t.balance = 50.0  # not enough
        result = t.allocate_to_position("p1", "m1", 2_000.0)
        assert result is False
        assert t.balance == pytest.approx(50.0, abs=0.01)
        assert t.deployed == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# PnL tracker — derived statistics correctness
# ---------------------------------------------------------------------------

class TestPnLTrackerStatistics:
    def _tracker(self):
        return PnLTracker(initial_balance=10_000.0)

    def test_profit_factor_ratio(self):
        t = self._tracker()
        # Two wins of 100 each, one loss of 50
        t.open_position("p1", "m1", 100.0, 0.0); t.close_position("p1", exit_price=1.0)  # +100
        t.open_position("p2", "m2", 100.0, 0.0); t.close_position("p2", exit_price=1.0)  # +100
        t.open_position("p3", "m3", 100.0, 0.5); t.close_position("p3", exit_price=0.0)  # -50
        summary = t.get_summary()
        # profit_factor = total_wins / abs(total_losses) = 200 / 50 = 4.0
        assert summary.profit_factor == pytest.approx(4.0, rel=0.01)

    def test_average_win(self):
        t = self._tracker()
        t.open_position("p1", "m1", 100.0, 0.0); t.close_position("p1", exit_price=1.0)  # 100
        t.open_position("p2", "m2", 200.0, 0.0); t.close_position("p2", exit_price=1.0)  # 200
        summary = t.get_summary()
        assert summary.average_win == pytest.approx(150.0, abs=0.01)

    def test_average_loss(self):
        t = self._tracker()
        t.open_position("p1", "m1", 100.0, 1.0); t.close_position("p1", exit_price=0.0)  # -100
        t.open_position("p2", "m2", 200.0, 1.0); t.close_position("p2", exit_price=0.0)  # -200
        summary = t.get_summary()
        assert summary.average_loss == pytest.approx(-150.0, abs=0.01)

    def test_win_rate_with_mixed_trades(self):
        t = self._tracker()
        t.open_position("p1", "m1", 100.0, 0.0); t.close_position("p1", exit_price=1.0)
        t.open_position("p2", "m2", 100.0, 1.0); t.close_position("p2", exit_price=0.0)
        t.open_position("p3", "m3", 100.0, 0.0); t.close_position("p3", exit_price=1.0)
        summary = t.get_summary()
        assert summary.win_rate == pytest.approx(2 / 3 * 100, rel=0.01)

    def test_no_loss_profit_factor_is_zero(self):
        """When there are no losses abs_loss==0, so profit_factor is defined as 0.0."""
        t = self._tracker()
        t.open_position("p1", "m1", 100.0, 0.0); t.close_position("p1", exit_price=1.0)
        summary = t.get_summary()
        assert summary.profit_factor == pytest.approx(0.0, abs=1e-6)

    def test_max_drawdown_after_sequence(self):
        t = self._tracker()
        # Win, then bigger loss
        t.open_position("p1", "m1", 100.0, 0.0); t.close_position("p1", exit_price=1.0)  # +100
        t.open_position("p2", "m2", 500.0, 1.0); t.close_position("p2", exit_price=0.0)  # -500
        assert t.max_drawdown > 0.0

    def test_total_pnl_sums_correctly(self):
        t = self._tracker()
        t.open_position("p1", "m1", 100.0, 0.985); t.close_position("p1", exit_price=1.0)
        t.open_position("p2", "m2", 100.0, 0.985); t.close_position("p2", exit_price=0.0)
        summary = t.get_summary()
        expected = (1.0 - 0.985) * 100 + (0.0 - 0.985) * 100
        assert summary.total_pnl == pytest.approx(expected, abs=0.01)


# ---------------------------------------------------------------------------
# has_sufficient_liquidity edge cases
# ---------------------------------------------------------------------------

class TestLiquidityCheck:
    def test_zero_volume_fails_any_min(self):
        raw = {"id": "x", "clobTokenIds": []}
        m = PolymarketMarket.from_api(raw)
        assert m.has_sufficient_liquidity(0.0) is False

    def test_exact_match_passes(self):
        m = PolymarketMarket.from_api(_raw_market(volume=1_000.0))
        assert m.has_sufficient_liquidity(1_000.0) is True

    def test_above_min_passes(self):
        m = PolymarketMarket.from_api(_raw_market(volume=5_000.0))
        assert m.has_sufficient_liquidity(1_000.0) is True

    def test_below_min_fails(self):
        m = PolymarketMarket.from_api(_raw_market(volume=999.0))
        assert m.has_sufficient_liquidity(1_000.0) is False
