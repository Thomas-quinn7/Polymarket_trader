"""
Unit tests for data/polymarket_models.py
Covers TradeStatus, TradeOpportunity, TradePosition, FakeCurrency, TradeRecord,
MarketCache, and backward-compatibility aliases.
"""

import pytest
from datetime import datetime, timezone, timedelta

from data.polymarket_models import (
    TradeStatus,
    PositionStatus,
    TradeOpportunity,
    TradePosition,
    FakeCurrency,
    TradeRecord,
    MarketCache,
    ArbitrageStatus,
    ArbitrageOpportunity,
    ArbitragePosition,
)

# ---------------------------------------------------------------------------
# TradeStatus
# ---------------------------------------------------------------------------


class TestTradeStatus:
    def test_values_are_lowercase_strings(self):
        assert TradeStatus.DETECTED.value == "detected"
        assert TradeStatus.EXECUTED.value == "executed"
        assert TradeStatus.FAILED.value == "failed"
        assert TradeStatus.CLOSED.value == "closed"

    def test_is_string_subclass(self):
        assert isinstance(TradeStatus.DETECTED, str)

    def test_comparison_with_plain_string(self):
        assert TradeStatus.DETECTED == "detected"


# ---------------------------------------------------------------------------
# PositionStatus
# ---------------------------------------------------------------------------


class TestPositionStatus:
    def test_values(self):
        assert PositionStatus.OPEN.value == "open"
        assert PositionStatus.SETTLED.value == "settled"
        assert PositionStatus.CLOSED.value == "closed"


# ---------------------------------------------------------------------------
# Backward-compatibility aliases
# ---------------------------------------------------------------------------


class TestBackwardCompatAliases:
    def test_arbitrage_status_is_trade_status(self):
        assert ArbitrageStatus is TradeStatus

    def test_arbitrage_opportunity_is_trade_opportunity(self):
        assert ArbitrageOpportunity is TradeOpportunity

    def test_arbitrage_position_is_trade_position(self):
        assert ArbitragePosition is TradePosition


# ---------------------------------------------------------------------------
# TradeOpportunity.to_dict()
# ---------------------------------------------------------------------------


