"""
Unit tests for PnLTracker.
"""

import pytest
from utils.pnl_tracker import PnLTracker


@pytest.fixture
def tracker():
    return PnLTracker(initial_balance=10_000.0)


class TestInit:
    def test_initial_balance(self, tracker):
        assert tracker.initial_balance == 10_000.0
        assert tracker.current_balance == 10_000.0
        assert tracker.peak_balance == 10_000.0

    def test_initial_state_empty(self, tracker):
        assert tracker.trades == []
        assert tracker.open_positions == {}
        assert tracker.max_drawdown == 0.0


class TestOpenPosition:
    def test_creates_trade_record(self, tracker):
        tracker.open_position("pos1", "mkt1", 100.0, 0.985)
        assert "pos1" in tracker.open_positions
        record = tracker.open_positions["pos1"]
        assert record.market_id == "mkt1"
        assert record.quantity == 100.0
        assert record.entry_price == 0.985

    def test_returns_trade_id(self, tracker):
        trade_id = tracker.open_position("pos1", "mkt1", 100.0, 0.985)
        assert "pos1" in trade_id

    def test_appends_to_trades_list(self, tracker):
        tracker.open_position("pos1", "mkt1", 100.0, 0.985)
        assert len(tracker.trades) == 1


class TestClosePosition:
    def test_profit_pnl(self, tracker):
        tracker.open_position("pos1", "mkt1", 100.0, 0.985)
        pnl = tracker.close_position("pos1", exit_price=1.0)
        # (1.0 - 0.985) * 100 = 1.5
        assert pytest.approx(pnl, abs=1e-6) == 1.5

    def test_loss_pnl(self, tracker):
        tracker.open_position("pos1", "mkt1", 100.0, 0.985)
        pnl = tracker.close_position("pos1", exit_price=0.0)
        # (0.0 - 0.985) * 100 = -98.5
        assert pytest.approx(pnl, abs=1e-6) == -98.5

    def test_balance_increases_on_profit(self, tracker):
        tracker.open_position("pos1", "mkt1", 100.0, 0.985)
        tracker.close_position("pos1", exit_price=1.0)
        assert tracker.current_balance > 10_000.0

    def test_balance_decreases_on_loss(self, tracker):
        tracker.open_position("pos1", "mkt1", 100.0, 0.985)
        tracker.close_position("pos1", exit_price=0.0)
        assert tracker.current_balance < 10_000.0

    def test_removes_from_open_positions(self, tracker):
        tracker.open_position("pos1", "mkt1", 100.0, 0.985)
        tracker.close_position("pos1", exit_price=1.0)
        assert "pos1" not in tracker.open_positions

    def test_unknown_position_returns_none(self, tracker):
        result = tracker.close_position("ghost", exit_price=1.0)
        assert result is None

    def test_peak_balance_updates_on_profit(self, tracker):
        tracker.open_position("pos1", "mkt1", 100.0, 0.985)
        tracker.close_position("pos1", exit_price=1.0)
        assert tracker.peak_balance > 10_000.0

    def test_drawdown_tracked_on_loss(self, tracker):
        # First trade: profit → sets peak above 10k
        tracker.open_position("pos1", "mkt1", 100.0, 0.985)
        tracker.close_position("pos1", exit_price=1.0)
        # Second trade: loss → drawdown non-zero
        tracker.open_position("pos2", "mkt2", 500.0, 0.985)
        tracker.close_position("pos2", exit_price=0.0)
        assert tracker.current_drawdown > 0.0
        assert tracker.max_drawdown > 0.0


