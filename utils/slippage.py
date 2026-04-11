"""
Order-book slippage estimator.

Given a real order book and a capital amount, walks the relevant side of the
book level-by-level to compute the volume-weighted average fill price (VWAP)
and the resulting price impact vs. the best available price.

This is used in two ways:
  - Paper mode:  the estimate *is* the simulated slippage recorded on the trade.
  - Live mode:   the estimate is a pre-trade gate; if it exceeds the configured
                 tolerance the order is cancelled before submission.  After the
                 real fill the executor also compares the actual filled price
                 against the expected price for a second post-trade check.

All functions are pure — they take plain dicts and return plain dicts so they
can be unit-tested without any API dependencies.
"""

from __future__ import annotations

from typing import Dict, List


def estimate_slippage(
    order_book: Dict,
    capital_usd: float,
    side: str = "BUY",
) -> Dict:
    """
    Estimate the market-impact slippage for a market order of `capital_usd` USD.

    Algorithm:
      Walk the relevant side of the book (asks for BUY, bids for SELL) from best
      to worst price, consuming available size at each level until the full order
      is filled or the book is exhausted.  The VWAP of all consumed levels is the
      expected average fill price; slippage is the percentage deviation from the
      best (top-of-book) price.

    Args:
        order_book:   Dict returned by PolymarketClient.get_order_book():
                        {"asks": [{"price": float, "size": float}, ...],
                         "bids": [{"price": float, "size": float}, ...],
                         "mid_price": float}
                      Asks must be sorted low→high; bids high→low.
        capital_usd:  USD amount to spend (BUY) or USD value of shares to sell
                      (SELL).  For a SELL use  shares * current_price  as the
                      dollar value so the walker knows how much to consume.
        side:         "BUY" or "SELL".

    Returns:
        {
          "vwap":                   float  — weighted average fill price
          "best_price":             float  — top-of-book price
          "slippage_pct":           float  — adverse deviation from best price (%)
          "fill_ratio":             float  — fraction of order filled (1.0 = full)
          "unfilled_usd":           float  — USD not filled due to thin book
          "insufficient_liquidity": bool   — True if book couldn't absorb full order
          "levels_consumed":        int    — number of price levels touched
        }
    """
    _empty = dict(
        vwap=0.0,
        best_price=0.0,
        slippage_pct=0.0,
        fill_ratio=0.0,
        unfilled_usd=float(capital_usd),
        insufficient_liquidity=True,
        levels_consumed=0,
    )

    if capital_usd <= 0:
        return _empty

    levels: List[Dict] = order_book.get("asks" if side == "BUY" else "bids", [])
    if not levels:
        return _empty

    # Find the best (top-of-book) price from the first level that has a valid price.
    # Levels with price=0 or negative are skipped here and again in the walk loop.
    best_price: float = 0.0
    for lvl in levels:
        p = float(lvl.get("price", 0))
        if p > 0:
            best_price = p
            break
    if best_price <= 0:
        return _empty

    remaining_usd = capital_usd
    total_shares = 0.0
    total_cost = 0.0
    levels_consumed = 0

    for level in levels:
        price = float(level.get("price", 0))
        size = float(level.get("size", 0))   # shares available at this price
        if price <= 0 or size <= 0:
            continue

        level_value_usd = price * size        # USD equivalent of this whole level

        if remaining_usd <= level_value_usd:
            # This level fully covers the remaining order
            shares_filled = remaining_usd / price
            total_shares += shares_filled
            total_cost += remaining_usd
            remaining_usd = 0.0
            levels_consumed += 1
            break
        else:
            # Consume the entire level and move to the next
            total_shares += size
            total_cost += level_value_usd
            remaining_usd -= level_value_usd
            levels_consumed += 1

    if total_shares == 0:
        return _empty

    vwap = total_cost / total_shares
    fill_ratio = (capital_usd - remaining_usd) / capital_usd

    # Slippage convention: positive = adverse (paid more on BUY / received less on SELL)
    if side == "BUY":
        slippage_pct = (vwap - best_price) / best_price * 100
    else:
        slippage_pct = (best_price - vwap) / best_price * 100

    return dict(
        vwap=round(vwap, 6),
        best_price=round(best_price, 6),
        slippage_pct=round(max(slippage_pct, 0.0), 4),  # negative = favourable; report as 0
        fill_ratio=round(fill_ratio, 4),
        unfilled_usd=round(remaining_usd, 4),
        insufficient_liquidity=remaining_usd > 0,
        levels_consumed=levels_consumed,
    )


def liquidity_available_usd(order_book: Dict, side: str = "BUY") -> float:
    """
    Return the total USD liquidity on the given side of the book.

    Useful for a quick pre-trade sanity check before running the full estimator.
    """
    levels: List[Dict] = order_book.get("asks" if side == "BUY" else "bids", [])
    return sum(float(lvl.get("price", 0)) * float(lvl.get("size", 0)) for lvl in levels)
