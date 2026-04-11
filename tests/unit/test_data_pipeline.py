"""
Pipeline integration tests — data validation end-to-end.

Exercises the full buy → track → settle lifecycle across all three
in-memory trackers (FakeCurrencyTracker, PositionTracker, PnLTracker)
and the OrderExecutor that coordinates them.

These tests are diagnostic / debugging aids; they are not run as part
of the live trading process.
"""

import pytest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from utils.pnl_tracker import PnLTracker
from portfolio.fake_currency_tracker import FakeCurrencyTracker
from portfolio.position_tracker import PositionTracker
from execution.order_executor import OrderExecutor

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

STARTING_BALANCE = 10_000.0
CAPITAL_SPLIT = 0.20  # 20 % → $2 000 per position
ALLOCATED = STARTING_BALANCE * CAPITAL_SPLIT  # $2 000


def _make_all(starting_balance=STARTING_BALANCE, max_positions=5):
    """Construct a fully wired set of trackers + executor (paper mode)."""
    with patch("portfolio.fake_currency_tracker.config") as cfg:
        cfg.FAKE_CURRENCY_BALANCE = starting_balance
        cfg.MAX_POSITIONS = max_positions
        currency = FakeCurrencyTracker()

    pnl = PnLTracker(initial_balance=starting_balance)

    with patch("portfolio.position_tracker.config") as cfg:
        cfg.MAX_POSITIONS = max_positions
        positions = PositionTracker(pnl)

    with patch("execution.order_executor.config") as cfg:
        cfg.PAPER_TRADING_ONLY = True
        cfg.CAPITAL_SPLIT_PERCENT = CAPITAL_SPLIT
        executor = OrderExecutor(
            pnl_tracker=pnl,
            position_tracker=positions,
            currency_tracker=currency,
        )

    return executor, currency, pnl, positions


def _opp(
    market_id="mkt-1",
    market_slug="test-slug",
    price=0.985,
    edge=1.5,
    expires_at=None,
):
    """Minimal opportunity object; sets expires_at if supplied."""
    opp = SimpleNamespace(
        market_id=market_id,
        market_slug=market_slug,
        question=f"Will {market_slug} happen?",
        token_id_yes=f"{market_id}_yes",
        token_id_no=f"{market_id}_no",
        winning_token_id=f"{market_id}_yes",
        current_price=price,
        edge_percent=edge,
    )
    opp.expires_at = expires_at
    return opp


def _buy(executor, opp, pid, capital_split=CAPITAL_SPLIT, max_positions=5, fee_pct=0.0):
    """Execute a buy, patching both the executor and currency-tracker configs."""
    with (
        patch("execution.order_executor.config") as ocfg,
        patch("portfolio.fake_currency_tracker.config") as fcfg,
    ):
        ocfg.PAPER_TRADING_ONLY = True
        ocfg.CAPITAL_SPLIT_PERCENT = capital_split
        ocfg.TAKER_FEE_PERCENT = fee_pct
        fcfg.MAX_POSITIONS = max_positions
        fcfg.FAKE_CURRENCY_BALANCE = STARTING_BALANCE
        return executor.execute_buy(opp, pid)


def _settle(executor, pid, settlement_price, fee_pct=0.0):
    """Settle a position, patching executor config for fee rate."""
    with patch("execution.order_executor.config") as ocfg:
        ocfg.TAKER_FEE_PERCENT = fee_pct
        return executor.settle_position(pid, settlement_price=settlement_price)


# ---------------------------------------------------------------------------
# Single buy → win cycle
# ---------------------------------------------------------------------------


class TestBuyWinCycle:
    def test_buy_succeeds(self):
        executor, currency, pnl, positions = _make_all()
        assert _buy(executor, _opp(), "p1") is True

    def test_balance_deducted_after_buy(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _opp(), "p1")
        assert currency.get_balance() == pytest.approx(STARTING_BALANCE - ALLOCATED, abs=0.01)

    def test_deployed_equals_allocated_after_buy(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _opp(), "p1")
        assert currency.get_deployed() == pytest.approx(ALLOCATED, abs=0.01)

    def test_position_is_open_after_buy(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _opp(), "p1")
        pos = positions.get_position("p1")
        assert pos is not None
        assert pos.status == "OPEN"

    def test_settle_win_pnl_positive(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _opp(price=0.985), "p1")
        result = _settle(executor, "p1", settlement_price=1.0)
        assert result is not None
        assert result > 0

    def test_settle_win_balance_above_starting(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _opp(price=0.985), "p1")
        _settle(executor, "p1", settlement_price=1.0)
        assert currency.get_balance() > STARTING_BALANCE

    def test_position_settled_after_settlement(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _opp(), "p1")
        executor.settle_position("p1", settlement_price=1.0)
        pos = positions.get_position("p1")
        assert pos.status == "SETTLED"

    def test_deployed_zero_after_settlement(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _opp(), "p1")
        executor.settle_position("p1", settlement_price=1.0)
        assert currency.get_deployed() == pytest.approx(0.0, abs=0.01)

    def test_order_history_has_buy_and_sell(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _opp(), "p1")
        executor.settle_position("p1", settlement_price=1.0)
        actions = {o["action"] for o in executor.order_history}
        assert actions == {"BUY", "SELL"}


