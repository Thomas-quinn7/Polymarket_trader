"""
Tests for the pre-trade order-book slippage gate in OrderExecutor.execute_buy().

Covers:
- Paper mode: estimated slippage recorded on position when client available
- Pre-trade gate aborts order before allocation when estimate exceeds tolerance
- Thin-book warning logged but trade still proceeds if within tolerance
- Order book fetch failure is non-fatal (trade proceeds)
- No client → slippage_pct defaults to 0.0
"""

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from utils.pnl_tracker import PnLTracker
from portfolio.fake_currency_tracker import FakeCurrencyTracker
from portfolio.position_tracker import PositionTracker
from execution.order_executor import OrderExecutor

BALANCE = 10_000.0
SPLIT = 0.20


def _deps():
    with patch("portfolio.fake_currency_tracker.config") as c:
        c.FAKE_CURRENCY_BALANCE = BALANCE
        c.MAX_POSITIONS = 5
        currency = FakeCurrencyTracker()
    pnl = PnLTracker(initial_balance=BALANCE)
    with patch("portfolio.position_tracker.config") as c:
        c.MAX_POSITIONS = 5
        positions = PositionTracker(pnl)
    return currency, pnl, positions


def _executor(client=None, paper=True, tolerance=5.0):
    currency, pnl, positions = _deps()
    with patch("execution.order_executor.config") as c:
        c.PAPER_TRADING_ONLY = paper
        c.CAPITAL_SPLIT_PERCENT = SPLIT
        c.TAKER_FEE_PERCENT = 0.0
        c.SLIPPAGE_TOLERANCE_PERCENT = tolerance
        c.MAX_RETRIES = 1
        c.RETRY_DELAY_MS = 0
        executor = OrderExecutor(
            pnl_tracker=pnl,
            position_tracker=positions,
            currency_tracker=currency,
            polymarket_client=client,
        )
    return executor, currency, pnl, positions


def _opp(price=0.985):
    return SimpleNamespace(
        market_id="mkt-1",
        market_slug="test-slug",
        question="Will X happen?",
        token_id_yes="tok_yes",
        token_id_no="tok_no",
        winning_token_id="tok_yes",
        current_price=price,
        edge_percent=(1.0 - price) * 100,
        expires_at=None,
    )


def _deep_book(best_ask=0.985, shares=10_000.0):
    """Single-level book with plenty of liquidity — near-zero slippage."""
    return {
        "asks": [{"price": best_ask, "size": shares}],
        "bids": [],
        "mid_price": best_ask,
    }


def _thin_book(best_ask=0.985, shares=1.0):
    """Book with almost no liquidity — high slippage."""
    return {
        "asks": [{"price": best_ask, "size": shares}],
        "bids": [],
        "mid_price": best_ask,
    }


def _buy(executor, opp, pid, tolerance=5.0):
    with patch("execution.order_executor.config") as c:
        c.PAPER_TRADING_ONLY = True
        c.CAPITAL_SPLIT_PERCENT = SPLIT
        c.TAKER_FEE_PERCENT = 0.0
        c.SLIPPAGE_TOLERANCE_PERCENT = tolerance
        c.MAX_RETRIES = 1
        c.RETRY_DELAY_MS = 0
        return executor.execute_buy(opp, pid)


# ── no client → zero slippage ──────────────────────────────────────────────

class TestNoClient:
    def test_no_client_slippage_defaults_zero(self):
        executor, currency, pnl, positions = _executor(client=None)
        _buy(executor, _opp(), "p1")
        order = next(o for o in executor.order_history if o["action"] == "BUY")
        assert order["slippage_pct"] == pytest.approx(0.0)

    def test_no_client_buy_succeeds(self):
        executor, currency, pnl, positions = _executor(client=None)
        assert _buy(executor, _opp(), "p1") is True


# ── deep book → low/zero slippage ─────────────────────────────────────────

class TestDeepBook:
    def test_deep_book_buy_succeeds(self):
        client = MagicMock()
        client.get_order_book.return_value = _deep_book()
        executor, *_ = _executor(client=client)
        assert _buy(executor, _opp(), "p1") is True

    def test_deep_book_slippage_near_zero(self):
        client = MagicMock()
        client.get_order_book.return_value = _deep_book(shares=100_000.0)
        executor, *_ = _executor(client=client)
        _buy(executor, _opp(), "p1")
        order = next(o for o in executor.order_history if o["action"] == "BUY")
        assert order["slippage_pct"] == pytest.approx(0.0, abs=0.01)

    def test_order_book_fetched_with_10_levels(self):
        """Executor must request 10 levels for accurate impact estimation."""
        client = MagicMock()
        client.get_order_book.return_value = _deep_book()
        executor, *_ = _executor(client=client)
        _buy(executor, _opp(), "p1")
        client.get_order_book.assert_called_once_with("tok_yes", levels=10)


