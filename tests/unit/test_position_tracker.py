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
        # can_open_position() reads config.MAX_POSITIONS live so the patch must
        # remain active for the entire test, not just during construction.
        pnl = PnLTracker()
        opp = make_opportunity()
        with patch("portfolio.position_tracker.config") as cfg:
            cfg.MAX_POSITIONS = 2
            t = PositionTracker(pnl)
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


class TestPositionSlots:
    def test_position_has_slots(self):
        from portfolio.position_tracker import Position

        assert hasattr(Position, "__slots__")

    def test_position_no_instance_dict(self, tracker):
        opp = make_opportunity()
        tracker.create_position(opp, 10.0, 985.0, 15.0, position_id="p1")
        pos = tracker.get_position("p1")
        assert not hasattr(pos, "__dict__")

    def test_position_slots_allow_field_assignment(self, tracker):
        """Slots must support all declared fields — no AttributeError on normal ops."""
        opp = make_opportunity()
        tracker.create_position(opp, 10.0, 985.0, 15.0, position_id="p1")
        tracker.settle_position("p1", settlement_price=1.0)
        pos = tracker.get_position("p1")
        assert pos.status == "SETTLED"
        assert pos.settlement_price == 1.0


class TestSettlePositionConcurrency:
    def test_concurrent_settle_does_not_double_settle(self):
        """Two threads racing to settle the same position — only one should succeed."""
        import threading

        pnl = PnLTracker()
        t = make_tracker(pnl)
        opp = make_opportunity()
        t.create_position(opp, 10.0, 985.0, 15.0, position_id="race")

        results = []
        errors = []

        def settle():
            try:
                result = t.settle_position("race", settlement_price=1.0)
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=settle) for _ in range(5)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        assert errors == [], f"Unexpected exceptions: {errors}"
        # Position should be SETTLED with consistent final state
        pos = t.get_position("race")
        assert pos.status == "SETTLED"
        # Exactly one non-None result (the first thread to win); others return None
        non_none = [r for r in results if r is not None]
        assert len(non_none) == 1

    def test_settle_position_consistent_state_after_concurrent_calls(self):
        """After concurrent settlement, pnl and position status agree."""
        import threading

        pnl = PnLTracker()
        t = make_tracker(pnl)
        opp = make_opportunity(current_price=0.985)
        t.create_position(opp, 100.0, 985.0, 15.0, position_id="consistent")

        barrier = threading.Barrier(3)
        results = []

        def settle():
            barrier.wait()
            results.append(t.settle_position("consistent", settlement_price=1.0))

        threads = [threading.Thread(target=settle) for _ in range(3)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        pos = t.get_position("consistent")
        assert pos.status == "SETTLED"
        assert pos.realized_pnl is not None

    def test_concurrent_create_and_settle_different_positions(self):
        """
        Multiple threads each create their own position and immediately settle it.
        No shared position IDs — verifies that locking does not deadlock and
        all positions end in SETTLED state with consistent PnL.
        """
        import threading

        NUM = 10
        pnl = PnLTracker()
        t = make_tracker(pnl, max_positions=NUM)
        errors = []

        def create_and_settle(n):
            try:
                pid = f"pos-{n}"
                opp = make_opportunity(market_id=f"mkt-{n}", current_price=0.985)
                t.create_position(opp, 10.0, 98.5, 0.15, position_id=pid)
                result = t.settle_position(pid, settlement_price=1.0)
                if result is None:
                    errors.append(f"settle returned None for {pid}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=create_and_settle, args=(i,)) for i in range(NUM)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        assert errors == [], f"Errors during concurrent create+settle: {errors}"
        settled = t.get_settled_positions()
        assert len(settled) == NUM
        for pos in settled:
            assert pos.status == "SETTLED"
            assert pos.realized_pnl is not None

    def test_settle_while_create_races_on_same_tracker(self):
        """
        One thread continuously creates positions while another continuously
        settles them.  Verifies no deadlock, no AttributeError, and that
        every created position eventually reaches SETTLED.
        """
        import threading, time as _time

        pnl = PnLTracker()
        t = make_tracker(pnl, max_positions=50)
        created_ids = []
        errors = []
        stop_event = threading.Event()

        def creator():
            for n in range(20):
                try:
                    pid = f"cr-{n}"
                    opp = make_opportunity(market_id=f"m-{n}", current_price=0.99)
                    t.create_position(opp, 5.0, 4.95, 0.05, position_id=pid)
                    created_ids.append(pid)
                    _time.sleep(0.002)
                except Exception as e:
                    errors.append(e)

        def settler():
            settled = set()
            deadline = _time.monotonic() + 5.0
            while _time.monotonic() < deadline:
                for pid in list(created_ids):
                    if pid not in settled:
                        pos = t.get_position(pid)
                        if pos and pos.status == "OPEN":
                            try:
                                t.settle_position(pid, settlement_price=1.0)
                                settled.add(pid)
                            except Exception as e:
                                errors.append(e)
                _time.sleep(0.001)

        creator_thread = threading.Thread(target=creator)
        settler_thread = threading.Thread(target=settler)
        creator_thread.start()
        settler_thread.start()
        creator_thread.join()
        settler_thread.join()

        assert errors == [], f"Errors: {errors}"
        # All created positions must be settled
        for pid in created_ids:
            pos = t.get_position(pid)
            assert pos is not None
            assert pos.status == "SETTLED", f"{pid} stuck in {pos.status}"