# ---------------------------------------------------------------------------
# Single buy → loss cycle
# ---------------------------------------------------------------------------


class TestBuyLossCycle:
    def test_settle_loss_pnl_negative(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _opp(price=0.985), "p1")
        result = executor.settle_position("p1", settlement_price=0.0)
        assert result is not None
        assert result < 0

    def test_settle_loss_balance_below_starting(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _opp(price=0.985), "p1")
        executor.settle_position("p1", settlement_price=0.0)
        assert currency.get_balance() < STARTING_BALANCE

    def test_pnl_summary_records_loss(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _opp(price=0.985), "p1")
        executor.settle_position("p1", settlement_price=0.0)
        summary = pnl.get_summary()
        assert summary.losses == 1
        assert summary.total_pnl < 0


# ---------------------------------------------------------------------------
# Balance invariant: balance + deployed == starting + cumulative_pnl
# ---------------------------------------------------------------------------


class TestBalanceInvariant:
    """After any buy/settle sequence, the books must always balance."""

    def _total_value(self, currency, pnl):
        return currency.get_balance() + currency.get_deployed()

    def test_invariant_holds_after_buy(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _opp(), "p1")
        # Total value = balance + deployed capital (no PnL yet)
        assert self._total_value(currency, pnl) == pytest.approx(STARTING_BALANCE, abs=0.01)

    def test_invariant_holds_after_win(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _opp(price=0.985), "p1")
        realized = executor.settle_position("p1", settlement_price=1.0)
        # balance + deployed == starting + realized PnL
        assert currency.get_balance() == pytest.approx(STARTING_BALANCE + realized, abs=0.01)

    def test_invariant_holds_after_loss(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _opp(price=0.985), "p1")
        realized = executor.settle_position("p1", settlement_price=0.0)
        assert currency.get_balance() == pytest.approx(STARTING_BALANCE + realized, abs=0.01)

    def test_invariant_holds_across_multiple_cycles(self):
        executor, currency, pnl, positions = _make_all()
        total_pnl = 0.0
        for i in range(3):
            opp = _opp(market_id=f"mkt-{i}", market_slug=f"slug-{i}", price=0.985)
            _buy(executor, opp, f"p{i}")
            price = [1.0, 0.0, 0.50][i]
            pnl_i = executor.settle_position(f"p{i}", settlement_price=price)
            total_pnl += pnl_i
        assert currency.get_balance() == pytest.approx(STARTING_BALANCE + total_pnl, abs=0.01)


# ---------------------------------------------------------------------------
# Data fidelity: opportunity fields preserved in the position
# ---------------------------------------------------------------------------


class TestOpportunityToPositionFidelity:
    def test_market_id_preserved(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _opp(market_id="fidelity-market"), "p1")
        assert positions.get_position("p1").market_id == "fidelity-market"

    def test_market_slug_preserved(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _opp(market_slug="my-slug"), "p1")
        assert positions.get_position("p1").market_slug == "my-slug"

    def test_entry_price_preserved(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _opp(price=0.987), "p1")
        assert positions.get_position("p1").entry_price == pytest.approx(0.987, abs=1e-6)

    def test_edge_percent_preserved(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _opp(edge=3.14), "p1")
        assert positions.get_position("p1").edge_percent == pytest.approx(3.14, abs=1e-6)

    def test_shares_computed_from_price(self):
        """shares = allocated_capital / entry_price"""
        executor, currency, pnl, positions = _make_all()
        price = 0.985
        _buy(executor, _opp(price=price), "p1")
        pos = positions.get_position("p1")
        expected_shares = ALLOCATED / price
        assert pos.shares == pytest.approx(expected_shares, rel=1e-4)

    def test_expires_at_propagated_from_opportunity(self):
        executor, currency, pnl, positions = _make_all()
        expiry = datetime.now(timezone.utc) + timedelta(hours=2)
        _buy(executor, _opp(expires_at=expiry), "p1")
        assert positions.get_position("p1").expires_at == expiry

    def test_expires_at_none_when_not_set(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _opp(expires_at=None), "p1")
        assert positions.get_position("p1").expires_at is None