# ── pre-trade gate: tolerance exceeded ────────────────────────────────────
# We mock estimate_slippage directly here — the estimator's own correctness is
# covered by test_slippage.py.  These tests verify the executor's gate logic.

_HIGH_SLIP = dict(
    vwap=1.10, best_price=0.985, slippage_pct=15.0,
    fill_ratio=1.0, unfilled_usd=0.0, insufficient_liquidity=False, levels_consumed=3
)
_ZERO_SLIP = dict(
    vwap=0.985, best_price=0.985, slippage_pct=0.0,
    fill_ratio=1.0, unfilled_usd=0.0, insufficient_liquidity=False, levels_consumed=1
)


class TestPreTradeGate:
    def test_high_slippage_estimate_aborts_buy(self):
        """Estimated slippage 15% >> 1% tolerance → abort before allocation."""
        client = MagicMock()
        client.get_order_book.return_value = _deep_book()
        executor, currency, pnl, positions = _executor(client=client, tolerance=1.0)
        with patch("execution.order_executor.estimate_slippage", return_value=_HIGH_SLIP):
            result = _buy(executor, _opp(), "p1", tolerance=1.0)
        assert result is False

    def test_aborted_buy_creates_no_position(self):
        client = MagicMock()
        client.get_order_book.return_value = _deep_book()
        executor, currency, pnl, positions = _executor(client=client, tolerance=1.0)
        with patch("execution.order_executor.estimate_slippage", return_value=_HIGH_SLIP):
            _buy(executor, _opp(), "p1", tolerance=1.0)
        assert positions.get_position("p1") is None

    def test_aborted_buy_does_not_deduct_balance(self):
        client = MagicMock()
        client.get_order_book.return_value = _deep_book()
        executor, currency, pnl, positions = _executor(client=client, tolerance=1.0)
        balance_before = currency.get_balance()
        with patch("execution.order_executor.estimate_slippage", return_value=_HIGH_SLIP):
            _buy(executor, _opp(), "p1", tolerance=1.0)
        assert currency.get_balance() == pytest.approx(balance_before, abs=0.01)

    def test_within_tolerance_proceeds(self):
        client = MagicMock()
        client.get_order_book.return_value = _deep_book()
        executor, *_ = _executor(client=client, tolerance=5.0)
        with patch("execution.order_executor.estimate_slippage", return_value=_ZERO_SLIP):
            result = _buy(executor, _opp(), "p1", tolerance=5.0)
        assert result is True


# ── non-fatal order book failure ───────────────────────────────────────────

class TestOrderBookFailure:
    def test_book_fetch_exception_is_non_fatal(self):
        """If get_order_book raises, buy should still proceed (no gate applied)."""
        client = MagicMock()
        client.get_order_book.side_effect = ConnectionError("API down")
        executor, *_ = _executor(client=client)
        result = _buy(executor, _opp(), "p1")
        assert result is True

    def test_book_fetch_exception_logs_warning(self, caplog):
        import logging
        client = MagicMock()
        client.get_order_book.side_effect = RuntimeError("timeout")
        executor, *_ = _executor(client=client)
        with caplog.at_level(logging.WARNING):
            _buy(executor, _opp(), "p1")
        assert any("pre-trade estimate" in r.message.lower() or
                   "order book" in r.message.lower()
                   for r in caplog.records)


# ── insufficient liquidity warning ────────────────────────────────────────

class TestInsufficientLiquidityWarning:
    def test_thin_book_within_tolerance_logs_warning(self, caplog):
        """Thin book that still passes slippage gate should log an insufficient-liquidity warning."""
        import logging
        client = MagicMock()
        # Very little liquidity but slippage tolerance is generous (50%)
        client.get_order_book.return_value = _thin_book(shares=0.5)
        executor, *_ = _executor(client=client, tolerance=50.0)
        with caplog.at_level(logging.WARNING):
            _buy(executor, _opp(), "p1", tolerance=50.0)
        assert any("thin book" in r.message.lower() or
                   "insufficient" in r.message.lower()
                   for r in caplog.records)