class TestGetSummary:
    def test_empty_summary(self, tracker):
        summary = tracker.get_summary()
        assert summary.total_trades == 0
        assert summary.win_rate == 0.0
        assert summary.total_pnl == 0.0

    def test_win_rate_100_percent(self, tracker):
        tracker.open_position("p1", "m1", 100.0, 0.985)
        tracker.close_position("p1", exit_price=1.0)
        summary = tracker.get_summary()
        assert summary.total_trades == 1
        assert summary.wins == 1
        assert summary.losses == 0
        assert summary.win_rate == 100.0

    def test_win_rate_0_percent(self, tracker):
        tracker.open_position("p1", "m1", 100.0, 0.985)
        tracker.close_position("p1", exit_price=0.0)
        summary = tracker.get_summary()
        assert summary.win_rate == 0.0

    def test_mixed_trades_win_rate(self, tracker):
        tracker.open_position("p1", "m1", 100.0, 0.985)
        tracker.close_position("p1", exit_price=1.0)
        tracker.open_position("p2", "m2", 100.0, 0.985)
        tracker.close_position("p2", exit_price=0.0)
        summary = tracker.get_summary()
        assert summary.total_trades == 2
        assert summary.win_rate == 50.0


class TestHistory:
    def test_get_open_positions(self, tracker):
        tracker.open_position("p1", "m1", 100.0, 0.985)
        tracker.open_position("p2", "m2", 200.0, 0.990)
        open_pos = tracker.get_open_positions()
        assert len(open_pos) == 2

    def test_get_trade_history_closed_only(self, tracker):
        tracker.open_position("p1", "m1", 100.0, 0.985)
        tracker.close_position("p1", exit_price=1.0)
        tracker.open_position("p2", "m2", 100.0, 0.990)  # still open
        history = tracker.get_trade_history()
        assert len(history) == 1
        assert history[0].position_id == "p1"

    def test_pnl_history_running_balance(self, tracker):
        tracker.open_position("p1", "m1", 100.0, 0.985)
        tracker.close_position("p1", exit_price=1.0)
        history = tracker.get_pnl_history()
        assert len(history) == 1
        assert history[0]["balance"] == pytest.approx(10_001.5, abs=0.01)


class TestClosedTradesIndex:
    """_closed_trades is the incremental index used by get_summary()."""

    def test_starts_empty(self, tracker):
        assert tracker._closed_trades == []

    def test_appended_on_close(self, tracker):
        tracker.open_position("p1", "m1", 100.0, 0.985)
        tracker.close_position("p1", exit_price=1.0)
        assert len(tracker._closed_trades) == 1

    def test_open_position_not_in_index(self, tracker):
        tracker.open_position("p1", "m1", 100.0, 0.985)
        assert len(tracker._closed_trades) == 0

    def test_multiple_closes_all_indexed(self, tracker):
        for i in range(5):
            tracker.open_position(f"p{i}", "m1", 10.0, 0.985)
            tracker.close_position(f"p{i}", exit_price=1.0)
        assert len(tracker._closed_trades) == 5

    def test_index_count_matches_summary(self, tracker):
        tracker.open_position("p1", "m1", 100.0, 0.985)
        tracker.close_position("p1", exit_price=1.0)
        tracker.open_position("p2", "m2", 100.0, 0.985)
        tracker.close_position("p2", exit_price=0.0)
        summary = tracker.get_summary()
        assert summary.total_trades == len(tracker._closed_trades)

    def test_reset_clears_index(self, tracker):
        tracker.open_position("p1", "m1", 100.0, 0.985)
        tracker.close_position("p1", exit_price=1.0)
        tracker.reset()
        assert tracker._closed_trades == []

    def test_get_trade_history_uses_index(self, tracker):
        tracker.open_position("p1", "m1", 100.0, 0.985)
        tracker.close_position("p1", exit_price=1.0)
        tracker.open_position("p2", "m2", 100.0, 0.990)  # still open
        history = tracker.get_trade_history()
        assert len(history) == 1
        assert history[0].position_id == "p1"


class TestSlots:
    def test_trade_record_has_slots(self):
        from utils.pnl_tracker import TradeRecord

        assert hasattr(TradeRecord, "__slots__")

    def test_trade_record_no_instance_dict(self, tracker):
        tracker.open_position("p1", "m1", 10.0, 0.985)
        record = tracker.open_positions["p1"]
        assert not hasattr(record, "__dict__")

    def test_pnl_summary_has_slots(self):
        from utils.pnl_tracker import PnLSummary

        assert hasattr(PnLSummary, "__slots__")

    def test_pnl_summary_no_instance_dict(self, tracker):
        summary = tracker.get_summary()
        assert not hasattr(summary, "__dict__")
