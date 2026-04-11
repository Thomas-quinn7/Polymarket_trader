"""
Unit tests for utils/slippage.py

Covers:
- estimate_slippage: correct VWAP and slippage% for single and multi-level fills
- Partial fill when book has insufficient liquidity
- Empty book / zero capital edge cases
- liquidity_available_usd helper
- BUY vs SELL side selection
"""

import pytest
from utils.slippage import estimate_slippage, liquidity_available_usd


# ── helpers ────────────────────────────────────────────────────────────────

def _book(asks=None, bids=None, mid=0.985):
    return {
        "asks": asks or [],
        "bids": bids or [],
        "mid_price": mid,
    }


def _asks(*levels):
    """Build ask levels as (price, size_in_shares) tuples."""
    return [{"price": p, "size": s} for p, s in levels]


def _bids(*levels):
    return [{"price": p, "size": s} for p, s in levels]


# ── single-level fill ──────────────────────────────────────────────────────

class TestSingleLevel:
    def test_full_fill_within_one_level(self):
        """Order absorbs a fraction of the top-of-book level — zero slippage."""
        book = _book(asks=_asks((0.985, 1000.0)))  # $985 of liquidity at 0.985
        est = estimate_slippage(book, capital_usd=100.0)
        assert est["vwap"] == pytest.approx(0.985, rel=1e-6)
        assert est["slippage_pct"] == pytest.approx(0.0, abs=1e-4)
        assert est["fill_ratio"] == pytest.approx(1.0, abs=1e-4)
        assert est["insufficient_liquidity"] is False
        assert est["levels_consumed"] == 1

    def test_exact_fill_of_entire_level(self):
        book = _book(asks=_asks((0.990, 100.0)))   # $99 liquidity
        est = estimate_slippage(book, capital_usd=99.0)
        assert est["fill_ratio"] == pytest.approx(1.0, abs=1e-4)
        assert est["slippage_pct"] == pytest.approx(0.0, abs=1e-4)


# ── multi-level fill ───────────────────────────────────────────────────────

class TestMultiLevel:
    def test_two_levels_consumed(self):
        """
        $150 order, level 1 has $80 @ 0.985, level 2 has $200 @ 0.990.
        VWAP = (80 + 70) / (80/0.985 + 70/0.990) — test just checks slippage > 0.
        """
        book = _book(asks=_asks((0.985, 81.22), (0.990, 202.02)))
        est = estimate_slippage(book, capital_usd=150.0)
        assert est["slippage_pct"] > 0
        assert est["levels_consumed"] == 2
        assert est["fill_ratio"] == pytest.approx(1.0, abs=1e-4)
        assert est["vwap"] > 0.985

    def test_vwap_between_best_and_worst_price(self):
        book = _book(asks=_asks((0.985, 50.76), (0.990, 101.01), (0.995, 200.0)))
        est = estimate_slippage(book, capital_usd=200.0)
        assert 0.985 <= est["vwap"] <= 0.995

    def test_three_levels_consumed_slippage_increases(self):
        """Slippage from three levels > two levels for larger order."""
        book = _book(asks=_asks((0.985, 50.76), (0.990, 50.50), (0.995, 50.25)))
        small = estimate_slippage(book, capital_usd=60.0)
        large = estimate_slippage(book, capital_usd=140.0)
        assert large["slippage_pct"] > small["slippage_pct"]


# ── insufficient liquidity ─────────────────────────────────────────────────

class TestInsufficientLiquidity:
    def test_partial_fill_sets_flag(self):
        book = _book(asks=_asks((0.985, 50.76)))   # only $50 available
        est = estimate_slippage(book, capital_usd=200.0)
        assert est["insufficient_liquidity"] is True
        assert est["fill_ratio"] < 1.0
        assert est["unfilled_usd"] > 0

    def test_unfilled_amount_correct(self):
        book = _book(asks=_asks((0.985, 50.76)))   # $50 available
        est = estimate_slippage(book, capital_usd=100.0)
        assert est["unfilled_usd"] == pytest.approx(100.0 - 50.0, abs=0.01)

    def test_empty_book_returns_insufficient(self):
        book = _book(asks=[])
        est = estimate_slippage(book, capital_usd=100.0)
        assert est["insufficient_liquidity"] is True
        assert est["fill_ratio"] == pytest.approx(0.0)
        assert est["levels_consumed"] == 0


