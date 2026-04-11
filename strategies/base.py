# Copyright (C) 2026  Thomas Quinn (github.com/Thomas-quinn7)
#                     Ciaran McDonnell (github.com/CiaranMcDonnell)
# SPDX-License-Identifier: AGPL-3.0-only

"""
TradingStrategy base class.

All strategies must inherit from BaseStrategy and implement the two abstract
methods.  The optional hook methods (should_exit, get_exit_price,
get_scan_categories) have sensible defaults and can be overridden as needed.
"""

from abc import ABC, abstractmethod
from typing import List, TYPE_CHECKING

from data.polymarket_models import TradeOpportunity
from data.market_schema import PolymarketMarket
from data.market_provider import MarketCriteria, MarketDataSource


class BaseStrategy(ABC):
    """
    Abstract base for every trading strategy.

    Required (must override)
    ------------------------
    scan_for_opportunities  – examine pre-filtered PolymarketMarket objects,
                              return qualifying TradeOpportunity instances
    get_best_opportunities  – rank/limit a candidate list

    Optional hooks (override to customise behaviour)
    ------------------------------------------------
    get_market_criteria     – declare what markets this strategy wants and how
                              prices should be resolved (replaces get_scan_categories)
    should_exit             – return True when an open position should be closed
    get_exit_price          – return the target exit price for a position
    get_scan_categories     – backward-compatible alias; delegates to get_market_criteria
    """

    # Framework provenance — inherited by all strategy subclasses.
    _framework_id: str = "pmf-7e3f-tq343"

    # ── Required ───────────────────────────────────────────────────────────

    @abstractmethod
    def scan_for_opportunities(self, markets: List[PolymarketMarket]) -> List[TradeOpportunity]:
        """
        Examine a list of pre-filtered, pre-priced markets and return qualifying
        opportunities.

        Markets are provided by MarketProvider, which has already:
          - Converted raw dicts to PolymarketMarket objects (no from_api() needed)
          - Applied the criteria gates from get_market_criteria() (volume, binary, time)
          - Set market.resolved_price using the strategy's price_source_preference

        Strategies should read market.resolved_price instead of calling
        client.get_price() or accessing outcome_prices directly.

        Args:
            markets: Pre-filtered PolymarketMarket objects with resolved_price set.

        Returns:
            List of TradeOpportunity objects (may be empty).
        """

    @abstractmethod
    def get_best_opportunities(
        self, opportunities: List[TradeOpportunity], limit: int = 5
    ) -> List[TradeOpportunity]:
        """
        Rank and return the top N opportunities from a candidate list.

        Args:
            opportunities: Candidates returned by scan_for_opportunities().
            limit: Maximum number of opportunities to return.

        Returns:
            Top opportunities, highest-priority first.
        """

    # ── Optional hooks ─────────────────────────────────────────────────────

    def get_market_criteria(self) -> MarketCriteria:
        """
        Declare what this strategy needs from the market universe.

        MarketProvider uses this to:
          - Decide which categories to fetch from the Gamma API
          - Apply pre-filters (volume, binary, time bounds) before the strategy
            sees any markets — eliminating redundant per-market checks inside
            scan_for_opportunities()
          - Resolve prices using the preferred source (fastest by default)

        Override to restrict the market universe or change price source priority.

        Price source preference (fastest → slowest):
          GAMMA_EMBEDDED  — price embedded in Gamma API response (zero extra calls)
          CLOB_REST       — CLOB SDK get_price() — one call per market
          ORDER_BOOK_MID  — full order-book midpoint — most expensive

        Example (strategy that only wants highly-liquid crypto markets closing soon):

            def get_market_criteria(self) -> MarketCriteria:
                return MarketCriteria(
                    categories=["crypto"],
                    min_volume_usd=10_000.0,
                    require_binary=True,
                    max_time_to_close_s=86_400,   # within 24 h
                    price_source_preference=[
                        MarketDataSource.GAMMA_EMBEDDED,
                        MarketDataSource.CLOB_REST,
                    ],
                )
        """
        return MarketCriteria()

    def should_exit(self, position, current_price: float) -> bool:
        """
        Return True if this open position should be closed now.

        The main loop calls this every scan cycle for each open position.
        Default: never auto-exit.
        """
        return False

    def get_exit_price(self, position, current_price: float) -> float:
        """
        Return the price at which to close this position.

        Called only when should_exit() has returned True.
        Default: exit at the current market price.
        """
        return current_price

    def get_scan_categories(self) -> List[str]:
        """
        Backward-compatible alias — delegates to get_market_criteria().categories.

        New strategies should override get_market_criteria() instead.
        """
        return self.get_market_criteria().categories


# ---------------------------------------------------------------------------
# Backward-compatibility alias so existing code that imports TradingStrategy
# still resolves.
# ---------------------------------------------------------------------------
TradingStrategy = BaseStrategy
