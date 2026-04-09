"""
Fee and slippage tests.

Verifies that:
  - Entry and exit fees are calculated, stored, and deducted from PnL
  - Net PnL = gross PnL - total fees
  - Balance invariant holds after fee deduction
  - Slippage is measured, recorded, and enforced against the tolerance
"""

import pytest
from unittest.mock import patch, MagicMock

from utils.pnl_tracker import PnLTracker
from portfolio.fake_currency_tracker import FakeCurrencyTracker
from portfolio.position_tracker import PositionTracker
from execution.order_executor import OrderExecutor

STARTING_BALANCE = 10_000.0
CAPITAL_SPLIT = 0.20
ALLOCATED = STARTING_BALANCE * CAPITAL_SPLIT  # $2 000
FEE_PCT = 2.0
# price=0.95 → gross edge 5%, total fees ~4% → net positive
PRICE_WITH_EDGE = 0.95


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_all(starting_balance=STARTING_BALANCE, max_positions=5):
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
        cfg.TAKER_FEE_PERCENT = 0.0
        executor = OrderExecutor(
            pnl_tracker=pnl,
            position_tracker=positions,
            currency_tracker=currency,
        )
    return executor, currency, pnl, positions


def _make_opp(price=PRICE_WITH_EDGE):
    from types import SimpleNamespace

    opp = SimpleNamespace(
        market_id="mkt-1",
        market_slug="test-slug",
        question="Will it happen?",
        token_id_yes="mkt-1_yes",
        token_id_no="mkt-1_no",
        winning_token_id="mkt-1_yes",
        current_price=price,
        edge_percent=(1.0 - price) * 100,
    )
    opp.expires_at = None
    return opp


def _buy(executor, opp, pid, fee_pct=0.0):
    with (
        patch("execution.order_executor.config") as ocfg,
        patch("portfolio.fake_currency_tracker.config") as fcfg,
    ):
        ocfg.PAPER_TRADING_ONLY = True
        ocfg.CAPITAL_SPLIT_PERCENT = CAPITAL_SPLIT
        ocfg.TAKER_FEE_PERCENT = fee_pct
        fcfg.MAX_POSITIONS = 5
        fcfg.FAKE_CURRENCY_BALANCE = STARTING_BALANCE
        return executor.execute_buy(opp, pid)


def _settle(executor, pid, settlement_price, fee_pct=0.0):
    with patch("execution.order_executor.config") as ocfg:
        ocfg.TAKER_FEE_PERCENT = fee_pct
        return executor.settle_position(pid, settlement_price=settlement_price)


# ---------------------------------------------------------------------------
# Fee tracking
# ---------------------------------------------------------------------------


