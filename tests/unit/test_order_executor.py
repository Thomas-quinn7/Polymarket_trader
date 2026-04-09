"""
Unit tests for OrderExecutor.
"""

import pytest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from utils.pnl_tracker import PnLTracker
from portfolio.fake_currency_tracker import FakeCurrencyTracker
from portfolio.position_tracker import PositionTracker
from execution.order_executor import OrderExecutor


def _make_deps(starting_balance=10_000.0, max_positions=5):
    with patch("portfolio.fake_currency_tracker.config") as cfg:
        cfg.FAKE_CURRENCY_BALANCE = starting_balance
        cfg.MAX_POSITIONS = max_positions
        currency = FakeCurrencyTracker()

    pnl = PnLTracker(initial_balance=starting_balance)

    with patch("portfolio.position_tracker.config") as cfg:
        cfg.MAX_POSITIONS = max_positions
        positions = PositionTracker(pnl)

    return currency, pnl, positions


def _make_executor(starting_balance=10_000.0, max_positions=5):
    currency, pnl, positions = _make_deps(starting_balance, max_positions)
    with patch("execution.order_executor.config") as cfg:
        cfg.PAPER_TRADING_ONLY = True
        cfg.CAPITAL_SPLIT_PERCENT = 0.20
        executor = OrderExecutor(
            pnl_tracker=pnl,
            position_tracker=positions,
            currency_tracker=currency,
        )
    return executor, currency, pnl, positions


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


class TestExecuteBuy:
    def test_returns_true_on_success(self):
        executor, currency, pnl, positions = _make_executor()
        with patch("execution.order_executor.config") as cfg:
            cfg.PAPER_TRADING_ONLY = True
            cfg.CAPITAL_SPLIT_PERCENT = 0.20
            cfg.TAKER_FEE_PERCENT = 0.0
            result = executor.execute_buy(make_opportunity(), "p1")
        assert result is True

    def test_deducts_currency(self):
        executor, currency, pnl, positions = _make_executor()
        with patch("execution.order_executor.config") as cfg:
            cfg.PAPER_TRADING_ONLY = True
            cfg.CAPITAL_SPLIT_PERCENT = 0.20
            cfg.TAKER_FEE_PERCENT = 0.0
            executor.execute_buy(make_opportunity(), "p1")
        assert currency.get_balance() < 10_000.0

    def test_position_findable_by_caller_id(self):
        """The key P1 fix: caller-supplied position_id must be retrievable."""
        executor, currency, pnl, positions = _make_executor()
        with patch("execution.order_executor.config") as cfg:
            cfg.PAPER_TRADING_ONLY = True
            cfg.CAPITAL_SPLIT_PERCENT = 0.20
            cfg.TAKER_FEE_PERCENT = 0.0
            executor.execute_buy(make_opportunity(), "caller-id-123")
        pos = positions.get_position("caller-id-123")
        assert pos is not None
        assert pos.position_id == "caller-id-123"

    def test_records_order_history(self):
        executor, currency, pnl, positions = _make_executor()
        with patch("execution.order_executor.config") as cfg:
            cfg.PAPER_TRADING_ONLY = True
            cfg.CAPITAL_SPLIT_PERCENT = 0.20
            cfg.TAKER_FEE_PERCENT = 0.0
            executor.execute_buy(make_opportunity(), "p1")
        assert len(executor.order_history) == 1
        assert executor.order_history[0]["action"] == "BUY"
        assert executor.order_history[0]["position_id"] == "p1"

    def test_returns_false_if_insufficient_funds(self):
        executor, currency, pnl, positions = _make_executor()
        # Drain balance to $1 so the $2000 allocation fails
        currency.balance = 1.0
        with patch("execution.order_executor.config") as cfg:
            cfg.PAPER_TRADING_ONLY = True
            cfg.CAPITAL_SPLIT_PERCENT = 0.20
            cfg.TAKER_FEE_PERCENT = 0.0
            result = executor.execute_buy(make_opportunity(), "p1")
        assert result is False

    def test_rollback_on_create_position_failure(self):
        """Balance must be restored if position creation raises; execute_buy returns False."""
        executor, currency, pnl, positions = _make_executor()
        balance_before = currency.get_balance()

        positions.create_position = MagicMock(side_effect=RuntimeError("boom"))

        with patch("execution.order_executor.config") as cfg, \
             patch("execution.order_executor.alert_manager"):
            cfg.PAPER_TRADING_ONLY = True
            cfg.CAPITAL_SPLIT_PERCENT = 0.20
            cfg.TAKER_FEE_PERCENT = 0.0
            result = executor.execute_buy(make_opportunity(), "p1")

        assert result is False
        # Balance should be fully restored
        assert currency.get_balance() == pytest.approx(balance_before, abs=0.01)