def _make_opportunity(**kwargs):
    defaults = dict(
        market_id="mkt-001",
        market_slug="test-market",
        question="Will X happen?",
        category="crypto",
        token_id_yes="tok_yes",
        token_id_no="tok_no",
        winning_token_id="tok_yes",
        # side and opportunity_type have SQLAlchemy column defaults (applied at
        # INSERT) not Python-level defaults, so supply them explicitly here.
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


class TestTradeOpportunityToDict:
    def test_required_keys_present(self):
        opp = _make_opportunity()
        d = opp.to_dict()
        for key in (
            "market_id",
            "market_slug",
            "question",
            "category",
            "winning_token_id",
            "winning_price",
            "side",
            "opportunity_type",
            "edge_percent",
            "confidence",
            "detected_at",
            "executed_at",
            "status",
        ):
            assert key in d, f"Missing key: {key}"

    def test_status_is_string(self):
        opp = _make_opportunity()
        assert opp.to_dict()["status"] == "detected"

    def test_detected_at_isoformat(self):
        detected = datetime(2026, 3, 15, 10, 30, 0)
        opp = _make_opportunity(detected_at=detected)
        assert opp.to_dict()["detected_at"] == detected.isoformat()

    def test_defaults_side_yes(self):
        opp = _make_opportunity()
        assert opp.to_dict()["side"] == "YES"

    def test_defaults_opportunity_type_single(self):
        opp = _make_opportunity()
        assert opp.to_dict()["opportunity_type"] == "single"

    def test_executed_at_none_by_default(self):
        opp = _make_opportunity()
        assert opp.to_dict()["executed_at"] is None


# ---------------------------------------------------------------------------
# TradePosition.to_dict()
# ---------------------------------------------------------------------------


def _make_position(**kwargs):
    defaults = dict(
        id="pos-001",
        market_id="mkt-001",
        market_slug="test-market",
        question="Will X happen?",
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


class TestTradePositionToDict:
    def test_required_keys_present(self):
        pos = _make_position()
        d = pos.to_dict()
        for key in (
            "id",
            "market_id",
            "market_slug",
            "question",
            "token_id",
            "shares",
            "entry_price",
            "current_price",
            "expected_pnl",
            "edge_percent",
            "status",
            "opened_at",
            "settled_at",
            "settlement_price",
            "realized_pnl",
        ):
            assert key in d, f"Missing key: {key}"

    def test_status_is_string(self):
        pos = _make_position()
        assert pos.to_dict()["status"] == "open"

    def test_opened_at_isoformat(self):
        dt = datetime(2026, 1, 1, 12, 0, 0)
        pos = _make_position(opened_at=dt)
        assert pos.to_dict()["opened_at"] == dt.isoformat()

    def test_settled_at_none_by_default(self):
        pos = _make_position()
        assert pos.to_dict()["settled_at"] is None

    def test_realized_pnl_none_by_default(self):
        pos = _make_position()
        assert pos.to_dict()["realized_pnl"] is None

    def test_settled_position_dict(self):
        settled_at = datetime(2026, 1, 2, 0, 0, 0)
        pos = _make_position(
            status=PositionStatus.SETTLED,
            settled_at=settled_at,
            settlement_price=1.0,
            realized_pnl=1.5,
        )
        d = pos.to_dict()
        assert d["status"] == "settled"
        assert d["settlement_price"] == 1.0
        assert d["realized_pnl"] == 1.5


# ---------------------------------------------------------------------------
# FakeCurrency.to_dict()
# ---------------------------------------------------------------------------


class TestFakeCurrencyToDict:
    def test_required_keys(self):
        fc = FakeCurrency(
            balance=10000.0,
            deployed=500.0,
            pending_returns=0.0,
            created_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 1),
        )
        d = fc.to_dict()
        for key in ("id", "balance", "deployed", "pending_returns", "created_at", "updated_at"):
            assert key in d

    def test_values(self):
        fc = FakeCurrency(
            balance=9500.0,
            deployed=500.0,
            pending_returns=0.0,
            created_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 1),
        )
        d = fc.to_dict()
        assert d["balance"] == 9500.0
        assert d["deployed"] == 500.0


# ---------------------------------------------------------------------------
# TradeRecord.to_dict()
# ---------------------------------------------------------------------------


class TestTradeRecordToDict:
    def test_required_keys(self):
        tr = TradeRecord(
            market_id="mkt-1",
            market_slug="mkt",
            token_id="tok",
            shares=100.0,
            entry_price=0.985,
            exit_price=1.0,
            pnl=1.5,
            pnl_percent=1.52,
            edge_percent=1.5,
            status=TradeStatus.CLOSED,
            opened_at=datetime(2026, 1, 1),
            settled_at=datetime(2026, 1, 2),
            settlement_price=1.0,
        )
        d = tr.to_dict()
        for key in (
            "market_id",
            "market_slug",
            "token_id",
            "shares",
            "entry_price",
            "exit_price",
            "pnl",
            "pnl_percent",
            "edge_percent",
            "status",
            "opened_at",
            "settled_at",
            "settlement_price",
        ):
            assert key in d

    def test_status_is_string(self):
        tr = TradeRecord(
            market_id="m",
            market_slug="m",
            token_id="t",
            shares=1.0,
            entry_price=0.5,
            exit_price=1.0,
            pnl=0.5,
            pnl_percent=100.0,
            edge_percent=2.0,
            status=TradeStatus.CLOSED,
            opened_at=datetime(2026, 1, 1),
        )
        assert tr.to_dict()["status"] == "closed"


# ---------------------------------------------------------------------------
# MarketCache.to_dict()
# ---------------------------------------------------------------------------


class TestMarketCacheToDict:
    def test_required_keys(self):
        mc = MarketCache(
            market_id="mkt-1",
            token_id_yes="ty",
            token_id_no="tn",
            yes_price=0.6,
            no_price=0.4,
            mid_price=0.5,
            cached_at=datetime(2026, 1, 1),
            expires_at=datetime(2026, 1, 1, 0, 5, 0),
        )
        d = mc.to_dict()
        for key in (
            "id",
            "market_id",
            "yes_price",
            "no_price",
            "mid_price",
            "cached_at",
            "expires_at",
        ):
            assert key in d