# ---------------------------------------------------------------------------
# Capital sizing precision
# ---------------------------------------------------------------------------


class TestCapitalSizing:
    def test_allocated_capital_is_20_percent_of_starting(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _opp(price=0.50), "p1")
        pos = positions.get_position("p1")
        assert pos.allocated_capital == pytest.approx(ALLOCATED, abs=0.01)

    def test_shares_scale_with_price(self):
        """Higher price → fewer shares for the same capital."""
        executor_lo, _, _, positions_lo = _make_all()
        executor_hi, _, _, positions_hi = _make_all()
        _buy(executor_lo, _opp(price=0.50), "p_lo")
        _buy(executor_hi, _opp(price=0.95), "p_hi")
        assert positions_lo.get_position("p_lo").shares > positions_hi.get_position("p_hi").shares

    def test_capital_split_respected(self):
        """10 % split → $1 000 allocated per position."""
        executor, currency, pnl, positions = _make_all()
        with patch("execution.order_executor.config") as cfg:
            cfg.PAPER_TRADING_ONLY = True
            cfg.CAPITAL_SPLIT_PERCENT = 0.10
            executor.execute_buy(_opp(), "p1")
        expected = STARTING_BALANCE * 0.10
        assert currency.get_deployed() == pytest.approx(expected, abs=0.01)


# ---------------------------------------------------------------------------
# Multiple simultaneous positions
# ---------------------------------------------------------------------------


class TestMultiplePositions:
    def test_three_open_positions(self):
        executor, currency, pnl, positions = _make_all(max_positions=5)
        for i in range(3):
            _buy(
                executor, _opp(market_id=f"mkt-{i}", market_slug=f"s{i}"), f"p{i}", max_positions=5
            )
        assert positions.get_position_count() == 3

    def test_deployed_sums_across_positions(self):
        # Capital sizing is dynamic: each allocation is 20% of the *remaining*
        # available balance, not a fixed fraction of starting balance.
        # Pos 0: 20% × $10,000 = $2,000  (avail → $8,000)
        # Pos 1: 20% × $8,000  = $1,600  (avail → $6,400)
        # Pos 2: 20% × $6,400  = $1,280  (avail → $5,120)
        # Total deployed: $4,880
        executor, currency, pnl, positions = _make_all(max_positions=5)
        for i in range(3):
            _buy(
                executor, _opp(market_id=f"mkt-{i}", market_slug=f"s{i}"), f"p{i}", max_positions=5
            )
        b = STARTING_BALANCE
        expected_deployed = sum(b * (0.8 ** i) * CAPITAL_SPLIT for i in range(3))
        assert currency.get_deployed() == pytest.approx(expected_deployed, abs=0.01)

    def test_pnl_accumulates_across_settlements(self):
        executor, currency, pnl, positions = _make_all(max_positions=5)
        for i in range(3):
            _buy(
                executor,
                _opp(market_id=f"mkt-{i}", market_slug=f"s{i}", price=0.985),
                f"p{i}",
                max_positions=5,
            )
        total = 0.0
        for i in range(3):
            p = executor.settle_position(f"p{i}", settlement_price=1.0)
            total += p
        summary = pnl.get_summary()
        assert summary.total_trades == 3
        assert summary.total_pnl == pytest.approx(total, abs=0.01)

    def test_max_positions_blocks_new_buy(self):
        executor, currency, pnl, positions = _make_all(max_positions=2)
        opp0 = _opp(market_id="m0", market_slug="s0")
        opp1 = _opp(market_id="m1", market_slug="s1")
        opp2 = _opp(market_id="m2", market_slug="s2")
        _buy(executor, opp0, "p0", max_positions=2)
        _buy(executor, opp1, "p1", max_positions=2)
        result = _buy(executor, opp2, "p2", max_positions=2)
        assert result is False
        assert positions.get_position("p2") is None


# ---------------------------------------------------------------------------
# Order history ordering and shape
# ---------------------------------------------------------------------------


