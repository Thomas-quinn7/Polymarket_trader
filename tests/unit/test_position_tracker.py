"""
Unit tests for PositionTracker.
"""

import pytest
from types import SimpleNamespace
from unittest.mock import patch

from utils.pnl_tracker import PnLTracker
from portfolio.position_tracker import PositionTracker


@pytest.fixture
def pnl():
    return PnLTracker(initial_balance=10_000.0)


def make_tracker(pnl_tracker, max_positions=5):
    with patch("portfolio.position_tracker.config") as cfg:
        cfg.MAX_POSITIONS = max_positions
        t = PositionTracker(pnl_tracker)
    return t


@pytest.fixture
def tracker(pnl):
    return make_tracker(pnl)


def make_opportunity(
    market_id="mkt1",
    market_slug="test-market",
    question="Will X happen?",
    token_id_yes="tok_yes",
    token_id_no="tok_no",
    winning_token_id="tok_yes",
    current_price=0.985,
    edge_percent=1.5,
):
    return SimpleNamespace(
        market_id=market_id,
        market_slug=market_slug,
        question=question,
        token_id_yes=token_id_yes,
        token_id_no=token_id_no,
        winning_token_id=winning_token_id,
        current_price=current_price,
        edge_percent=edge_percent,
    )


class TestInit:
    def test_reads_max_positions_from_config(self):
        pnl = PnLTracker()
        with patch("portfolio.position_tracker.config") as cfg:
            cfg.MAX_POSITIONS = 3
            t = PositionTracker(pnl)
        assert t.max_positions == 3

    def test_starts_empty(self, tracker):
        assert tracker.positions == {}


class TestCreatePosition:
    def test_stores_under_provided_id(self, tracker):
        opp = make_opportunity()
        returned_id = tracker.create_position(opp, 10.0, 985.0, 15.0, position_id="my-id")
        assert returned_id == "my-id"
        assert tracker.get_position("my-id") is not None

    def test_generates_id_if_none_given(self, tracker):
        opp = make_opportunity()
        returned_id = tracker.create_position(opp, 10.0, 985.0, 15.0)
        assert returned_id is not None
        assert tracker.get_position(returned_id) is not None

    def test_position_is_open(self, tracker):
        opp = make_opportunity()
        pid = tracker.create_position(opp, 10.0, 985.0, 15.0, position_id="p1")
        pos = tracker.get_position("p1")
        assert pos.status == "OPEN"

    def test_position_fields_match_opportunity(self, tracker):
        opp = make_opportunity(market_id="m99", current_price=0.990, edge_percent=2.0)
        tracker.create_position(opp, 5.0, 500.0, 10.0, position_id="p1")
        pos = tracker.get_position("p1")
        assert pos.market_id == "m99"
        assert pos.entry_price == 0.990
        assert pos.shares == 5.0


class TestSettlePosition:
    def test_status_changes_to_settled(self, tracker):
        opp = make_opportunity()
        tracker.create_position(opp, 10.0, 985.0, 15.0, position_id="p1")
        tracker.settle_position("p1", settlement_price=1.0)
        pos = tracker.get_position("p1")
        assert pos.status == "SETTLED"

    def test_profit_pnl(self, tracker):
        opp = make_opportunity(current_price=0.985)
        tracker.create_position(opp, 100.0, 985.0, 15.0, position_id="p1")
        pnl = tracker.settle_position("p1", settlement_price=1.0)
        assert pytest.approx(pnl, abs=1e-4) == (1.0 - 0.985) * 100.0

    def test_loss_pnl(self, tracker):
        opp = make_opportunity(current_price=0.985)
        tracker.create_position(opp, 100.0, 985.0, 15.0, position_id="p1")
        pnl = tracker.settle_position("p1", settlement_price=0.0)
        assert pytest.approx(pnl, abs=1e-4) == (0.0 - 0.985) * 100.0

    def test_unknown_position_returns_none(self, tracker):
        result = tracker.settle_position("ghost", settlement_price=1.0)
        assert result is None


class TestFilters:
    def _create_two(self, tracker):
        opp = make_opportunity()
        tracker.create_position(opp, 10.0, 985.0, 15.0, position_id="open1")
        tracker.create_position(opp, 10.0, 985.0, 15.0, position_id="open2")
        tracker.settle_position("open2", settlement_price=1.0)

    def test_get_open_positions(self, tracker):
        self._create_two(tracker)
        assert len(tracker.get_open_positions()) == 1

    def test_get_settled_positions(self, tracker):
        self._create_two(tracker)
        assert len(tracker.get_settled_positions()) == 1

    def test_get_all_positions(self, tracker):
        self._create_two(tracker)
        assert len(tracker.get_all_positions()) == 2

    def test_get_position_count_ignores_settled(self, tracker):
        self._create_two(tracker)
        assert tracker.get_position_count() == 1


class TestCanOpenPosition:
    def test_true_when_under_limit(self, tracker):
        assert tracker.can_open_position() is True

    def test_false_when_at_limit(self):
        pnl = PnLTracker()
        t = make_tracker(pnl, max_positions=2)
        opp = make_opportunity()
        t.create_position(opp, 10.0, 985.0, 15.0, position_id="p1")
        t.create_position(opp, 10.0, 985.0, 15.0, position_id="p2")
        assert t.can_open_position() is False

    def test_settled_does_not_count_toward_limit(self):
        pnl = PnLTracker()
        t = make_tracker(pnl, max_positions=1)
        opp = make_opportunity()
        t.create_position(opp, 10.0, 985.0, 15.0, position_id="p1")
        t.settle_position("p1", settlement_price=1.0)
        assert t.can_open_position() is True