class TestSettlePosition:
    def _open_position(self, executor, currency, pnl, positions, pid="p1"):
        with patch("execution.order_executor.config") as cfg:
            cfg.PAPER_TRADING_ONLY = True
            cfg.CAPITAL_SPLIT_PERCENT = 0.20
            cfg.TAKER_FEE_PERCENT = 0.0
            executor.execute_buy(make_opportunity(), pid)

    def test_settle_returns_pnl(self):
        executor, currency, pnl, positions = _make_executor()
        self._open_position(executor, currency, pnl, positions)
        result = executor.settle_position("p1", settlement_price=1.0)
        assert result is not None
        assert isinstance(result, float)

    def test_settle_returns_currency(self):
        executor, currency, pnl, positions = _make_executor()
        self._open_position(executor, currency, pnl, positions)
        balance_after_buy = currency.get_balance()
        executor.settle_position("p1", settlement_price=1.0)
        assert currency.get_balance() > balance_after_buy

    def test_settle_records_sell_order(self):
        executor, currency, pnl, positions = _make_executor()
        self._open_position(executor, currency, pnl, positions)
        executor.settle_position("p1", settlement_price=1.0)
        sell_orders = [o for o in executor.order_history if o["action"] == "SELL"]
        assert len(sell_orders) == 1

    def test_settle_unknown_position_returns_none(self):
        executor, currency, pnl, positions = _make_executor()
        result = executor.settle_position("ghost", settlement_price=1.0)
        assert result is None


class TestStats:
    def test_execution_stats_fill_rate(self):
        executor, currency, pnl, positions = _make_executor()
        with patch("execution.order_executor.config") as cfg:
            cfg.PAPER_TRADING_ONLY = True
            cfg.CAPITAL_SPLIT_PERCENT = 0.20
            cfg.TAKER_FEE_PERCENT = 0.0
            executor.execute_buy(make_opportunity(), "p1")
        stats = executor.get_execution_stats()
        assert stats["total_orders"] == 1
        assert stats["filled_orders"] == 1
        assert stats["fill_rate"] == 100.0

    def test_order_history_limit(self):
        executor, currency, pnl, positions = _make_executor()
        with patch("execution.order_executor.config") as cfg:
            cfg.PAPER_TRADING_ONLY = True
            cfg.CAPITAL_SPLIT_PERCENT = 0.20
            cfg.TAKER_FEE_PERCENT = 0.0
            executor.execute_buy(make_opportunity(market_id="m1"), "p1")
        orders = executor.get_order_history(limit=1)
        assert len(orders) == 1


class TestExecuteSell:
    def _open(self, executor, currency, pnl, positions, pid="p1"):
        with patch("execution.order_executor.config") as cfg:
            cfg.PAPER_TRADING_ONLY = True
            cfg.CAPITAL_SPLIT_PERCENT = 0.20
            cfg.TAKER_FEE_PERCENT = 0.0
            executor.execute_buy(make_opportunity(), pid)

    def test_execute_sell_returns_pnl(self):
        executor, currency, pnl, positions = _make_executor()
        self._open(executor, currency, pnl, positions)
        result = executor.execute_sell("p1", current_price=0.90, reason="stop_loss")
        assert result is not None
        assert isinstance(result, float)
        assert result < 0  # sold below entry of 0.985 → loss

    def test_execute_sell_unknown_position_returns_none(self):
        executor, currency, pnl, positions = _make_executor()
        result = executor.execute_sell("ghost", current_price=0.50)
        assert result is None

    def test_execute_sell_records_order(self):
        executor, currency, pnl, positions = _make_executor()
        self._open(executor, currency, pnl, positions)
        executor.execute_sell("p1", current_price=1.0)
        sell_orders = [o for o in executor.order_history if o["action"] == "SELL"]
        assert len(sell_orders) == 1

    def test_real_order_placed_when_not_paper(self):
        """When PAPER_TRADING_ONLY=False, execute_buy calls polymarket_client."""
        currency, pnl, positions = _make_deps()
        mock_client = MagicMock()
        mock_client.create_market_order.return_value = {"status": "MATCHED"}

        with patch("execution.order_executor.config") as cfg:
            cfg.PAPER_TRADING_ONLY = False
            cfg.CAPITAL_SPLIT_PERCENT = 0.20
            cfg.TAKER_FEE_PERCENT = 0.0
            cfg.SLIPPAGE_TOLERANCE_PERCENT = 5.0
            cfg.MAX_RETRIES = 3
            cfg.RETRY_DELAY_MS = 0
            executor = OrderExecutor(
                pnl_tracker=pnl,
                position_tracker=positions,
                currency_tracker=currency,
                polymarket_client=mock_client,
            )
            result = executor.execute_buy(make_opportunity(), "live-p1")

        assert result is True
        mock_client.create_market_order.assert_called_once()

    def test_failed_real_order_aborts_buy(self):
        """When exchange returns empty dict, execute_buy returns False without creating position."""
        currency, pnl, positions = _make_deps()
        mock_client = MagicMock()
        mock_client.create_market_order.return_value = {}

        with patch("execution.order_executor.config") as cfg:
            cfg.PAPER_TRADING_ONLY = False
            cfg.CAPITAL_SPLIT_PERCENT = 0.20
            cfg.TAKER_FEE_PERCENT = 0.0
            cfg.SLIPPAGE_TOLERANCE_PERCENT = 5.0
            cfg.MAX_RETRIES = 3
            cfg.RETRY_DELAY_MS = 0
            executor = OrderExecutor(
                pnl_tracker=pnl,
                position_tracker=positions,
                currency_tracker=currency,
                polymarket_client=mock_client,
            )
            result = executor.execute_buy(make_opportunity(), "live-p2")

        assert result is False
        assert positions.get_position("live-p2") is None