class TestFeeTracking:

    def test_entry_fee_stored_on_position(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _make_opp(), "p1", fee_pct=FEE_PCT)
        pos = positions.get_position("p1")
        assert pos.entry_fee == pytest.approx(ALLOCATED * FEE_PCT / 100, rel=1e-6)

    def test_entry_fee_stored_on_trade_record(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _make_opp(), "p1", fee_pct=FEE_PCT)
        record = pnl.open_positions["p1"]
        assert record.entry_fee == pytest.approx(ALLOCATED * FEE_PCT / 100, rel=1e-6)

    def test_entry_fee_in_buy_order_record(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _make_opp(), "p1", fee_pct=FEE_PCT)
        buy_order = next(o for o in executor.order_history if o["action"] == "BUY")
        assert buy_order["fee"] == pytest.approx(ALLOCATED * FEE_PCT / 100, rel=1e-6)

    def test_exit_fee_stored_after_settlement(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _make_opp(), "p1", fee_pct=FEE_PCT)
        _settle(executor, "p1", settlement_price=1.0, fee_pct=FEE_PCT)
        pos = positions.get_position("p1")
        shares = ALLOCATED / PRICE_WITH_EDGE
        expected_exit_fee = shares * 1.0 * FEE_PCT / 100
        assert pos.exit_fee == pytest.approx(expected_exit_fee, rel=1e-4)

    def test_net_pnl_less_than_gross_pnl_when_fees_nonzero(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _make_opp(), "p1", fee_pct=FEE_PCT)
        net_pnl = _settle(executor, "p1", settlement_price=1.0, fee_pct=FEE_PCT)
        pos = positions.get_position("p1")
        assert pos.gross_pnl is not None
        assert net_pnl < pos.gross_pnl

    def test_net_pnl_positive_when_edge_covers_fees(self):
        """price=0.95 → gross edge 5% > total ~4% fees → net positive."""
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _make_opp(PRICE_WITH_EDGE), "p1", fee_pct=FEE_PCT)
        net_pnl = _settle(executor, "p1", settlement_price=1.0, fee_pct=FEE_PCT)
        assert net_pnl > 0

    def test_net_pnl_negative_when_fees_exceed_edge(self):
        """price=0.985 → gross edge 1.5% < total ~4% fees → net negative."""
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _make_opp(0.985), "p1", fee_pct=FEE_PCT)
        net_pnl = _settle(executor, "p1", settlement_price=1.0, fee_pct=FEE_PCT)
        assert net_pnl < 0

    def test_zero_fee_gross_equals_net(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _make_opp(), "p1", fee_pct=0.0)
        net_pnl = _settle(executor, "p1", settlement_price=1.0, fee_pct=0.0)
        pos = positions.get_position("p1")
        assert net_pnl == pytest.approx(pos.gross_pnl, rel=1e-6)

    def test_pnl_summary_totals_fees(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _make_opp(), "p1", fee_pct=FEE_PCT)
        _settle(executor, "p1", settlement_price=1.0, fee_pct=FEE_PCT)
        summary = pnl.get_summary()
        assert summary.total_fees_paid > 0
        assert summary.gross_pnl > summary.total_pnl

    def test_execution_stats_total_fees(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _make_opp(), "p1", fee_pct=FEE_PCT)
        _settle(executor, "p1", settlement_price=1.0, fee_pct=FEE_PCT)
        stats = executor.get_execution_stats()
        assert stats["total_fees_paid"] > 0

    def test_balance_invariant_holds_with_fees(self):
        """final_balance == starting_balance + net_pnl regardless of fee rate."""
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _make_opp(), "p1", fee_pct=FEE_PCT)
        net_pnl = _settle(executor, "p1", settlement_price=1.0, fee_pct=FEE_PCT)
        assert abs(currency.get_balance() - (STARTING_BALANCE + net_pnl)) < 0.01

    def test_trade_record_total_fees_property(self):
        executor, currency, pnl, positions = _make_all()
        _buy(executor, _make_opp(), "p1", fee_pct=FEE_PCT)
        _settle(executor, "p1", settlement_price=1.0, fee_pct=FEE_PCT)
        closed = pnl.get_trade_history(limit=1)[0]
        assert closed.total_fees == pytest.approx(closed.entry_fee + closed.exit_fee, rel=1e-6)
        assert closed.total_fees > 0


# ---------------------------------------------------------------------------
# Slippage enforcement
# ---------------------------------------------------------------------------


