"""
Unit tests for FakeCurrencyTracker.
"""

import pytest
from unittest.mock import patch

from portfolio.fake_currency_tracker import FakeCurrencyTracker


@pytest.fixture
def tracker():
    with patch("portfolio.fake_currency_tracker.config") as cfg:
        cfg.FAKE_CURRENCY_BALANCE = 10_000.0
        cfg.MAX_POSITIONS = 5
        t = FakeCurrencyTracker()
    return t


class TestFakeCurrencyTrackerInit:
    def test_starting_balance(self):
        with patch("portfolio.fake_currency_tracker.config") as cfg:
            cfg.FAKE_CURRENCY_BALANCE = 5_000.0
            cfg.MAX_POSITIONS = 5
            t = FakeCurrencyTracker()
        assert t.starting_balance == 5_000.0
        assert t.balance == 5_000.0
        assert t.deployed == 0.0

    def test_positions_empty_on_init(self, tracker):
        assert tracker.positions == {}


class TestAllocate:
    def test_allocate_deducts_balance(self, tracker):
        tracker.allocate_to_position("p1", "m1", 2_000.0)
        assert tracker.balance == 8_000.0

    def test_allocate_increases_deployed(self, tracker):
        tracker.allocate_to_position("p1", "m1", 2_000.0)
        assert tracker.deployed == 2_000.0

    def test_allocate_caps_at_20_percent(self, tracker):
        # Allocating more than 20 % of starting balance is capped
        tracker.allocate_to_position("p1", "m1", 9_000.0)
        assert tracker.balance == 8_000.0  # 10k - 20% (2k)

    def test_allocate_returns_true_on_success(self, tracker):
        result = tracker.allocate_to_position("p1", "m1", 1_000.0)
        assert result is True

    def test_allocate_returns_false_if_insufficient_balance(self, tracker):
        # Drain balance first
        tracker.balance = 100.0
        result = tracker.allocate_to_position("p1", "m1", 1_000.0)
        assert result is False
        assert tracker.balance == 100.0  # unchanged

    def test_allocate_returns_false_at_max_positions(self, tracker):
        with patch("portfolio.fake_currency_tracker.config") as cfg:
            cfg.FAKE_CURRENCY_BALANCE = 10_000.0
            cfg.MAX_POSITIONS = 2
            t = FakeCurrencyTracker()
            t.allocate_to_position("p1", "m1", 500.0)
            t.allocate_to_position("p2", "m2", 500.0)
            result = t.allocate_to_position("p3", "m3", 500.0)
        assert result is False

    def test_duplicate_position_id_overwrites(self, tracker):
        tracker.allocate_to_position("p1", "m1", 500.0)
        before_balance = tracker.balance
        tracker.allocate_to_position("p1", "m1", 500.0)
        # Second allocation debits again and overwrites the record
        assert tracker.balance < before_balance


class TestReturnToBalance:
    def test_return_increases_balance(self, tracker):
        tracker.allocate_to_position("p1", "m1", 2_000.0)
        tracker.return_to_balance("p1", 2_100.0)
        assert tracker.balance == 10_100.0  # profit scenario

    def test_return_decreases_deployed(self, tracker):
        tracker.allocate_to_position("p1", "m1", 2_000.0)
        tracker.return_to_balance("p1", 2_100.0)
        assert tracker.deployed == 0.0  # capital freed after settlement

    def test_return_true_on_success(self, tracker):
        tracker.allocate_to_position("p1", "m1", 1_000.0)
        result = tracker.return_to_balance("p1", 1_000.0)
        assert result is True

    def test_return_false_for_unknown_position(self, tracker):
        result = tracker.return_to_balance("unknown", 500.0)
        assert result is False
        assert tracker.balance == 10_000.0  # unchanged


class TestGetters:
    def test_get_balance(self, tracker):
        assert tracker.get_balance() == 10_000.0

    def test_get_deployed(self, tracker):
        tracker.allocate_to_position("p1", "m1", 2_000.0)
        assert tracker.get_deployed() == 2_000.0

    def test_get_available_equals_balance(self, tracker):
        assert tracker.get_available() == tracker.get_balance()


class TestReset:
    def test_reset_restores_state(self, tracker):
        tracker.allocate_to_position("p1", "m1", 2_000.0)
        tracker.reset()
        assert tracker.balance == tracker.starting_balance
        assert tracker.deployed == 0.0
        assert tracker.positions == {}
