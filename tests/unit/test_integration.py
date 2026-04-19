# Copyright (C) 2026  Thomas Quinn (github.com/Thomas-quinn7)
#                     Ciaran McDonnell (github.com/CiaranMcDonnell)
# SPDX-License-Identifier: AGPL-3.0-only
"""
Integration tests: scan → execute_buy → settle_position full lifecycle.

These tests instantiate real framework classes (no MagicMock for the core
path) and assert that the accounting is correct end-to-end.  A lightweight
stub strategy is used so signal logic is not the subject under test.
"""

from datetime import datetime, timedelta, timezone
from typing import List
from unittest.mock import MagicMock

import pytest

from config.polymarket_config import PolymarketConfig
from data.market_schema import PolymarketMarket
from data.polymarket_models import TradeOpportunity, TradeStatus
from execution.order_executor import OrderExecutor
from portfolio.paper_portfolio import PaperPortfolio
from portfolio.position_tracker import PositionTracker
from strategies.base import BaseStrategy
from utils.pnl_tracker import PnLTracker

# ---------------------------------------------------------------------------
# Stub strategy: returns a known opportunity for any non-empty market list
# ---------------------------------------------------------------------------


class _FixedPriceStrategy(BaseStrategy):
    """
    Minimal strategy that always returns one opportunity at a fixed price.
    Used to exercise the framework's execution and accounting paths without
    testing strategy signal logic.
    """

    def __init__(self, entry_price: float = 0.60, edge_pct: float = 10.0):
        self._entry_price = entry_price
        self._edge_pct = edge_pct

    def scan_for_opportunities(self, markets: List[PolymarketMarket]) -> List[TradeOpportunity]:
        if not markets:
            return []
        m = markets[0]
        opp = TradeOpportunity(
            market_id=m.market_id,
            market_slug=m.slug,
            question=m.question,
            category=m.category,
            token_id_yes=m.token_ids[0],
            token_id_no=m.token_ids[1],
            winning_token_id=m.token_ids[0],
            current_price=self._entry_price,
            edge_percent=self._edge_pct,
            confidence=0.8,
            detected_at=datetime.now(timezone.utc),
            status=TradeStatus.DETECTED,
        )
        opp.expires_at = datetime.now(timezone.utc) + timedelta(seconds=60)
        return [opp]

    def get_best_opportunities(self, opportunities, limit=5):
        return opportunities[:limit]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_market(
    market_id: str = "test-001",
    price: float = 0.60,
    volume: float = 5000.0,
) -> PolymarketMarket:
    m = PolymarketMarket(
        market_id=market_id,
        slug=f"test-market-{market_id}",
        question="Will X happen?",
        token_ids=["yes-token", "no-token"],
        category="crypto",
        volume=volume,
        end_time=datetime.now(timezone.utc) + timedelta(seconds=300),
    )
    m.resolved_price = price
    return m


