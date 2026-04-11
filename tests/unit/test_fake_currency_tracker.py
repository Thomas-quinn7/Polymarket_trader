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

    def test_allocate_full_amount_no_cap(self, tracker):
        # The tracker honours the caller-supplied amount exactly.
        # A hard cap at starting_balance * 0.2 was removed because it caused a
        # silent mismatch: the executor's shares/fee calculations used the full
        # amount while only the capped amount was deducted from the balance.
        tracker.allocate_to_position("p1", "m1", 9_000.0)
        assert tracker.balance == 1_000.0  # 10k - 9k

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

    def test_return_frees_position_slot(self, tracker):
        # After returning, the position is removed so the slot can be reused
        tracker.allocate_to_position("p1", "m1", 2_000.0)
        tracker.return_to_balance("p1", 2_000.0)
        assert "p1" not in tracker.positions
        # Slot is free — a 6th allocation should now succeed even after 5 cycles
        for i in range(5):
            tracker.allocate_to_position(f"cycle_{i}", "m1", 100.0)
            tracker.return_to_balance(f"cycle_{i}", 100.0)
        assert tracker.balance == 10_000.0  # back to starting balance

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