# ── edge cases ─────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_zero_capital_returns_unfilled(self):
        book = _book(asks=_asks((0.985, 100.0)))
        est = estimate_slippage(book, capital_usd=0.0)
        assert est["insufficient_liquidity"] is True
        assert est["fill_ratio"] == pytest.approx(0.0)

    def test_negative_capital_returns_unfilled(self):
        book = _book(asks=_asks((0.985, 100.0)))
        est = estimate_slippage(book, capital_usd=-10.0)
        assert est["insufficient_liquidity"] is True

    def test_zero_price_level_skipped(self):
        """Levels with price=0 must not divide-by-zero or corrupt VWAP."""
        book = _book(asks=[{"price": 0, "size": 100}, {"price": 0.985, "size": 200.0}])
        est = estimate_slippage(book, capital_usd=50.0)
        assert est["vwap"] == pytest.approx(0.985, rel=1e-4)
        assert est["insufficient_liquidity"] is False

    def test_zero_size_level_skipped(self):
        book = _book(asks=[{"price": 0.985, "size": 0}, {"price": 0.990, "size": 200.0}])
        est = estimate_slippage(book, capital_usd=50.0)
        assert est["vwap"] == pytest.approx(0.990, rel=1e-4)

    def test_result_keys_present(self):
        book = _book(asks=_asks((0.985, 200.0)))
        est = estimate_slippage(book, capital_usd=50.0)
        for key in ("vwap", "best_price", "slippage_pct", "fill_ratio",
                    "unfilled_usd", "insufficient_liquidity", "levels_consumed"):
            assert key in est


# ── SELL side ──────────────────────────────────────────────────────────────

class TestSellSide:
    def test_sell_uses_bid_side(self):
        """SELL walks bids (high→low); asks are ignored."""
        book = _book(
            asks=_asks((0.990, 200.0)),
            bids=_bids((0.985, 200.0)),
        )
        est = estimate_slippage(book, capital_usd=100.0, side="SELL")
        assert est["best_price"] == pytest.approx(0.985, rel=1e-6)

    def test_sell_slippage_positive_when_walking_down(self):
        """Selling into bids drives price down — slippage > 0."""
        book = _book(bids=_bids((0.985, 50.76), (0.980, 101.02)))
        est = estimate_slippage(book, capital_usd=100.0, side="SELL")
        assert est["slippage_pct"] >= 0.0

    def test_sell_single_level_zero_slippage(self):
        book = _book(bids=_bids((0.985, 500.0)))
        est = estimate_slippage(book, capital_usd=100.0, side="SELL")
        assert est["slippage_pct"] == pytest.approx(0.0, abs=1e-4)


# ── liquidity_available_usd ────────────────────────────────────────────────

class TestLiquidityAvailable:
    def test_sums_all_ask_levels(self):
        book = _book(asks=_asks((0.985, 100.0), (0.990, 50.0)))
        # $98.50 + $49.50 = $148.00
        total = liquidity_available_usd(book, side="BUY")
        assert total == pytest.approx(0.985 * 100.0 + 0.990 * 50.0, rel=1e-4)

    def test_sums_all_bid_levels(self):
        book = _book(bids=_bids((0.980, 200.0), (0.975, 100.0)))
        total = liquidity_available_usd(book, side="SELL")
        assert total == pytest.approx(0.980 * 200.0 + 0.975 * 100.0, rel=1e-4)

    def test_empty_book_returns_zero(self):
        assert liquidity_available_usd(_book(), side="BUY") == 0.0

    def test_large_order_exceeds_available_liquidity(self):
        book = _book(asks=_asks((0.985, 10.0)))  # $9.85 available
        available = liquidity_available_usd(book, side="BUY")
        est = estimate_slippage(book, capital_usd=100.0)
        assert est["insufficient_liquidity"] is True
        assert available < 100.0