def _make_executor(cfg: PolymarketConfig):
    """Build a fully wired executor using real (not mocked) components."""
    portfolio = PaperPortfolio()
    # Patch config on the portfolio so it reads our test config's MAX_POSITIONS.
    portfolio.starting_balance = cfg.FAKE_CURRENCY_BALANCE
    portfolio.balance = cfg.FAKE_CURRENCY_BALANCE

    pnl = PnLTracker(initial_balance=cfg.FAKE_CURRENCY_BALANCE)
    tracker = PositionTracker(pnl)

    client = MagicMock()
    client.get_order_book.return_value = {"bids": [], "asks": []}

    executor = OrderExecutor(
        pnl_tracker=pnl,
        position_tracker=tracker,
        currency_tracker=portfolio,
        polymarket_client=client,
    )
    return executor, portfolio, tracker, pnl


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFullTradeLifecycle:
    """scan → execute_buy → settle_position with accounting assertions."""

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        self.cfg = PolymarketConfig.from_dict(
            {
                "PAPER_TRADING_ONLY": True,
                "FAKE_CURRENCY_BALANCE": 1000.0,
                "MAX_POSITIONS": 5,
                "CAPITAL_SPLIT_PERCENT": 0.10,  # 10% per trade = $100
                "KELLY_FRACTION": 0.25,
                "TAKER_FEE_PERCENT": 2.0,
                "SLIPPAGE_TOLERANCE_PERCENT": 100.0,  # disable slippage gate
            }
        )
        # Patch the module-level config used by OrderExecutor and PaperPortfolio.
        monkeypatch.setattr("execution.order_executor.config", self.cfg)
        monkeypatch.setattr("portfolio.fake_currency_tracker.config", self.cfg)

        self.executor, self.portfolio, self.tracker, self.pnl = _make_executor(self.cfg)
        self.strategy = _FixedPriceStrategy(entry_price=0.60, edge_pct=10.0)

    def _scan_and_execute(self, market: PolymarketMarket) -> str:
        """Run one scan cycle and execute the first opportunity. Returns position_id."""
        opps = self.strategy.scan_for_opportunities([market])
        assert opps, "Strategy returned no opportunities"
        best = self.strategy.get_best_opportunities(opps, limit=1)
        opp = best[0]
        position_id = f"{opp.market_id}_test"
        success = self.executor.execute_buy(opp, position_id)
        assert success, "execute_buy returned False"
        return position_id

    def test_balance_decreases_after_buy(self):
        market = _make_market()
        self._scan_and_execute(market)
        assert self.portfolio.get_balance() < 1000.0

    def test_deployed_equals_allocated_after_buy(self):
        market = _make_market()
        self._scan_and_execute(market)
        allocated = self.cfg.FAKE_CURRENCY_BALANCE * self.cfg.CAPITAL_SPLIT_PERCENT
        assert self.portfolio.get_deployed() == pytest.approx(allocated, rel=1e-4)

    def test_position_is_open_after_buy(self):
        market = _make_market()
        pid = self._scan_and_execute(market)
        pos = self.tracker.get_position(pid)
        assert pos is not None
        assert pos.status == "OPEN"

    def test_win_settlement_increases_balance(self):
        market = _make_market()
        pid = self._scan_and_execute(market)
        balance_before = self.portfolio.get_balance()
        self.executor.settle_position(pid, settlement_price=1.0)
        assert self.portfolio.get_balance() > balance_before

    def test_loss_settlement_decreases_balance(self):
        market = _make_market()
        pid = self._scan_and_execute(market)
        balance_before = self.portfolio.get_balance()
        self.executor.settle_position(pid, settlement_price=0.0)
        assert self.portfolio.get_balance() < balance_before

    def test_position_settled_after_settlement(self):
        market = _make_market()
        pid = self._scan_and_execute(market)
        self.executor.settle_position(pid, settlement_price=1.0)
        pos = self.tracker.get_position(pid)
        assert pos.status == "SETTLED"

    def test_deployed_zero_after_settlement(self):
        market = _make_market()
        pid = self._scan_and_execute(market)
        self.executor.settle_position(pid, settlement_price=1.0)
        assert self.portfolio.get_deployed() == pytest.approx(0.0, abs=1e-9)

    def test_balance_invariant_win(self):
        """balance + deployed == starting_balance + net_pnl at all times."""
        market = _make_market()
        pid = self._scan_and_execute(market)
        self.executor.settle_position(pid, settlement_price=1.0)
        pos = self.tracker.get_position(pid)
        net_pnl = pos.realized_pnl or 0.0
        total = self.portfolio.get_balance() + self.portfolio.get_deployed()
        assert total == pytest.approx(self.cfg.FAKE_CURRENCY_BALANCE + net_pnl, rel=1e-4)

    def test_win_pnl_positive(self):
        market = _make_market()
        pid = self._scan_and_execute(market)
        self.executor.settle_position(pid, settlement_price=1.0)
        pos = self.tracker.get_position(pid)
        assert (pos.realized_pnl or 0.0) > 0

    def test_loss_pnl_negative(self):
        market = _make_market()
        pid = self._scan_and_execute(market)
        self.executor.settle_position(pid, settlement_price=0.0)
        pos = self.tracker.get_position(pid)
        assert (pos.realized_pnl or 0.0) < 0

    def test_order_history_has_buy_and_sell(self):
        market = _make_market()
        pid = self._scan_and_execute(market)
        self.executor.settle_position(pid, settlement_price=1.0)
        history = self.executor.get_order_history()
        actions = {o["action"] for o in history}
        assert "BUY" in actions
        assert "SELL" in actions


class TestConfigFactory:
    """PolymarketConfig.from_dict() creates isolated test configs."""

    def test_override_is_applied(self):
        cfg = PolymarketConfig.from_dict({"MAX_POSITIONS": 99})
        assert cfg.MAX_POSITIONS == 99

    def test_singleton_is_not_mutated(self):
        from config.polymarket_config import config as live_config

        original = live_config.MAX_POSITIONS
        PolymarketConfig.from_dict({"MAX_POSITIONS": 999})
        assert live_config.MAX_POSITIONS == original

    def test_non_overridden_fields_inherit_defaults(self):
        cfg = PolymarketConfig.from_dict({"MAX_POSITIONS": 1})
        assert cfg.PAPER_TRADING_ONLY is True  # default from .env