class TestOrderHistoryShape:
    def test_newest_first_ordering(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _opp(market_id="m1", market_slug="s1"), "p1")
        executor.settle_position("p1", settlement_price=1.0)
        history = executor.get_order_history()
        # Most recent action (SELL) should appear first
        assert history[0]["action"] == "SELL"
        assert history[1]["action"] == "BUY"

    def test_order_record_has_required_keys(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _opp(), "p1")
        order = executor.order_history[0]
        for key in (
            "order_id",
            "position_id",
            "action",
            "market_id",
            "market_slug",
            "token_id",
            "quantity",
            "price",
            "total",
            "executed_at",
            "status",
        ):
            assert key in order, f"Missing key: {key}"

    def test_position_id_matches_in_order(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _opp(), "my-unique-pid")
        assert executor.order_history[0]["position_id"] == "my-unique-pid"

    def test_total_equals_quantity_times_price(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _opp(price=0.985), "p1")
        order = executor.order_history[0]
        # total is the allocated capital, quantity is shares
        assert order["total"] == pytest.approx(order["quantity"] * order["price"], rel=1e-4)

    def test_limit_respected(self):
        executor, currency, pnl, positions = _make_all(max_positions=5)
        for i in range(3):
            _buy(executor, _opp(market_id=f"m{i}", market_slug=f"s{i}"), f"p{i}", max_positions=5)
        assert len(executor.get_order_history(limit=2)) == 2

    def test_limit_zero_treated_as_no_limit(self):
        """limit=0 is treated the same as no limit — returns all records."""
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _opp(), "p1")
        # There is 1 order; limit=0 should return it (not suppress it)
        assert len(executor.get_order_history(limit=0)) == 1


# ---------------------------------------------------------------------------
# Settlement price clamping — executor must clamp before recording
# ---------------------------------------------------------------------------


class TestSettlementPriceClamping:
    def _open(self, executor, pid="p1"):
        _buy(executor, _opp(), pid)

    def test_settlement_above_one_clamped_to_one(self):
        executor, currency, pnl, positions = _make_all()
        self._open(executor)
        pnl_val = executor.settle_position("p1", settlement_price=1.5)
        pos = positions.get_position("p1")
        assert pos.settlement_price == pytest.approx(1.0, abs=1e-6)

    def test_settlement_below_zero_clamped_to_zero(self):
        executor, currency, pnl, positions = _make_all()
        self._open(executor)
        executor.settle_position("p1", settlement_price=-0.5)
        pos = positions.get_position("p1")
        assert pos.settlement_price == pytest.approx(0.0, abs=1e-6)

    def test_settlement_nan_clamped_to_zero(self):
        import math

        executor, currency, pnl, positions = _make_all()
        self._open(executor)
        executor.settle_position("p1", settlement_price=float("nan"))
        pos = positions.get_position("p1")
        assert pos.settlement_price == pytest.approx(0.0, abs=1e-6)

    def test_settlement_inf_clamped_to_zero(self):
        """inf is non-finite — the executor treats it the same as NaN and clamps to 0."""
        executor, currency, pnl, positions = _make_all()
        self._open(executor)
        executor.settle_position("p1", settlement_price=float("inf"))
        pos = positions.get_position("p1")
        assert pos.settlement_price == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Rollback on create_position failure
# ---------------------------------------------------------------------------


class TestRollback:
    def test_balance_restored_after_failed_position_creation(self):
        from unittest.mock import MagicMock

        executor, currency, pnl, positions = _make_all()
        balance_before = currency.get_balance()
        positions.create_position = MagicMock(side_effect=RuntimeError("boom"))
        with patch("execution.order_executor.alert_manager"):
            result = _buy(executor, _opp(), "p1")
        assert result is False
        assert currency.get_balance() == pytest.approx(balance_before, abs=0.01)
        assert currency.get_deployed() == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# PnL tracker ↔ position tracker consistency
# ---------------------------------------------------------------------------


class TestTrackerConsistency:
    """Verify PnLTracker and PositionTracker agree on trade outcomes."""

    def test_pnl_win_count_matches_position_win(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _opp(price=0.985), "p1")
        _settle(executor, "p1", settlement_price=1.0)
        summary = pnl.get_summary()
        pos_summary = positions.get_summary()
        assert summary.wins == 1
        assert pos_summary["wins"] == 1

    def test_pnl_loss_count_matches_position_loss(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _opp(price=0.985), "p1")
        executor.settle_position("p1", settlement_price=0.0)
        summary = pnl.get_summary()
        pos_summary = positions.get_summary()
        assert summary.losses == 1
        assert pos_summary["losses"] == 1

    def test_settled_count_matches_pnl_total_trades(self):
        executor, currency, pnl, positions = _make_all(max_positions=5)
        for i in range(3):
            _buy(executor, _opp(market_id=f"m{i}", market_slug=f"s{i}"), f"p{i}", max_positions=5)
            executor.settle_position(f"p{i}", settlement_price=1.0)
        summary = pnl.get_summary()
        pos_summary = positions.get_summary()
        assert summary.total_trades == pos_summary["settled_positions"] == 3