class TestSlippageEnforcement:

    def _live_executor(self, mock_client, slippage_tolerance=5.0, fee_pct=0.0):
        with patch("portfolio.fake_currency_tracker.config") as cfg:
            cfg.FAKE_CURRENCY_BALANCE = STARTING_BALANCE
            cfg.MAX_POSITIONS = 5
            currency = FakeCurrencyTracker()
        pnl = PnLTracker(initial_balance=STARTING_BALANCE)
        with patch("portfolio.position_tracker.config") as cfg:
            cfg.MAX_POSITIONS = 5
            positions = PositionTracker(pnl)
        with patch("execution.order_executor.config") as cfg:
            cfg.PAPER_TRADING_ONLY = False
            cfg.CAPITAL_SPLIT_PERCENT = CAPITAL_SPLIT
            cfg.TAKER_FEE_PERCENT = fee_pct
            cfg.SLIPPAGE_TOLERANCE_PERCENT = slippage_tolerance
            cfg.MAX_RETRIES = 1
            cfg.RETRY_DELAY_MS = 0
            executor = OrderExecutor(
                pnl_tracker=pnl,
                position_tracker=positions,
                currency_tracker=currency,
                polymarket_client=mock_client,
            )
        return executor, currency, pnl, positions

    def _live_buy(self, executor, opp, pid, slippage_tolerance=5.0, fee_pct=0.0):
        with patch("execution.order_executor.config") as cfg:
            cfg.PAPER_TRADING_ONLY = False
            cfg.CAPITAL_SPLIT_PERCENT = CAPITAL_SPLIT
            cfg.TAKER_FEE_PERCENT = fee_pct
            cfg.SLIPPAGE_TOLERANCE_PERCENT = slippage_tolerance
            cfg.MAX_RETRIES = 1
            cfg.RETRY_DELAY_MS = 0
            return executor.execute_buy(opp, pid)

    def test_within_tolerance_succeeds(self):
        """Filled 1% above expected — within 5% → position created."""
        mock_client = MagicMock()
        mock_client.create_market_order.return_value = {"status": "MATCHED", "price": "0.995"}
        executor, *_ = self._live_executor(mock_client)
        result = self._live_buy(executor, _make_opp(0.985), "p1")
        assert result is True

    def test_exceeds_tolerance_aborts(self):
        """Filled 10% above expected — exceeds 5% → buy aborted, no position."""
        mock_client = MagicMock()
        mock_client.create_market_order.return_value = {"status": "MATCHED", "price": "1.085"}
        executor, currency, pnl, positions = self._live_executor(mock_client)
        result = self._live_buy(executor, _make_opp(0.985), "p2")
        assert result is False
        assert positions.get_position("p2") is None

    def test_exceeds_tolerance_does_not_deduct_balance(self):
        """If slippage aborts the order, balance must not be changed."""
        mock_client = MagicMock()
        mock_client.create_market_order.return_value = {"status": "MATCHED", "price": "1.085"}
        executor, currency, pnl, positions = self._live_executor(mock_client)
        balance_before = currency.get_balance()
        self._live_buy(executor, _make_opp(0.985), "p3")
        assert currency.get_balance() == pytest.approx(balance_before, abs=0.01)

    def test_slippage_recorded_in_order_history(self):
        """slippage_pct in BUY order record matches (filled-expected)/expected*100."""
        mock_client = MagicMock()
        mock_client.create_market_order.return_value = {"status": "MATCHED", "price": "0.990"}
        executor, *_ = self._live_executor(mock_client)
        self._live_buy(executor, _make_opp(0.985), "p4")
        buy = next(o for o in executor.order_history if o["action"] == "BUY")
        expected_slip = (0.990 - 0.985) / 0.985 * 100
        assert buy["slippage_pct"] == pytest.approx(expected_slip, rel=1e-4)

    def test_slippage_aggregated_in_execution_stats(self):
        mock_client = MagicMock()
        mock_client.create_market_order.return_value = {"status": "MATCHED", "price": "0.990"}
        executor, *_ = self._live_executor(mock_client)
        self._live_buy(executor, _make_opp(0.985), "p5")
        stats = executor.get_execution_stats()
        assert stats["avg_slippage_pct"] > 0
        assert stats["max_slippage_pct"] > 0

    def test_paper_mode_slippage_is_zero(self):
        executor, *_ = _make_all()
        _buy(executor, _make_opp(), "p6")
        buy = next(o for o in executor.order_history if o["action"] == "BUY")
        assert buy["slippage_pct"] == 0.0

    def test_no_price_in_response_skips_slippage_check(self):
        """If exchange returns no price field, slippage check is skipped (order proceeds)."""
        mock_client = MagicMock()
        mock_client.create_market_order.return_value = {"status": "MATCHED"}
        executor, *_ = self._live_executor(mock_client, slippage_tolerance=0.0)
        result = self._live_buy(executor, _make_opp(0.985), "p7", slippage_tolerance=0.0)
        assert result is True
